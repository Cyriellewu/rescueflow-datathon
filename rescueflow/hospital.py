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
