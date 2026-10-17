"""Discrete-event EMS simulator ("policy lab"): does early warning lead to better decisions?

Calls come from a real (or synthetic) incident stream: creation time, borough, severity.
Everything about the fleet is a labeled SCENARIO assumption: units per borough, on-scene time,
transport share, hospital handover slots and time. In-borough travel medians are calibrated from
FDNY data; cross-borough travel is an assumption.

Unit cycle: assigned → travel → on scene → (transport → wait for a handover slot → handover)
→ available where it is. Dispatch: per-borough priority queue (severity, then arrival time); a
free unit in the call's borough first; for severity 1–3 only, a free unit elsewhere (mutual aid).

Arms differ only in when reserve units are activated, under the same reserve budget:
  baseline  never
  reactive  when a borough's high-acuity queue reaches a threshold (no prediction)
  ai        when the warning model's risk for the next hour crosses its threshold

Two further policies move FREE units between boroughs instead of adding reserves (rescueflow/rebalance.py
solves the plan every `rebalance_min` minutes; a unit in transit is unavailable until it arrives):
  rebalance     plan from the online queue and trailing arrival rate only
  rebalance_ai  same plan, with each borough's expected arrivals scaled up by the warning model's risk
"""
import heapq
import json
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from rescueflow import rebalance

CROSS_MIN = 14.0  # minutes for a cross-borough response (SCENARIO assumption)


_MATRIX = None


def _matrix():
    """Borough-to-borough expected travel by hour from the spatial module (spatial/build_matrix.py), if built."""
    global _MATRIX
    if _MATRIX is None:
        p = Path(__file__).resolve().parent.parent / "spatial" / "spatial_data" / "borough_travel_matrix.json"
        _MATRIX = json.loads(p.read_text())["minutes_by_hour"] if p.exists() else {}
    return _MATRIX


def travel_minutes(sc, from_borough: str, to_borough: str, hour_of_day: int | None = None) -> float:
    """Median travel time for a response leg. In-borough: the borough's observed FDNY median. Cross-borough:
    the spatial model's expected base->ZIP time for that origin/destination pair and hour (fitted on FDNY
    transport legs, straight-line distance x calibrated pace), floored at CROSS_MIN; CROSS_MIN if the
    matrix is not built."""
    if from_borough == to_borough:
        return sc.travel_min.get(to_borough, 8.0)
    mx = _matrix()
    row, own = mx.get(f"{from_borough}|{to_borough}"), mx.get(f"{to_borough}|{to_borough}")
    if row is None or own is None:
        return max(sc.travel_min.get(to_borough, 8.0), CROSS_MIN)
    h = 12 if hour_of_day is None else int(hour_of_day) % 24
    # the spatial model was fitted on transport legs (slower than lights-and-sirens response); rescale by the
    # destination borough's observed FDNY in-borough median over the model's in-borough estimate
    scale = sc.travel_min.get(to_borough, 8.0) / max(float(own[h]), 1.0)
    return max(float(row[h]) * scale, sc.travel_min.get(to_borough, 8.0))
SIM_FEATURES = ["pending_high", "pending_low", "n_pending_gt_10min", "oldest_pending_age_min",
                "n_calls_lag1", "n_calls_lag3", "busy_share", "hosp_waiting", "hour_of_day"]


@dataclass
class Scenario:
    units: dict                                   # borough -> staffed units
    travel_min: dict                              # borough -> median in-borough travel minutes
    scene_min: float = 20.0                       # mean on-scene time
    transport_share: float = 0.65                 # share of calls transported to hospital
    transport_min: float = 12.0
    handover_min: float = 20.0                    # mean hospital handover time
    handover_slots: dict = field(default_factory=dict)  # borough -> concurrent handovers
    shock: dict = field(default_factory=dict)     # {"borough", "start_h", "end_h", "factor"}
    congestion: float = 1.0                       # travel-time multiplier (rush-hour toggle)
    mutual_aid: bool = True
    reserve_units: int = 3                        # units a borough activates per trigger
    reserve_hours: float = 2.0                    # length of one activation
    reserve_budget_unit_h: float = 36.0           # cap on reserve unit-hours per run, citywide
    traffic: dict = field(default_factory=dict)   # borough -> list of travel multipliers per hour of the replayed week
                                                  # (NYC DOT speeds: borough median speed / that hour's speed); {} = none
    hold_floor: float = 0.10                      # SCENARIO: share of a borough's units kept free for high-acuity calls;
                                                  # low-acuity calls are held while idle units are at or below this floor
                                                  # (FDNY holds ~43% of low-acuity calls; the simulator had no such rule)
    reactive_queue: int = 3                       # reactive trigger: calls of the watched acuity waiting
    watch: str = "high"                           # which queue the arms watch and the lab scores: "high" (sev 1-3) or "low" (4-8)
    rebalance_min: float = 60.0                   # decision grid for the rebalance policies (RB-01: hourly)
    rebalance_cap: float = 100.0                  # max units relocated per run for the gated policies (equal budget)
    rebalance_cap_min: float = 2000.0             # max relocation unit-minutes per run (shared; 100 moves x ~20 min)
    max_moves_per_decision: int = 3               # citywide, per decision (RB-01)
    transfer_min: dict | None = None              # borough -> borough minutes for a relocation; None = CROSS_MIN everywhere
    plan_cfg: rebalance.PlanConfig = field(default_factory=rebalance.PlanConfig)


class Sim:
    def __init__(self, calls: pd.DataFrame, sc: Scenario, policy="baseline", risk_fn=None,
                 threshold=0.5, seed=0, log_events=False, collect_features=False, snapshot_min=None):
        self.sc, self.policy, self.risk_fn, self.thr = sc, policy, risk_fn, threshold
        # Common random numbers: each call's random quantities are drawn up front by call id, so
        # the same call gets the same travel, scene, transport and handover draws in every arm.
        rng = np.random.default_rng(seed)
        n = len(calls)
        self.draw = {"proc": rng.uniform(0.3, 1.5, n), "travel_z": rng.normal(0, 1, n),
                     "scene": rng.exponential(1.0, n), "transport": rng.random(n),
                     "transport_z": rng.normal(0, 1, n), "handover": rng.exponential(1.0, n)}
        self.t0 = calls["incident_datetime"].min().floor("h")
        mins = (calls["incident_datetime"] - self.t0).dt.total_seconds().to_numpy() / 60.0
        self.calls = list(zip(mins, calls["borough"], calls["severity"].astype(int)))
        self.home, self.loc, self.expires, self.off = [], [], [], set()
        self.idle = {b: set() for b in sc.units}
        for b, n in sc.units.items():
            for _ in range(n):
                self._new_unit(b, np.inf)
        self.queue = {b: [] for b in sc.units}      # heap of (severity, created, call idx)
        self.hosp_busy = {b: 0 for b in sc.units}
        self.hosp_wait = {b: deque() for b in sc.units}
        self.recent = {b: deque() for b in sc.units}
        self.events, self.seq = [], 0
        self.records, self.activations, self.reserve_unit_h = [], [], 0.0
        self.log = [] if log_events else None
        self.hour_rows = [] if collect_features else None
        self.snapshot_min = snapshot_min
        self.snaps = []
        self.busy_in = {b: 0 for b in sc.units}     # units working a call in this borough
        self.transit = {b: 0 for b in sc.units}     # relocating units on their way to this borough
        self.moves = []                              # (t, from, to, units) executed by a rebalance policy
        self.reloc_minutes = 0.0                     # relocation unit-minutes spent (units x transfer time)

    def _new_unit(self, borough, expires):
        uid = len(self.home)
        self.home.append(borough)
        self.loc.append(borough)
        self.expires.append(expires)
        self.idle[borough].add(uid)
        return uid

    def push(self, t, kind, payload=None):
        self.seq += 1
        heapq.heappush(self.events, (t, self.seq, kind, payload))

    def emit(self, t, kind, **kw):
        if self.log is not None:
            self.log.append({"sim_min": round(float(t), 2), "event": kind, **kw})

    @staticmethod
    def lognorm(median, z, sigma=0.35):
        return float(np.exp(np.log(max(median, 0.1)) + sigma * z))

    # ---- dispatch -------------------------------------------------------------------------
    def try_dispatch(self, t):
        while True:
            waiting = sorted((q[0][:2], b) for b, q in self.queue.items() if q)
            for (sev, _), b in waiting:
                if self.idle[b]:
                    if sev > 3 and len(self.idle[b]) <= self._floor(b):
                        continue  # hold the low-acuity call: keep the last units free for severity 1-3
                    self.assign(t, b, min(self.idle[b]))
                    break
                if self.sc.mutual_aid and sev <= 3:
                    donors = [d for d in self.idle if self.idle[d]]
                    if donors:  # take from the borough with the most idle units
                        d = max(donors, key=lambda d: len(self.idle[d]))
                        self.assign(t, b, min(self.idle[d]))
                        break
            else:
                return

    def assign(self, t, borough, uid):
        sev, created, idx = heapq.heappop(self.queue[borough])
        self.idle[self.loc[uid]].discard(uid)
        cross = self.loc[uid] != borough
        self.busy_in[borough] += 1
        d = self.draw
        t_assign = t + float(d["proc"][idx])  # dispatcher processing
        base = travel_minutes(self.sc, self.loc[uid], borough, (self.t0 + pd.Timedelta(minutes=float(t))).hour)
        tf = self.sc.traffic.get(borough)
        traffic = tf[min(int(t // 60), len(tf) - 1)] if tf else 1.0   # real road speed that hour, if provided
        travel = self.lognorm(base * self.sc.congestion * traffic, d["travel_z"][idx])
        self.records.append((idx, borough, sev, created, t_assign, t_assign + travel, cross, self.expires[uid] < np.inf))
        self.emit(t_assign, "assign", unit=uid, call=int(idx), borough=borough, severity=sev, cross=cross)
        done = t_assign + travel + float(d["scene"][idx]) * self.sc.scene_min
        if d["transport"][idx] < self.sc.transport_share:
            self.push(done + self.lognorm(self.sc.transport_min, d["transport_z"][idx]), "arrive_hospital",
                      (uid, borough, idx))
        else:
            self.push(done, "free", (uid, borough))

    # ---- hospital handover ----------------------------------------------------------------
    def handover_time(self, b, t, idx):
        s = self.sc.shock
        f = s["factor"] if s and s["borough"] == b and s["start_h"] * 60 <= t < s["end_h"] * 60 else 1.0
        return float(self.draw["handover"][idx]) * self.sc.handover_min * f

    def arrive_hospital(self, t, uid, b, idx):
        self.emit(t, "arrive_hospital", unit=uid, borough=b)
        if self.hosp_busy[b] < self.sc.handover_slots.get(b, 10):
            self.hosp_busy[b] += 1
            self.push(t + self.handover_time(b, t, idx), "handover_done", (uid, b))
        else:
            self.hosp_wait[b].append((uid, idx))

    def handover_done(self, t, uid, b):
        if self.hosp_wait[b]:
            nxt, idx = self.hosp_wait[b].popleft()
            self.push(t + self.handover_time(b, t, idx), "handover_done", (nxt, b))
        else:
            self.hosp_busy[b] -= 1
        self.free(t, uid, b)

    def free(self, t, uid, b):
        self.busy_in[b] -= 1
        self.loc[uid] = b
        if self.expires[uid] <= t:
            self.off.add(uid)  # reserve activation ended while busy: goes off shift now
        else:
            self.idle[b].add(uid)
        self.emit(t, "free", unit=uid, borough=b)
        self.try_dispatch(t)

    # ---- reserves and policies ------------------------------------------------------------
    def activate(self, t, b, why):
        sc = self.sc
        if any(a["borough"] == b and a["until"] > t for a in self.activations):
            return
        cost = sc.reserve_units * sc.reserve_hours
        if self.reserve_unit_h + cost > sc.reserve_budget_unit_h + 1e-9:
            return
        self.reserve_unit_h += cost
        until = t + sc.reserve_hours * 60
        self.activations.append({"borough": b, "at_min": t, "until": until, "why": why})
        self.emit(t, "activate_reserve", borough=b, units=sc.reserve_units, why=why)
        for _ in range(sc.reserve_units):
            self.push(until, "expire", self._new_unit(b, until))
        self.try_dispatch(t)

    def expire(self, uid):
        for s in self.idle.values():
            if uid in s:
                s.discard(uid)
                self.off.add(uid)

    def features(self, t, b) -> dict:
        """Online state at time t, known at t (no look-ahead)."""
        q, rc = self.queue[b], self.recent[b]
        while rc and rc[0] < t - 180:
            rc.popleft()
        return {"borough": b, "t": float(t),
                "pending_high": sum(1 for s, _, _ in q if s <= 3),
                "pending_low": sum(1 for s, _, _ in q if s > 3),
                "n_pending_gt_10min": sum(1 for _, c, _ in q if t - c > 10),
                "oldest_pending_age_min": t - min((c for _, c, _ in q), default=t),
                "n_calls_lag1": sum(1 for c in rc if c >= t - 60), "n_calls_lag3": len(rc),
                # units in this borough right now: working a call here, or idle here
                "busy_share": self.busy_in[b] / max(self.busy_in[b] + len(self.idle[b]), 1),
                "hosp_waiting": len(self.hosp_wait[b]),
                "hour_of_day": (self.t0 + pd.Timedelta(minutes=float(t))).hour}

    def hourly(self, t):
        for b in self.queue:
            f = None
            if self.hour_rows is not None:
                f = self.features(t, b)
                self.hour_rows.append({"t": t, "borough": b, **f})
            if self.policy == "ai" and self.risk_fn is not None:
                f = f or self.features(t, b)
                if self.risk_fn(f) >= self.thr:
                    self.activate(t, b, "ai warning")

    # ---- cross-borough rebalancing --------------------------------------------------------
    def move_minutes(self, a, b) -> float:
        return self.sc.transfer_min[a][b] if self.sc.transfer_min else CROSS_MIN

    def rebalance_now(self, t):
        """Plan with the online state at t and send the planned free units on their way.

        Policies: `rebalance` plans every interval; `rebalance_ai` the same with warning risk in the plan;
        `rebalance_reactive` plans only when some borough's watched queue reaches the reactive threshold;
        `rebalance_predictive` plans only when some borough's warning risk crosses the alert threshold.
        The two gated policies share the same cap on units relocated per run (equal budget)."""
        # trigger x planner matrix (RB-01 diagnostics): who decides WHEN, and whether the planner sees the risk
        GATED = {"rebalance_reactive": ("queue", False), "rebalance_predictive": ("risk", True),
                 "rebalance_reactive_riskplan": ("queue", True), "rebalance_predictive_stateplan": ("risk", False)}
        gated = self.policy in GATED
        feats = {b: self.features(t, b) for b in self.queue}
        if gated:
            trigger, plan_with_risk = GATED[self.policy]
            moved = sum(n for *_, n in self.moves)
            if moved >= self.sc.rebalance_cap or self.reloc_minutes >= self.sc.rebalance_cap_min:
                return
            if trigger == "queue":
                fire = any(sum(1 for s, _, _ in self.queue[b] if self._watched(s)) >= self.sc.reactive_queue for b in self.queue)
            else:
                fire = self.risk_fn is not None and any(self.risk_fn(feats[b]) >= self.thr for b in self.queue)
            if not fire:
                return
            use_risk = plan_with_risk and self.risk_fn is not None
        else:
            use_risk = self.policy == "rebalance_ai" and self.risk_fn is not None
        states = []
        for b in self.queue:
            f = feats[b]
            risk = self.risk_fn(f) if use_risk else 0.0
            states.append(rebalance.BoroughState(
                b, fleet=len(self.idle[b]) + self.busy_in[b], idle=len(self.idle[b]),
                queue_high=f["pending_high"], queue_low=f["pending_low"],
                arrivals_per_h=f["n_calls_lag3"] / min(3.0, max(t / 60, 0.25)), risk=risk, inbound=self.transit[b]))
        transfer = {a: {b: self.move_minutes(a, b) for b in self.queue} for a in self.queue}
        remaining = (self.sc.rebalance_cap - sum(n for *_, n in self.moves)) if gated else float("inf")
        remaining_min = (self.sc.rebalance_cap_min - self.reloc_minutes) if gated else float("inf")
        per_decision = self.sc.max_moves_per_decision if gated else float("inf")
        for mv in rebalance.plan(states, transfer, self.sc.plan_cfg)["moves"]:
            src, dst = mv["from"], mv["to"]
            tm = self.move_minutes(src, dst)
            by_minutes = float("inf") if remaining_min == float("inf") else int(max(remaining_min, 0) // max(tm, 1e-9))
            allowed = min(mv["units"], max(remaining, 0), per_decision, by_minutes)
            mv = {**mv, "units": int(allowed)}
            if mv["units"] <= 0:
                continue
            remaining -= mv["units"]; per_decision -= mv["units"]
            remaining_min -= mv["units"] * tm; self.reloc_minutes += mv["units"] * tm
            # send units that belong to the destination first (they are going home)
            for uid in sorted(self.idle[src], key=lambda u: (self.home[u] != dst, u))[:mv["units"]]:
                self.idle[src].discard(uid)
                self.transit[dst] += 1
                self.push(t + self.move_minutes(src, dst), "relocated", (uid, dst))
                self.emit(t, "relocate", unit=uid, src=src, dst=dst)
            self.moves.append((t, src, dst, mv["units"]))

    def relocated(self, t, uid, dst):
        self.transit[dst] -= 1
        self.loc[uid] = dst
        self.idle[dst].add(uid)
        self.emit(t, "arrive_relocated", unit=uid, borough=dst)
        self.try_dispatch(t)

    def snapshot(self, t):
        """Per-borough state for the dashboard (counts only; no GPS positions are simulated)."""
        for b in self.queue:
            q = self.queue[b]
            self.snaps.append({"t": t, "borough": b, "q_high": sum(1 for s, _, _ in q if s <= 3),
                               "q_low": sum(1 for s, _, _ in q if s > 3), "idle": len(self.idle[b]),
                               "busy": self.busy_in[b],
                               "at_hospital": self.hosp_busy[b] + len(self.hosp_wait[b]),
                               "hosp_queue": len(self.hosp_wait[b]),
                               "reserve_active": any(a["borough"] == b and a["at_min"] <= t < a["until"]
                                                     for a in self.activations)})

    # ---- run ------------------------------------------------------------------------------
    def run(self) -> "Sim":
        for i, c in enumerate(self.calls):
            self.push(c[0], "call", i)
        end = max(c[0] for c in self.calls)
        for h in range(int(end // 60) + 1):
            self.push(h * 60.0, "hour")
        if self.snapshot_min:
            for k in range(int(end // self.snapshot_min) + 1):
                self.push(k * self.snapshot_min, "snap")
        if self.policy.startswith("rebalance"):
            for k in range(int(end // self.sc.rebalance_min) + 1):
                self.push(k * self.sc.rebalance_min, "rebalance")
        while self.events:
            t, _, kind, p = heapq.heappop(self.events)
            if kind == "call":
                _, b, sev = self.calls[p]
                if b not in self.queue:
                    continue
                heapq.heappush(self.queue[b], (sev, t, p))
                self.recent[b].append(t)
                self.emit(t, "call", call=p, borough=b, severity=sev)
                if self.policy == "reactive" and sum(1 for s, _, _ in self.queue[b] if self._watched(s)) >= self.sc.reactive_queue:
                    self.activate(t, b, "queue threshold")
                self.try_dispatch(t)
            elif kind == "arrive_hospital":
                self.arrive_hospital(t, *p)
            elif kind == "handover_done":
                self.handover_done(t, *p)
            elif kind == "free":
                self.free(t, *p)
            elif kind == "expire":
                self.expire(p)
            elif kind == "hour":
                self.hourly(t)
            elif kind == "snap":
                self.snapshot(t)
            elif kind == "rebalance":
                self.rebalance_now(t)
            elif kind == "relocated":
                self.relocated(t, *p)
        return self

    def _floor(self, b) -> int:
        return int(round(self.sc.units.get(b, 0) * self.sc.hold_floor))

    def _watched(self, sev) -> bool:
        return sev > 3 if self.sc.watch == "low" else sev <= 3

    def results(self) -> pd.DataFrame:
        r = pd.DataFrame(self.records, columns=["idx", "borough", "severity", "created", "assign",
                                                "on_scene", "cross", "by_reserve"])
        r["wait_min"] = r["assign"] - r["created"]
        r["response_min"] = r["on_scene"] - r["created"]
        r["high"] = r["severity"] <= 3
        return r


def summarize(r: pd.DataFrame, sim: Sim | None = None) -> dict:
    h, lo = r[r["high"]], r[~r["high"]]
    out = {
        "calls": len(r),
        "p90_wait_min": float(r["wait_min"].quantile(0.9)),
        "high_p90_wait_min": float(h["wait_min"].quantile(0.9)),
        "high_mean_wait_min": float(h["wait_min"].mean()),
        "high_p90_response_min": float(h["response_min"].quantile(0.9)),
        "high_share_within_10min": float((h["response_min"] <= 10).mean()),
        "worst_borough_high_p90_wait_min": float(h.groupby("borough")["wait_min"].quantile(0.9).max()),
        # low-acuity queue: where a handover shock lands under priority dispatch (audit s4)
        "low_p90_wait_min": float(lo["wait_min"].quantile(0.9)) if len(lo) else float("nan"),
        "low_mean_wait_min": float(lo["wait_min"].mean()) if len(lo) else float("nan"),
        "low_share_within_30min": float((lo["wait_min"] <= 30).mean()) if len(lo) else float("nan"),
        "low_held_share": float((lo["wait_min"] > 10).mean()) if len(lo) else float("nan"),  # cf. FDNY held ~43%
        "worst_borough_low_p90_wait_min": float(lo.groupby("borough")["wait_min"].quantile(0.9).max()) if len(lo) else float("nan"),
        "cross_borough_share": float(r["cross"].mean()),
    }
    if sim is not None:
        out["reserve_unit_h"] = sim.reserve_unit_h
        out["activations"] = len(sim.activations)
        out["units_relocated"] = sum(n for *_, n in sim.moves)
        out["relocation_unit_min"] = float(sim.reloc_minutes)
    return out


def scenario_from_data(df: pd.DataFrame, units_per_call_h=1.15, slots_per_unit=0.3) -> Scenario:
    """SCENARIO fleet sized from observed demand; in-borough travel medians from the data."""
    hours = (df["incident_datetime"].max() - df["incident_datetime"].min()).total_seconds() / 3600
    rate = df.groupby("borough").size() / max(hours, 1)
    travel = (df.groupby("borough")["travel_s"].median() / 60).fillna(8.0)
    units = {b: max(2, int(round(rate[b] * units_per_call_h))) for b in rate.index}
    return Scenario(units=units, travel_min=travel.to_dict(),
                    handover_slots={b: max(1, int(round(n * slots_per_unit))) for b, n in units.items()})


def calibrate_units(calls: pd.DataFrame, sc: Scenario, target_wait_min: dict, seed=0,
                    lo=0.3, hi=2.0, steps=18, q=0.9) -> tuple[Scenario, pd.DataFrame]:
    """Per borough, pick the fleet size whose simulated all-call dispatch-wait quantile `q` is
    closest to the observed FDNY value (mutual aid off so boroughs calibrate independently).
    Default q=0.9: the high-acuity *median* (under 30 s in FDNY data) sits below the simulated
    dispatcher-processing floor, so it cannot size a fleet; the all-call p90 (8–48 min by
    borough) is where real queueing shows and is reachable by the simulator."""
    base = dict(sc.units)
    trials = []
    for f in np.linspace(lo, hi, steps):
        units = {b: max(2, int(round(n * f))) for b, n in base.items()}
        trial = replace(sc, units=units, mutual_aid=False,
                        handover_slots={b: max(1, int(round(n * 0.3))) for b, n in units.items()})
        r = Sim(calls, trial, seed=seed).run().results()
        med = r.groupby("borough")["wait_min"].quantile(q)
        trials += [{"factor": f, "borough": b, "units": units[b], "sim_wait_q": med.get(b, np.nan),
                    "target": target_wait_min.get(b), "q": q} for b in base]
    t = pd.DataFrame(trials).dropna(subset=["target", "sim_wait_q"])
    if t.empty:
        return sc, t
    best = t.loc[(np.log(t["sim_wait_q"].clip(lower=0.1)) - np.log(t["target"].clip(lower=0.1))).abs()
                 .groupby(t["borough"]).idxmin()]
    units = {**base, **dict(zip(best["borough"], best["units"]))}
    return replace(sc, units=units, handover_slots={b: max(1, int(round(n * 0.3))) for b, n in units.items()}), t


def scale_demand(calls: pd.DataFrame, factor: float, seed=0) -> pd.DataFrame:
    """SCENARIO demand multiplier. factor > 1 adds resampled copies of the week's own calls with
    their creation time jittered by up to ±30 min (same borough and severity mix); factor < 1
    thins them. factor == 1 returns the calls unchanged. Deterministic for a given seed."""
    if factor == 1.0 or calls.empty:
        return calls
    rng = np.random.default_rng(seed)
    if factor < 1.0:
        keep = rng.random(len(calls)) < factor
        return calls[keep].sort_values("incident_datetime").reset_index(drop=True)
    n_extra = int(round((factor - 1.0) * len(calls)))
    extra = calls.sample(n=n_extra, replace=True, random_state=int(rng.integers(2**31 - 1))).copy()
    extra["incident_datetime"] = extra["incident_datetime"] + pd.to_timedelta(rng.uniform(-30, 30, n_extra), unit="m")
    lo, hi = calls["incident_datetime"].min(), calls["incident_datetime"].max()
    extra["incident_datetime"] = extra["incident_datetime"].clip(lo, hi)
    return pd.concat([calls, extra], ignore_index=True).sort_values("incident_datetime").reset_index(drop=True)


def traffic_factors(week_start, hours=7 * 24, baseline_weeks=8) -> dict:
    """Per-borough hourly travel multipliers for a replayed week from NYC DOT speeds
    (data/traffic_borough_hour.csv): baseline median speed over the prior weeks / that hour's speed,
    clipped to [0.7, 2.0]; 1.0 where no reading. {} if the file is absent."""
    p = Path(__file__).resolve().parent.parent / "data" / "traffic_borough_hour.csv"
    if not p.exists():
        return {}
    tr = pd.read_csv(p, parse_dates=["hour"])
    t0 = pd.Timestamp(week_start)
    base = tr[(tr["hour"] >= t0 - pd.Timedelta(weeks=baseline_weeks)) & (tr["hour"] < t0)]
    med = base.groupby("borough")["mean_speed_mph"].median()
    week = tr[(tr["hour"] >= t0) & (tr["hour"] < t0 + pd.Timedelta(hours=hours))]
    out = {}
    for b, g in week.groupby("borough"):
        if b not in med or not np.isfinite(med[b]):
            continue
        idx = ((g["hour"] - t0) / pd.Timedelta(hours=1)).astype(int)
        f = np.ones(hours)
        f[idx.to_numpy()] = (med[b] / g["mean_speed_mph"].clip(lower=1)).clip(0.7, 2.0).to_numpy()
        out[b] = f.tolist()
    return out


def with_shock(sc: Scenario, borough, start_h, end_h, factor) -> Scenario:
    return replace(sc, shock={"borough": borough, "start_h": start_h, "end_h": end_h, "factor": factor})


# ---- warning model for the "ai" arm -------------------------------------------------------
def hourly_training_rows(calls, sc: Scenario, seed) -> pd.DataFrame:
    """Run the baseline arm and pair each hour's online state with next hour's outcome."""
    sim = Sim(calls, sc, "baseline", seed=seed, collect_features=True).run()
    X = pd.DataFrame(sim.hour_rows)
    r = sim.results()
    watched = ~r["high"] if sc.watch == "low" else r["high"]
    r = r[watched].assign(t=(r["created"] // 60) * 60)
    med = r.groupby(["borough", "t"])["wait_min"].median().rename("next_wait").reset_index()
    return X.merge(med, on=["borough", "t"], how="left")  # outcome for [t, t+60)


DEMAND_SIM_FEATURES = ["n_calls_lag1", "n_calls_lag3", "hour_of_day"]   # ablation: no queue state


def train_warning_model(windows, scenarios, seeds, wait_threshold_min=None, features=SIM_FEATURES, rows=None):
    """Fit on training windows/seeds only; label = next-hour median wait of the watched acuity above threshold.
    `features` selects the inputs (ablations); `rows` reuses already simulated training rows."""
    from rescueflow.model import xgb
    if rows is None:
        rows = pd.concat([hourly_training_rows(c, s, seed) for c, s in zip(windows, scenarios) for seed in seeds],
                         ignore_index=True).dropna(subset=["next_wait"])
    thr = wait_threshold_min or float(rows["next_wait"].quantile(0.8))
    y = (rows["next_wait"] > thr).astype(int)
    clf = xgb.XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.1, eval_metric="logloss")
    clf.fit(rows[features], y)
    clf._sim_features = list(features)
    return clf, thr, rows


def risk_fn_for(clf):
    feats = getattr(clf, "_sim_features", SIM_FEATURES)
    def fn(f: dict) -> float:
        return float(clf.predict_proba(pd.DataFrame([f])[feats])[:, 1][0])
    return fn


def hour_of_week_risk_fn(rows, thr):
    """Ablation B: risk = historical rate of a late next hour by hour of day (training rows only)."""
    rate = (rows["next_wait"] > thr).groupby(rows["hour_of_day"]).mean().to_dict()
    base = float((rows["next_wait"] > thr).mean())
    return lambda f: float(rate.get(int(f["hour_of_day"]), base))


def oracle_risk_fn(calls, sc, thr=None, seed=0, q=0.95):
    """P3 oracle (upper bound, offline only): perfect knowledge of EXOGENOUS next-hour arrivals, never of
    policy-dependent waits. risk = 1 when the destination borough's call count in [t, t+60) is at or above its
    own q-quantile of hourly counts over the week (relative surge), else the count's percentile rank."""
    t0 = calls["incident_datetime"].min().floor("h")
    h = ((calls["incident_datetime"] - t0).dt.total_seconds() // 3600).astype(int)
    cnt = calls.groupby([calls["borough"].astype(str), h]).size()
    cut = cnt.groupby(level=0).quantile(q)
    lo = cnt.groupby(level=0).min(); hi = cnt.groupby(level=0).max()
    table = {k: (1.0 if v >= cut[k[0]] else float((v - lo[k[0]]) / max(hi[k[0]] - lo[k[0]], 1)) * 0.9) for k, v in cnt.items()}
    return lambda f: table.get((f["borough"], int(f["t"] // 60)), 0.0)


def _run_arm(calls, name, policy, sc, risk_fn, threshold, seed):
    sim = Sim(calls, sc, policy, risk_fn, threshold, seed).run()
    return {"arm": name, "seed": seed, **summarize(sim.results(), sim)}


def experiment(calls, arms: dict, seeds, risk_fn=None, threshold=0.5, n_jobs: int = -1) -> pd.DataFrame:
    """Every arm sees the same calls and seeds (common random numbers). One row per run.
    An arm is (policy, scenario) or (policy, scenario, risk_fn, threshold) for its own risk input (ablations).
    Runs are independent, so they fan out over all cores (n_jobs=1 to time a single core)."""
    from joblib import Parallel, delayed
    def unpack(v):
        policy, sc = v[0], v[1]
        return policy, sc, (v[2] if len(v) > 2 else risk_fn), (v[3] if len(v) > 3 else threshold)
    jobs = [(name, *unpack(v), seed) for seed in seeds for name, v in arms.items()]
    if n_jobs == 1:
        rows = [_run_arm(calls, n, p, sc, rf, th, s) for n, p, sc, rf, th, s in jobs]
    else:
        rows = Parallel(n_jobs=n_jobs)(delayed(_run_arm)(calls, n, p, sc, rf, th, s) for n, p, sc, rf, th, s in jobs)
    return pd.DataFrame(rows)


def compare(runs: pd.DataFrame, a: str, b: str, metric: str) -> dict:
    """Paired difference b − a across seeds, with a normal-approximation 95% CI."""
    x = runs[runs.arm == a].set_index("seed")[metric]
    y = runs[runs.arm == b].set_index("seed")[metric]
    d = (y - x).dropna()
    from scipy.stats import t as student_t
    n = len(d)
    half = student_t.ppf(0.975, n - 1) * d.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {"metric": metric, "a": a, "b": b, "mean_a": float(x.mean()), "mean_b": float(y.mean()),
            "diff": float(d.mean()), "ci95": [float(d.mean() - half), float(d.mean() + half)], "n_seeds": n}
