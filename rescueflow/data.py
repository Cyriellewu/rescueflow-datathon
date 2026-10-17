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
    df = df[df["severity"].notna()]
    df["high"] = df["severity"] <= 3
    df["held"] = df["held_indicator"].fillna("N") == "Y"

    created = df["incident_datetime"]
    dispatch = (df["first_assignment_datetime"] - created).dt.total_seconds()
    travel = (df["first_on_scene_datetime"] - df["first_assignment_datetime"]).dt.total_seconds()
    ok_d = (df["valid_dispatch_rspns_time_indc"] == "Y") & dispatch.between(0, MAX_DISPATCH_S)
    ok_t = (df["valid_incident_rspns_time_indc"] == "Y") & travel.between(0, MAX_TRAVEL_S)
    df["dispatch_s"] = dispatch.where(ok_d)
    df["travel_s"] = travel.where(ok_t)

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
            "borough", "severity", "high", "held", "dispatch_s", "travel_s"]
    return df[keep].sort_values("incident_datetime").reset_index(drop=True)


def audit(raw: pd.DataFrame, df: pd.DataFrame) -> dict:
    """Numbers for docs/data_audit.md: how the published durations compare to recomputed ones."""
    r = raw.copy()
    for c in TIME_COLS:
        r[c] = pd.to_datetime(r[c], errors="coerce") if c in r else pd.NaT
    recomputed = (r["first_assignment_datetime"] - r["incident_datetime"]).dt.total_seconds()
    published = pd.to_numeric(r["dispatch_response_seconds_qy"], errors="coerce")
    both = recomputed.notna() & published.notna()
    held = df["held"]
    return {
        "rows_raw": len(raw),
        "rows_clean": len(df),
        "date_min": str(df["incident_datetime"].min()),
        "date_max": str(df["incident_datetime"].max()),
        "dispatch_mismatch_rate": float((np.abs(recomputed[both] - published[both]) > 1).mean()),
        "dispatch_valid_rate": float(df["dispatch_s"].notna().mean()),
        "travel_valid_rate": float(df["travel_s"].notna().mean()),
        "held_rate": float(held.mean()),
        "median_dispatch_held_s": float(df.loc[held, "dispatch_s"].median()),
        "median_dispatch_not_held_s": float(df.loc[~held, "dispatch_s"].median()),
        "severity_counts": df["severity"].value_counts().sort_index().to_dict(),
        "boroughs": df["borough"].value_counts().to_dict(),
        "hosp_arrival_rate": float(df["hosp_arrival"].notna().mean()),
        "median_hosp_to_close_min": float(((df["hosp_end"] - df["hosp_arrival"]).dt.total_seconds() / 60).median()),
    }
