# RescueFlow AI — Build Plan

Goal: a judge-clickable demo where a Manhattan surge is dispatched two ways
(nearest hospital vs. capacity-aware OR-Tools) and the metrics show why the
optimized one is better. Real NYC EMS demand data; hospital capacity is synthetic
and labeled as such everywhere.

## Phase 1 — Data (done / in progress)
- [x] `scripts/fetch_data.py` → `data/hourly_counts.csv` (incidents per hour per borough since 2024-10)
- [ ] `data/manhattan_sample.csv` (2026 Manhattan incidents: severity, zip, response times) — downloading
- Use the sample to draw realistic surge cases: severity mix from `final_severity_level_code`, location from `zipcode`.

## Phase 2 — Synthetic hospital network + scenarios  (`rescueflow/hospitals.py`, `rescueflow/scenarios.py`)
- 5–6 fictional Manhattan hospitals: lat/lon (near real ED locations but renamed), ED beds, open beds, staff factor, service time.
- Travel time = haversine distance × speed factor + baseline (minutes). Labeled simulated.
- `Case`: id, lat/lon, severity (1 = critical … 7 = minor), arrival minute.
- Scenario generator: "major accident, N cases in zip X", sampling severities from real distribution.

## Phase 3 — Allocators + evaluation  (`rescueflow/allocate.py`, `rescueflow/evaluate.py`)
- Baseline: each case → nearest hospital, ignore capacity.
- Optimized: OR-Tools CP-SAT. Variables x[case, hospital]; each case assigned once; hospital load ≤ open beds (soft, penalty); objective = Σ travel_min × severity_weight + overload penalty + waiting cost.
- Metrics: mean/max travel, capacity violations, estimated queue delay (simple M/M/c or load/beds × service time), high-acuity (sev 1–2) travel time, solve time.
- Tests in `tests/` for both allocators on a fixed scenario.

## Phase 4 — Demand forecasting  (`rescueflow/forecast.py`)
- LightGBM on hourly counts: features hour, dow, month, holiday flag, lag-24/168, borough.
- Backtest last 4 weeks, report MAE; chart predicted vs actual.
- Feeds the dashboard as "expected background load" per hospital during the surge window.

## Phase 5 — API + dashboard  (`rescueflow/api.py`, `app.py`)
- FastAPI `/allocate` (POST scenario → both assignments + metrics). This is the component to host on IBM LinuxONE.
- Streamlit: map of hospitals + cases, "Simulate surge" button, sliders for case count / open beds, side-by-side metric cards, forecast chart.

## Phase 6 — Polish + submission
- README with assumptions, limitations, data sources, LinuxONE deployment steps.
- Record 2–3 min demo; verify a real request from the dashboard reaches the LinuxONE service.

## Open questions
- Confirm IBM Z Datathon 2026 platform requirements (LinuxONE access, submission format, deadline).
- Team split: who owns data/forecast vs. optimizer vs. UI.
