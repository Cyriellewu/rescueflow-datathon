# RescueNYC — How it is used, and how it is judged

## Who uses it

| Person | When | What they need in under ten seconds |
|---|---|---|
| EMS shift supervisor (borough or citywide desk) | every hour, and whenever a borough tile turns amber or red | which borough will run late next hour, how sure, why, and the one action that fits |
| Operations analyst / Comptroller or Council staff | weekly, monthly | what changed, where the time goes, whether demand explains it |
| Planner / CAD product owner | before a policy or staffing change | what a handover slowdown or a demand surge does to the queue, and whether acting on a warning beats reacting |

## The supervisor's hour

The Supervisor view is prediction-first. The user picks an hour T in the held-out 2026 window; the model has
seen only what the dispatch record held before T and forecasts the hour T to T+1. What really happened stays
hidden until "Reveal what happened" is pressed, so a viewer sees a forecast being made, not an outcome being
explained. The view says on its face that this is a historical backtest, not live CAD data: the model's inputs
are the five events any CAD emits, but no live feed is connected. From an alert whose action is to release
reserve capacity, one link opens the capacity planner with that borough and the hour pre-filled; the planner
reruns the simulator for that borough-day without and with the activation and shows cost in unit-hours beside
the simulated effect. The decision, and dispatch itself, stay with the person and the CAD.


1. **Glance.** The Supervisor screen shows the five boroughs ranked by the chance that the dispatch queue runs late in the next hour. Bars and a band word (Alert / Watch / Normal). Nothing else competes for attention.
2. **Read the situation.** One sentence per borough from the live queue: how many calls are waiting, how many are held with no unit, how long the oldest has waited, how many units are at hospitals.
3. **Take the action, or not.** One recommendation per borough: release reserve capacity (hold the outgoing shift, activate standby units); check hospital handover; no unit action, travel pressure; watch; no action. Cross-borough unit moves are not recommended: the lab found they do not beat leaving units in place, even with an oracle. The person decides. Nothing is dispatched by the system.
4. **Ask why if needed.** The "Why" line names the pressure (dispatch, travel, both, hospital) and the signals that drove the score. The briefing contains only numbers the model produced; a verifier rejects anything else.
5. **Later, see what happened.** In replay the tile shows "Afterwards: the queue did run late" or "stayed within normal". In live use this line appears an hour later and becomes the running scorecard.

Everything above is reached without scrolling on a laptop screen. The other three tabs (Overview, Early warning with the map and 48-hour chart, Policy lab) are for analysts, planners and judges.

The Policy lab answers "so what?" in pictures: Parallel Worlds plays the same week twice on a 3D city map, one side without reserves (or on a fixed schedule), the other with reserves timed by the warning; boroughs rise with the number of calls waiting and a ribbon under the maps shows right-minus-left waiting across the week with the 20-seed interval for that pair, because a single replay can show the AI's edge over doing nothing but not its smaller edge over a fixed schedule. The hospital bottleneck scene lets a planner drag handover time and bays and watch the simulator rerun one borough-day: hospital queue, units free, dispatch queue, patient wait. Positions on the maps are illustrative; every count is the simulator's. The lab closes with an outside check of its own assumptions against real EMS records from four places, one verdict per assumption.

## What changes in practice

Today the queue is managed by looking at it. With the warning the same decisions move about an hour earlier and become targeted at one borough:

- 20:00, Brooklyn 84%, Queens 20%: hold Brooklyn's outgoing crews at 20:05 rather than finding a 100-call queue at 23:00.
- A hold-over of the outgoing shift decided at 17:30 for the one borough that needs it.
- "Hospital" pressure goes to the hospital liaison, not to more ambulances.
- Five green tiles is also a decision, with evidence, to do nothing.

## How performance is evaluated, in three layers

**1. The signal (done, on the record).** Chronological hold-out: train 2023-01 to 2025-06, calibrate and set thresholds on 2025-07 to 2025-12, score 2026-01 to 2026-09 once. Every model alerts on its own top 10% of validation hours, so budgets match.

| Metric | Plain meaning | Full model, 2026 |
|---|---|---|
| PR-AUC (95% CI, day-block bootstrap) | how well bad hours rank above good ones, any budget | 0.60 (0.56–0.62); demand-only 0.47 |
| Alert precision | of flagged hours, share that ran late | 0.69 |
| False alerts per day | citywide, at that budget | about 4 |
| Onset recall | of hours that turned from normal to late, share flagged | 0.09 full model, 0.22 onset-weighted variant |
| Brier | are the probabilities honest | 0.153 (always-base-rate 0.19) |

Reported alongside: hour-of-week history, persistence, backlog-only logistic, demand-only, queue-aware, cross-borough, external-data ablation. "Better" means confidence intervals apart.

**2. The decision (done, in simulation).** Same real calls for the evaluation week, same random numbers, three policies: do nothing, react when the queue is long, act on the warning. Fleet calibrated to FDNY's all-call p90 wait, low-acuity calls held while units are scarce (as FDNY does), cross-borough travel from the spatial model, hourly travel scaled by that week's real NYC DOT road speeds, a 2× hospital handover shock in one borough. Outcomes: low-acuity P90 and mean wait, held share, high-acuity travel, worst-borough wait, reserve hours spent. Paired differences over 20 seeds with 95% intervals. The warning counts as valuable only if it beats the reactive rule under the same budget. Results are reported whichever way they come out; all of it is labelled SIMULATION. As of Oct 17: reserves
released on the warning cut low-acuity mean wait by about 0.9 min against doing nothing; moving free units
between boroughs does not beat leaving them in place, even with an oracle that knows next hour's calls
(RB-01/RB-02 in `docs/evaluation.md`).

**3. The product (next, in the field).** A stepped-wedge pilot: each week the screen is on in some boroughs and off in others, rotating over twelve weeks. Primary outcome: low-acuity P90 dispatch wait. Secondary: held share, high-acuity travel median, re-graded calls waiting over 30 minutes. Process: alerts acknowledged, minutes from alert to action, actions per alert. Thresholds pre-registered. Never claimed before it runs: minutes or lives saved.

## System performance

Measured on the VM and recorded in `artifacts/benchmark.json`: replay throughput (single core and all cores), per-request scoring latency p50/p99, batch scoring rate, and the accelerator check. Calls never leave the machine; only aggregates and scores do.
