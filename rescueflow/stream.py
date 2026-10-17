"""Replay engine: consume call events in time order and snapshot the unassigned backlog.

This is the "real-time" part: the same code produces training features in batch and scores a
replayed CAD stream on LinuxONE. A call is pending at T if created < T and queue_end >= T.
"""
import heapq
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LONG_WAIT_S = 600


@dataclass
class QueueState:
    pending: dict = field(default_factory=dict)  # call id -> (created_ts, high, held)
    oldest: list = field(default_factory=list)   # heap of (created_ts, call id), lazy deletes
    at_hospital: int = 0                         # units arrived at a hospital, call not closed
    active: int = 0                              # calls with a unit assigned and the incident not yet closed

    def create(self, cid: int, ts: float, high: bool, held: bool):
        self.pending[cid] = (ts, high, held)
        heapq.heappush(self.oldest, (ts, cid))

    def leave(self, cid: int):
        self.pending.pop(cid, None)

    def snapshot(self, t: float) -> dict:
        while self.oldest and self.oldest[0][1] not in self.pending:
            heapq.heappop(self.oldest)
        snap = {"pending_high": 0, "pending_low": 0, "held_pending_high": 0, "held_pending_low": 0,
                "n_pending_gt_10min": 0, "at_hospital": self.at_hospital, "active_responses": self.active,
                "oldest_pending_age_s": t - self.oldest[0][0] if self.oldest else 0.0}
        for created, high, held in self.pending.values():
            band = "high" if high else "low"
            snap[f"pending_{band}"] += 1
            if held:
                snap[f"held_pending_{band}"] += 1
            if t - created > LONG_WAIT_S:
                snap["n_pending_gt_10min"] += 1
        return snap


def _seconds(s: pd.Series) -> np.ndarray:
    return s.astype("datetime64[ns]").astype("int64").to_numpy() / 1e9


def replay_borough(calls: pd.DataFrame, hours: pd.DatetimeIndex) -> tuple[pd.DataFrame, int]:
    """Snapshot one borough's backlog at each hour boundary. Returns (snapshots, events seen)."""
    created = _seconds(calls["incident_datetime"])
    ended = _seconds(calls["queue_end"])
    high = calls["high"].to_numpy()
    held = calls["held"].to_numpy()
    n = len(calls)
    hosp = calls["hosp_arrival"].notna().to_numpy()
    h_in, h_out = _seconds(calls["hosp_arrival"])[hosp], _seconds(calls["hosp_end"])[hosp]
    m = int(hosp.sum())
    work = calls["first_assignment_datetime"].notna().to_numpy()
    w_in, w_out = _seconds(calls["first_assignment_datetime"])[work], _seconds(calls["busy_end"])[work]
    q = int(work.sum())
    # (time, kind, id): create (1) sorts before leave (2) at the same instant, so a call that
    # leaves the instant it is created is never left behind as pending; likewise hospital
    # arrival (3) before hospital departure (4), and unit assigned (5) before incident closed (6)
    times = np.concatenate([created, ended, h_in, h_out, w_in, w_out])
    kinds = np.concatenate([np.ones(n, dtype=np.int8), np.full(n, 2, dtype=np.int8),
                            np.full(m, 3, dtype=np.int8), np.full(m, 4, dtype=np.int8),
                            np.full(q, 5, dtype=np.int8), np.full(q, 6, dtype=np.int8)])
    ids = np.concatenate([np.arange(n), np.arange(n), np.zeros(2 * m + 2 * q, dtype=int)])
    order = np.lexsort((kinds, times))
    times, kinds, ids = times[order], kinds[order], ids[order]

    state, rows, i = QueueState(), [], 0
    for t in _seconds(pd.Series(hours)):
        while i < len(times) and times[i] < t:
            cid = ids[i]
            k = kinds[i]
            if k == 1:
                state.create(cid, created[cid], high[cid], held[cid])
            elif k == 2:
                state.leave(cid)
            elif k == 3:
                state.at_hospital += 1
            elif k == 4:
                state.at_hospital -= 1
            elif k == 5:
                state.active += 1
            else:
                state.active -= 1
            i += 1
        rows.append(state.snapshot(t))
    out = pd.DataFrame(rows)
    out.insert(0, "hour", hours)
    return out, i


def _replay_one(borough, calls, hours):
    snap, n = replay_borough(calls, hours)
    snap.insert(1, "borough", str(borough))
    return snap, n


def backlog_snapshots(df: pd.DataFrame, hours: pd.DatetimeIndex, n_jobs: int = -1) -> tuple[pd.DataFrame, dict]:
    """Backlog features for every borough at every hour boundary, plus replay throughput.
    Boroughs replay independently, so they run in parallel processes (n_jobs=1 for a single-core timing)."""
    from joblib import Parallel, delayed
    groups = [(str(b), calls) for b, calls in df.groupby("borough", sort=True, observed=True)]
    start = time.perf_counter()
    if n_jobs == 1 or len(groups) == 1:
        results = [_replay_one(b, c, hours) for b, c in groups]
    else:
        results = Parallel(n_jobs=n_jobs)(delayed(_replay_one)(b, c, hours) for b, c in groups)
    elapsed = time.perf_counter() - start
    events = sum(n for _, n in results)
    stats = {"events": events, "seconds": elapsed, "events_per_s": events / elapsed if elapsed else 0.0,
             "n_jobs": n_jobs}
    return pd.concat([s for s, _ in results], ignore_index=True), stats
