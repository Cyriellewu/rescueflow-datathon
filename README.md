# RescueFlow AI

IBM Z Datathon 2026 · AI for Healthcare · Emergency hospital resource optimization.

Forecasts NYC EMS demand from real FDNY dispatch data, simulates hospital capacity
(clearly labeled synthetic), and compares nearest-hospital dispatch against a
capacity-aware OR-Tools allocator during surge scenarios. Research/demo only — not clinical dispatch.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_data.py   # pulls NYC Open Data 76xm-jjuj into data/
```

## Layout

- `scripts/fetch_data.py` — download hourly EMS counts + Manhattan incident sample
- `scripts/demo_compare.py` — print nearest-vs-optimized metrics for a 15-case surge in ZIP 10029
- `rescueflow/hospitals.py` — 6 fictional Manhattan hospitals (synthetic beds, `SIMULATED = True`) + haversine travel-time model
- `rescueflow/scenarios.py` — `Case` / `Scenario`, ZIP centroids, real severity mix, `make_surge()` generator
- `rescueflow/allocate.py` — `nearest_assignment()` baseline and OR-Tools CP-SAT `optimized_assignment()`
- `rescueflow/evaluate.py` — `metrics()` and `compare()` (travel, capacity violations, est. queue delay)
- `rescueflow/` — forecasting and API to come (Phases 4–5)
- `app.py` — Streamlit dashboard (to come)
- `tests/` — pytest (`.venv/bin/pytest -q`; no data download needed)

## Quick demo

```bash
.venv/bin/python scripts/demo_compare.py
```
