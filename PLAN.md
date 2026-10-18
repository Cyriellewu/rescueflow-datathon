# RescueNYC — Build Plan

**Project:** RescueNYC — EMS Dispatch-Stress Early Warning on IBM LinuxONE
**Event:** IBM Z Datathon 2026 · Theme 1: Real-Time AI for Critical Decisions (Detect · Decide · Respond)
**Window:** Oct 17–18, 2026. Guidebook: Day 2 ends Oct 18 10:00 AM; NYU hub schedule: Day 2
"12 AM – 10:30 AM EST", closing ceremony 10:30. Treat **10:00 NY time** as the cutoff until
organizers confirm. **Internal submit: Oct 18 08:30.**

**One LinuxONE server per team** (NYU schedule). O owns the VM: every member gets SSH-key
access with their own Linux user; one shared repo checkout in `/opt/rescuenyc`, deployed with
`git pull`; one long-running API container; heavy jobs (training, benchmark) are announced in
the team chat first so they don't collide with the demo or each other. Don't reinstall or reset
the VM after G1 without telling everyone.

Scope came out of a four-lens review (judge rubric, data feasibility, novelty, delivery).
Contracts live in [`docs/SPEC.md`](docs/SPEC.md); change the spec first, then the code.

## One-line pitch

When NYC's ambulance dispatch queue starts to back up, RescueNYC warns a supervisor an hour
ahead, says whether the pressure is in dispatch or travel, and its briefing can't state a number
the model didn't produce. Scored on a replayed CAD event stream, on LinuxONE.

## Core idea and what makes it ours

- **Predict dispatch-queue stress, not demand.** Output is the risk that next hour's
  high-acuity dispatch delay is elevated versus that borough's own recent norm. Demand is only
  an input feature. (Demand forecast + ambulance staging is FirstWave's idea, and its lift over
  an hour-of-week baseline was ~1.3%; guidebook rule 4 bans reusing other projects' ideas.)
- **The real-time signal is the live backlog:** calls created but not yet assigned at time T,
  by severity, how long the oldest has waited, and held calls. Known at T, no leakage.
- **Headline finding to test — the severity cascade:** FDNY dispatches by priority, so held
  *low-acuity* calls should pile up before *high-acuity* delay rises. We test whether the
  low-acuity backlog adds predictive power and how much lead time it gives. Either answer is
  a real finding on real data.
- **Hybrid multi-model chain mirroring the two mandatory labs:**
  (1) stress classifier + baselines (predictive, multi-model) →
  (2) calibrated alert / watch / insufficient-data bands →
  (3) operator briefing (template, optionally a local LLM on LinuxONE) checked by a
  deterministic verifier that rejects any number not in the model output (predictive + GenAI).
- **Why LinuxONE:** scoring belongs next to the dispatch system of record — reliable, secure,
  no row-level call data shipped elsewhere; only aggregates leave the VM. Backed by measured
  replay throughput and latency on s390x, not adjectives.

## Out of scope

Standalone demand forecast, ambulance staging, patient-to-hospital allocation, per-call scoring,
3D maps / road routing / RL, free-form chat, dispatch-area grain, Isolation Forest, ONNX,
LightGBM, any real-world "minutes/lives saved" claim (simulated results are labeled as such).

## Guidebook requirement → our answer

| Requirement | Answer |
|---|---|
| Theme 1: streaming data, identify risk, support decisions as events unfold | Replay engine updates queue state per call event; hourly risk + bottleneck alerts |
| "Why IBM Z / LinuxONE is the right platform" | System-of-record co-location story + measured s390x benchmark |
| Criterion 3: AI/ML on LinuxONE; containerization, security, scalability, compute with screenshots | Train + infer on the VM; API in a container on s390x; NNPA check; evidence in `submission/evidence/` |
| Mandatory labs: hybrid multi-model; predictive + generative | Done first; architecture is those two labs joined up |
| ≤3-min video showing problem, data, solution, LinuxONE instance and model | One replayed real night, then terminal on the VM |
| Title `[Team]_IBM Z Datathon 2026 Project`, repo link, OSS links | Checklist in SPEC §9 |
| No political inclination | Ops-support framing; cite Comptroller/Council as facts |

## Research order

Measure the problem → find the bottleneck → predict the risk → simulate interventions →
quantify improvement.

1. **P0 performance audit** (`scripts/performance_audit.py`): where high-acuity time is lost
   (dispatch vs travel, by year, borough, severity), whether delay is just volume, when the
   backlog peaks. It picks the label stage (`--target dispatch|travel|response`); don't assume
   dispatch. Its chart is the pitch's first figure.
2. **Model ladder:** hour-of-week history → demand-only → queue-aware (demand + queue state) →
   full (+ recent delays). Same alert budget for all; held-out 2026 window.
3. **Policy lab:** the AI-warned arm has to beat the *reactive* arm on the same reserve budget,
   not just the no-reserve baseline. Simulated improvement is reported both ways:
   (W_baseline − W_AI) / W_baseline and (W_reactive − W_AI) / W_reactive.

We measure FDNY's historical operational performance; we cannot score FDNY's CAD itself (its
predictions and unit states are not public).

## Policy lab (does the warning lead to better decisions?)

A discrete-event simulator (`rescueflow/des.py`) replays real call arrivals (time, borough,
severity) through a SCENARIO fleet: dispatch queue → travel → scene → transport → hospital
handover → available. Fleet size is calibrated so the simulated all-call p90 dispatch wait matches FDNY
data from before the evaluation week (the high-acuity median is below the simulator's floor; see
SPEC §10). An optional demand multiplier stresses the same fleet. Two controlled experiments, same calls and seeds per arm:

1. **Vulnerability:** baseline vs a hospital handover shock in one borough. Does it spread?
2. **Value of warning:** under the shock, reserves triggered by the AI warning vs by a reactive
   queue threshold, **same reserve budget**, plus no reserves. Only an AI win over *reactive*
   counts as value from prediction.

The warning model in the lab is trained on other weeks with random shocks. Report paired
differences with 95% CIs, whatever they show. No 3D map, no road routing, no RL.

## Work items (whoever is free takes the next one; no fixed roles)

- **VM:** set up the one team VM, imports, port/tunnel, NNPA check, `scripts/verify_linuxone.sh`
- **Data:** run `scripts/fetch_data.py` on a laptop, scp CSV to the VM, fill `docs/data_audit.md`
- **Model:** `scripts/run_pipeline.py --raw ... --benchmark` on the VM; write `docs/evaluation.md`
- **Policy lab:** `scripts/run_policy_lab.py --raw ...` on the VM; pick the shock scenario
- **Dashboard:** policy-lab view (two worlds side by side) on top of `app/index.html`
- **Pitch:** labs, evidence screenshots, video script, README

## Schedule (NY time) and gates

| Time | Work |
|---|---|
| 11:30–12:00 | Lock this plan and the SPEC §7 API contract; assign names. Discord: do labs count per team? deadline timezone? |
| 12:00–13:30 | **O:** VM up, L1CC jupyter-lab-ml image, hello-world API reachable (port or SSH tunnel), `python -c "import pandas, sklearn, xgboost"`, `grep nnpa /proc/cpuinfo` screenshot. **D:** laptop pull 2023→latest, recompute durations from timestamps, audit fields. **L, F:** mandatory labs, then F builds dashboard on mock JSON. **M:** variance split of response into dispatch vs travel; base rate of the trailing label |
| **13:30 G1** | VM reachable + imports OK + data pulled. Else: tunnel fallback / Flask / stdlib server |
| 13:30–16:00 | **D:** `borough_hour.csv` + `backlog_snapshots.csv` (DuckDB on laptop) → scp to VM; `docs/data_audit.md`. **M:** baselines. **O:** Dockerfile + `/health`. **F:** timeline + borough cards |
| **16:00 G2** | Aggregates on the VM, audit done |
| 16:00–20:00 | **M:** xgboost on VM, chronological split, cascade test. **O:** `/risk`, `/replay`, replay engine. **F:** wire to API. **L:** problem framing, sources |
| **20:00 G3** | Model beats backlog-only logistic on PR-AUC or onset recall? If not → pitch "dispatch-stress detection + attribution" honestly |
| 20:00–23:00 | Calibration bands, briefing + verifier, s390x benchmark, end-to-end on LinuxONE, screenshots. Optional cached llama.cpp briefing |
| **23:00 freeze** | No new features |
| 23:00–07:00 | Two shifts: fixes, README, `docs/evaluation.md`, video script; each person sleeps ≥4h |
| 07:00–08:30 | Record video, submit on Hack2skill. 08:30–10:00 buffer only |

## Cut order if slipping

1. LLM briefing (keep template + verifier) 2. NNPA timing 3. calibration plot 4. live API from
dashboard (JSON replay + VM terminal on screen) 5. the ML model (keep attribution + baselines).
Never cut: real data, something visibly running on s390x, the video, the repo link.

## Open items

- [ ] Abstract submitted Oct 15 — does it match this scope? If not, ask #helpdesk whether the pivot is fine
- [ ] Both mandatory labs done (screenshots)
- [ ] Team name for the title; 4–6 members on Hack2skill
- [ ] Owner names for L / D / M / O / F

## Results on real FDNY data (final laptop run, Oct 17 evening; VM rerun reproduces before the video)

Data: 2023-01 → 2026-09 refetched with `incident_id`, `initial_call_type`, `zipcode`,
`incident_dispatch_area` (6,065,090 rows, 5,960,214 after cleaning); NYC DOT road speeds aggregated
to borough-hour; hourly weather; 2005–2022 pulled for the long-run audit only. All P0 gate checks
passed (`docs/performance_audit.md`, Findings 1–11). Test window 2026-01-01 → 2026-09-30, never
used for any choice.

- **Label target: `dispatch_low`** (team decision). High-acuity dispatch is held under 30 s by
  priority dispatch; severity 4–8 calls wait 20–50 min at p90 and are held 35–56% of the time. The
  queue state describes that queue. High-acuity dispatch, travel and response are sensitivity runs.
- **Features (final, 45):** queue state 7, flow and change 9, the label's own stage 4 (last hour's
  completed low-acuity wait, its deviation from baseline, its distance to the label line, hours already
  late), call-type mix 6, road speed 2, weather 4, demand 5, recent high-acuity durations 4, context 4.
  Hyperparameters chosen on validation only (grid of 8; chosen 600 trees, depth 3, lr 0.05).
- **The one feature change that moved the needle (evening):** the model predicted the low-acuity queue
  but its "recent duration" inputs were all high-acuity. Adding the low-acuity stage as of T lifted
  validation PR-AUC 0.604 → 0.624 and test **0.567 → 0.595 (0.563–0.621)**, alert precision 0.65 → 0.69
  at 4.0 false alerts/day; the onset-weighted companion 0.539 → 0.572 with onset recall 0.22. Gain share
  moved from `stressed_now` (51% → 1%) to the continuous versions of the same information: deviation
  13.8%, distance to line 9.6%, streak 11.4%.
- **H1 (queue beats demand): established.** PR-AUC 0.595 (0.563–0.621) vs demand-only 0.471
  (0.444–0.499); intervals apart. Backlog-only logistic 0.430, hour-of-week 0.265, persistence 0.364.
- **What did not move the ranking:** seven more training years (0.563), other boroughs' queues
  (+0.002), call-type mix + road speed + weather (ablation without them: 0.567, identical). The
  information ceiling is unit availability, which the public record does not contain.
- **What moves the metric a supervisor needs:** the onset-weighted companion (transitions normal → late
  weighted ×3): onset recall **0.09 → 0.22** at precision 0.67 and 4.4 false alerts/day (PR-AUC 0.572).
  Served as `p_onset` next to `p_stress`; the trade-off was visible on validation before the test was seen.
- **H2 (cascade): small positive**, ΔPR-AUC +0.003 (+0.001 to +0.005).
- **Policy lab (final):** fleet calibrated to the all-call p90 wait of the 8 weeks before the
  evaluation week (Bronx 49, Brooklyn 63, Manhattan 51, Queens 47, Staten Island 12 units); low-acuity
  calls held while idle units ≤ 10% (FDNY practice); cross-borough travel from the spatial model
  rescaled to FDNY medians; hourly travel scaled by that week's real NYC DOT speeds; Brooklyn
  handover ×2 Wed 14–22; week of 2026-09-21; 20 seeds. Baseline low-acuity P90 19.4 min (FDNY
  8–48 by borough). The shock adds +3.0 min to low-acuity P90 (CI +2.5 to +3.4) and nothing to
  high-acuity. Reserves on the warning vs none: low-acuity mean −0.91 min (−1.31 to −0.51), P90
  −0.87 (−1.45 to −0.30), using 32 of 36 reserve unit-hours. Warning vs reactive trigger, same
  budget: no clear difference (mean −0.20, −0.52 to +0.11). Demand ×1.5: the fleet saturates and
  the scenario is uninformative; reported as such.
- **Experiment 3 (teammate's rebalancing planner, run with the final simulator):** moving free units
  between boroughs every hour by a capacity-vs-demand optimisation makes things worse at the transfer
  times the spatial model gives (15–35 min cross-borough): low-acuity P90 +3.5 min (CI +2.0 to +5.0),
  mean +1.8 (CI +0.9 to +2.8), 333 relocations per week; raising demand by the warning risk relocates
  521 units and adds another +1.3 min to the mean (CI +0.5 to +2.1). High-acuity unchanged. Reading:
  units in transit between boroughs serve nobody; with 15-minute-plus transfers, repositioning has to
  be rarer and earlier than this planner does it, or confined to the Bronx–Manhattan pair. A clean
  negative result, reported as such.
- **RB-01 (pre-registered rebalancing protocol, normal conditions, 20 seeds; `artifacts/policy_lab_rb01.json`):**
  same week, no shock, hourly decisions, shared budget of 100 moves / 2,000 relocation unit-minutes, at most
  3 moves per decision, oracle = perfect knowledge of next hour's exogenous arrivals only. Low-acuity mean
  wait, baseline 13.81 min: always-rebalance +1.31 (171 moves); P1 reactive +0.76 (−0.09 to +1.60, 63
  moves, 1,532 unit-min); P2 predictive −0.08 (−0.39 to +0.23, 0.4 moves); P2 vs P1 −0.83 (−1.61 to
  −0.05); hour-of-week risk −0.03; demand-only risk never fires; **oracle −0.10 (−0.78 to +0.57, 11 moves)**.
  Reserve activation on the warning in the same week: −0.84 (−1.12 to −0.57). By the protocol's decision
  rule: P2 beats P1 formally, but by not moving; no relocation policy beats doing nothing, and neither does
  the oracle, so prediction quality is not the binding constraint — transfer time and lost origin coverage
  are. Adding capacity for two hours is the lever that works; moving units across boroughs is not.
- **RB-02 (same protocol under the Brooklyn handover ×2 shock):** baseline 15.80 min; P1 +0.80 (−0.10 to
  +1.70, 64 moves); P2 +0.45 (−0.02 to +0.92, 2.2 moves); P2 vs P1 −0.35 (−1.20 to +0.50); oracle +0.04
  (−0.53 to +0.62, 11 moves); warning-triggered reserves −0.91 (−1.31 to −0.51). Same picture as RB-01.
- **RB-03 (same 36 reserve unit-hours, five ways to spend them; 20 seeds; both conditions).** Low-acuity
  mean wait vs no reserves, normal / shock: fixed historical-peak schedule −0.36 / −0.33 (30 unit-h);
  reactive −0.94 / −0.71 (36); **AI-timed −0.84 (−1.12 to −0.57) / −0.91 (−1.31 to −0.51)** (24 / 32);
  arrivals oracle −0.72 / −0.52 (36). Paired: **AI vs fixed −0.48 (−0.79 to −0.17) and −0.58 (−0.97 to
  −0.19)**, intervals apart, less budget; AI vs reactive +0.10 / −0.20 (no clear difference) at two-thirds
  of the cost in the normal week; AI vs oracle: level in the normal week, **AI better by 0.39 (+0.05 to
  +0.73) under the shock**, because the queue state the model sees matters more than next hour's arrivals.
  High-acuity endpoints unchanged in every arm. This is the result that shows prediction creating
  operational value: when to add capacity, decided by the warning, beats a fixed schedule and matches
  reaction at lower cost. Together with RB-01/RB-02: add capacity on the warning; do not move it.
- **Reading:** the warning turns reserves into a measurable reduction of low-acuity waiting, but a
  simple queue-threshold rule achieves the same in this simulator. The value of prediction over
  reaction is not yet shown; the simulator now reproduces FDNY's queue, so the next lever is the
  intervention design (handover-side action, budget with physical meaning), per Findings.
- **Model families on the final features:** sklearn boosting 0.594, random forest 0.577, logistic 0.556,
  XGBoost 0.595; a rank-mean ensemble did not beat the best member. The algorithm is not the constraint.
- **Training from 2005 (30.1 M rows): 0.568**, no gain over 2023+ with the same features; the queue
  barely existed before 2022, so those years teach nothing about it.
- **Long-run audit 2005–2026 (`docs/long_run_audit.md`):** demand +35% over 2005–2019 with a flat queue;
  flat demand and a 9× queue after 2022. The first figure of the video.
- **Benchmark (laptop arm64):** replay 2.9 M events/s on one core, ×2.3 on all cores; scoring p50
  0.8 ms. VM figures replace these in the docs.
- **Demo evening:** 2026-07-04 23:00 Brooklyn, p = 0.90 one hour before the median low-acuity wait
  reached 47 min against a 26-min norm.
- **Tried by parallel agents (evening), all null, kept as records on their worktree branches:** 30-minute
  cutoffs (test 0.556 vs 0.567 hourly; 21% of half-hour cells too thin to label); a 2-hour-window label
  (0.570, indistinguishable); a "turns late from normal" label (onset recall 0.32 but precision 0.20 at
  10 false alerts/day). The label is not the bottleneck either.
- **Also tried by an agent on validation, on top of the final features:** exponentially weighted queue
  counts, rolling maxima, hours since the queue last exceeded 10, borough-relative scaling, stronger
  regularisation, 1,000 trees with early stopping, monotone constraints on queue features: +0.002
  validation PR-AUC at best, redundant with the label-stage features. Not merged.
- **Model families on validation (agent, late evening): LightGBM 0.6232, CatBoost 0.6250, XGBoost 0.6236;
  three-model probability ensemble 0.6255 (+0.002), test 0.5974 vs 0.5955 with the paired CI just above zero.**
  Below the +0.005 bar; not adopted (METHODS §5 table). Per-borough alert budgets, a two-stage demand
  forecast and low-acuity throughput features (agent 4): +0.002 at best on validation, test identical. Null.
- **Policy lab, demo layer (late evening):** Parallel Worlds in 3D (MapLibre building extrusions + deck.gl units,
  boroughs rise with calls waiting; fixed schedule / no reserves vs AI-timed reserves on the same calls and
  seed), a divergence ribbon with the 20-seed interval for the selected pair, and a hospital bottleneck scene
  that reruns one borough-day in the simulator per slider setting (`/lab/hospital`): Brooklyn, Wednesday,
  19 bays, mean low-acuity wait 1.2 min at a 20-min handover, 6.3 at 30, 89 at 40. Positions on the maps are
  illustrative (assumed bases, real ZIP centroids); every count comes from the simulator. In the week shown
  (seed 0) AI-timed reserves beat no reserves by 6,290 call-minutes of waiting and the fixed schedule by only
  240, so the fixed-vs-AI edge (−0.58 min, CI apart) is a 20-seed result, not something one replay shows.
- **Merged from a teammate (ivy-external-validation):** an outside check of the simulator's unit-cycle
  assumptions against NYC, San Francisco, Indiana and Riverside County records. Scene time, transport time and
  the share transported match; time at the hospital does not (lab median 13.9 min vs 41–43 real), because the
  lab frees the unit when the handover ends and ignores clean-up. The lab under-states how long hospitals tie up
  units; stated on the dashboard and in `docs/external_validation.md`.
- **Hospital time at its real value (sensitivity, late evening; METHODS §10d):** with the handover mean at 59 min
  (median 41, per the outside check) the calibrated fleet doubles, the shock hurts 2.7×, and every RB-03 ordering
  holds with intervals apart; the reserve effect is −0.16 min at 36 unit-hours and −0.35 at 72 (6 units per
  activation, the same share of the larger fleet). Official artifacts unchanged; the sensitivity run is quoted.
- **Precision (METHODS §7):** 0.69 at the default budget is a line, not a ceiling: 0.78 at 5% of hours alerted,
  0.83 at 3%; a two-hour confirmation rule is worse than simply raising the line. Ranking quality is where
  every model family lands within 0.003 of each other.
- **Two alert tiers (late evening; METHODS §7, UX):** High alert = top 5% of validation scores (test precision
  0.78, recall 0.17, onset recall 0.02, 1.4 false alerts/day), Watch = to 10% (together 0.69 / 0.31 / 0.09 / 4.0).
  A precision-recall choice inside one budget, not a model gain; said so on the page. The 5% line was chosen after
  the budget table had been read on test, so its 0.78 is not an independent confirmation; the next unseen months are.
- **Merged from agents:** per-unit event tracks from the simulator (`rescueflow/tracks.py`, `/lab/tracks`, 11 MB for
  four arms of the real week, results unchanged, 32 tests) as the data layer for binding animated units to simulated
  ones; submission docs refreshed (project description, demo script, JUDGING re-score ~33–34).
- **Running (validation only):** an onset specialist trained on currently-normal hours, and 15/30-minute observation
  features on the hourly label. Adopt only if they clear the pre-set bars; otherwise recorded as null.
- **Onset specialist (agent, validation only): the model is null, the rule is adopted.** A model trained only on
  currently-normal hours equals the primary's own scores on those hours (conditional PR-AUC 0.429 vs 0.431). A
  second, conditional budget on the served onset score (top 5% of currently-normal validation hours) lifts onset
  recall 0.074 → 0.162 on validation against 0.099 for alerting equally often with the primary line, at −0.011
  precision; the one test read agrees (0.094 → 0.202 vs 0.139). Served as the "Onset warning" flag; METHODS §7.
- **Sub-hour observation features (agent, validation only): null.** Ten 15/30-minute leading indicators (calls,
  assignments, clearance ratio, low-acuity pending change, as-of 30-min median wait, fresh share of the backlog),
  leakage-tested, on the hourly label: +0.001 to +0.002 validation PR-AUC, onset recall slightly down. Kept in the
  code as `build_table(subhour=True)`, out of FEATURES. With this, feature search on the hourly grid is exhausted.
- **LinuxONE rerun (night of Oct 17/18, `vm_results/`, METHODS §10c-bis):** trained_on s390x, primary = sklearn
  HistGradientBoosting (no xgboost wheel), test PR-AUC 0.596, precision 0.69, 4.0 FA/day; lab 140 runs in 124 s,
  AI vs none −0.46 (apart), AI vs fixed −0.15 (not separable); replay 257 k/s one core, 577 k/s three cores; scoring
  p50 2.3 ms. Evidence copied to `submission/evidence/` (benchmark_s390x.json, platform_s390x.txt, evaluation_s390x.md).
  The VM pulled the code before the two-tier, onset-warning, tracks and Snap ML commits; it serves the older bands.
- **Not done tonight, by decision:** 30-minute cutoffs in the product (would touch every hourly assumption in
  label, evaluation and dashboard; roadmap item 3).
