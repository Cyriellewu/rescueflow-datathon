"""Build features, train + evaluate, and (optionally) benchmark. Run on the LinuxONE VM.

    python scripts/run_pipeline.py --raw data/raw \
        --val-start 2025-07-01 --test-start 2026-01-01 --benchmark
    python scripts/run_pipeline.py --synthetic --benchmark     # SYNTHETIC demo data only
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m, pipeline  # noqa: E402
from rescueflow.data import clean, load_clean, raw_files  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, nargs="+",
                    help="incident CSV(s) or a directory of them from scripts/fetch_data.py")
    ap.add_argument("--synthetic", action="store_true", help="use the SYNTHETIC simulator instead")
    ap.add_argument("--out", type=Path, default=Path("artifacts"))
    ap.add_argument("--val-start")
    ap.add_argument("--test-start")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--target", choices=["dispatch", "travel", "response", "dispatch_low"], default="dispatch",
                    help="stage the label measures; choose from docs/performance_audit.md")
    args = ap.parse_args()

    if args.synthetic:
        from rescueflow.sim import synthetic_incidents
        raw = synthetic_incidents(weeks=20, boroughs=("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"))
        args.out = args.out / "synthetic"
        df = clean(raw)
        checks = raw
    else:
        df, checks = load_clean(raw_files(args.raw))

    print(f"clean rows: {len(df):,}")
    table = pipeline.build(checks, args.out, clean_df=df, target=args.target)
    meta = pipeline.train(table, args.out, args.val_start, args.test_start,
                          data_source="SYNTHETIC" if args.synthetic else "FDNY")
    print(json.dumps({k: meta[k] for k in ["model_version", "trained_on", "windows", "cascade"]}, indent=2))
    for name, r in meta["evaluation"].items():
        r = {k: (float("nan") if v is None else v) for k, v in r.items()}
        print(f"{name:18s} PR-AUC {r['pr_auc']:.3f} [{r['pr_auc_ci95'][0]:.3f}, {r['pr_auc_ci95'][1]:.3f}]  "
              f"onset recall {r['onset_recall']:.2f}  alert precision {r['alert_precision']:.2f}  "
              f"false alerts/day {r['false_alerts_per_day']:.1f}  lead {r['mean_lead_h']:.1f} h  "
              f"(base rate {r['base_rate']:.2f})")
    if args.benchmark:
        clf, _ = m.load(args.out)
        bench = pipeline.benchmark(df, clf, table)
        (args.out / "benchmark.json").write_text(json.dumps(bench, indent=2))
        print(json.dumps(bench, indent=2))
