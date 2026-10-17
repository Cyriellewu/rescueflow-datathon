"""Time a small neural risk model on CPU vs the IBM Z on-chip AI accelerator (NNPA), if present.

xgboost stays the production model. This trains a small MLP on the same features and label so
there is a like-for-like workload to time; it reports the MLP's PR-AUC too, so nobody mistakes
it for a better model. Every path is tried defensively and the output says exactly what ran;
nothing is claimed for a device that did not run.

    python scripts/nnpa_bench.py --art artifacts
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.features import FEATURES  # noqa: E402
from rescueflow.pipeline import load_table  # noqa: E402


def timed(fn, reps=20):
    fn()  # warm-up
    t = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t) / reps


def data(art):
    t = load_table(art / "borough_hour.csv")
    split = m.split_by_fraction(t)
    mu = split.train[FEATURES].mean()
    sd = split.train[FEATURES].std().replace(0, 1)
    prep = lambda d: ((d[FEATURES] - mu) / sd).fillna(0).to_numpy(np.float32)
    return (prep(split.train), split.train["stress"].to_numpy(np.float32),
            prep(split.test), split.test["stress"].to_numpy(np.float32))


def try_tensorflow(Xtr, ytr, Xte, yte, batch):
    import tensorflow as tf
    devices = [d.device_type for d in tf.config.list_physical_devices()]
    out = {"framework": f"tensorflow {tf.__version__}", "devices": devices}
    model = tf.keras.Sequential([tf.keras.Input((Xtr.shape[1],)), tf.keras.layers.Dense(128, activation="relu"),
                                 tf.keras.layers.Dense(64, activation="relu"), tf.keras.layers.Dense(1, activation="sigmoid")])
    model.compile("adam", "binary_crossentropy")
    with tf.device("/CPU:0"):
        model.fit(Xtr, ytr, epochs=8, batch_size=256, verbose=0)
        out["mlp_pr_auc"] = m._pr_auc(yte.astype(int), model.predict(Xte, verbose=0).ravel())
        out["cpu_ms_per_batch"] = 1000 * timed(lambda: model(batch, training=False))
    if "NNPA" in devices:
        with tf.device("/device:NNPA:0"):
            out["nnpa_ms_per_batch"] = 1000 * timed(lambda: model(batch, training=False))
    return out


def try_torch(Xtr, ytr, Xte, yte, batch):
    import torch
    out = {"framework": f"torch {torch.__version__}"}
    try:
        import torch_nnpa  # noqa: F401  (IBM Z accelerated PyTorch, if installed)
        out["torch_nnpa"] = True
    except Exception as e:
        out["torch_nnpa"] = f"not importable: {type(e).__name__}"
    net = torch.nn.Sequential(torch.nn.Linear(Xtr.shape[1], 128), torch.nn.ReLU(), torch.nn.Linear(128, 64),
                              torch.nn.ReLU(), torch.nn.Linear(64, 1))
    opt = torch.optim.Adam(net.parameters(), 1e-3)
    X, y = torch.from_numpy(Xtr), torch.from_numpy(ytr)
    for _ in range(8):
        for i in range(0, len(X), 256):
            opt.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(net(X[i:i + 256]).ravel(), y[i:i + 256])
            loss.backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        out["mlp_pr_auc"] = m._pr_auc(yte.astype(int), torch.sigmoid(net(torch.from_numpy(Xte))).ravel().numpy())
        b = torch.from_numpy(batch)
        out["cpu_ms_per_batch"] = 1000 * timed(lambda: net(b))
        for dev in ["nnpa"]:
            try:
                nd = net.to(dev)
                bd = b.to(dev)
                out[f"{dev}_ms_per_batch"] = 1000 * timed(lambda: nd(bd))
            except Exception as e:
                out[f"{dev}_device"] = f"unavailable: {type(e).__name__}: {str(e)[:120]}"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", type=Path, default=Path("artifacts"))
    ap.add_argument("--batch", type=int, default=4096)
    args = ap.parse_args()
    cpuinfo = Path("/proc/cpuinfo").read_text() if Path("/proc/cpuinfo").exists() else ""
    result = {"machine": platform.machine(), "nnpa_in_cpuinfo": "nnpa" in cpuinfo,
              "note": "MLP is a timing workload only; xgboost remains the production model"}
    Xtr, ytr, Xte, yte = data(args.art)
    batch = np.resize(Xte, (args.batch, Xte.shape[1])).astype(np.float32)
    for name, fn in [("tensorflow", try_tensorflow), ("torch", try_torch)]:
        try:
            result[name] = fn(Xtr, ytr, Xte, yte, batch)
        except Exception as e:
            result[name] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    ran = [k for k in ("tensorflow", "torch") if any(x.startswith("nnpa_ms") for x in result.get(k, {}))]
    result["accelerator_measured"] = bool(ran)
    result["claim"] = (f"NNPA measured via {', '.join(ran)}" if ran
                       else "no accelerator path ran: say 'CPU inference' in the pitch")
    (args.art / "nnpa_bench.json").write_text(json.dumps(m._json_safe(result), indent=2))
    print(json.dumps(m._json_safe(result), indent=2))
