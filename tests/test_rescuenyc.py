"""Small hand-checked cases for the queue counts and the label."""
import numpy as np
import pandas as pd

from rescuenyc.table import build_table, covering

T0 = pd.Timestamp("2026-01-05 00:00")


def ts(*hours):
    return np.array([T0 + pd.Timedelta(hours=h) for h in hours], dtype="datetime64[ns]")


def test_covering_counts_calls_still_waiting_at_the_cutoff():
    created = ts(0.2, 0.5, 0.9)
    left = ts(0.3, 1.5, 2.5)          # first call got a unit before 01:00, the other two did not
    assert covering(created, left, ts(1, 2)).tolist() == [2, 1]


def test_covering_ignores_empty_intervals():
    # "waiting > 10 min" for a call assigned after 5 min: start (created+10min) is after end
    start = ts(0.5) + np.timedelta64(10, "m")
    end = ts(0.5) + np.timedelta64(5, "m")
    assert covering(start, end, ts(0.55, 1)).tolist() == [0, 0]


def _calls(weeks_waits):
    """Five low-acuity calls at Monday 00:10 of each week, all with the given dispatch wait."""
    rows = []
    for w, wait in enumerate(weeks_waits):
        t = T0 + pd.Timedelta(weeks=w, minutes=10)
        for _ in range(5):
            rows.append({"borough": "BROOKLYN", "created": t, "assigned": t + pd.Timedelta(seconds=wait),
                         "on_scene": pd.NaT, "at_hospital": pd.NaT, "closed": t + pd.Timedelta(hours=1),
                         "severity": 5, "high": False, "held": False, "dispatch_s": float(wait), "travel_s": np.nan})
    c = pd.DataFrame(rows)
    c["left_queue"] = c["assigned"]
    return c


def test_label_compares_with_the_same_hour_in_previous_weeks():
    t = build_table(_calls([60, 60, 60, 60, 600])).set_index("hour")
    monday = t[t["hour_of_day"].eq(0) & t["day_of_week"].eq(0)]
    assert monday["stressed"].isna().iloc[:4].all()          # fewer than 4 weeks of history
    last = monday.iloc[4]
    assert last["threshold_s"] == 60 and last["low_dispatch_median_s"] == 600 and last["stressed"] == 1
