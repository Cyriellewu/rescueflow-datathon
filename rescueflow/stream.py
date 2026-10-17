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

    def create(self, cid: int, ts: float, high: bool, held: bool):
        self.pending[cid] = (ts, high, held)
        heapq.heappush(self.oldest, (ts, cid))

    def leave(self, cid: int):
        self.pending.pop(cid, None)

    def snapshot(self, t: float) -> dict:
        while self.oldest and self.oldest[0][1] not in self.pending:
            heapq.heappop(self.oldest)
        snap = {"pending_high": 0, "pending_low": 0, "held_pending_high": 0, "held_pending_low": 0,
                "n_pending_gt_10min": 0,
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
    # (time, kind, id): kind 1 = create sorts before kind 2 = leave at the same instant, so a call
    # that leaves the instant it is created is never left behind as pending
    times = np.concatenate([created, ended])
    kinds = np.concatenate([np.ones(n, dtype=np.int8), np.full(n, 2, dtype=np.int8)])
    ids = np.concatenate([np.arange(n), np.arange(n)])
    order = np.lexsort((kinds, times))
    times, kinds, ids = times[order], kinds[order], ids[order]

    state, rows, i = QueueState(), [], 0
    for t in _seconds(pd.Series(hours)):
        while i < len(times) and times[i] < t:
            cid = ids[i]
            if kinds[i] == 1:
                state.create(cid, created[cid], high[cid], held[cid])
            else:
                state.leave(cid)
            i += 1
        rows.append(state.snapshot(t))
    out = pd.DataFrame(rows)
    out.insert(0, "hour", hours)
    return out, i


def backlog_snapshots(df: pd.DataFrame, hours: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    """Backlog features for every borough at every hour boundary, plus replay throughput."""
    parts, events, start = [], 0, time.perf_counter()
    for borough, calls in df.groupby("borough", sort=True):
        snap, n = replay_borough(calls, hours)
        snap.insert(1, "borough", borough)
        parts.append(snap)
        events += n
    elapsed = time.perf_counter() - start
    stats = {"events": events, "seconds": elapsed, "events_per_s": events / elapsed if elapsed else 0.0}
    return pd.concat(parts, ignore_index=True), stats
