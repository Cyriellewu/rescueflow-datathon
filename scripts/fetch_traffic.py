"""NYC DOT real-time traffic speeds (Open Data i4gi-tjb9), aggregated server-side to borough x hour.

About 120 highway/arterial links report every ~5 minutes. We never download the raw rows (tens of
millions); Socrata aggregates mean speed and travel time per borough and hour. Output is an
aggregate (committed): data/traffic_borough_hour.csv with mean_speed_mph, mean_travel_time_s,
n_readings, n_links per borough-hour.

    python scripts/fetch_traffic.py --start 2023-01-01 --end 2026-10-01
"""
import argparse
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://data.cityofnewyork.us/resource/i4gi-tjb9.json"
OUT = Path(__file__).resolve().parent.parent / "data" / "traffic_borough_hour.csv"
BORO = {"Manhattan": "MANHATTAN", "Brooklyn": "BROOKLYN", "Queens": "QUEENS", "Bronx": "BRONX",
        "Staten Island": "RICHMOND / STATEN ISLAND"}


def month(m0, m1):
    rows, offset = [], 0
    while True:
        params = {
            "$select": "borough, date_trunc_ymd(data_as_of) AS day, date_extract_hh(data_as_of) AS hh, "
                       "avg(speed::number) AS mean_speed_mph, avg(travel_time::number) AS mean_travel_time_s, "
                       "count(*) AS n_readings, count(distinct link_id) AS n_links",
            "$where": f"data_as_of >= '{m0:%Y-%m-%dT%H:%M:%S}' AND data_as_of < '{m1:%Y-%m-%dT%H:%M:%S}' AND speed::number > 0",
            "$group": "borough, date_trunc_ymd(data_as_of), date_extract_hh(data_as_of)",
            "$order": "borough, day, hh", "$limit": 50000, "$offset": offset}
        for attempt in range(5):
            try:
                r = requests.get(URL, params=params, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 4:
                    raise
                print(f"  retry {m0:%Y-%m}: {e}")
                time.sleep(2 ** (attempt + 1))
        batch = r.json()
        rows += batch
        if len(batch) < 50000:
            return rows
        offset += 50000


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-10-01")
    args = ap.parse_args()
    parts = []
    if OUT.exists():
        parts.append(pd.read_csv(OUT, parse_dates=["hour"]))
        have = set(parts[0]["hour"].dt.to_period("M").astype(str))
    else:
        have = set()
    for m0 in pd.date_range(pd.Timestamp(args.start).replace(day=1), args.end, freq="MS"):
        if m0 >= pd.Timestamp(args.end):
            break
        if f"{m0:%Y-%m}" in have:
            continue
        rows = month(m0, min(m0 + pd.offsets.MonthBegin(1), pd.Timestamp(args.end)))
        df = pd.DataFrame(rows)
        if df.empty:
            print(f"{m0:%Y-%m}: no rows"); continue
        df["borough"] = df["borough"].map(BORO)
        df = df.dropna(subset=["borough"])
        df["hour"] = pd.to_datetime(df["day"]) + pd.to_timedelta(df["hh"].astype(int), unit="h")
        for c in ["mean_speed_mph", "mean_travel_time_s", "n_readings", "n_links"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        parts.append(df[["borough", "hour", "mean_speed_mph", "mean_travel_time_s", "n_readings", "n_links"]])
        pd.concat(parts, ignore_index=True).drop_duplicates(["borough", "hour"]).sort_values(["borough", "hour"]).to_csv(OUT, index=False)
        print(f"{m0:%Y-%m}: {len(df):,} borough-hours")
    print(f"done → {OUT}")
