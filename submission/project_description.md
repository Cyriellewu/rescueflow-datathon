# [Team Name]_IBM Z Datathon 2026 Project — RescueNYC

**Theme:** Real-Time AI for Critical Decisions · **Event code:** SSF2026

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
  hour's dispatch wait for the queued, lower-acuity calls breaks that borough's own recent norm,
  while confirming high-acuity calls stay protected.
- **Decide:** each alert says whether the pressure is in dispatch or in travel, and which signals
  drove it.
- **Respond:** an operator briefing, written by a template or a local language model, passes
  through a verifier that rejects any number the model did not produce.
- **Test the decision:** a discrete-event policy lab replays real call arrivals through a
  calibrated, clearly labeled scenario fleet with hospital handover. It asks whether reserves
  triggered by the warning beat reserves triggered by the queue itself, under the same budget.

## Results (held-out 2026 data)

- Where the time goes: public records show high-acuity dispatch held under 30 seconds by priority
  dispatch, while low-acuity (severity 4–8) calls wait 20–50 minutes at the 90th percentile and
  are held 35–56% of the time. The queue lives there, so that is what the model predicts.
- Queue-aware model PR-AUC 0.566 (95% CI 0.533–0.593) vs 0.470 (0.442–0.497) for the same
  model given demand features only, 0.430 for a backlog-only logistic baseline and 0.265 for
  hour-of-week history. Alert precision 0.65 at 5 false alerts per day citywide.
- On the high-acuity label the same comparison is 0.388 vs 0.356 with overlapping intervals:
  there is little to predict where FDNY already protects the call. Both are reported.
- A second, onset-weighted model raises the share of new stress episodes caught from 9% to 25%
  at 6 false alerts per day, and is shown next to the main score. The cascade effect is small:
  adding the low-acuity backlog changes PR-AUC by +0.003 (+0.001 to +0.005).
- Adding call-type mix, NYC DOT road speeds and weather did not change the ranking (0.567 with and
  without), nor did seven more years of training data: the remaining ceiling is unit availability,
  which no public dataset contains. We say so.
- Policy lab, with FDNY's hold practice, spatial travel times and that week's real road speeds in
  the simulator: a 2× hospital handover slowdown in Brooklyn adds 3 minutes to the low-acuity P90
  wait (19 → 22 min) and nothing to high-acuity waits. Reserves released on the warning cut the
  low-acuity mean wait by 0.9 min against doing nothing (CI −1.3 to −0.5); against a reactive
  queue-threshold trigger on the same budget there is no clear difference. The warning is
  actionable; its edge over simple reaction is not yet demonstrated, and we report that.

We report the comparisons whichever way they come out.

## Why now

FDNY's EMS dispatch system (CAD) was last updated in 2017. In March 2025 the City approved building a replacement on FireCAD, and in August 2026 FDNY awarded a $10.6M contract to keep the current one running. RescueNYC is a working prototype of an analytics layer a new CAD could feed. It needs only the five events every CAD already emits (call created, unit assigned, on scene, at hospital, closed), and it never touches dispatch itself. Sources are in `docs/integration.md`.

## IBM Z / LinuxONE

The whole pipeline runs on our LinuxONE Community Cloud VM (s390x): feature building,
training, live per-request scoring (1.6 ms p50, 2.7 ms p99), the replay engine (358,000 CAD events per
second), and 200 policy simulations (two labs × 100 runs). It runs natively on Ubuntu for s390x
(the LinuxONE ML container image could not be pulled on our VM, so the Dockerfile is provided
but the evidence is from a native run). Call-level data stays on
the machine; only aggregates and scores leave it. The Telum on-chip AI accelerator (NNPA) is present on the VM; model inference is CPU (gradient boosting does not use it; see `artifacts/nnpa_bench.json` for the measured check).
Mainframe-class systems already run the transactional workloads this is meant to sit beside.

## Links

- Code: [GitHub repo URL]
- Video: [≤ 3 min]
- Data: https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj
- Open-source libraries: pandas, NumPy, scikit-learn, XGBoost, FastAPI, Uvicorn, Requests,
  pytest, HTTPX (links in the README)

Research prototype on historical data; not clinical dispatch.
