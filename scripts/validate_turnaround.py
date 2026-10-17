"""External check of the simulator's hospital assumption: how long does an ambulance stay at the hospital?

Compares three distributions of "arrived at hospital -> next step":
  - San Francisco Fire Department, ambulance units (MEDIC, PRIVATE, BLS): hospital_dttm -> available_dttm
    (data.sf.gov nuek-vuh3, real; an independent city, so a reference, not proof about NYC)
  - NYC FDNY EMS: first_hosp_arrival_datetime -> incident_close_datetime (real; close is a proxy for the unit
    being free, not a unit-availability time)
  - the policy lab's assumption: hospital handover ~ Exponential(mean Scenario.handover_min)

    python scripts/validate_turnaround.py --raw data/raw [--since 2023-01-01] [--sf-cache sf.csv]

Writes docs/external_validation.json (read by the dashboard at /external) and docs/external_validation.md.
"""
import argparse
import dataclasses
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescueflow.des import Scenario  # noqa: E402

SF_URL = "https://data.sf.gov/resource/nuek-vuh3.json"
SF_UNITS = ("MEDIC", "PRIVATE", "BLS")
QS = [0.25, 0.5, 0.75, 0.9, 0.95]
BINS = np.arange(0, 125, 5)  # 5-minute bins, 0-120 min
MAX_MIN = 240


def fetch_sf(since: str, cache: Path | None) -> pd.DataFrame:
    if cache and cache.exists():
        return pd.read_csv(cache)
    where = (f"hospital_dttm IS NOT NULL AND available_dttm IS NOT NULL AND hospital_dttm >= '{since}T00:00:00' "
             f"AND unit_type in ({','.join(repr(u) for u in SF_UNITS)})")
    rows, offset = [], 0
    while True:
        for attempt in range(4):
            try:
                r = requests.get(SF_URL, params={"$select": "unit_id,unit_type,call_number,hospital_dttm,available_dttm",
                                                 "$where": where, "$order": "hospital_dttm,call_number,unit_id",
                                                 "$limit": 50000, "$offset": offset}, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                print("retry:", e)
                time.sleep(2 ** (attempt + 1))
        batch = r.json()
        rows += batch
        print(f"  SF offset {offset}: {len(batch)} rows")
        if len(batch) < 50000:
            break
        offset += 50000
    df = pd.DataFrame(rows)
    if cache:
        df.to_csv(cache, index=False)
    return df


def minutes(start, end):
    m = (pd.to_datetime(end, format="ISO8601", errors="coerce")
         - pd.to_datetime(start, format="ISO8601", errors="coerce")).dt.total_seconds() / 60
    return m


def summarize(m: pd.Series, when: pd.Series) -> dict:
    ok = (m > 0) & (m <= MAX_MIN)
    v, w = m[ok], when[ok]
    hist = np.histogram(v.clip(upper=BINS[-1] - 1e-9), bins=BINS)[0] / len(v)
    years = {int(y): {"median": round(float(g.median()), 1), "p90": round(float(g.quantile(0.9)), 1), "n": int(len(g))}
             for y, g in v.groupby(w.dt.year)}
    return {"n": int(len(v)), "excluded_share": round(float(1 - ok.mean()), 4),
            "mean": round(float(v.mean()), 1), "cv": round(float(v.std() / v.mean()), 2),
            "quantiles": {f"p{int(q * 100)}": round(float(v.quantile(q)), 1) for q in QS},
            "hist": [round(float(h), 4) for h in hist], "by_year": years,
            "window": [str(w.min().date()), str(w.max().date())]}


def exponential(mean: float) -> dict:
    cdf = lambda x: 1 - math.exp(-x / mean)
    hist = [cdf(b) - cdf(a) for a, b in zip(BINS[:-1], BINS[1:])]
    hist[-1] += 1 - cdf(BINS[-1])  # tail into the last bin, like the clipped data
    return {"mean": mean, "cv": 1.0, "quantiles": {f"p{int(q * 100)}": round(-mean * math.log(1 - q), 1) for q in QS},
            "hist": [round(h, 4) for h in hist]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--sf-cache", type=Path)
    args = ap.parse_args()

    files = sorted(Path(args.raw).glob("incidents_*.csv"))
    if not files:
        raise SystemExit(f"no FDNY CSVs in {args.raw}")
    nyc = pd.concat((pd.read_csv(f, usecols=["first_hosp_arrival_datetime", "incident_close_datetime"]) for f in files),
                    ignore_index=True)
    nyc_when = pd.to_datetime(nyc["first_hosp_arrival_datetime"], format="ISO8601", errors="coerce")
    nyc = nyc[nyc_when >= args.since]
    nyc_s = summarize(minutes(nyc["first_hosp_arrival_datetime"], nyc["incident_close_datetime"]), nyc_when[nyc.index])

    sf = fetch_sf(args.since, args.sf_cache)
    sf = sf[sf["unit_type"].isin(SF_UNITS)].drop_duplicates(["call_number", "unit_id"])
    sf_s = summarize(minutes(sf["hospital_dttm"], sf["available_dttm"]),
                     pd.to_datetime(sf["hospital_dttm"], format="ISO8601", errors="coerce"))
    sf_s["by_unit_type"] = {u: round(float(minutes(g["hospital_dttm"], g["available_dttm"]).loc[lambda m: (m > 0) & (m <= MAX_MIN)].median()), 1)
                            for u, g in sf.groupby("unit_type")}

    handover = next(f.default for f in dataclasses.fields(Scenario) if f.name == "handover_min")
    out = {
        "question": "How long does an ambulance stay at the hospital before it can take the next call?",
        "bins_min": BINS.tolist(),
        "series": {
            "sf": {"label": "San Francisco ambulances (real)", "measure": "hospital arrival -> unit available",
                   "source": "SFFD Calls for Service, data.sf.gov nuek-vuh3; unit types MEDIC, PRIVATE, BLS", **sf_s},
            "nyc": {"label": "NYC FDNY (real, proxy)", "measure": "hospital arrival -> incident close",
                    "source": "FDNY EMS Incident Dispatch Data, NYC Open Data 76xm-jjuj", **nyc_s},
            "sim": {"label": f"Policy lab assumption", "measure": f"hospital handover ~ Exponential(mean {handover:g} min)",
                    "source": "rescueflow/des.py Scenario.handover_min", **exponential(float(handover))},
        },
        "caveats": [
            "San Francisco is an independent city: a reference for the size and shape of hospital time, not proof about NYC.",
            "NYC has no unit-available time in public data; incident close is a proxy and can differ from when the unit is free.",
            "Hospital arrival -> available includes handover, cleaning, restocking and paperwork, not only the patient handover.",
            "In the lab, a unit also queues for a handover slot when slots are full, so its simulated hospital time can exceed the handover draw.",
            f"Durations outside 0-{MAX_MIN} min are excluded as data errors.",
        ],
    }
    (ROOT / "docs" / "external_validation.json").write_text(json.dumps(out, indent=1))

    s, n, m = out["series"]["sf"], out["series"]["nyc"], out["series"]["sim"]
    row = lambda d: " | ".join(f"{d['quantiles'][k]:.1f}" for k in ["p25", "p50", "p75", "p90"])
    years = sorted(set(s["by_year"]) | set(n["by_year"]))
    md = f"""# External check: time at the hospital

Generated by `scripts/validate_turnaround.py`. {out['question']}

| Source | Measure | n | Mean | P25 | Median | P75 | P90 | CV |
|---|---|---|---|---|---|---|---|---|
| {s['label']} | {s['measure']} | {s['n']:,} | {s['mean']:.1f} | {row(s)} | {s['cv']:.2f} |
| {n['label']} | {n['measure']} | {n['n']:,} | {n['mean']:.1f} | {row(n)} | {n['cv']:.2f} |
| {m['label']} | {m['measure']} | – | {m['mean']:.1f} | {row(m)} | {m['cv']:.2f} |

Windows: SF {s['window'][0]} → {s['window'][1]}; NYC {n['window'][0]} → {n['window'][1]}. SF median by unit type:
{', '.join(f'{k} {v:.1f}' for k, v in s['by_unit_type'].items())} min.

Median (P90) by year:

| Year | San Francisco | NYC (proxy) |
|---|---|---|
""" + "\n".join(f"| {y} | " + " | ".join(f"{d['by_year'][y]['median']:.1f} ({d['by_year'][y]['p90']:.1f})" if y in d["by_year"] else "–"
                                         for d in (s, n)) + " |" for y in years) + f"""

**Reading.** Two independent sources put the time an ambulance spends at the hospital at a median of about
{min(s['quantiles']['p50'], n['quantiles']['p50']):.0f}–{max(s['quantiles']['p50'], n['quantiles']['p50']):.0f} minutes, with a narrow spread (CV {n['cv']:.2f}–{s['cv']:.2f}). The policy lab's handover assumption
(median {m['quantiles']['p50']:.1f}, exponential) is shorter and far more spread out, so the lab under-states how long hospitals tie up
units; its fleets, calibrated to observed dispatch waits, are therefore likely smaller than the real ones.

Caveats:
""" + "\n".join(f"- {c}" for c in out["caveats"]) + "\n"
    (ROOT / "docs" / "external_validation.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
