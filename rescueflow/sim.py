"""SYNTHETIC incident generator for tests and a clearly labeled demo mode. Never for results.

A priority queue per borough: calls arrive (diurnal rate, occasional surges), wait for one of
`units` ambulances, highest acuity first, then travel and stay busy for a service time. Output
has the same columns as scripts/fetch_data.py so the real pipeline runs on it unchanged.
"""
import heapq

import numpy as np
import pandas as pd

ISO = "%Y-%m-%dT%H:%M:%S.000"


def _borough(rng, name, start, hours, base_rate, units, surge_prob):
    t0 = pd.Timestamp(start)
    hour_of_day = np.arange(hours) % 24
    rate = base_rate * (0.6 + 0.6 * np.sin((hour_of_day - 8) / 24 * 2 * np.pi).clip(0) + 0.2)
    surge = rng.random(hours) < surge_prob
    rate = np.where(surge | np.roll(surge, 1) | np.roll(surge, 2), rate * 1.8, rate)
    arrivals = np.sort(np.concatenate(
        [h * 3600 + rng.random(rng.poisson(r)) * 3600 for h, r in enumerate(rate)]))
    sev = rng.choice(np.arange(1, 9), size=len(arrivals),
                     p=[.04, .10, .14, .16, .18, .16, .12, .10])

    free_at = [0.0] * units  # heap of times each unit becomes free
    heapq.heapify(free_at)
    waiting, rows, i = [], [], 0  # waiting: heap of (severity, created, idx)
    clock = 0.0
    while i < len(arrivals) or waiting:
        next_arrival = arrivals[i] if i < len(arrivals) else np.inf
        if waiting and free_at[0] <= next_arrival:
            clock = max(free_at[0], waiting[0][1])
            heapq.heappop(free_at)
            s, created, idx = heapq.heappop(waiting)
            assign = max(clock, created) + rng.uniform(20, 90)
            travel = rng.lognormal(np.log(420), 0.35)
            service = rng.exponential(2400) + 600
            heapq.heappush(free_at, assign + travel + service)
            rows.append((idx, created, assign, travel, s))
        else:
            heapq.heappush(waiting, (sev[i], arrivals[i], i))
            i += 1

    out = pd.DataFrame(rows, columns=["idx", "created", "assign", "travel", "sev"]).sort_values("idx")
    ts = lambda secs: (t0 + pd.to_timedelta(secs, unit="s")).dt.strftime(ISO)
    held = (out["assign"] - out["created"]) > 300
    return pd.DataFrame({
        "incident_datetime": ts(out["created"]),
        "first_assignment_datetime": ts(out["assign"]),
        "first_activation_datetime": ts(out["assign"] + 30),
        "first_on_scene_datetime": ts(out["assign"] + out["travel"]),
        "incident_close_datetime": ts(out["assign"] + out["travel"] + 3600),
        "dispatch_response_seconds_qy": (out["assign"] - out["created"]).round().astype(int),
        "incident_travel_tm_seconds_qy": out["travel"].round().astype(int),
        "incident_response_seconds_qy": (out["assign"] + out["travel"] - out["created"]).round().astype(int),
        "valid_dispatch_rspns_time_indc": "Y",
        "valid_incident_rspns_time_indc": "Y",
        "initial_severity_level_code": out["sev"].astype(str),
        "held_indicator": np.where(held, "Y", "N"),
        "reopen_indicator": "N", "transfer_indicator": "N", "standby_indicator": "N",
        "borough": name,
    })


def synthetic_incidents(weeks=12, boroughs=("BROOKLYN", "QUEENS"), base_rate=20.0, units=26,
                        surge_prob=0.03, start="2025-01-06", seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = [_borough(rng, b, start, weeks * 168, base_rate, units, surge_prob) for b in boroughs]
    return pd.concat(parts, ignore_index=True).sort_values("incident_datetime", ignore_index=True)
