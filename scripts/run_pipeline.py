"""Build features, train + evaluate, and (optionally) benchmark. Run on the LinuxONE VM.

    python scripts/run_pipeline.py --raw data/raw/incidents.csv \
        --val-start 2025-07-01 --test-start 2026-01-01 --benchmark
    python scripts/run_pipeline.py --synthetic --benchmark     # SYNTHETIC demo data only
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m, pipeline  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, help="incident CSV from scripts/fetch_data.py")
    ap.add_argument("--synthetic", action="store_true", help="use the SYNTHETIC simulator instead")
    ap.add_argument("--out", type=Path, default=Path("artifacts"))
    ap.add_argument("--val-start")
    ap.add_argument("--test-start")
    ap.add_argument("--benchmark", action="store_true")
    args = ap.parse_args()

    if args.synthetic:
        from rescueflow.sim import synthetic_incidents
        raw = synthetic_incidents(weeks=20, boroughs=("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"))
        args.out = args.out / "synthetic"
    else:
        raw = pd.read_csv(args.raw, dtype=str)

    print(f"rows: {len(raw):,}")
    table = pipeline.build(raw, args.out)
    meta = pipeline.train(table, args.out, args.val_start, args.test_start,
                          data_source="SYNTHETIC" if args.synthetic else "FDNY")
    print(json.dumps({k: meta[k] for k in ["model_version", "trained_on", "windows", "cascade"]}, indent=2))
    for name, r in meta["evaluation"].items():
        print(f"{name:20s} PR-AUC {r['pr_auc']:.3f} {r['pr_auc_ci95']}  onset recall {r['onset_recall']:.2f}  "
              f"alert precision {r['alert_precision']:.2f}  (base rate {r['base_rate']:.2f})")
    if args.benchmark:
        clf, _ = m.load(args.out)
        bench = pipeline.benchmark(raw, clf, table)
        (args.out / "benchmark.json").write_text(json.dumps(bench, indent=2))
        print(json.dumps(bench, indent=2))
