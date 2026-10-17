"""Download NYC EMS Incident Dispatch data (dataset 76xm-jjuj) from NYC Open Data.

Writes two files into data/:
  hourly_counts.csv   - incident counts per hour per borough (for forecasting)
  manhattan_sample.csv - raw incident rows in Manhattan (severity / zip mix for surges)
"""
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.cityofnewyork.us/resource/76xm-jjuj.json"
DATA = Path(__file__).resolve().parent.parent / "data"
START = "2024-10-01T00:00:00"
PAGE = 50_000


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


def hourly_counts() -> pd.DataFrame:
    rows = soql({
        # date_trunc_ymdh is not available on this dataset, so group by day + hour-of-day
        "$select": "date_trunc_ymd(incident_datetime) AS d, date_extract_hh(incident_datetime) AS h, "
                   "borough, count(*) AS n",
        "$where": f"incident_datetime >= '{START}' AND borough != 'UNKNOWN'",
        "$group": "d, h, borough",
        "$order": "d, h, borough",
    })
    df = pd.DataFrame(rows)
    df["hour"] = pd.to_datetime(df["d"]) + pd.to_timedelta(df["h"].astype(int), unit="h")
    df["n"] = df["n"].astype(int)
    return df[["hour", "borough", "n"]].sort_values(["hour", "borough"])


def manhattan_sample() -> pd.DataFrame:
    cols = ["incident_datetime", "final_call_type", "final_severity_level_code", "zipcode",
            "dispatch_response_seconds_qy", "incident_travel_tm_seconds_qy",
            "incident_response_seconds_qy", "valid_incident_rspns_time_indc"]
    rows = soql({
        "$select": ", ".join(cols),
        "$where": "borough = 'MANHATTAN' AND incident_datetime >= '2026-01-01T00:00:00'",
        "$order": "incident_datetime DESC",
    })
    return pd.DataFrame(rows, columns=cols)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    print("hourly counts by borough ...")
    hourly_counts().to_csv(DATA / "hourly_counts.csv", index=False)
    print("manhattan incident sample ...")
    manhattan_sample().to_csv(DATA / "manhattan_sample.csv", index=False)
    print("done")
