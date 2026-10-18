# Evergreen Labs_IBM Z Datathon 2026 Project — RescueNYC

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
  triggered by the warning beat reserves triggered by a schedule, by the queue itself, or by an
  oracle, under the same budget.

### The dashboard

One screen with a left sidebar and four views. Everything is a replay of the public record;
nothing is a live feed.

- **Supervisor** is prediction-first. Pick an hour T in the held-out 2026 window. The model
  forecasts T to T+1 from data before T: five borough tiles ranked by risk, a band word (Alert /
  Watch / Normal), one sentence on the queue as it stood, the bottleneck tag and the verified
  briefing. What really happened in that hour stays hidden until the user clicks **Reveal what
  happened**. This is a historical backtest on FDNY's records, not live CAD data; the screen says so.
- **Overview** shows what twenty-one years of the record say about demand and the queue.
- **Early warning** is the hour-by-hour replay with the map and the 48-hour chart.
- **Policy lab** answers "so what?" in simulation, every panel badged SIMULATION:
  - **Parallel Worlds** plays the same week under two reserve policies on a 3D city map
    (MapLibre building extrusions, deck.gl units). Boroughs rise with the number of calls waiting.
    Unit positions are illustrative; every count comes from the simulator. A divergence ribbon
    under the maps shows right-minus-left waiting across the week with the 20-seed interval for the
    selected pair. Default comparison: no reserves vs AI-timed reserves; "Jump to the biggest gap"
    goes to the hour where the two worlds differ most.
  - **Capacity planner** ("what if we add reserve units?") is pre-filled from the alert on screen
    and reruns one borough-day in the simulator without and with an activation; units × hours is
    the cost shown next to the change in waiting.
  - **Hospital bottleneck** reruns one borough-day per handover-time and bays setting, so a planner
    can drag the hospital side and watch the chain reaction: hospital queue, units free, dispatch
    queue, patient wait.
  - **Outside check** closes the lab: the simulator's own assumptions against real EMS records from
    New York, San Francisco, Indiana and Riverside County, one verdict per assumption.

## Results (held-out 2026 data)

- Twenty-one years of the public record: calls per borough-hour rose 35% from 2005 to 2019 while the
  dispatch queue stayed flat; since 2022 calls are flat and the queue has grown ninefold (low-acuity
  p90 wait 3 → 42 minutes). The change is on the supply side, and it is recent.
- Where the time goes: public records show high-acuity dispatch held under 30 seconds by priority
  dispatch, while low-acuity (severity 4–8) calls wait 20–50 minutes at the 90th percentile and
  are held 35–56% of the time. The queue lives there, so that is what the model predicts.
- Queue-aware model (XGBoost, 45 features) PR-AUC 0.595 (95% CI 0.563–0.621) vs 0.471 (0.444–0.499)
  for the same model given demand features only, 0.430 for a backlog-only logistic baseline and
  0.265 for hour-of-week history. Alert precision 0.69 at 4 false alerts per day citywide.
- Precision is a budget choice, not a model property: the same model reaches 0.78 when 5% of hours
  are alerted and 0.83 at 3% (recall 0.17 and 0.11). The dashboard's Alert and Watch bands expose
  the same trade-off.
- The algorithm is not the constraint. LightGBM, CatBoost and a three-model probability ensemble
  were tried on the final features, selected on validation only: all within 0.002 of XGBoost on
  test (0.596, 0.596, 0.597), below our pre-set +0.005 bar, so XGBoost stays as the single model.
  Random forest 0.577 and logistic regression 0.556 on the same inputs; the large gap is between
  any queue-aware model and demand-only.
- On the high-acuity label the same comparison is 0.388 vs 0.356 with overlapping intervals:
  there is little to predict where FDNY already protects the call. Both are reported.
- A second, onset-weighted model raises the share of new stress episodes caught from 9% to 22%
  at 4.4 false alerts per day, and is shown next to the main score. The cascade effect is small:
  adding the low-acuity backlog changes PR-AUC by +0.003 (+0.001 to +0.005).
- Adding call-type mix, NYC DOT road speeds and weather did not change the ranking, nor did training
  from 2005 instead of 2023, per-borough alert budgets, a two-stage demand forecast, or 30-minute
  and two-hour label variants: the remaining ceiling is unit availability, which no public dataset
  contains. We say so.
- Policy lab (simulation), with FDNY's hold practice, spatial travel times and that week's real road
  speeds in the simulator: a 2× hospital handover slowdown in Brooklyn adds 3 minutes to the
  low-acuity P90 wait (19 → 22 min) and nothing to high-acuity waits. Reserves released on the
  warning cut the low-acuity mean wait by 0.9 min against doing nothing (CI −1.3 to −0.5); against
  a reactive queue-threshold trigger on the same budget there is no clear difference.
- The same 36 reserve unit-hours spent five ways (simulation): released on the warning they cut
  low-acuity mean wait by 0.84 min in a normal week and 0.91 under a handover shock; against a fixed
  historical-peak schedule the warning is better by 0.48 and 0.58 min (95% CIs exclude zero) while
  using less of the budget; it matches a reactive queue trigger at two-thirds of the cost, and under
  the shock beats an oracle that knows next hour's arrivals. Timing capacity by the queue forecast
  is where the prediction pays. In the single week Parallel Worlds shows (seed 0), AI-timed reserves
  beat no reserves by 6,290 call-minutes of waiting and the fixed schedule by only 240, which is why
  the ribbon carries the 20-seed interval.
- A pre-registered rebalancing protocol (hourly decisions, equal move and unit-minute budgets, an oracle
  that knows next hour's arrivals) finds that moving free units between boroughs does not beat leaving
  them in place, under normal or shocked conditions, even with perfect foresight. At New York's 15 to
  35 minute cross-borough transfers, units in transit serve nobody. Prediction quality is not the
  binding constraint; the lever that works is adding capacity on the warning, not moving it.
- Hospital bottleneck scene (simulation, Brooklyn, a Wednesday, 19 bays): mean low-acuity wait
  1.2 min at a 20-minute handover, 6.3 at 30 and 89 at 40. The queue does not grow gently; it tips.
- Outside check of the simulator against real EMS records (NYC, San Francisco, Indiana, Riverside
  County): time on scene, transport time and the share transported are close to real. Time at the
  hospital is not: the lab's median is 13.9 min against 41–43 real, because the lab frees the unit
  when the handover ends and ignores clean-up. The lab under-states how long hospitals tie up units.
- With hospital time at its real value (sensitivity run, handover mean 59 min): the calibrated fleet
  roughly doubles, the handover shock does 2.7× the damage, and every ordering in the five-way
  reserve comparison holds with intervals apart. The reserve effect shrinks to −0.16 min at the
  original 36 unit-hours and is −0.35 at the same share of the larger fleet (72 unit-hours): the
  size of the effect depends on the reserve's share of the fleet, not on the hospital assumption.

We report the comparisons whichever way they come out.

## Why now

FDNY's EMS dispatch system (CAD) was last updated in 2017. In March 2025 the City approved building a replacement on FireCAD, and in August 2026 FDNY awarded a $10.6M contract to keep the current one running. RescueNYC is a working prototype of an analytics layer a new CAD could feed. It needs only the five events every CAD already emits (call created, unit assigned, on scene, at hospital, closed), and it never touches dispatch itself. Sources are in `docs/integration.md`.

## IBM Z / LinuxONE

The whole pipeline runs on our LinuxONE Community Cloud VM (s390x, 3 vCPU, 8 GB, Ubuntu 24.04): feature
building from six million cleaned calls, training, calibration, per-request scoring (2.3 ms p50, 4.5 ms p99),
the replay engine (257,000 CAD events per second on one core, 577,000 on three, 2.2 million times faster than
the city's real event stream, a year of the record in 14 s), and the policy lab's 20-seed simulations (140
whole-week runs in 124 s). Evidence: `submission/evidence/benchmark_s390x.json`, `platform_s390x.txt`,
`evaluation_s390x.md`. The model trained on the VM is scikit-learn HistGradientBoosting (xgboost has no s390x
wheel) and scores the held-out 2026 window at PR-AUC 0.596, the same as the laptop's xgboost 0.595, so the
served model is reproducible on the platform. It runs natively (the LinuxONE ML container image could not be
pulled on our VM; the Dockerfile is provided, the evidence is from the native run). Both mandatory labs were
executed end to end on the same VM (`submission/evidence/labs/`). Call-level data stays on the machine; only
aggregates and scores leave it. The Telum on-chip AI accelerator (NNPA) is present; inference is on CPU
(`nnpa_bench.json` and `snapml_bench_s390x.json` record two attempts: Snap ML ran boosted trees on CPU, but its zDNN accelerator path is not exposed on the Community Cloud VM; no accelerator path ran).
Mainframe-class systems already run the transactional workloads this is meant to sit beside.

## Links

- Code: [GitHub repo URL]
- Video: [≤ 3 min]
- Data: https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj
- Open-source libraries: pandas, NumPy, scikit-learn, XGBoost, FastAPI, Uvicorn, Requests,
  pytest, HTTPX; MapLibre GL and deck.gl for the 3D maps (links in the README)

Research prototype on historical data; a replayed backtest, not clinical dispatch and not a live feed.
