"""Download NYC EMS Incident Dispatch data (dataset 76xm-jjuj) from NYC Open Data.

Writes data/raw/incidents.csv: one row per incident, only the columns listed in docs/SPEC.md §2.
Raw rows stay local (git-ignored); rescueflow/features.py aggregates them into borough_hour.

Usage: python scripts/fetch_data.py [--start 2025-01-01] [--end 2026-10-01]
Run this on a laptop: NYC Open Data is not reachable from the cloud sandbox.
"""
import argparse
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.cityofnewyork.us/resource/76xm-jjuj.json"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PAGE = 50_000
COLS = [
    "incident_datetime", "first_assignment_datetime", "first_on_scene_datetime",
    "dispatch_response_seconds_qy", "incident_travel_tm_seconds_qy", "incident_response_seconds_qy",
    "valid_dispatch_rspns_time_indc", "valid_incident_rspns_time_indc",
    "initial_severity_level_code", "held_indicator", "borough", "incident_dispatch_area",
]


def soql(params: dict) -> list[dict]:
    rows, offset = [], 0
    while True:
        r = requests.get(BASE, params={**params, "$limit": PAGE, "$offset": offset}, timeout=300)
        r.raise_for_status()
        batch = r.json()
        rows += batch
        print(f"  fetched {len(rows):,} rows")
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def incidents(start: str, end: str) -> pd.DataFrame:
    rows = soql({
        "$select": ", ".join(COLS),
        "$where": f"incident_datetime >= '{start}T00:00:00' AND incident_datetime < '{end}T00:00:00' "
                  "AND borough != 'UNKNOWN'",
        # stable order so offset paging doesn't skip or repeat rows
        "$order": "incident_datetime, cad_incident_id",
    })
    return pd.DataFrame(rows, columns=COLS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-10-01")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"incidents {args.start} .. {args.end} ...")
    df = incidents(args.start, args.end)
    df.to_csv(RAW / "incidents.csv", index=False)
    print(f"wrote {len(df):,} rows to {RAW / 'incidents.csv'}")
