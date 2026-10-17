"""Hourly weather for NYC (Central Park, 40.78 N 73.97 W) from the Open-Meteo archive API (free, no key).
Writes data/weather_hourly.csv: hour, temp_c, precip_mm, snowfall_cm, wind_kmh. An aggregate, committed.

    python scripts/fetch_weather.py --start 2023-01-01 --end 2026-09-30
"""
import argparse
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "weather_hourly.csv"
URL = "https://archive-api.open-meteo.com/v1/archive"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-09-30")
    args = ap.parse_args()
    parts = []
    for y0 in pd.date_range(args.start, args.end, freq="YS").union([pd.Timestamp(args.start)]):
        y1 = min(y0 + pd.offsets.YearEnd(0), pd.Timestamp(args.end))
        r = requests.get(URL, params={"latitude": 40.78, "longitude": -73.97, "start_date": f"{y0:%Y-%m-%d}",
                                      "end_date": f"{y1:%Y-%m-%d}", "hourly": "temperature_2m,precipitation,snowfall,wind_speed_10m",
                                      "timezone": "America/New_York"}, timeout=120)
        r.raise_for_status()
        h = r.json()["hourly"]
        parts.append(pd.DataFrame({"hour": pd.to_datetime(h["time"]), "temp_c": h["temperature_2m"], "precip_mm": h["precipitation"],
                                   "snowfall_cm": h["snowfall"], "wind_kmh": h["wind_speed_10m"]}))
        print(f"{y0:%Y}: {len(h['time']):,} hours")
    df = pd.concat(parts).drop_duplicates("hour").sort_values("hour")
    df.to_csv(OUT, index=False)
    print(f"done → {OUT} ({len(df):,} rows)")
