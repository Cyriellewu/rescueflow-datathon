"""Read the raw FDNY EMS CSVs and turn each row into one clean call."""
from pathlib import Path

import numpy as np
import pandas as pd

from rescuenyc.config import HIGH_ACUITY, LOW_ACUITY, MAX_SECONDS

COLUMNS = [
    "incident_datetime", "first_assignment_datetime", "first_on_scene_datetime",
    "first_hosp_arrival_datetime", "incident_close_datetime",
    "dispatch_response_seconds_qy", "incident_travel_tm_seconds_qy",
    "valid_dispatch_rspns_time_indc", "initial_severity_level_code", "held_indicator", "borough",
]


def _seconds(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.where((x > 0) & (x <= MAX_SECONDS))


def load_calls(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    files = sorted(Path(raw_dir).glob("incidents_*.csv"))
    if not files:
        raise SystemExit(f"No incidents_*.csv in {raw_dir}. Run scripts/fetch_data.py first.")
    raw = pd.concat((pd.read_csv(f, usecols=COLUMNS, dtype=str) for f in files), ignore_index=True)
    n_raw = len(raw)

    t = {c: pd.to_datetime(raw[c], format="ISO8601", errors="coerce") for c in COLUMNS if c.endswith("datetime")}
    sev = pd.to_numeric(raw["initial_severity_level_code"], errors="coerce")
    calls = pd.DataFrame({
        "borough": raw["borough"].str.strip(),
        "created": t["incident_datetime"],
        "assigned": t["first_assignment_datetime"],
        "on_scene": t["first_on_scene_datetime"],
        "at_hospital": t["first_hosp_arrival_datetime"],
        "closed": t["incident_close_datetime"],
        "severity": sev,
        "held": raw["held_indicator"].eq("Y"),
        # FDNY's own dispatch duration, only where FDNY marks it valid
        "dispatch_s": _seconds(raw["dispatch_response_seconds_qy"]).where(raw["valid_dispatch_rspns_time_indc"].eq("Y")),
        "travel_s": _seconds(raw["incident_travel_tm_seconds_qy"]),
    })
    calls = calls[calls["created"].notna() & calls["severity"].isin(HIGH_ACUITY + LOW_ACUITY)
                  & calls["borough"].notna() & calls["borough"].ne("UNKNOWN")].copy()
    calls["severity"] = calls["severity"].astype(np.int8)
    calls["high"] = calls["severity"].isin(HIGH_ACUITY)

    # A call leaves the waiting queue when a unit is assigned, or when it is closed without one.
    left = calls["assigned"].fillna(calls["closed"]).fillna(calls["created"])
    calls["left_queue"] = left.where(left >= calls["created"], calls["created"])

    summary = {
        "files": len(files),
        "rows_raw": n_raw,
        "rows_clean": len(calls),
        "first_call": str(calls["created"].min()),
        "last_call": str(calls["created"].max()),
        "held_share": float(calls["held"].mean()),
        "median_dispatch_s_held": float(calls.loc[calls["held"], "dispatch_s"].median()),
        "median_dispatch_s_not_held": float(calls.loc[~calls["held"], "dispatch_s"].median()),
        "median_dispatch_s_high": float(calls.loc[calls["high"], "dispatch_s"].median()),
        "median_dispatch_s_low": float(calls.loc[~calls["high"], "dispatch_s"].median()),
        "calls_per_borough": calls["borough"].value_counts().to_dict(),
    }
    return calls.reset_index(drop=True), summary
