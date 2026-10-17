"""Hospital bottleneck scene: one borough, one day, the handover parameters as sliders.

The simulator decides everything (rescueflow/des.py); this module only sets up a one-borough run with
the chosen handover time and bays and returns 5-minute counts plus a recent-wait series, so the
dashboard can animate hospital queue -> units free -> dispatch queue -> patient wait. SIMULATION:
handover time and bays are scenario parameters, not measured FDNY hospital capacities."""
from dataclasses import fields, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from rescueflow import des

WARMUP_H = 2


def scenario_from_json(d: dict) -> des.Scenario:
    """Rebuild the Scenario saved in policy_lab.json (plan_cfg falls back to its default)."""
    names = {f.name for f in fields(des.Scenario)} - {"plan_cfg"}
    d = {k: v for k, v in d.items() if k in names}
    d["fixed_schedule"] = tuple(tuple(x) for x in d.get("fixed_schedule", ()))
    return des.Scenario(**d)


def export_week(calls: pd.DataFrame, out: Path) -> Path:
    """The evaluation week's calls (time, borough, severity only) for the interactive scenes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    calls[["incident_datetime", "borough", "severity"]].to_csv(out, index=False)
    return out


def load_week(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["incident_datetime"])


def chain(calls: pd.DataFrame, sc: des.Scenario, borough: str, handover_min: float, slots: int,
          day: int = 2, hours: int = 24, seed: int = 0) -> dict:
    """One borough from `day` 00:00 (0 = Monday of the week) for `hours`, with a 2 h warm-up that is
    simulated but not reported. Units, travel and traffic come from the saved scenario."""
    t0 = calls["incident_datetime"].min().floor("D")
    start = t0 + pd.Timedelta(hours=day * 24 - WARMUP_H)
    end = t0 + pd.Timedelta(hours=day * 24 + hours)
    c = calls[(calls["borough"] == borough) & (calls["incident_datetime"] >= start) & (calls["incident_datetime"] < end)]
    tf = sc.traffic.get(borough) if sc.traffic else None
    one = replace(sc, units={borough: sc.units[borough]}, handover_slots={borough: int(slots)}, handover_min=float(handover_min),
                  traffic={borough: list(tf[max(0, day * 24 - WARMUP_H):])} if tf else {}, shock={}, fixed_schedule=())
    sim = des.Sim(c, one, "baseline", seed=seed, snapshot_min=5).run()
    r = sim.results()
    snaps = pd.DataFrame(sim.snaps)
    off = (c["incident_datetime"].min().floor("h") - start).total_seconds() / 60  # sim minutes start at the first call's hour
    snaps["t"] = snaps["t"] + off - WARMUP_H * 60
    r["assign_t"] = r["assign"] + off - WARMUP_H * 60
    snaps = snaps[(snaps["t"] >= 0) & (snaps["t"] <= hours * 60)]
    low = r[(~r["high"]) & (r["assign_t"] >= 0)]
    recent = [float(low[(low["assign_t"] > t - 60) & (low["assign_t"] <= t)]["wait_min"].mean()) for t in snaps["t"]]
    scored = r[r["assign_t"] >= 0]
    s = des.summarize(scored, sim)
    return {
        "borough": borough, "day": day, "hours": hours, "handover_min": handover_min, "slots": int(slots),
        "units": sc.units[borough], "t": snaps["t"].round(1).tolist(),
        "series": {k: snaps[k].astype(int).tolist() for k in ["q_high", "q_low", "idle", "busy", "at_hospital", "hosp_queue"]},
        "handing_over": (snaps["at_hospital"] - snaps["hosp_queue"]).astype(int).tolist(),
        "recent_low_wait_min": [None if np.isnan(v) else round(v, 2) for v in recent],
        "summary": {k: s[k] for k in ["calls", "low_mean_wait_min", "low_p90_wait_min", "low_held_share", "high_p90_wait_min", "high_share_within_10min"]},
        "hosp_queue_peak": int(snaps["hosp_queue"].max()), "hosp_queue_unit_min": int(snaps["hosp_queue"].sum() * 5),
    }


@lru_cache(maxsize=256)
def _cached(art: str, borough: str, handover_min: float, slots: int, day: int, hours: int) -> dict:
    import json
    art_p = Path(art)
    calls = load_week(art_p / "lab_week_calls.csv")
    sc = scenario_from_json(json.loads((art_p / "policy_lab.json").read_text())["scenario"])
    return chain(calls, sc, borough, handover_min, slots, day, hours)


def cached_chain(art: Path, borough: str, handover_min: float, slots: int, day: int, hours: int) -> dict:
    return _cached(str(art), borough, round(float(handover_min), 1), int(slots), int(day), int(hours))


ARMS = {"none": "baseline", "plan": "reserve_fixed", "react": "reactive"}
SUMMARY_KEYS = ["calls", "low_mean_wait_min", "low_p90_wait_min", "low_held_share", "high_p90_wait_min", "high_share_within_10min"]


def _paired(a: list, b: list) -> dict:
    """Mean of b - a over seeds (same calls and draws per seed), with a t 95% interval."""
    d = np.array(b, float) - np.array(a, float)
    d = d[~np.isnan(d)]
    if len(d) < 2:
        return {"diff": float(d.mean()) if len(d) else None, "ci95": [None, None], "n_seeds": int(len(d))}
    from scipy.stats import t as student_t
    half = float(student_t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d)))
    return {"diff": float(d.mean()), "ci95": [float(d.mean() - half), float(d.mean() + half)], "n_seeds": int(len(d))}


def whatif(calls: pd.DataFrame, sc: des.Scenario, borough: str, day: int, start_h: int, units: int, hours: float,
           handover_min: float | None = None, horizon_h: int = 24, seeds: int = 10, ai_hours: tuple = ()) -> dict:
    """Capacity planner: one borough from `day` 00:00 for `horizon_h` hours under three arms with the same budget
    (one activation of `units` units for `hours` hours): no action; the supervisor's plan, starting at `start_h`; and
    the lab's reactive rule, which activates when the borough's watched queue reaches `sc.reactive_queue`. Every arm
    sees the same calls and, per seed, the same random draws (common random numbers), so paired differences over
    `seeds` seeds isolate the timing and size of the activation. Seed 0's 5-minute series is returned for the chart.
    `ai_hours` are the hours of this day at which the lab's warning released reserves here (context, not rerun)."""
    t0 = calls["incident_datetime"].min().floor("D")
    start = t0 + pd.Timedelta(hours=day * 24 - WARMUP_H)
    end = t0 + pd.Timedelta(hours=day * 24 + horizon_h)
    c = calls[(calls["borough"] == borough) & (calls["incident_datetime"] >= start) & (calls["incident_datetime"] < end)]
    tf = sc.traffic.get(borough) if sc.traffic else None
    off_h = int(round((c["incident_datetime"].min().floor("h") - start).total_seconds() / 3600))
    one = replace(sc, units={borough: sc.units[borough]}, handover_slots={borough: sc.handover_slots[borough]},
                  handover_min=float(handover_min or sc.handover_min), shock={},
                  traffic={borough: list(tf[max(0, day * 24 - WARMUP_H):])} if tf else {},
                  reserve_units=int(units), reserve_hours=float(hours), reserve_budget_unit_h=float(units) * float(hours),
                  fixed_schedule=((WARMUP_H + int(start_h) - off_h, borough),))
    shift = off_h * 60 - WARMUP_H * 60
    w0, w1 = start_h * 60, (start_h + hours + 2) * 60
    runs = {k: [] for k in ARMS}
    out = {}
    for seed in range(seeds):
        for name, policy in ARMS.items():
            sim = des.Sim(c, one, policy, seed=seed, snapshot_min=5 if seed == 0 else None).run()
            r = sim.results()
            r["assign_t"] = r["assign"] + shift
            scored = r[r["assign_t"] >= 0]
            s = des.summarize(scored, sim)
            low = scored[~scored["high"]]
            win = low[(low["assign_t"] >= w0) & (low["assign_t"] < w1)]
            s["window_low_mean_wait_min"] = float(win["wait_min"].mean()) if len(win) else float("nan")
            s["window_low_calls"] = int(len(win))
            runs[name].append(s)
            if seed == 0:
                snaps = pd.DataFrame(sim.snaps)
                snaps["t"] = snaps["t"] + shift
                snaps = snaps[(snaps["t"] >= 0) & (snaps["t"] <= horizon_h * 60)]
                out[name] = {"t": snaps["t"].round(1).tolist(), "q_low": snaps["q_low"].astype(int).tolist(),
                             "q_high": snaps["q_high"].astype(int).tolist(), "idle": snaps["idle"].astype(int).tolist(),
                             "activations": [{"at_min": a["at_min"] + shift, "until": a["until"] + shift} for a in sim.activations]}
    nan = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else v
    for name, rs in runs.items():
        out[name]["summary"] = {k: nan(float(np.nanmean([x[k] for x in rs]))) for k in SUMMARY_KEYS + ["window_low_mean_wait_min"]}
        out[name]["summary"]["window_low_calls"] = rs[0]["window_low_calls"]
        out[name]["summary"]["reserve_unit_h"] = float(np.mean([x["reserve_unit_h"] for x in rs]))
        out[name]["fired_share"] = float(np.mean([x["activations"] > 0 for x in rs]))
    col = lambda name, k: [x[k] for x in runs[name]]
    compare = {f"{b}_vs_{a}": {k: _paired(col(a, k), col(b, k)) for k in ["window_low_mean_wait_min", "low_mean_wait_min", "low_p90_wait_min"]}
               for a, b in [("none", "plan"), ("none", "react"), ("react", "plan")]}
    return {"borough": borough, "day": day, "start_h": int(start_h), "units": int(units), "hours": float(hours),
            "cost_unit_h": float(units) * float(hours), "handover_min": one.handover_min, "fleet": sc.units[borough],
            "reactive_queue": sc.reactive_queue, "watch": sc.watch, "horizon_h": horizon_h, "seeds": seeds,
            "ai_hours": [int(h) for h in ai_hours], "arms": out, "compare": compare}


def ai_hours_by_day(series: dict, arm: str = "shock_ai") -> dict:
    """{(borough, day): (hour, ...)} at which the lab's warning arm released reserves (seed 0 run)."""
    s = series.get(arm) or {}
    t0 = pd.Timestamp(s.get("t0", "1970-01-01"))
    out = {}
    for a in s.get("activations", []):
        t = t0 + pd.Timedelta(minutes=a["at_min"])
        d = (t.normalize() - t0.normalize()).days
        out.setdefault((a["borough"], d), []).append(t.hour)
    return {k: tuple(sorted(v)) for k, v in out.items()}


@lru_cache(maxsize=8)
def _lab_inputs(art: str):
    import json
    art_p = Path(art)
    calls = load_week(art_p / "lab_week_calls.csv")
    sc = scenario_from_json(json.loads((art_p / "policy_lab.json").read_text())["scenario"])
    sp = art_p / "policy_lab_series.json"
    ai = ai_hours_by_day(json.loads(sp.read_text())) if sp.exists() else {}
    return calls, sc, ai


@lru_cache(maxsize=512)
def _cached_whatif(art: str, borough: str, day: int, start_h: int, units: int, hours: float, handover_min: float) -> dict:
    calls, sc, ai = _lab_inputs(art)
    return whatif(calls, sc, borough, day, start_h, units, hours, handover_min or None, ai_hours=ai.get((borough, day), ()))


def cached_whatif(art: Path, borough: str, day: int, start_h: int, units: int, hours: float, handover_min: float = 0.0) -> dict:
    return _cached_whatif(str(art), borough, int(day), int(start_h), int(units), round(float(hours), 1), round(float(handover_min), 1))
