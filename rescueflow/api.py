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
        _state.update(clf=clf, meta=meta, table=table.set_index("hour").sort_index())
    return _state


@app.get("/health")
def health():
    s = state()
    return {"status": "ok", "computed_on": platform.machine(), "model_version": s["meta"]["model_version"],
            "trained_on": s["meta"]["trained_on"]}


@app.get("/risk")
def risk(at: str):
    s = state()
    t = pd.Timestamp(at).floor("h")
    if t not in s["table"].index:
        raise HTTPException(404, f"no data for {t}")
    return payloads(s["clf"], s["meta"], s["table"].loc[[t]].reset_index())[0]


@app.get("/replay")
def replay(start: str, end: str):
    s = state()
    a, b = pd.Timestamp(start).floor("h"), pd.Timestamp(end).floor("h")
    if (b - a) / pd.Timedelta(hours=1) > MAX_REPLAY_HOURS:
        raise HTTPException(400, f"at most {MAX_REPLAY_HOURS} hours per request")
    rows = s["table"].loc[a:b].reset_index()
    return payloads(s["clf"], s["meta"], rows) if len(rows) else []


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
