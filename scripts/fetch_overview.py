"""Fetch compact public FDNY aggregates for the local Overview, not a trained model.

    python scripts/fetch_overview.py [--start 2023-01-01] [--end 2026-10-01]

    Uses the same flag exclusions and queue-end rule as rescueflow.data.clean.
    Counts events by NYC local day/hour; no incident-level rows are downloaded.
    Yearly responses are cached so interrupted downloads can resume. Output is a
    portable JSON file that can also be replaced by an export from the full server.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rescueflow.overview import historical_profiles

BASE = "https://data.cityofnewyork.us/resource/76xm-jjuj.json"
FILTER = ("borough in ('BRONX','BROOKLYN','MANHATTAN','QUEENS','RICHMOND / STATEN ISLAND') "
          "AND initial_severity_level_code is not null "
          "AND (reopen_indicator is null OR reopen_indicator != 'Y') "
          "AND (transfer_indicator is null OR transfer_indicator != 'Y') "
          "AND (standby_indicator is null OR standby_indicator != 'Y')")
LOW = "initial_severity_level_code in ('4','5','6','7','8')"
QUEUE_END = "greatest(coalesce(least(first_assignment_datetime, incident_close_datetime), incident_datetime + 'PT6H'), incident_datetime)"


def fetch_counts(kind, begin, end, cache):
    path = cache / f"{kind}-{begin.date()}-{end.date()}.json"
    if path.exists():
        return json.loads(path.read_text())
    stamp = "incident_datetime" if kind == "arrivals" else QUEUE_END
    measure = f"count(*) as n_calls, sum(case({LOW}, 1, true, 0)) as n_low" if kind == "arrivals" else "count(*) as n_low"
    params = {
        "$select": f"borough, date_trunc_ymd({stamp}) as day, date_extract_hh({stamp}) as hod, {measure}",
        "$where": f"incident_datetime >= '{begin.isoformat()}' AND incident_datetime < '{end.isoformat()}' AND {FILTER}" + (f" AND {LOW}" if kind == "departures" else ""),
        "$group": "borough,day,hod", "$order": "borough,day,hod", "$limit": 50000,
    }
    # Departure groups are selected by creation year and may extend beyond that year.
    # Page with a stable group order, including anomalously late queue-end timestamps.
    rows = []
    headers = {"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]} if os.environ.get("SOCRATA_APP_TOKEN") else {}
    while True:
        r = requests.get(BASE, params={**params, "$offset": len(rows)}, headers=headers, timeout=300)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < 50000:
            break
    path.write_text(json.dumps(rows))
    print(f"{kind} {begin.year}: {len(rows):,} groups", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-10-01", help="exclusive; use complete days only")
    ap.add_argument("--out", type=Path, default=Path("data/overview_fdny.json"))
    args = ap.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if start != start.normalize() or end != end.normalize() or end <= start:
        ap.error("start/end must be increasing whole-day timestamps")
    # Refuse to normalize missing/future years into a misleading flat zero line.
    r = requests.get(BASE, params={"$select": "min(incident_datetime) as first, max(incident_datetime) as last"}, timeout=90)
    r.raise_for_status()
    coverage = r.json()[0]
    if start < pd.Timestamp(coverage["first"]).normalize() or end > pd.Timestamp(coverage["last"]).normalize() + pd.Timedelta(days=1):
        raise ValueError(f"Requested interval exceeds published coverage: {coverage}")
    cache = Path("artifacts/overview_sources")
    cache.mkdir(parents=True, exist_ok=True)
    jobs = []
    begin = start
    while begin < end:
        stop = min(end, pd.Timestamp(year=begin.year + 1, month=1, day=1))
        jobs.extend((kind, begin, stop) for kind in ("arrivals", "departures"))
        begin = stop
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda j: fetch_counts(*j, cache), jobs))
    arrivals = [r for j, rows in zip(jobs, results) if j[0] == "arrivals" for r in rows]
    departures = [r for j, rows in zip(jobs, results) if j[0] == "departures" for r in rows]
    profiles = historical_profiles(arrivals, departures, start, end)
    provenance = {
        "data_source": "FDNY · NYC Open Data", "source_url": "https://data.cityofnewyork.us/d/76xm-jjuj",
        "start": str(start.date()), "end_exclusive": str(end.date()),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "method": "Hourly means over all calendar hours, including zero-call hours. Queue reconstructed at hour boundaries from arrivals and earliest assignment/close; six-hour fallback when both are missing. Excludes reopened, transferred and standby incidents. Queue includes calls created in this coverage window only.",
    }
    profiles["metric_provenance"] = {key: provenance for key in profiles}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".part")
    tmp.write_text(json.dumps(profiles, indent=2) + "\n")
    tmp.replace(args.out)
    print(f"Saved {args.out}: {sum(int(r['n_calls']) for r in arrivals):,} cleaned calls", flush=True)


if __name__ == "__main__":
    main()
