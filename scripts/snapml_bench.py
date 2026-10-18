"""Tree-ensemble inference on the IBM Z on-chip AI accelerator via Snap ML, if available.

Our production model is a gradient-boosted tree ensemble. IBM's Snap ML can compile a boosted-tree model to
zDNN tensors and run inference on the Telum AI accelerator (z16 and later). This script trains a Snap ML
boosting machine on the same features and label (so quality is comparable; its PR-AUC is reported), then times
the same model's predictions on CPU and, when the accelerator path is available, on zDNN. Nothing is claimed
for a path that did not run; the JSON says exactly what happened.

    python scripts/snapml_bench.py --art artifacts            # writes artifacts/snapml_bench.json
"""
import argparse
import json
import platform
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.features import FEATURES  # noqa: E402
from rescueflow.pipeline import load_table  # noqa: E402


def timed(fn, reps=30):
    fn()
    t = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t) / reps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", type=Path, default=Path("artifacts"))
    ap.add_argument("--batch", type=int, default=5000, help="rows per timed predict call")
    a = ap.parse_args()
    out = {"machine": platform.machine(), "snapml": None, "cpu": None, "zdnn": None, "claim": None}
    try:
        import snapml
        from snapml import BoostingMachineClassifier
        out["snapml"] = getattr(snapml, "__version__", "unknown")
    except Exception as e:  # noqa: BLE001
        out["claim"] = f"snapml not importable ({type(e).__name__}: {e}); no accelerator path ran, say 'CPU inference'"
        (a.art / "snapml_bench.json").write_text(json.dumps(out, indent=2)); print(json.dumps(out, indent=2)); return
    t = load_table(a.art / "borough_hour.csv")
    split = m.split_by_fraction(t)
    X, y = split.train[FEATURES].fillna(0).to_numpy(np.float32), split.train["stress"].to_numpy(np.float32)
    Xt, yt = split.test[FEATURES].fillna(0).to_numpy(np.float32), split.test["stress"].to_numpy(np.float32)
    clf = BoostingMachineClassifier(num_round=600, max_depth=3, learning_rate=0.05, n_jobs=4, random_state=0)
    t0 = time.perf_counter(); clf.fit(X, y); out["fit_s"] = round(time.perf_counter() - t0, 2)
    p = clf.predict_proba(Xt)[:, 1]
    from sklearn.metrics import average_precision_score
    out["pr_auc_test"] = float(average_precision_score(yt, p))
    xb = Xt[: a.batch]
    out["cpu"] = {"batch_rows": int(len(xb)), "ms_per_batch": round(timed(lambda: clf.predict_proba(xb)) * 1000, 3),
                  "ms_per_row_single": round(timed(lambda: clf.predict_proba(xb[:1])) * 1000, 4)}
    try:
        clf.optimize_trees(tree_format="zdnn_tensors")   # compile the ensemble for the on-chip AI accelerator
        pz = clf.predict_proba(Xt)[:, 1]
        out["zdnn"] = {"batch_rows": int(len(xb)), "ms_per_batch": round(timed(lambda: clf.predict_proba(xb)) * 1000, 3),
                       "ms_per_row_single": round(timed(lambda: clf.predict_proba(xb[:1])) * 1000, 4),
                       "max_abs_prob_diff_vs_cpu": float(np.max(np.abs(pz - p)))}
        out["speedup_batch"] = round(out["cpu"]["ms_per_batch"] / out["zdnn"]["ms_per_batch"], 2)
        out["claim"] = (f"same boosted-tree model, {len(xb)} rows: CPU {out['cpu']['ms_per_batch']} ms, "
                        f"AI accelerator (zDNN) {out['zdnn']['ms_per_batch']} ms, {out['speedup_batch']}x; probabilities agree to "
                        f"{out['zdnn']['max_abs_prob_diff_vs_cpu']:.2e}")
    except Exception as e:  # noqa: BLE001
        out["zdnn"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        out["claim"] = "snapml ran on CPU only; the zDNN tree format was not available here, say 'CPU inference'"
    (a.art / "snapml_bench.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "zdnn" or not isinstance(v, dict) or "trace" not in v}, indent=2))


if __name__ == "__main__":
    main()
