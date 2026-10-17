"""Load and clean raw EMS incident rows (columns as in scripts/fetch_data.py)."""
import numpy as np
import pandas as pd

TIME_COLS = ["incident_datetime", "first_assignment_datetime", "first_activation_datetime",
             "first_on_scene_datetime", "first_to_hosp_datetime", "first_hosp_arrival_datetime",
             "incident_close_datetime"]
# Plausible bounds for recomputed durations; P0 audit should justify these with histograms.
MAX_DISPATCH_S = 3 * 3600
MAX_TRAVEL_S = 2 * 3600
# A call with neither assignment nor close time is dropped from the backlog after this long.
MAX_PENDING_S = 6 * 3600
# A unit that reached a hospital with no close time is assumed to leave after this long.
MAX_AT_HOSPITAL_S = 3 * 3600
# Fixed category set so chunks concatenate as one small categorical (a string per row costs
# ~60 bytes; at ~6M rows that matters on a 4 GB VM).
BOROUGHS = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "RICHMOND / STATEN ISLAND"]


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    for c in TIME_COLS:
        if c not in df:
            df[c] = None
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df = df[df["incident_datetime"].notna() & df["borough"].notna()]
    for flag in ["reopen_indicator", "transfer_indicator", "standby_indicator"]:
        df = df[df[flag].fillna("N") != "Y"]

    df["severity"] = pd.to_numeric(df["initial_severity_level_code"], errors="coerce")
    df = df[df["severity"].notna() & df["borough"].isin(BOROUGHS)]
    df["severity"] = df["severity"].astype("int8")
    df["borough"] = pd.Categorical(df["borough"], categories=BOROUGHS)
    df["high"] = df["severity"] <= 3
    df["held"] = df["held_indicator"].fillna("N") == "Y"

    created = df["incident_datetime"]
    dispatch = (df["first_assignment_datetime"] - created).dt.total_seconds()
    travel = (df["first_on_scene_datetime"] - df["first_assignment_datetime"]).dt.total_seconds()
    ok_d = (df["valid_dispatch_rspns_time_indc"] == "Y") & dispatch.between(0, MAX_DISPATCH_S)
    ok_t = (df["valid_incident_rspns_time_indc"] == "Y") & travel.between(0, MAX_TRAVEL_S)
    df["dispatch_s"] = dispatch.where(ok_d)
    df["dispatch_over_cap"] = (df["valid_dispatch_rspns_time_indc"] == "Y") & (dispatch > MAX_DISPATCH_S)
    df["travel_s"] = travel.where(ok_t)
    response = (df["first_on_scene_datetime"] - created).dt.total_seconds()
    ok_r = (df["valid_incident_rspns_time_indc"] == "Y") & response.between(0, MAX_DISPATCH_S + MAX_TRAVEL_S)
    df["response_s"] = response.where(ok_r)

    # Leaves the unassigned backlog at the first of assignment / close; never before creation.
    end = df[["first_assignment_datetime", "incident_close_datetime"]].min(axis=1)
    end = end.fillna(created + pd.Timedelta(seconds=MAX_PENDING_S))
    df["queue_end"] = end.where(end >= created, created)

    # At hospital from first hospital arrival until the incident closes (proxy for handover load;
    # close is not the same as the unit becoming available — P0 audit should check the gap).
    arrive = df["first_hosp_arrival_datetime"]
    leave = df["incident_close_datetime"].fillna(arrive + pd.Timedelta(seconds=MAX_AT_HOSPITAL_S))
    df["hosp_arrival"] = arrive
    df["hosp_end"] = leave.where(leave >= arrive, arrive)

    keep = ["incident_datetime", "first_assignment_datetime", "first_on_scene_datetime", "queue_end",
            "hosp_arrival", "hosp_end",
            "borough", "severity", "high", "held", "dispatch_s", "travel_s", "response_s", "dispatch_over_cap"]
    return df[keep].sort_values("incident_datetime", kind="stable").reset_index(drop=True)


def raw_checks(raw: pd.DataFrame) -> dict:
    """Counts on raw rows that clean() can't recover: rows and published-vs-recomputed mismatches."""
    created = pd.to_datetime(raw["incident_datetime"], errors="coerce")
    assigned = pd.to_datetime(raw["first_assignment_datetime"], errors="coerce")
    recomputed = (assigned - created).dt.total_seconds()
    published = pd.to_numeric(raw["dispatch_response_seconds_qy"], errors="coerce")
    both = recomputed.notna() & published.notna()
    return {"rows_raw": len(raw), "n_compared": int(both.sum()),
            "n_mismatch": int((np.abs(recomputed[both] - published[both]) > 1).sum())}


def raw_files(paths) -> list:
    """Expand CLI paths: files as given, directories to their incidents*.csv."""
    from pathlib import Path
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("incidents*.csv")) if p.is_dir() else [p]
    if not files:
        raise SystemExit(f"no incident CSVs in {list(map(str, paths))}")
    return files


def load_clean(paths, chunksize=500_000) -> tuple[pd.DataFrame, dict]:
    """Read raw CSVs in chunks and clean each, so the raw strings never all sit in memory."""
    parts, checks = [], {"rows_raw": 0, "n_compared": 0, "n_mismatch": 0}
    for path in paths:
        for chunk in pd.read_csv(path, dtype=str, chunksize=chunksize):
            for k, v in raw_checks(chunk).items():
                checks[k] += v
            parts.append(clean(chunk))
    df = pd.concat(parts, ignore_index=True)
    del parts
    df.sort_values("incident_datetime", kind="stable", ignore_index=True, inplace=True)
    return df, checks


def audit(raw_or_checks, df: pd.DataFrame) -> dict:
    """Numbers for docs/data_audit.md. Accepts the raw frame or load_clean()'s checks."""
    c = raw_checks(raw_or_checks) if isinstance(raw_or_checks, pd.DataFrame) else raw_or_checks
    held = df["held"]
    return {
        "rows_raw": c["rows_raw"],
        "rows_clean": len(df),
        "date_min": str(df["incident_datetime"].min()),
        "date_max": str(df["incident_datetime"].max()),
        "dispatch_mismatch_rate": c["n_mismatch"] / c["n_compared"] if c["n_compared"] else float("nan"),
        "dispatch_valid_rate": float(df["dispatch_s"].notna().mean()),
        # valid dispatches longer than the cap are dropped from medians; if this is not tiny, the
        # label under-states the worst held calls and the cap should be raised
        "dispatch_over_cap_rate": float(df["dispatch_over_cap"].mean()),
        "travel_valid_rate": float(df["travel_s"].notna().mean()),
        "held_rate": float(held.mean()),
        "median_dispatch_held_s": float(df.loc[held, "dispatch_s"].median()),
        "median_dispatch_not_held_s": float(df.loc[~held, "dispatch_s"].median()),
        "severity_counts": df["severity"].value_counts().sort_index().to_dict(),
        "boroughs": df["borough"].value_counts().to_dict(),
        "hosp_arrival_rate": float(df["hosp_arrival"].notna().mean()),
        "median_hosp_to_close_min": float(((df["hosp_end"] - df["hosp_arrival"]).dt.total_seconds() / 60).median()),
    }
