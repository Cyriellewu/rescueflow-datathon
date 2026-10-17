"""Quick P0 check on downloaded raw CSVs (run on the laptop right after fetch_data.py).

Answers the questions the whole approach depends on, in seconds, before anything is copied to the VM:
months present and row counts, null rates of the timestamps the backlog needs, whether published
dispatch seconds match the timestamps, whether held calls really wait longer, and the severity
code set per year.

    python scripts/check_raw.py data/raw
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow.data import raw_files  # noqa: E402

TS = ["incident_datetime", "first_assignment_datetime", "first_on_scene_datetime",
      "first_hosp_arrival_datetime", "incident_close_datetime"]


def main(paths):
    files = raw_files(paths)
    months, parts = [], []
    for f in files:
        df = pd.read_csv(f, dtype=str)
        months.append((f.name, len(df)))
        # a 5% sample per file is enough for rates and medians
        parts.append(df.sample(frac=0.05, random_state=0) if len(df) > 20_000 else df)
    s = pd.concat(parts, ignore_index=True)
    for c in TS:
        s[c] = pd.to_datetime(s.get(c), errors="coerce")

    print("== files / rows")
    for name, n in months:
        print(f"  {name:28s} {n:>9,}")
    total = sum(n for _, n in months)
    print(f"  total {total:,} rows in {len(months)} files")
    have = sorted({n.split("_")[-1][:7] for n, _ in months if n.startswith("incidents_")})
    if have:
        expected = pd.period_range(have[0], have[-1], freq="M").astype(str).tolist()
        missing = sorted(set(expected) - set(have))
        print(f"  months {have[0]} → {have[-1]}; missing: {missing or 'none'}")

    print("\n== null rate of timestamps (sample)")
    for c in TS:
        print(f"  {c:30s} {s[c].isna().mean():6.1%}")

    created, assigned = s["incident_datetime"], s["first_assignment_datetime"]
    recomputed = (assigned - created).dt.total_seconds()
    published = pd.to_numeric(s["dispatch_response_seconds_qy"], errors="coerce")
    both = recomputed.notna() & published.notna()
    print("\n== published vs recomputed dispatch seconds")
    print(f"  compared {both.sum():,}; |diff| > 1 s: {(np.abs(recomputed[both] - published[both]) > 1).mean():.2%}")
    print(f"  negative recomputed: {(recomputed < 0).mean():.2%}; > 3 h: {(recomputed > 3 * 3600).mean():.2%}")

    held = s["held_indicator"] == "Y"
    valid = s["valid_dispatch_rspns_time_indc"] == "Y"
    d = recomputed.where(valid)
    print("\n== held_indicator (the backlog story needs held calls to wait much longer)")
    print(f"  held share: {held.mean():.2%}")
    print(f"  median dispatch, held: {d[held].median():.0f} s; not held: {d[~held].median():.0f} s")
    verdict = "OK" if d[held].median() > 3 * d[~held].median() else "CHECK: held does not mean waiting much longer"
    print(f"  → {verdict}")

    sev = pd.to_numeric(s["initial_severity_level_code"], errors="coerce")
    print("\n== severity code set by year (sample counts)")
    print(pd.crosstab(created.dt.year, sev).to_string())
    hi = sev <= 3
    print(f"\n  median dispatch, severity 1–3: {d[hi].median():.0f} s; 4–8: {d[~hi].median():.0f} s")

    print("\n== hospital proxy")
    arrive, close = s["first_hosp_arrival_datetime"], s["incident_close_datetime"]
    gap = (close - arrive).dt.total_seconds() / 60
    print(f"  calls with hospital arrival: {arrive.notna().mean():.1%}; "
          f"median arrival → close: {gap.median():.0f} min (p90 {gap.quantile(0.9):.0f})")

    print("\n== boroughs")
    print(s["borough"].value_counts(normalize=True).round(3).to_string())
    print(f"\nlatest incident: {created.max()}  (publication lag: the test window must end before this)")


if __name__ == "__main__":
    main(sys.argv[1:] or ["data/raw"])
