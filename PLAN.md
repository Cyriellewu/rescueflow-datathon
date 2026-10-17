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

## Results on real FDNY data (laptop dry run, Oct 17 2026; VM rerun must reproduce before the video)

Data: 45 months 2023-01 → 2026-09, 6,065,090 rows (5,960,214 after cleaning). All seven P0 gate
checks passed (`docs/performance_audit.md` → Findings). Test window 2026-01-01 → 2026-09-30.

- **Label target: `dispatch` (team decision, confirmed Oct 17).** The audit rule (stage behind most of the rise) picks `travel` (+1.61 of
  +1.91 min since 2023). We train on `dispatch` anyway, because the queue state describes the
  dispatch stage and reserves act on it; dispatch is also far more variable hour to hour (CV 0.87
  vs 0.24). All three targets were run and are reported side by side in `docs/evaluation.md`
  (the dispatch label also scores best, but that was seen after the choice was argued, and the
  gaps are small: PR-AUC 0.388 dispatch, 0.383 response, 0.357 travel).
- **H1 (queue beats demand): not established at 95%.** Full model PR-AUC 0.388 (0.370–0.412)
  vs demand-only 0.356 (0.339–0.376): the intervals overlap by 0.006. Direction is right, lift is
  small. Queue-aware without recent delays: 0.369.
- **H2 (severity cascade): null.** Dropping the low-acuity backlog changes PR-AUC by +0.000
  (−0.003 to +0.002) for every target. The low-acuity backlog z-score barely moves before onsets
  (0.04 → 0.09 over the six hours before, 0.16 in the stressed hour). Say so in the video.
- **H3 (onsets): weak for the full model, better for simpler queue models.** Onset recall 0.09
  for the full model (persistence 0.00 by construction), 0.22 for queue-aware, 0.21 for
  backlog-only logistic, at 7–10 false alerts per day citywide. `find_demo_moments`: 436 of 4,616
  onsets caught, 231 of them an hour early.
- **Gate G3: passed narrowly.** Full model beats backlog-only logistic (0.340, 0.325–0.361;
  intervals do not overlap) and edges demand-only. Pitch framing: dispatch-stress detection +
  attribution with a modest, honestly reported lift over demand.
- **Policy lab (historical demand, fleet calibrated to all-call p90 wait, Brooklyn handover ×2
  Wed 14–22, week of 2026-09-21, 20 seeds):** the shock is detectable but tiny on high-acuity
  waits (P90 1.38 → 1.40 min). AI-warned vs reactive reserves: +0.00 min on every metric.
  **Stress scenario (demand ×1.5, same fleet):** the fleet saturates; the shock spreads into the
  all-call P90 wait (+144 min, 95% CI +112 to +176) while high-acuity P90 moves 2.04 → 2.07 min
  (priority dispatch + mutual aid shield severity 1–3). AI vs reactive: no high-acuity difference;
  all-call P90 +37 min (−2 to +76). **The warning does not buy a better decision in this
  simulator**; the lab's finding is where a handover shock lands (the low-acuity queue).
- **Benchmark (laptop arm64, replace with VM):** replay 2.86 M events/s; scoring p50 0.75 ms,
  p99 0.97 ms.
- **Demo evening:** 2026-07-04 20:00 Brooklyn, alert p=0.78 one hour before next-hour median
  high-acuity dispatch hit 161 s against a p80 norm of 40 s (`artifacts/demo_moments.json`).
