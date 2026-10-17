"""Download NYC EMS Incident Dispatch data (dataset 76xm-jjuj) from NYC Open Data.

Writes one CSV per month to data/raw/incidents_YYYY-MM.csv (only the columns in docs/SPEC.md §2),
skipping months already on disk, so an interrupted download resumes. Raw rows stay local
(git-ignored); the pipeline reads them in chunks.

Usage: python scripts/fetch_data.py [--start 2023-01-01] [--end 2026-10-18]
Set SOCRATA_APP_TOKEN to avoid throttling. Run on a laptop: NYC Open Data is not reachable from
the cloud sandbox.
"""
import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.cityofnewyork.us/resource/76xm-jjuj.json"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PAGE = 50_000
COLS = [
    "incident_datetime", "first_assignment_datetime", "first_activation_datetime",
    "first_on_scene_datetime", "first_to_hosp_datetime", "first_hosp_arrival_datetime",
    "incident_close_datetime",
    "dispatch_response_seconds_qy", "incident_travel_tm_seconds_qy", "incident_response_seconds_qy",
    "valid_dispatch_rspns_time_indc", "valid_incident_rspns_time_indc",
    "initial_severity_level_code", "held_indicator", "reopen_indicator", "transfer_indicator",
    "standby_indicator", "borough",
]


def soql(params: dict) -> list[dict]:
    headers = {"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]} if os.environ.get("SOCRATA_APP_TOKEN") else {}
    rows, offset = [], 0
    while True:
        for attempt in range(4):
            try:
                r = requests.get(BASE, params={**params, "$limit": PAGE, "$offset": offset},
                                 headers=headers, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                print(f"  retry after {e}")
                time.sleep(2 ** (attempt + 1))
        batch = r.json()
        rows += batch
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def month(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = soql({
        "$select": ", ".join(COLS),
        "$where": f"incident_datetime >= '{start:%Y-%m-%dT%H:%M:%S}' AND incident_datetime < '{end:%Y-%m-%dT%H:%M:%S}' "
                  "AND borough != 'UNKNOWN'",
        # stable order so offset paging doesn't skip or repeat rows
        "$order": "incident_datetime, cad_incident_id",
    })
    return pd.DataFrame(rows, columns=COLS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-10-18")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    total = 0
    for m0 in pd.date_range(pd.Timestamp(args.start).replace(day=1), args.end, freq="MS"):
        m1 = min(m0 + pd.offsets.MonthBegin(1), pd.Timestamp(args.end))
        out = RAW / f"incidents_{m0:%Y-%m}.csv"
        if out.exists():
            print(f"{m0:%Y-%m}: on disk, skipped")
            continue
        df = month(max(m0, pd.Timestamp(args.start)), m1)
        tmp = out.with_suffix(".part")
        df.to_csv(tmp, index=False)
        tmp.rename(out)  # only complete months get the final name
        total += len(df)
        print(f"{m0:%Y-%m}: {len(df):,} rows")
    print(f"done, {total:,} new rows in {RAW}")
