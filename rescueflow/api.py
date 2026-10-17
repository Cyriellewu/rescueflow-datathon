"""FastAPI service (docs/SPEC.md §7). Scores live on each request using the model on this machine.

    RESCUENYC_ARTIFACTS=artifacts uvicorn rescueflow.api:app --host 0.0.0.0 --port 8000
"""
import json
import os
import platform
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from rescueflow import model as m
from rescueflow.pipeline import load_table, payloads

ART = Path(os.environ.get("RESCUENYC_ARTIFACTS", "artifacts"))
MAX_REPLAY_HOURS = 24 * 14

app = FastAPI(title="RescueNYC")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
_state = {}


def state():
    if not _state:
        clf, meta = m.load(ART)
        table = load_table(ART / "borough_hour.csv")
        _state.update(clf=clf, meta=meta, onset=m.load_onset(ART), table=table.set_index("hour").sort_index())
    return _state


def _naive(ts: str) -> pd.Timestamp:
    """Timestamps are NYC local and naive; drop any timezone the client sends."""
    t = pd.Timestamp(ts)
    return (t.tz_localize(None) if t.tzinfo else t).floor("h")


@app.get("/health")
def health():
    s = state()
    return {"status": "ok", "computed_on": platform.machine(), "model_version": s["meta"]["model_version"],
            "trained_on": s["meta"]["trained_on"], "data_source": s["meta"].get("data_source", "FDNY")}


@app.get("/risk")
def risk(at: str):
    s = state()
    t = _naive(at)
    if t not in s["table"].index:
        raise HTTPException(404, f"no data for {t}")
    return payloads(s["clf"], s["meta"], s["table"].loc[[t]].reset_index(), use_llm=True, onset_clf=s["onset"])[0]


@app.get("/replay")
def replay(start: str, end: str):
    s = state()
    a, b = _naive(start), _naive(end)
    if (b - a) / pd.Timedelta(hours=1) > MAX_REPLAY_HOURS:
        raise HTTPException(400, f"at most {MAX_REPLAY_HOURS} hours per request")
    rows = s["table"].loc[a:b].reset_index()
    return payloads(s["clf"], s["meta"], rows, onset_clf=s["onset"]) if len(rows) else []


@app.get("/evaluation")
def evaluation():
    meta = state()["meta"]
    return {k: meta[k] for k in ["evaluation", "cascade", "lead_time_profile", "windows", "thresholds"]}


@app.get("/benchmark")
def benchmark():
    path = ART / "benchmark.json"
    if not path.exists():
        raise HTTPException(404, "run scripts/run_pipeline.py --benchmark on this machine first")
    return json.loads(path.read_text())


@app.get("/moments")
def moments():
    """Candidate replay moments for the demo (from scripts/find_demo_moments.py)."""
    path = ART / "demo_moments.json"
    if not path.exists():
        raise HTTPException(404, "run scripts/find_demo_moments.py first")
    return json.loads(path.read_text())


@app.get("/lab")
def lab():
    """Policy-lab experiment results (simulated; SCENARIO parameters included)."""
    path = ART / "policy_lab.json"
    if not path.exists():
        raise HTTPException(404, "run scripts/run_policy_lab.py first")
    return json.loads(path.read_text())


@app.get("/lab/series")
def lab_series():
    path = ART / "policy_lab_series.json"
    if not path.exists():
        raise HTTPException(404, "run scripts/run_policy_lab.py first")
    return json.loads(path.read_text())


ROOT = Path(__file__).resolve().parent.parent
SPATIAL = ROOT / "spatial" / "spatial_data"


@app.get("/spatial")
def spatial():
    """Spatial reference layer (spatial/): real ZIP centroids with call volume, NYS DOH hospitals, and
    ASSUMED ambulance bases (one per FDNY dispatch area). No unit positions are observed or served."""
    if not (SPATIAL / "zones.csv").exists():
        raise HTTPException(404, "run spatial/build_spatial.py first")
    z = pd.read_csv(SPATIAL / "zones.csv", dtype={"zipcode": str})
    h = pd.read_csv(SPATIAL / "hospitals.csv")
    b = pd.read_csv(SPATIAL / "bases.csv", dtype={"base_zip": str})
    model = json.loads((SPATIAL / "travel_model.json").read_text())
    clean = lambda df: json.loads(df.to_json(orient="records"))  # NaN -> null  # noqa: E731
    h = h.rename(columns={"latitude": "lat", "longitude": "lon"}).dropna(subset=["lat", "lon"])
    return {"zones": clean(z[["zipcode", "borough", "dispatch_area", "n_calls", "lat", "lon", "obs_median_travel_s"]]),
            "hospitals": clean(h[["facility_name", "lat", "lon"]]),
            "bases": clean(b[["dispatch_area", "base_zip", "borough", "lat", "lon", "fleet_share"]]),
            "provenance": {"zones": "FDNY EMS incidents aggregated by ZIP (real)", "hospitals": "NYS DOH facilities (real)",
                           "bases": "ASSUMED: one per FDNY dispatch area at its busiest ZIP",
                           "travel_model_validation": model.get("validation"), "assumptions": model.get("assumptions")}}


@app.get("/overview")
def overview():
    """Historical overview from the feature table: calls and low-acuity queue by hour of day per borough and
    year, and how local stress is in the test window."""
    t = state()["table"].reset_index()
    t = t[t["hour"] >= "2023-01-01"]
    year, hod = t["hour"].dt.year, t["hour"].dt.hour
    def by(v):
        g = t.assign(year=year, hod=hod).groupby(["borough", "year", "hod"])[v].mean().round(2)
        out = {}
        for (b, y, h), val in g.items():
            out.setdefault(b, {}).setdefault(str(y), [None] * 24)[h] = float(val)
        return out
    test = t[t["hour"] >= state()["meta"]["test_start"]]
    w = test.pivot(index="hour", columns="borough", values="stress")
    n = w.sum(axis=1)[(w.sum(axis=1) >= 1) & (w.notna().sum(axis=1) >= 4)]
    conc = (n.value_counts(normalize=True).sort_index() * 100).round(1)
    held = test.pivot(index="hour", columns="borough", values="held_pending_low")
    slack = {}
    for b in w.columns:
        idx = w.index[w[b] == 1]
        others = [c for c in w.columns if c != b]
        slack[b] = round(float((held.loc[idx, others].min(axis=1) == 0).mean() * 100), 1) if len(idx) else None
    return {"calls_by_hour": by("n_calls"), "pending_low_by_hour": by("pending_low"),
            "stressed_hours": int(len(n)), "boroughs_stressed_at_once_pct": {int(k): float(v) for k, v in conc.items()},
            "pct_hours_another_borough_holds_zero": slack}


# dashboard on the same origin, so the demo needs one open port
app.mount("/figures", StaticFiles(directory=ROOT / "submission"), name="figures")
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "app", html=True), name="app")
