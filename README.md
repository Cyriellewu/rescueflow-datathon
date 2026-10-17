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
- `rescueflow/` — hospitals, scenarios, allocators, forecasting, API
- `app.py` — Streamlit dashboard (to come)
- `tests/` — pytest
