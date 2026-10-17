"""Build the borough x hour table: 20 inputs known at time T, and the answer for [T, T+1h).

One row = one borough at one whole hour T (e.g. BROOKLYN, Fri 2026-09-18 20:00).
Inputs use only what had happened before T. The answer (`stressed`) is about [T, T+1h).
"""
import numpy as np
import pandas as pd

from rescuenyc.config import LABEL_QUANTILE, MIN_CALLS_FOR_LABEL, MIN_TRAILING_WEEKS, TRAILING_WEEKS

H = np.timedelta64(1, "h")
MIN = np.timedelta64(1, "m")

QUEUE = ["pending_high", "pending_low", "held_pending_high", "held_pending_low",
         "pending_low_over_10min", "pending_low_over_30min", "units_at_hospital"]
DEMAND = ["calls_last_1h", "calls_last_3h", "calls_last_24h", "high_calls_last_1h", "usual_calls_this_hour"]
RECENT = ["recent_low_dispatch_s", "recent_high_dispatch_s", "recent_high_travel_s",
          "low_dispatch_vs_usual", "stressed_now"]
TIME = ["hour_of_day", "day_of_week", "borough_code"]
FEATURES = QUEUE + DEMAND + RECENT + TIME          # 20 inputs to the full model
DEMAND_ONLY = DEMAND + TIME                         # what a call-volume forecast knows


def covering(start, end, cutoffs):
    """How many intervals [start, end) are open at each cutoff T: start < T <= end.

    #(start < T) - #(end < T). Empty intervals (end <= start) are dropped first, otherwise they
    would count as -1 between end and start.
    """
    keep = ~(np.isnat(start) | np.isnat(end)) & (end > start)
    s, e = np.sort(start[keep]), np.sort(end[keep])
    return np.searchsorted(s, cutoffs, "left") - np.searchsorted(e, cutoffs, "left")


def created_between(created_sorted, lo, hi):
    return np.searchsorted(created_sorted, hi, "left") - np.searchsorted(created_sorted, lo, "left")


def _hourly_median(times, values, hours):
    """Median of `values`, binned by the hour `times` falls in, aligned to `hours`."""
    s = pd.Series(np.asarray(values, float), index=pd.DatetimeIndex(np.asarray(times))).dropna()
    s = s[s.index.notna()]
    g = s.groupby(s.index.floor("h"))
    return g.median().reindex(hours).to_numpy(), g.size().reindex(hours).fillna(0).to_numpy()


def _borough_rows(c: pd.DataFrame, hours: pd.DatetimeIndex, code: int) -> pd.DataFrame:
    T = hours.values
    created, left = c["created"].values, c["left_queue"].values
    high, held = c["high"].values, c["held"].values
    low = ~high
    cs = np.sort(created)
    cs_high = np.sort(created[high])

    r = pd.DataFrame({"hour": hours, "borough_code": code})
    # queue state at T: created before T, not yet given a unit (or closed) by T
    r["pending_high"] = covering(created[high], left[high], T)
    r["pending_low"] = covering(created[low], left[low], T)
    r["held_pending_high"] = covering(created[high & held], left[high & held], T)
    r["held_pending_low"] = covering(created[low & held], left[low & held], T)
    r["pending_low_over_10min"] = covering(created[low] + 10 * MIN, left[low], T)
    r["pending_low_over_30min"] = covering(created[low] + 30 * MIN, left[low], T)
    r["units_at_hospital"] = covering(c["at_hospital"].values, c["closed"].values, T)

    # call volume before T
    r["calls_last_1h"] = created_between(cs, T - H, T)
    r["calls_last_3h"] = created_between(cs, T - 3 * H, T)
    r["calls_last_24h"] = created_between(cs, T - 24 * H, T)
    r["high_calls_last_1h"] = created_between(cs_high, T - H, T)
    r["calls_this_hour"] = created_between(cs, T, T + H)  # only used for the trailing average

    # delays that became known in the hour before T (binned by when the unit was assigned / arrived)
    lo_assign, _ = _hourly_median(c.loc[low, "assigned"], c.loc[low, "dispatch_s"], hours)
    hi_assign, _ = _hourly_median(c.loc[high, "assigned"], c.loc[high, "dispatch_s"], hours)
    hi_travel, _ = _hourly_median(c.loc[high, "on_scene"], c.loc[high, "travel_s"], hours)
    r["recent_low_dispatch_s"] = pd.Series(lo_assign).shift(1).to_numpy()
    r["recent_high_dispatch_s"] = pd.Series(hi_assign).shift(1).to_numpy()
    r["recent_high_travel_s"] = pd.Series(hi_travel).shift(1).to_numpy()

    # the answer: low-acuity calls created in [T, T+1h), median FDNY dispatch wait
    med, n = _hourly_median(c.loc[low, "created"], c.loc[low, "dispatch_s"], hours)
    r["low_dispatch_median_s"] = np.where(n >= MIN_CALLS_FOR_LABEL, med, np.nan)
    r["low_calls_with_wait"] = n
    return r


def _trailing(table, col, q):
    """Statistic over the previous TRAILING_WEEKS values at the same borough and hour-of-week."""
    key = [table["borough"], table["day_of_week"] * 24 + table["hour_of_day"]]
    return table.groupby(key)[col].transform(
        lambda s: s.shift(1).rolling(TRAILING_WEEKS, min_periods=MIN_TRAILING_WEEKS).quantile(q))


def build_table(calls: pd.DataFrame) -> pd.DataFrame:
    hours = pd.date_range(calls["created"].min().floor("h"), calls["created"].max().floor("h"), freq="h")
    parts = []
    for code, (b, c) in enumerate(sorted(calls.groupby("borough"), key=lambda x: x[0])):
        r = _borough_rows(c, hours, code)
        r.insert(0, "borough", b)
        parts.append(r)
    t = pd.concat(parts, ignore_index=True)
    t["hour_of_day"] = t["hour"].dt.hour
    t["day_of_week"] = t["hour"].dt.dayofweek

    t["usual_calls_this_hour"] = _trailing(t, "calls_this_hour", 0.5)
    t["threshold_s"] = _trailing(t, "low_dispatch_median_s", LABEL_QUANTILE)
    t["usual_low_dispatch_s"] = _trailing(t, "low_dispatch_median_s", 0.5)
    t["stressed"] = np.where(t["low_dispatch_median_s"].notna() & t["threshold_s"].notna(),
                             (t["low_dispatch_median_s"] > t["threshold_s"]).astype(float), np.nan)

    # "stressed right now": the delay known at T for hour T-1 vs hour T-1's own threshold
    by_b = t.groupby("borough")
    prev_thr, prev_usual = by_b["threshold_s"].shift(1), by_b["usual_low_dispatch_s"].shift(1)
    t["stressed_now"] = np.where(t["recent_low_dispatch_s"].notna() & prev_thr.notna(),
                                 (t["recent_low_dispatch_s"] > prev_thr).astype(float), np.nan)
    t["low_dispatch_vs_usual"] = t["recent_low_dispatch_s"] / prev_usual.clip(lower=1)
    # hindsight only (NOT an input): was the previous hour's answer stressed? Used to pick clean examples.
    t["stressed_prev_hindsight"] = by_b["stressed"].shift(1)
    return t
