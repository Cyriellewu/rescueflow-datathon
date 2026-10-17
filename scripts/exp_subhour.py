"""Ablation: do sub-hour leading indicators (SUBHOUR, last 15/30 min before T) add signal to the 45 hourly features?

Develops and selects on train + validation only; `--test-read` scores the test window once for one chosen design.

    python scripts/exp_subhour.py build --raw data/raw_v2/incidents_2023-*.csv ... --out artifacts/subhour
    python scripts/exp_subhour.py validate --out artifacts/subhour --val-start 2025-07-01 --test-start 2026-01-01
    python scripts/exp_subhour.py validate ... --test-read "45+SUBHOUR"
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.features import FEATURES, SUBHOUR, build_table  # noqa: E402
from rescueflow.data import load_clean, raw_files  # noqa: E402

HP = {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.05, "onset_weight": 1.0}
SEEDS = [0, 1, 2]


def build(args):
    args.out.mkdir(parents=True, exist_ok=True)
    df, _ = load_clean(raw_files(args.raw))
    print(f"clean rows: {len(df):,}", flush=True)
    times = {}
    for flag in [False, True]:
        key = "with_subhour" if flag else "without_subhour"
        t0 = time.perf_counter()
        table, _ = build_table(df, target=args.target, subhour=flag)
        times[key] = time.perf_counter() - t0
        print(f"subhour={flag}: {times[key]:.1f}s, {table.shape}", flush=True)
    table.to_pickle(args.out / "table_subhour.pkl")
    (args.out / "build_times.json").write_text(json.dumps({**times, "cores": os.cpu_count()}, indent=2))


def run(split, feats, seed, df_eval):
    """Fit on train, alert threshold from validation scores, metrics on df_eval."""
    clf = m.fit_xgb(split.train, feats, seed, HP)
    s_val = m.predict(clf, split.val, feats)
    thr = m.band_thresholds(s_val)
    s = s_val if df_eval is split.val else m.predict(clf, df_eval, feats)
    ev = m.evaluate_fast(df_eval, s, thr, seed)
    y = df_eval["stress"].astype(int).to_numpy()
    alert = m.tiebreak(s, seed + 1) >= thr["alert"]
    days = max(df_eval["hour"].dt.floor("D").nunique(), 1)
    ev["alert_recall"] = float(alert[y == 1].mean())
    ev["false_alerts_per_day"] = float((alert & (y == 0)).sum() / days)
    gain = clf.get_booster().get_score(importance_type="gain")
    tot = sum(gain.values()) or 1.0
    ev["gain_share"] = {f: gain.get(f, 0.0) / tot for f in feats}
    return ev, clf


def summarize(name, evs):
    keys = ["pr_auc", "alert_precision", "alert_recall", "onset_recall", "false_alerts_per_day"]
    row = {"design": name}
    for k in keys:
        v = [e[k] for e in evs]
        row[k] = float(np.mean(v))
        row[k + "_seeds"] = [round(x, 4) for x in v]
    return row


def evaluate(args):
    table = pd.read_pickle(args.out / "table_subhour.pkl")
    split = m.split_by_dates(table, pd.Timestamp(args.val_start), pd.Timestamp(args.test_start))
    print(f"train {len(split.train):,}  val {len(split.val):,}  test {len(split.test):,} (test untouched until --test-read)")
    designs = {"45": FEATURES, "45+SUBHOUR": FEATURES + SUBHOUR}
    results, gains = {}, {}
    for name, feats in designs.items():
        evs = [run(split, feats, s, split.val)[0] for s in SEEDS]
        results[name] = summarize(name, evs)
        gains[name] = {f: float(np.mean([e["gain_share"][f] for e in evs])) for f in feats}
        print(json.dumps(results[name]), flush=True)
    ranked = sorted(SUBHOUR, key=lambda f: -gains["45+SUBHOUR"][f])
    print("SUBHOUR gain shares (45+SUBHOUR):", {f: round(gains["45+SUBHOUR"][f], 4) for f in ranked})
    # single-feature adds: which SUBHOUR feature alone moves validation most (mean of 3 seeds)
    single = {}
    for f in SUBHOUR:
        evs = [run(split, FEATURES + [f], s, split.val)[0] for s in SEEDS]
        single[f] = summarize("45+" + f, evs)
        print(json.dumps(single[f]), flush=True)
    best = sorted(SUBHOUR, key=lambda f: -single[f]["pr_auc"])
    for k in [2, 3]:
        name = "45+" + ",".join(best[:k])
        evs = [run(split, FEATURES + best[:k], s, split.val)[0] for s in SEEDS]
        results[name] = summarize(name, evs)
        print(json.dumps(results[name]), flush=True)
    out = {"hp": HP, "seeds": SEEDS, "validation": results, "single_feature_adds": single,
           "gain_share_45_plus_subhour": gains["45+SUBHOUR"], "gain_share_45": gains["45"],
           "windows": {k: [str(getattr(split, k)["hour"].min()), str(getattr(split, k)["hour"].max())]
                       for k in ["train", "val", "test"]}}
    (args.out / "subhour_validation.json").write_text(json.dumps(out, indent=2))


def test_read(args):
    """ONE confirmatory read of the test window for the chosen design (fit on train, thresholds from validation)."""
    table = pd.read_pickle(args.out / "table_subhour.pkl")
    split = m.split_by_dates(table, pd.Timestamp(args.val_start), pd.Timestamp(args.test_start))
    named = {"45": FEATURES, "45+SUBHOUR": FEATURES + SUBHOUR}
    feats = named.get(args.test_read) or FEATURES + args.test_read.split("45+")[1].split(",")
    rows = []
    for seed in SEEDS:
        clf = m.fit_xgb(split.train, feats, seed, HP)
        thr = m.band_thresholds(m.predict(clf, split.val, feats))
        ev = m.evaluate(split.test, m.predict(clf, split.test, feats), thr, seed)
        rows.append({k: ev[k] for k in ["pr_auc", "pr_auc_ci95", "alert_precision", "alert_recall", "onset_recall",
                                        "false_alerts_per_day", "n", "base_rate", "n_onsets"]})
        print(seed, json.dumps(rows[-1]), flush=True)
    (args.out / "subhour_test_read.json").write_text(json.dumps(
        {"design": args.test_read, "features": feats, "seeds": rows,
         "note": "single confirmatory read of the test window"}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "validate"])
    ap.add_argument("--raw", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, default=Path("artifacts/subhour"))
    ap.add_argument("--target", default="dispatch_low")
    ap.add_argument("--val-start", default="2025-07-01")
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--test-read", default=None)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a)
    elif a.test_read:
        test_read(a)
    else:
        evaluate(a)
