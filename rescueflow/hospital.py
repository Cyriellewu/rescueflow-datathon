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


def whatif(calls: pd.DataFrame, sc: des.Scenario, borough: str, day: int, start_h: int, units: int, hours: float,
           handover_min: float | None = None, horizon_h: int = 24, seed: int = 0) -> dict:
    """Capacity planner: one borough from `day` 00:00 for `horizon_h` hours, without and with one reserve activation
    of `units` units for `hours` hours starting at `start_h`. Same calls and random draws in both runs (common random
    numbers), so the difference is the activation's effect in this simulated day. Cost = units x hours."""
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
    out = {}
    for name, policy in [("before", "baseline"), ("after", "reserve_fixed")]:
        sim = des.Sim(c, one, policy, seed=seed, snapshot_min=5).run()
        r = sim.results(); snaps = pd.DataFrame(sim.snaps)
        shift = off_h * 60 - WARMUP_H * 60
        snaps["t"] = snaps["t"] + shift; r["assign_t"] = r["assign"] + shift
        snaps = snaps[(snaps["t"] >= 0) & (snaps["t"] <= horizon_h * 60)]
        scored = r[r["assign_t"] >= 0]
        s = des.summarize(scored, sim)
        low = scored[~scored["high"]]
        win = low[(low["assign_t"] >= start_h * 60) & (low["assign_t"] < (start_h + hours + 2) * 60)]
        out[name] = {"t": snaps["t"].round(1).tolist(), "q_low": snaps["q_low"].astype(int).tolist(),
                     "q_high": snaps["q_high"].astype(int).tolist(), "idle": snaps["idle"].astype(int).tolist(),
                     "summary": {k: s[k] for k in ["calls", "low_mean_wait_min", "low_p90_wait_min", "low_held_share",
                                                   "high_p90_wait_min", "high_share_within_10min"]},
                     "window_low_mean_wait_min": float(win["wait_min"].mean()) if len(win) else None,
                     "window_low_calls": int(len(win)),
                     "activations": [{"at_min": a["at_min"] + shift, "until": a["until"] + shift} for a in sim.activations]}
    return {"borough": borough, "day": day, "start_h": int(start_h), "units": int(units), "hours": float(hours),
            "cost_unit_h": float(units) * float(hours), "handover_min": one.handover_min, "fleet": sc.units[borough],
            "horizon_h": horizon_h, **out}


@lru_cache(maxsize=512)
def _cached_whatif(art: str, borough: str, day: int, start_h: int, units: int, hours: float, handover_min: float) -> dict:
    import json
    art_p = Path(art)
    calls = load_week(art_p / "lab_week_calls.csv")
    sc = scenario_from_json(json.loads((art_p / "policy_lab.json").read_text())["scenario"])
    return whatif(calls, sc, borough, day, start_h, units, hours, handover_min or None)


def cached_whatif(art: Path, borough: str, day: int, start_h: int, units: int, hours: float, handover_min: float = 0.0) -> dict:
    return _cached_whatif(str(art), borough, int(day), int(start_h), int(units), round(float(hours), 1), round(float(handover_min), 1))
