"""Build the borough × hour table: leakage-safe features at cutoff T and the label for [T, T+1).

Row (borough, hour=T) holds features computed only from events before T, and the label for
calls created in [T, T+1). See docs/SPEC.md §3 and §5.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from rescueflow.stream import backlog_snapshots

TRAIL_WEEKS = 8
MIN_WEEKS = 4
LABEL_Q = 0.8
MIN_HIGH_CALLS = 5
DEV_THRESHOLD = 1.0
MIN_IQR_S = 30.0

BACKLOG = ["pending_high", "pending_low", "held_pending_high", "held_pending_low",
           "n_pending_gt_10min", "oldest_pending_age_s", "at_hospital"]
# flow (throughput) and change: known at T, from events timestamped before T
FLOW = ["assigned_lag1", "closed_lag1", "assigned_lag3", "pending_low_delta1", "pending_low_delta3",
        "held_low_delta1", "oldest_delta1", "at_hospital_delta1", "net_flow_lag1"]
# call-type mix of the previous hour (needs initial_call_type from the extended fetch; NaN otherwise).
# Groups chosen for how often FDNY holds them: psychiatric (EDP*) calls are held ~75% vs ~45% for others.
CALL_GROUPS = {"psych": {"EDP", "EDPC", "EDPM"}, "intox": {"DRUG", "ALTMEN", "ETOH"},
               "trauma_minor": {"INJURY", "INJMIN", "MVAINJ", "PEDSTR", "ASSLT"},
               "medical_minor": {"SICK", "SICMIN", "UNKNOW", "ABDPN", "OTHER", "HEAT", "COLD"},
               "serious": {"CARD", "CARDBR", "DIFFBR", "UNC", "ARREST", "CVAC", "RESPIR", "INJMAJ", "ANAPH", "SEIZR", "STATEP", "INBLED", "CHOKE", "DROWN", "BURNMA"}}
CALLTYPE = [f"ct_{g}_lag1" for g in CALL_GROUPS] + ["ct_psych_share_lag1"]
# previous hour's road speed in the borough (NYC DOT i4gi-tjb9 aggregated by scripts/fetch_traffic.py)
TRAFFIC = ["speed_lag1_mph", "speed_dev"]
# citywide weather observed before T (Open-Meteo archive, Central Park; scripts/fetch_weather.py)
WEATHER = ["temp_c_lag1", "precip_mm_lag3", "snowfall_cm_lag3", "wind_kmh_lag1"]
# the label's own stage: last hour's completed LOW-acuity dispatch wait, its deviation, and how close it is to the line
LABEL_STAGE = ["asof_med_dispatch_low_s", "dispatch_low_dev", "asof_low_over_thr", "stress_streak_h"]
FEATURES = BACKLOG + FLOW + CALLTYPE + TRAFFIC + WEATHER + LABEL_STAGE + [
    "n_calls_lag1", "n_calls_lag3", "n_calls_lag24", "n_high_lag1", "expected_calls",
    "asof_med_dispatch_s", "asof_med_travel_s", "dispatch_dev", "travel_dev", "stressed_now",
    "hour_of_day", "day_of_week", "borough_code",
]
# cross-borough: the rest of the city's queue at T (stress is mostly local; slack usually exists next door)
CROSS = ["other_pending_low", "other_held_low", "other_pending_high"]
# kept out of FEATURES: on 2023-2026 data they add nothing (full model 0.566 -> 0.568 PR-AUC, queue-aware
# 0.529 -> 0.532), so the primary model stays as is and CROSS_BOROUGH is a reported ladder rung
LOW_ACUITY = ["pending_low", "held_pending_low"]
# H1 control: what a demand forecast knows (volume + calendar), no queue or delay state
DEMAND = ["n_calls_lag1", "n_calls_lag3", "n_calls_lag24", "n_high_lag1", "expected_calls",
          "hour_of_day", "day_of_week", "borough_code"]
# model ladder: history → demand → + queue state → + recent delays (= FEATURES)
QUEUE_AWARE = DEMAND + BACKLOG + FLOW
EXTERNAL = CALLTYPE + TRAFFIC + WEATHER   # ablation: do call-type mix, road speed and weather add signal?
CROSS_BOROUGH = QUEUE_AWARE + CROSS   # ladder rung: does the rest of the city's queue add signal?


def hour_grid(df: pd.DataFrame) -> pd.DatetimeIndex:
    start = df["incident_datetime"].min().floor("h")
    end = df["incident_datetime"].max().floor("h") + pd.Timedelta(hours=1)
    return pd.date_range(start, end, freq="h")


def _binned(df, time_col, value_col, how, hours, name):
    d = df[df[time_col].notna()]
    g = d.groupby(["borough", d[time_col].dt.floor("h")])[value_col]
    s = {"median": g.median, "size": g.size, "sum": g.sum, "count": g.count}[how]()
    # borough may be categorical; plain strings keep the reindex/merge below dtype-stable
    s.index = pd.MultiIndex.from_arrays([s.index.get_level_values(0).astype(str), s.index.get_level_values(1)],
                                        names=["borough", "hour"])
    return s.rename(name)


def _trailing(table, col, fn):
    """Statistic over the previous TRAIL_WEEKS same hour-of-week values, per borough."""
    keys = [table["borough"], table["hour"].dt.dayofweek * 24 + table["hour"].dt.hour]
    return table.groupby(keys)[col].transform(
        lambda s: fn(s.shift(1).rolling(TRAIL_WEEKS, min_periods=MIN_WEEKS)))


TARGETS = {"dispatch": ("med_dispatch_s", "n_high_valid"), "travel": ("med_travel_s", "n_high_valid_travel"),
           "response": ("med_response_s", "n_high_valid_response"),
           # low-acuity (severity 4-8) dispatch wait: where FDNY's queueing actually lands (audit s4)
           "dispatch_low": ("med_dispatch_low_s", "n_low_valid")}
TARGET_ACUITY = {"dispatch_low": "severity 4–8"}  # default: severity 1–3


def build_table(df: pd.DataFrame, target: str = "dispatch") -> tuple[pd.DataFrame, dict]:
    """target: which high-acuity stage the label measures (pick it from the performance audit)."""
    hours = hour_grid(df)
    boroughs = sorted(map(str, df["borough"].unique()))
    idx = pd.MultiIndex.from_product([boroughs, hours], names=["borough", "hour"])
    high = df[df["high"]]
    low = df[~df["high"]]

    table = pd.concat([
        _binned(df, "incident_datetime", "high", "size", hours, "n_calls"),
        _binned(df, "incident_datetime", "high", "sum", hours, "n_high"),
        _binned(high, "incident_datetime", "dispatch_s", "median", hours, "med_dispatch_s"),
        _binned(high, "incident_datetime", "dispatch_s", "count", hours, "n_high_valid"),
        _binned(high, "incident_datetime", "travel_s", "median", hours, "med_travel_s"),
        _binned(high, "incident_datetime", "response_s", "median", hours, "med_response_s"),
        _binned(high, "incident_datetime", "travel_s", "count", hours, "n_high_valid_travel"),
        _binned(high, "incident_datetime", "response_s", "count", hours, "n_high_valid_response"),
        _binned(low, "incident_datetime", "dispatch_s", "median", hours, "med_dispatch_low_s"),
        _binned(low, "incident_datetime", "dispatch_s", "count", hours, "n_low_valid"),
        # as-of side: binned by when the duration became known, used one hour later
        _binned(high, "first_assignment_datetime", "dispatch_s", "median", hours, "asof_dispatch_bin"),
        _binned(high, "first_on_scene_datetime", "travel_s", "median", hours, "asof_travel_bin"),
        _binned(high, "first_on_scene_datetime", "response_s", "median", hours, "asof_response_bin"),
        _binned(low, "first_assignment_datetime", "dispatch_s", "median", hours, "asof_dispatch_low_bin"),
        _binned(df, "first_assignment_datetime", "high", "size", hours, "assigned_bin"),
        _binned(df, "queue_end", "high", "size", hours, "closed_bin"),
    ], axis=1).reindex(idx)
    counts = ["n_calls", "n_high", "n_high_valid", "n_high_valid_travel", "n_high_valid_response", "n_low_valid",
              "assigned_bin", "closed_bin"]
    table[counts] = table[counts].fillna(0)
    table = table.reset_index()

    snaps, stream_stats = backlog_snapshots(df, hours)
    table = table.merge(snaps, on=["borough", "hour"], how="left")

    # other boroughs' queue at the same cutoff (known at T, same leakage rule as the own-borough snapshot)
    for src, dst in [("pending_low", "other_pending_low"), ("held_pending_low", "other_held_low"),
                     ("pending_high", "other_pending_high")]:
        table[dst] = table.groupby("hour")[src].transform("sum") - table[src]

    by_b = table.groupby("borough")
    table["n_calls_lag1"] = by_b["n_calls"].shift(1)
    table["n_calls_lag3"] = by_b["n_calls"].transform(lambda s: s.shift(1).rolling(3).sum())
    table["n_calls_lag24"] = by_b["n_calls"].transform(lambda s: s.shift(1).rolling(24).sum())
    table["n_high_lag1"] = by_b["n_high"].shift(1)
    table["asof_med_dispatch_s"] = by_b["asof_dispatch_bin"].shift(1)
    table["asof_med_travel_s"] = by_b["asof_travel_bin"].shift(1)
    table["asof_med_response_s"] = by_b["asof_response_bin"].shift(1)
    table["asof_med_dispatch_low_s"] = by_b["asof_dispatch_low_bin"].shift(1)
    # flow: units assigned / calls leaving the queue in the hour before T, and how the queue moved
    table["assigned_lag1"] = by_b["assigned_bin"].shift(1)
    table["assigned_lag3"] = by_b["assigned_bin"].transform(lambda x: x.shift(1).rolling(3).sum())
    table["closed_lag1"] = by_b["closed_bin"].shift(1)
    table["net_flow_lag1"] = table["n_calls_lag1"] - table["assigned_lag1"]
    for col, k in [("pending_low", 1), ("pending_low", 3), ("held_pending_low", 1), ("oldest_pending_age_s", 1), ("at_hospital", 1)]:
        name = {"pending_low": "pending_low", "held_pending_low": "held_low", "oldest_pending_age_s": "oldest",
                "at_hospital": "at_hospital"}[col] + f"_delta{k}"
        table[name] = table[col] - by_b[col].shift(k)

    # call-type mix in the previous hour
    if "call_type" in df.columns:
        ct = df["call_type"].astype(str)
        grp = pd.Series(pd.NA, index=df.index, dtype="object")
        for g, names in CALL_GROUPS.items():
            grp[ct.isin(names)] = g
        h = df["incident_datetime"].dt.floor("h")
        cnt = (pd.crosstab([df["borough"].astype(str), h], grp.fillna("other"))
               .reindex(idx, fill_value=0).reset_index())
        cnt.columns = ["borough", "hour"] + [f"ct_{c}" for c in cnt.columns[2:]]
        table = table.merge(cnt, on=["borough", "hour"], how="left")
        by_b = table.groupby("borough")
        for g in CALL_GROUPS:
            col = f"ct_{g}"
            table[f"ct_{g}_lag1"] = by_b[col].shift(1) if col in table else np.nan
        table["ct_psych_share_lag1"] = table["ct_psych_lag1"] / table["n_calls_lag1"].replace(0, np.nan)
        table = table.drop(columns=[c for c in table.columns if c.startswith("ct_") and not c.endswith("_lag1")])
    else:
        for c in CALLTYPE:
            table[c] = np.nan

    # road speed in the previous hour, relative to the borough's trailing same-hour-of-week median
    traffic_path = Path(__file__).resolve().parent.parent / "data" / "traffic_borough_hour.csv"
    if traffic_path.exists():
        tr = pd.read_csv(traffic_path, parse_dates=["hour"])[["borough", "hour", "mean_speed_mph"]]
        table = table.merge(tr, on=["borough", "hour"], how="left")
        table["speed_lag1_mph"] = table.groupby("borough")["mean_speed_mph"].shift(1)
        med = _trailing(table, "mean_speed_mph", lambda r: r.median())
        table["speed_dev"] = (table["speed_lag1_mph"] - med.groupby(table["borough"]).shift(1)) / med.groupby(table["borough"]).shift(1).clip(lower=1)
        table = table.drop(columns=["mean_speed_mph"])
    else:
        table["speed_lag1_mph"] = np.nan
        table["speed_dev"] = np.nan

    # weather observed before T (citywide, hourly)
    weather_path = Path(__file__).resolve().parent.parent / "data" / "weather_hourly.csv"
    if weather_path.exists():
        w = pd.read_csv(weather_path, parse_dates=["hour"]).sort_values("hour")
        w["temp_c_lag1"] = w["temp_c"].shift(1)
        w["wind_kmh_lag1"] = w["wind_kmh"].shift(1)
        w["precip_mm_lag3"] = w["precip_mm"].shift(1).rolling(3).sum()
        w["snowfall_cm_lag3"] = w["snowfall_cm"].shift(1).rolling(3).sum()
        table = table.merge(w[["hour"] + WEATHER], on="hour", how="left")
    else:
        for c in WEATHER:
            table[c] = np.nan

    # trailing baselines for the hour itself (prior weeks only)
    table["expected_calls"] = _trailing(table, "n_calls", lambda r: r.mean())
    target_col, target_n = TARGETS[target]
    table["threshold_s"] = _trailing(table, target_col, lambda r: r.quantile(LABEL_Q))
    for col in ["dispatch", "travel"]:
        med = _trailing(table, f"med_{col}_s", lambda r: r.median())
        iqr = (_trailing(table, f"med_{col}_s", lambda r: r.quantile(0.75))
               - _trailing(table, f"med_{col}_s", lambda r: r.quantile(0.25))).clip(lower=MIN_IQR_S)
        # the as-of value at T describes hour T-1, so compare it to hour T-1's baseline
        table[f"{col}_dev"] = ((table[f"asof_med_{col}_s"] - med.groupby(table["borough"]).shift(1))
                               / iqr.groupby(table["borough"]).shift(1))
    prev_thr = table.groupby("borough")["threshold_s"].shift(1)
    asof_now = table[f"asof_med_{target}_s"]  # same stage as the label, known by T
    table["stressed_now"] = (asof_now > prev_thr).astype(float)
    table.loc[asof_now.isna() | prev_thr.isna(), "stressed_now"] = np.nan
    # low-acuity stage as of T: deviation from its trailing baseline and distance to the label line
    med_l = _trailing(table, "med_dispatch_low_s", lambda r: r.median())
    iqr_l = (_trailing(table, "med_dispatch_low_s", lambda r: r.quantile(0.75))
             - _trailing(table, "med_dispatch_low_s", lambda r: r.quantile(0.25))).clip(lower=MIN_IQR_S)
    table["dispatch_low_dev"] = ((table["asof_med_dispatch_low_s"] - med_l.groupby(table["borough"]).shift(1))
                                 / iqr_l.groupby(table["borough"]).shift(1))
    table["asof_low_over_thr"] = table["asof_med_dispatch_low_s"] / prev_thr.clip(lower=1.0)
    # how many consecutive hours the borough has already been late (as of T)
    sn = table["stressed_now"].fillna(0).astype(int)
    grp = (sn == 0).groupby(table["borough"]).cumsum()
    table["stress_streak_h"] = sn.groupby([table["borough"], grp]).cumsum().astype(float)

    table["hour_of_day"] = table["hour"].dt.hour
    table["day_of_week"] = table["hour"].dt.dayofweek
    table["borough_code"] = table["borough"].map({b: i for i, b in enumerate(boroughs)})

    # label needs enough high-acuity calls with a valid dispatch time (not just enough calls)
    ok = (table[target_n] >= MIN_HIGH_CALLS) & table["threshold_s"].notna() & table[target_col].notna()
    table["stress"] = np.where(ok, (table[target_col] > table["threshold_s"]).astype(float), np.nan)
    table["target"] = target
    table["bottleneck"] = bottleneck(table["dispatch_dev"], table["travel_dev"], table.get("speed_dev"))
    return table.drop(columns=["asof_dispatch_bin", "asof_travel_bin", "asof_response_bin",
                               "asof_dispatch_low_bin", "assigned_bin", "closed_bin"]), stream_stats


def bottleneck(dispatch_dev, travel_dev, speed_dev=None) -> pd.Series:
    """Contributing indicators, not causes. Travel pressure is split by the previous hour's road speed
    (NYC DOT): roads clearly slower than this hour's norm -> "travel pressure (roads)"; roads normal while
    ambulances take longer -> "travel pressure (units far)", i.e. the nearest units were busy."""
    d = np.asarray(dispatch_dev, dtype=float) >= DEV_THRESHOLD
    t = np.asarray(travel_dev, dtype=float) >= DEV_THRESHOLD
    out = np.select([d & t, d, t], ["both", "dispatch pressure", "travel pressure"], "normal").astype(object)
    if speed_dev is not None:
        sd = np.asarray(speed_dev, dtype=float)
        roads = t & ~d & (sd <= -0.10)          # speed at least 10% below the trailing norm
        far = t & ~d & (sd > -0.10) & np.isfinite(sd)
        out[roads] = "travel pressure (roads)"
        out[far] = "travel pressure (units far)"
    return pd.Series(out, index=getattr(dispatch_dev, "index", None))
