"""Write artifacts/lab_week_calls.csv: the policy lab's evaluation week (time, borough, severity), used by the
interactive hospital scene. run_policy_lab.py writes the same file; this reproduces it without rerunning the lab."""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rescueflow.data import load_clean, raw_files  # noqa: E402
from rescueflow.hospital import export_week  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--raw", type=Path, nargs="+", required=True)
ap.add_argument("--art", type=Path, default=Path("artifacts"))
args = ap.parse_args()
week = pd.Timestamp(json.loads((args.art / "policy_lab.json").read_text())["eval_week"])
df, _ = load_clean(raw_files(args.raw))
calls = df[(df["incident_datetime"] >= week) & (df["incident_datetime"] < week + pd.Timedelta(days=7))]
print(export_week(calls, args.art / "lab_week_calls.csv"), len(calls), "calls")
