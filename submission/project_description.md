# [Team Name]_IBM Z Datathon 2026 Project — RescueNYC

**Theme:** Real-Time AI for Critical Decisions · **Event code:** SSF2026

Numbers below are from the laptop dry run on real FDNY data (Oct 17). Replace the three platform figures (scoring latency, replay rate, simulation count) with the VM's `artifacts/benchmark.json` and `policy_lab.json` before submitting, then delete this line.

## Problem

When a New Yorker calls 911 for a life-threatening medical emergency, the average ambulance
response is now 13 minutes 9 seconds, up from 9:34 in FY2021 (NYC Comptroller, October 16 2026).
The City's reports place the added time in dispatch and travel, and response times kept rising
even when call volume flattened. Demand alone doesn't explain it: when ambulances are busy or
held up at hospitals, new calls wait in a queue before any unit is assigned.

## What we built

RescueNYC watches that queue. A replay engine runs FDNY's public EMS Incident Dispatch records
(NYC Open Data, 6.1 million calls, 2023–2026) in time order and reconstructs, for each borough and
hour, only what was known at that moment: calls still waiting for a unit by acuity, held calls,
how long the oldest has waited, and ambulances at hospitals.

- **Detect:** a queue-aware gradient-boosting model scores each borough's risk that the next
  hour's high-acuity dispatch delay breaks that borough's own recent norm.
- **Decide:** each alert says whether the pressure is in dispatch or in travel, and which signals
  drove it.
- **Respond:** an operator briefing, written by a template or a local language model, passes
  through a verifier that rejects any number the model did not produce.
- **Test the decision:** a discrete-event policy lab replays real call arrivals through a
  calibrated, clearly labeled scenario fleet with hospital handover. It asks whether reserves
  triggered by the warning beat reserves triggered by the queue itself, under the same budget.

## Results (held-out 2026 data)

- Queue-aware model PR-AUC 0.388 (95% CI 0.370–0.412) vs 0.356 (0.339–0.376) for the same
  model given demand features only, 0.261 for hour-of-week history and 0.340 for a backlog-only
  logistic baseline. The lift over demand is real in direction but small; the intervals overlap.
- Catches 9% of new stress episodes (436 of 4,616), 231 of them an hour early, with 7.2 false
  alerts per day citywide; the simpler queue-only models catch 21–22% at 10 false alerts per day.
- The severity-cascade hypothesis did not hold: adding the low-acuity backlog changed PR-AUC by
  +0.000 (95% CI −0.003 to +0.002).
- Policy lab: at historical demand a 2× handover slowdown in Brooklyn barely moves high-acuity
  waits (P90 1.38 → 1.40 min). At 1.5× demand it spreads into the all-call queue (P90 +144 min,
  95% CI +112 to +176) while high-acuity waits stay near 2 min, because priority dispatch and
  mutual aid shield severity 1–3 calls. Warning-triggered reserves showed no detectable advantage
  over reactive reserves under the same budget (high-acuity P90 +0.00 min, 95% CI −0.01 to +0.01).

We report the comparisons whichever way they come out.

## Why now

FDNY's EMS dispatch system (CAD) was last updated in 2017. In March 2025 the City approved building a replacement on FireCAD, and in August 2026 FDNY awarded a $10.6M contract to keep the current one running. RescueNYC is a working prototype of an analytics layer a new CAD could feed. It needs only the five events every CAD already emits (call created, unit assigned, on scene, at hospital, closed), and it never touches dispatch itself. Sources are in `docs/integration.md`.

## IBM Z / LinuxONE

The whole pipeline runs on our LinuxONE Community Cloud VM (s390x): feature building,
training, live per-request scoring (0.75 ms p50 on the laptop dry run; VM figure to follow), the replay
engine (2.9 M events/s, laptop), and 200 policy simulations (two labs × 100 runs). It runs in one container built on the LinuxONE ML image. Call-level data stays on
the machine; only aggregates and scores leave it. Accelerator: [NNPA measured … / CPU inference — from `scripts/verify_linuxone.sh` on the VM].
Mainframe-class systems already run the transactional workloads this is meant to sit beside.

## Links

- Code: [GitHub repo URL]
- Video: [≤ 3 min]
- Data: https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj
- Open-source libraries: pandas, NumPy, scikit-learn, XGBoost, FastAPI, Uvicorn, Requests,
  pytest, HTTPX (links in the README)

Research prototype on historical data; not clinical dispatch.
