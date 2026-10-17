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
"""
import heapq
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

CROSS_MIN = 14.0  # minutes for a cross-borough response (SCENARIO assumption)
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
    reactive_queue: int = 3                       # reactive trigger: high-acuity calls waiting


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
        base = max(self.sc.travel_min.get(borough, 8.0), CROSS_MIN) if cross else self.sc.travel_min.get(borough, 8.0)
        travel = self.lognorm(base * self.sc.congestion, d["travel_z"][idx])
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
        return {"pending_high": sum(1 for s, _, _ in q if s <= 3),
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
        while self.events:
            t, _, kind, p = heapq.heappop(self.events)
            if kind == "call":
                _, b, sev = self.calls[p]
                if b not in self.queue:
                    continue
                heapq.heappush(self.queue[b], (sev, t, p))
                self.recent[b].append(t)
                self.emit(t, "call", call=p, borough=b, severity=sev)
                if self.policy == "reactive" and sum(1 for s, _, _ in self.queue[b] if s <= 3) >= self.sc.reactive_queue:
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
        return self

    def results(self) -> pd.DataFrame:
        r = pd.DataFrame(self.records, columns=["idx", "borough", "severity", "created", "assign",
                                                "on_scene", "cross", "by_reserve"])
        r["wait_min"] = r["assign"] - r["created"]
        r["response_min"] = r["on_scene"] - r["created"]
        r["high"] = r["severity"] <= 3
        return r


def summarize(r: pd.DataFrame, sim: Sim | None = None) -> dict:
    h = r[r["high"]]
    out = {
        "calls": len(r),
        "p90_wait_min": float(r["wait_min"].quantile(0.9)),
        "high_p90_wait_min": float(h["wait_min"].quantile(0.9)),
        "high_mean_wait_min": float(h["wait_min"].mean()),
        "high_p90_response_min": float(h["response_min"].quantile(0.9)),
        "high_share_within_10min": float((h["response_min"] <= 10).mean()),
        "worst_borough_high_p90_wait_min": float(h.groupby("borough")["wait_min"].quantile(0.9).max()),
        "cross_borough_share": float(r["cross"].mean()),
    }
    if sim is not None:
        out["reserve_unit_h"] = sim.reserve_unit_h
        out["activations"] = len(sim.activations)
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
                    lo=0.5, hi=2.0, steps=7) -> tuple[Scenario, pd.DataFrame]:
    """Per borough, pick the fleet size whose simulated median dispatch wait is closest to the
    observed FDNY median (mutual aid off so boroughs calibrate independently)."""
    base = dict(sc.units)
    trials = []
    for f in np.linspace(lo, hi, steps):
        units = {b: max(2, int(round(n * f))) for b, n in base.items()}
        trial = replace(sc, units=units, mutual_aid=False,
                        handover_slots={b: max(1, int(round(n * 0.3))) for b, n in units.items()})
        r = Sim(calls, trial, seed=seed).run().results()
        med = r.groupby("borough")["wait_min"].median()
        trials += [{"factor": f, "borough": b, "units": units[b], "sim_median_wait": med.get(b, np.nan),
                    "target": target_wait_min.get(b)} for b in base]
    t = pd.DataFrame(trials).dropna(subset=["target", "sim_median_wait"])
    if t.empty:
        return sc, t
    best = t.loc[(t["sim_median_wait"] - t["target"]).abs().groupby(t["borough"]).idxmin()]
    units = {**base, **dict(zip(best["borough"], best["units"]))}
    return replace(sc, units=units, handover_slots={b: max(1, int(round(n * 0.3))) for b, n in units.items()}), t


def with_shock(sc: Scenario, borough, start_h, end_h, factor) -> Scenario:
    return replace(sc, shock={"borough": borough, "start_h": start_h, "end_h": end_h, "factor": factor})


# ---- warning model for the "ai" arm -------------------------------------------------------
def hourly_training_rows(calls, sc: Scenario, seed) -> pd.DataFrame:
    """Run the baseline arm and pair each hour's online state with next hour's outcome."""
    sim = Sim(calls, sc, "baseline", seed=seed, collect_features=True).run()
    X = pd.DataFrame(sim.hour_rows)
    r = sim.results()
    r = r[r["high"]].assign(t=(r["created"] // 60) * 60)
    med = r.groupby(["borough", "t"])["wait_min"].median().rename("next_wait").reset_index()
    return X.merge(med, on=["borough", "t"], how="left")  # outcome for [t, t+60)


def train_warning_model(windows, scenarios, seeds, wait_threshold_min=None):
    """Fit on training windows/seeds only; label = next-hour median high-acuity wait above threshold."""
    from rescueflow.model import xgb
    rows = pd.concat([hourly_training_rows(c, s, seed) for c, s in zip(windows, scenarios) for seed in seeds],
                     ignore_index=True).dropna(subset=["next_wait"])
    thr = wait_threshold_min or float(rows["next_wait"].quantile(0.8))
    y = (rows["next_wait"] > thr).astype(int)
    clf = xgb.XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.1, eval_metric="logloss")
    clf.fit(rows[SIM_FEATURES], y)
    return clf, thr, rows


def risk_fn_for(clf):
    def fn(f: dict) -> float:
        return float(clf.predict_proba(pd.DataFrame([f])[SIM_FEATURES])[:, 1][0])
    return fn


def experiment(calls, arms: dict, seeds, risk_fn=None, threshold=0.5) -> pd.DataFrame:
    """Every arm sees the same calls and seeds (common random numbers). One row per run."""
    rows = []
    for seed in seeds:
        for name, (policy, sc) in arms.items():
            sim = Sim(calls, sc, policy, risk_fn, threshold, seed).run()
            rows.append({"arm": name, "seed": seed, **summarize(sim.results(), sim)})
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
