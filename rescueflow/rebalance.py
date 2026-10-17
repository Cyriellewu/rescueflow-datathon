"""Cross-borough unit rebalancing: one plan for all five boroughs.

Each borough has a fleet (units in service there) that can serve about `horizon / cycle` calls per
unit over the planning horizon, and a demand: calls already waiting plus the calls expected to
arrive, scaled up by the warning model's risk. The plan chooses how many FREE units each borough
sends to each other borough so that the severity-weighted number of calls served over the horizon is
as large as possible, minus a small cost per unit-minute in transit.

Why supply is a flow and not "units free right now": a borough taking 40 calls an hour turns a
unit over about once an hour, so its free units are gone in minutes. What matters is whether fleet
x horizon / cycle covers demand. A borough is a donor when that capacity exceeds its own demand
and it has free units to send; it is a receiver when demand exceeds capacity.

Every borough is both a possible donor and a possible receiver (20 directed pairs). A donor is never
stripped for free: units sent away stop counting toward its own capacity, so a transfer happens
only when the receiver gains more than the donor loses. Every borough also wants capacity above its
expected demand, by `buffer_sd` x sqrt(demand) calls (square-root staffing: a queue explodes as
utilisation nears 100%), and a shortfall of that buffer is penalised, so donors stop giving before
they run out of slack and the plan tends to equalise headroom across the five boroughs. A unit that needs T minutes to arrive only
counts (1 - T / horizon) for the receiver; pairs slower than `max_move_min` are not offered.

Solved as a small integer program (HiGHS via scipy.optimize.milp): 20 integer move variables and
10 served-calls variables, milliseconds per solve, so it can be re-run every few minutes.

What the public data does and does not give (docs/data_audit.md): queue sizes, arrivals and risk
come from the replay engine and the warning model. `fleet` and `idle` are NOT in any public dataset.
In the simulator they are exact; on real data they are estimates (the largest number of calls with a
unit assigned and not yet closed, and that minus the number right now), so a real-data plan is a
recommendation to investigate, not an instruction.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from rescueflow.data import BOROUGHS

FLAT_TRANSFER_MIN = 14.0  # same SCENARIO assumption as des.CROSS_MIN, used when no spatial layer is present
SEVERE_SHARE = 0.376      # share of calls with severity 1-3, 2,244,123 of 5,960,214 (docs/performance_audit.md)


@dataclass
class BoroughState:
    borough: str
    fleet: float               # units in service in this borough (busy + free)
    idle: int                  # of those, free now: the only units that can be sent
    queue_high: int            # severity 1-3 calls waiting for a unit
    queue_low: int             # severity 4-8 calls waiting for a unit
    arrivals_per_h: float      # expected new calls per hour (trailing mean or forecast)
    risk: float = 0.0          # warning-model P(stress next hour), 0..1
    inbound: int = 0           # units already on their way here from an earlier plan


@dataclass
class PlanConfig:
    horizon_min: float = 120.0  # a relocated unit stays where it is until the next plan, so look a couple of hours ahead
    cycle_min: float = 60.0    # minutes a unit is tied up per call (assignment to free again)
    w_high: float = 10.0       # value of serving a severity 1-3 call
    w_low: float = 1.0         # value of serving a severity 4-8 call
    risk_gain: float = 0.5     # expected arrivals are scaled by 1 + risk_gain * risk
    move_cost: float = 0.01    # value lost per unit-minute in transit (keeps the plan from shuffling)
    move_fixed: float = 0.3    # value lost per unit moved, whatever the distance
    buffer_sd: float = 1.0     # wanted headroom, in sqrt(demand) calls
    w_buffer: float = 2.0      # value lost per call of missing headroom
    min_keep: int = 1          # a borough never sends away its last `min_keep` free units
    max_move_min: float = 40.0
    severe_share: float = SEVERE_SHARE

    @property
    def calls_per_unit(self) -> float:
        return self.horizon_min / self.cycle_min


def transfer_minutes(spatial_dir: Path | None = None, hour: int = 12) -> dict:
    """Minutes for a unit to drive from one borough's busiest ZIP to another's.

    Straight-line distance between the busiest ZIPs through the spatial layer's fitted response
    model (spatial/spatial_data). Falls back to a flat FLAT_TRANSFER_MIN if the layer is absent.
    """
    d = Path(spatial_dir) if spatial_dir else Path(__file__).resolve().parent.parent / "spatial" / "spatial_data"
    flat = {a: {b: 0.0 if a == b else FLAT_TRANSFER_MIN for b in BOROUGHS} for a in BOROUGHS}
    try:
        import pandas as pd
        zones = pd.read_csv(d / "zones.csv", dtype={"zipcode": str})
        model = json.loads((d / "travel_model.json").read_text())["legs"]["response"]["by_borough"]
    except (OSError, KeyError, ValueError):
        return flat
    hub = zones.sort_values("n_calls").groupby("borough").tail(1).set_index("borough")
    if not set(BOROUGHS) <= set(hub.index):
        return flat

    def km(a, b):
        la1, lo1, la2, lo2 = (np.radians(float(hub.at[k, c])) for k, c in
                              [(a, "lat"), (a, "lon"), (b, "lat"), (b, "lon")])
        h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        return float(6371.0 * 2 * np.arcsin(np.sqrt(h)))

    out = {}
    for a in BOROUGHS:
        out[a] = {}
        for b in BOROUGHS:
            p = model.get(b) or next(iter(model.values()))
            secs = (p["overhead_s"] + p["pace_s_per_km"] * km(a, b)) * p["hour_multiplier"].get(str(hour % 24), 1.0)
            out[a][b] = 0.0 if a == b else round(float(secs) / 60, 1)
    return out


def demand(s: BoroughState, cfg: PlanConfig) -> tuple[float, float]:
    """(high, low) calls that want a unit within the horizon: waiting now plus expected arrivals."""
    new = s.arrivals_per_h * cfg.horizon_min / 60 * (1 + cfg.risk_gain * s.risk)
    return s.queue_high + new * cfg.severe_share, s.queue_low + new * (1 - cfg.severe_share)


def _served(capacity: float, d_hi: float, d_lo: float) -> tuple[float, float]:
    """Capacity fills severe calls first, as priority dispatch does."""
    hi = min(capacity, d_hi)
    return hi, min(max(capacity - hi, 0.0), d_lo)


def plan(states: list[BoroughState], transfer: dict | None = None, cfg: PlanConfig | None = None) -> dict:
    """Best set of unit moves between the given boroughs, with before/after numbers per borough."""
    cfg = cfg or PlanConfig()
    names = [s.borough for s in states]
    transfer = transfer or {a: {b: FLAT_TRANSFER_MIN for b in names} for a in names}
    n, k = len(states), cfg.calls_per_unit
    dem = [demand(s, cfg) for s in states]
    pairs = [(i, j) for i in range(n) for j in range(n)
             if i != j and transfer[names[i]][names[j]] <= cfg.max_move_min]
    m = len(pairs)
    disc = {(i, j): max(0.0, 1 - transfer[names[i]][names[j]] / cfg.horizon_min) for i, j in pairs}

    # variables: x[0:m] units moved per pair (integer), served_high[n], served_low[n], missing_headroom[n]
    nv = m + 3 * n
    c, ub = np.zeros(nv), np.full(nv, np.inf)
    buf = [cfg.buffer_sd * np.sqrt(d[0] + d[1]) for d in dem]
    for p, (i, j) in enumerate(pairs):
        c[p] = cfg.move_fixed + cfg.move_cost * transfer[names[i]][names[j]]
        ub[p] = max(states[i].idle - cfg.min_keep, 0)
    A, hi = [], []
    for b in range(n):
        c[m + b], c[m + n + b], c[m + 2 * n + b] = -cfg.w_high, -cfg.w_low, cfg.w_buffer
        ub[m + b], ub[m + n + b] = dem[b]
        # served <= calls_per_unit * (fleet + inbound - sent + discounted arrivals)
        row = np.zeros(nv)
        row[m + b] = row[m + n + b] = 1
        for p, (i, j) in enumerate(pairs):
            if i == b:
                row[p] += k
            if j == b:
                row[p] -= k * disc[(i, j)]
        A.append(row)
        hi.append(k * (states[b].fleet + states[b].inbound))
        # headroom: capacity - served + missing >= buffer, i.e. the same row with -missing and a smaller bound
        row2 = row.copy()
        row2[m + 2 * n + b] = -1
        A.append(row2)
        hi.append(k * (states[b].fleet + states[b].inbound) - buf[b])
        # a borough sends at most the free units it holds beyond min_keep, summed over destinations
        send = np.zeros(nv)
        for p, (i, _) in enumerate(pairs):
            if i == b:
                send[p] = 1
        A.append(send)
        hi.append(max(states[b].idle - cfg.min_keep, 0))
    integrality = np.r_[np.ones(m), np.zeros(3 * n)]
    res = milp(c, constraints=LinearConstraint(np.vstack(A), -np.inf, np.array(hi, dtype=float)),
               integrality=integrality, bounds=Bounds(np.zeros(nv), ub)) if m else None
    x = np.rint(res.x[:m]).astype(int) if res is not None and res.success else np.zeros(m, dtype=int)

    moves = [{"from": names[i], "to": names[j], "units": int(u), "eta_min": transfer[names[i]][names[j]]}
             for (i, j), u in zip(pairs, x) if u > 0]
    rows, w_before, w_after = [], 0.0, 0.0
    for b, s in enumerate(states):
        sent = sum(int(u) for (i, _), u in zip(pairs, x) if i == b)
        got = sum(int(u) for (_, j), u in zip(pairs, x) if j == b)
        arrive = sum(u * disc[(i, j)] for (i, j), u in zip(pairs, x) if j == b)
        before = _served(k * (s.fleet + s.inbound), *dem[b])
        after = _served(k * (s.fleet + s.inbound - sent + arrive), *dem[b])
        cap0, cap1 = k * (s.fleet + s.inbound), k * (s.fleet + s.inbound - sent + arrive)
        miss0, miss1 = max(0.0, buf[b] - (cap0 - sum(before))), max(0.0, buf[b] - (cap1 - sum(after)))
        w_before += cfg.w_high * before[0] + cfg.w_low * before[1] - cfg.w_buffer * miss0
        w_after += cfg.w_high * after[0] + cfg.w_low * after[1] - cfg.w_buffer * miss1
        total = dem[b][0] + dem[b][1]
        rows.append({"borough": s.borough, "fleet": round(s.fleet, 1), "idle": s.idle,
                     "queue_high": s.queue_high, "queue_low": s.queue_low, "risk": round(s.risk, 3),
                     "expected_calls": round(total - s.queue_high - s.queue_low, 1), "demand": round(total, 1),
                     "capacity_before": round(float(cap0), 1), "capacity_after": round(float(cap1), 1),
                     "headroom_wanted": round(float(buf[b]), 1),
                     "headroom_before": round(float(cap0 - total), 1), "headroom_after": round(float(cap1 - total), 1),
                     "sends": sent, "receives": got,
                     "unmet_before": round(float(total - sum(before)), 1), "unmet_after": round(float(total - sum(after)), 1)})
    return {"moves": moves, "boroughs": rows, "units_moved": int(x.sum()),
            "value_before": round(w_before, 2), "value_after": round(w_after, 2),
            "value_gain": round(w_after - w_before, 2), "config": asdict(cfg),
            "note": "fleet and free units are ESTIMATES on real data (exact only in the simulator)"}


def describe(p: dict) -> list[str]:
    """One plain sentence per move, from numbers in the plan only."""
    by = {r["borough"]: r for r in p["boroughs"]}
    out = []
    for mv in p["moves"]:
        a, b = by[mv["from"]], by[mv["to"]]
        out.append(f"Move {mv['units']} free unit{'s' if mv['units'] > 1 else ''} {mv['from'].title()} → {mv['to'].title()} "
                   f"(~{mv['eta_min']:.0f} min): {mv['to'].title()} expects {b['demand']:.0f} calls against capacity "
                   f"{b['capacity_before']:.0f}; {mv['from'].title()} expects {a['demand']:.0f} against {a['capacity_before']:.0f}.")
    return out or ["No transfer improves coverage: no borough has capacity to spare that a short enough drive can use."]
