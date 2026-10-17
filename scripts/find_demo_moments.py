"""Pick replay moments for the video: real onsets in the test window the model warned about early.

A good moment: the borough was normal at T-1, became stressed in [T, T+1), and the model was
already at alert at T (ideally also at T-1). Also lists misses, so the pitch can be honest.
Writes artifacts/demo_moments.json (served at /moments) and prints the top candidates.

    python scripts/find_demo_moments.py --art artifacts
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.pipeline import load_table  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", type=Path, default=Path("artifacts"))
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()
    clf, meta = m.load(args.art)
    from rescueflow.features import TARGETS
    label_col = TARGETS[meta.get("target", "dispatch")][0]  # the stage/acuity the label measures
    t = load_table(args.art / "borough_hour.csv")
    t["med_dispatch_s"] = t[label_col]
    t = t[t["hour"] >= meta["test_start"]].sort_values(["borough", "hour"]).reset_index(drop=True)
    t["score"] = m.predict(clf, t)
    t["alert"] = t["score"] >= meta["thresholds"]["alert"]
    prev_alert = t.groupby("borough")["alert"].shift(1).fillna(False).astype(bool)
    onset = (t["stressed_now"] == 0) & (t["stress"] == 1)
    caught = t[onset & t["alert"]].assign(early=prev_alert[onset & t["alert"]])
    missed = t[onset & ~t["alert"]]

    def row(r, kind):
        return {"kind": kind, "borough": r["borough"], "hour": str(r["hour"]),
                "replay_from": str(r["hour"] - np.timedelta64(3, "h")),
                "p_stress": round(float(m.calibrate([r["score"]], meta.get("calibration"))[0]), 3),
                "warned_hour_before": bool(r.get("early", False)), "bottleneck": r["bottleneck"],
                "pending_high": int(r["pending_high"]), "held_pending_low": int(r["held_pending_low"]),
                "med_dispatch_next_hour_s": None if np.isnan(r["med_dispatch_s"]) else float(r["med_dispatch_s"]),
                "threshold_s": float(r["threshold_s"])}

    caught = caught.sort_values(["early", "score", "med_dispatch_s"], ascending=False)
    out = {"data_source": meta.get("data_source", "FDNY"),
           "caught": [row(r, "caught") for _, r in caught.head(args.top).iterrows()],
           "missed": [row(r, "missed") for _, r in missed.sort_values("med_dispatch_s", ascending=False)
                      .head(3).iterrows()],
           "n_onsets": int(onset.sum()), "n_caught": int(len(caught)),
           "n_caught_hour_early": int(caught["early"].sum())}
    (args.art / "demo_moments.json").write_text(json.dumps(out, indent=2))
    print(f"{out['n_caught']}/{out['n_onsets']} onsets caught, {out['n_caught_hour_early']} already an hour early")
    for r in out["caught"]:
        print(f"  {r['hour']}  {r['borough']:26s} p={r['p_stress']:.2f}  early={r['warned_hour_before']}  "
              f"{r['bottleneck']}  next-hour median {meta.get('target', 'dispatch')} {r['med_dispatch_next_hour_s']:.0f}s vs p80 {r['threshold_s']:.0f}s")
