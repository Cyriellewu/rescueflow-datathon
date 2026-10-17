# [Team Name]_IBM Z Datathon 2026 Project — RescueNYC

**Theme:** Real-Time AI for Critical Decisions · **Event code:** SSF2026

Fill every `[…]` from `docs/evaluation.md` after the real run. Delete this line before submitting.

## Problem

When a New Yorker calls 911 for a life-threatening medical emergency, the average ambulance
response is now 13 minutes 9 seconds, up from 9:34 in FY2021 (NYC Comptroller, October 16 2026).
The City's reports place the added time in dispatch and travel, and response times kept rising
even when call volume flattened. Demand alone doesn't explain it: when ambulances are busy or
held up at hospitals, new calls wait in a queue before any unit is assigned.

## What we built

RescueNYC watches that queue. A replay engine runs FDNY's public EMS Incident Dispatch records
(NYC Open Data, [N] million calls, 2023–2026) in time order and reconstructs, for each borough and
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

- Queue-aware model PR-AUC [x] (95% CI [..]) vs [y] for the same model given demand features
  only, [z] for hour-of-week history.
- Catches [a]% of new stress episodes, [b] of them an hour early, with [c] false alerts per
  day.
- Policy lab: a handover slowdown in one borough [spreads / does not spread] into citywide
  dispatch waits. Warning-triggered reserves [result, with CI] versus reactive reserves.

We report the comparisons whichever way they come out.

## IBM Z / LinuxONE

The whole pipeline runs on our LinuxONE Community Cloud VM (s390x): feature building,
training, live per-request scoring ([p50] ms), the replay engine ([N] events/s), and [R] policy
simulations. It runs in one container built on the LinuxONE ML image. Call-level data stays on
the machine; only aggregates and scores leave it. Accelerator: [NNPA measured … / CPU inference].
Mainframe-class systems already run the transactional workloads this is meant to sit beside.

## Links

- Code: [GitHub repo URL]
- Video: [≤ 3 min]
- Data: https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj
- Open-source libraries: pandas, NumPy, scikit-learn, XGBoost, FastAPI, Uvicorn, Requests,
  pytest, HTTPX (links in the README)

Research prototype on historical data; not clinical dispatch.
