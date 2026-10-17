# RescueNYC

IBM Z Datathon 2026 · Theme 1: Real-Time AI for Critical Decisions.

EMS bottleneck intelligence and early warning: using real FDNY EMS Incident Dispatch Data, warn
an hour ahead where high-acuity response times are likely to be elevated, separate
dispatch-related from travel-related pressure, and help an operator decide where to look first.
Model inference runs on IBM LinuxONE. Historical replay, not a live 911 feed. Research/demo
only — not clinical dispatch.

- Plan and priorities: [`PLAN.md`](PLAN.md)
- Shared contracts (data, label, leakage rules, API, ownership): [`docs/SPEC.md`](docs/SPEC.md)

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_data.py   # pulls NYC Open Data 76xm-jjuj into data/raw/
```

## Data source

NYC Open Data, EMS Incident Dispatch Data (`76xm-jjuj`), FDNY. Raw rows are not committed;
only aggregated borough-hour tables.
