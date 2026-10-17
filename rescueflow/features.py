"""Build the borough × hour table: leakage-safe features at cutoff T and the label for [T, T+1).

Row (borough, hour=T) holds features computed only from events before T, and the label for
calls created in [T, T+1). See docs/SPEC.md §3 and §5.
"""
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
FEATURES = BACKLOG + [
    "n_calls_lag1", "n_calls_lag3", "n_calls_lag24", "n_high_lag1", "expected_calls",
    "asof_med_dispatch_s", "asof_med_travel_s", "dispatch_dev", "travel_dev", "stressed_now",
    "hour_of_day", "day_of_week", "borough_code",
]
LOW_ACUITY = ["pending_low", "held_pending_low"]
# H1 control: what a demand forecast knows (volume + calendar), no queue or delay state
DEMAND = ["n_calls_lag1", "n_calls_lag3", "n_calls_lag24", "n_high_lag1", "expected_calls",
          "hour_of_day", "day_of_week", "borough_code"]


def hour_grid(df: pd.DataFrame) -> pd.DatetimeIndex:
    start = df["incident_datetime"].min().floor("h")
    end = df["incident_datetime"].max().floor("h") + pd.Timedelta(hours=1)
    return pd.date_range(start, end, freq="h")


def _binned(df, time_col, value_col, how, hours, name):
    d = df[df[time_col].notna()]
    g = d.groupby(["borough", d[time_col].dt.floor("h")])[value_col]
    s = {"median": g.median, "size": g.size, "sum": g.sum, "count": g.count}[how]()
    s.index.names = ["borough", "hour"]
    return s.rename(name)


def _trailing(table, col, fn):
    """Statistic over the previous TRAIL_WEEKS same hour-of-week values, per borough."""
    keys = [table["borough"], table["hour"].dt.dayofweek * 24 + table["hour"].dt.hour]
    return table.groupby(keys)[col].transform(
        lambda s: fn(s.shift(1).rolling(TRAIL_WEEKS, min_periods=MIN_WEEKS)))


def build_table(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    hours = hour_grid(df)
    boroughs = sorted(df["borough"].unique())
    idx = pd.MultiIndex.from_product([boroughs, hours], names=["borough", "hour"])
    high = df[df["high"]]

    table = pd.concat([
        _binned(df, "incident_datetime", "high", "size", hours, "n_calls"),
        _binned(df, "incident_datetime", "high", "sum", hours, "n_high"),
        _binned(high, "incident_datetime", "dispatch_s", "median", hours, "med_dispatch_s"),
        _binned(high, "incident_datetime", "dispatch_s", "count", hours, "n_high_valid"),
        _binned(high, "incident_datetime", "travel_s", "median", hours, "med_travel_s"),
        # as-of side: binned by when the duration became known, used one hour later
        _binned(high, "first_assignment_datetime", "dispatch_s", "median", hours, "asof_dispatch_bin"),
        _binned(high, "first_on_scene_datetime", "travel_s", "median", hours, "asof_travel_bin"),
    ], axis=1).reindex(idx)
    table[["n_calls", "n_high", "n_high_valid"]] = table[["n_calls", "n_high", "n_high_valid"]].fillna(0)
    table = table.reset_index()

    snaps, stream_stats = backlog_snapshots(df, hours)
    table = table.merge(snaps, on=["borough", "hour"], how="left")

    by_b = table.groupby("borough")
    table["n_calls_lag1"] = by_b["n_calls"].shift(1)
    table["n_calls_lag3"] = by_b["n_calls"].transform(lambda s: s.shift(1).rolling(3).sum())
    table["n_calls_lag24"] = by_b["n_calls"].transform(lambda s: s.shift(1).rolling(24).sum())
    table["n_high_lag1"] = by_b["n_high"].shift(1)
    table["asof_med_dispatch_s"] = by_b["asof_dispatch_bin"].shift(1)
    table["asof_med_travel_s"] = by_b["asof_travel_bin"].shift(1)

    # trailing baselines for the hour itself (prior weeks only)
    table["expected_calls"] = _trailing(table, "n_calls", lambda r: r.mean())
    table["threshold_s"] = _trailing(table, "med_dispatch_s", lambda r: r.quantile(LABEL_Q))
    for col in ["dispatch", "travel"]:
        med = _trailing(table, f"med_{col}_s", lambda r: r.median())
        iqr = (_trailing(table, f"med_{col}_s", lambda r: r.quantile(0.75))
               - _trailing(table, f"med_{col}_s", lambda r: r.quantile(0.25))).clip(lower=MIN_IQR_S)
        # the as-of value at T describes hour T-1, so compare it to hour T-1's baseline
        table[f"{col}_dev"] = ((table[f"asof_med_{col}_s"] - med.groupby(table["borough"]).shift(1))
                               / iqr.groupby(table["borough"]).shift(1))
    prev_thr = table.groupby("borough")["threshold_s"].shift(1)
    table["stressed_now"] = (table["asof_med_dispatch_s"] > prev_thr).astype(float)
    table.loc[table["asof_med_dispatch_s"].isna() | prev_thr.isna(), "stressed_now"] = np.nan

    table["hour_of_day"] = table["hour"].dt.hour
    table["day_of_week"] = table["hour"].dt.dayofweek
    table["borough_code"] = table["borough"].map({b: i for i, b in enumerate(boroughs)})

    # label needs enough high-acuity calls with a valid dispatch time (not just enough calls)
    ok = (table["n_high_valid"] >= MIN_HIGH_CALLS) & table["threshold_s"].notna() & table["med_dispatch_s"].notna()
    table["stress"] = np.where(ok, (table["med_dispatch_s"] > table["threshold_s"]).astype(float), np.nan)
    table["bottleneck"] = bottleneck(table["dispatch_dev"], table["travel_dev"])
    return table.drop(columns=["asof_dispatch_bin", "asof_travel_bin"]), stream_stats


def bottleneck(dispatch_dev, travel_dev) -> pd.Series:
    d = np.asarray(dispatch_dev, dtype=float) >= DEV_THRESHOLD
    t = np.asarray(travel_dev, dtype=float) >= DEV_THRESHOLD
    out = np.select([d & t, d, t], ["both", "dispatch pressure", "travel pressure"], "normal")
    return pd.Series(out, index=getattr(dispatch_dev, "index", None))
