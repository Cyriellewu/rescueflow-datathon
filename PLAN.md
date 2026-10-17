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

- **Label target: `dispatch_low` (team decision, Oct 17 evening).** P0 showed where the queue
  is: high-acuity dispatch is held under 30 s by priority dispatch, while severity 4–8 calls wait
  20–50 min at p90 and are held 35–56% of the time. The queue state describes that queue, so the
  model predicts it. The audit rule's pick (`travel`, 84% of the 2023→2026 rise) and the original
  high-acuity `dispatch` label are reported as sensitivity runs in `docs/evaluation.md`.
- **H1 (queue beats demand): established on the low-acuity label.** Full model PR-AUC 0.566
  (0.533–0.593) vs demand-only 0.470 (0.442–0.497); intervals do not overlap. Alert precision
  0.65 at 5.0 false alerts/day citywide. On the high-acuity label the same gap was 0.388 vs 0.356
  with overlapping intervals: there is little to predict there.
- **H2 (severity cascade): small positive on the low-acuity label**, ΔPR-AUC +0.004 (+0.002 to
  +0.007); null (+0.000) on the high-acuity label. The low-acuity backlog z-score jumps only in
  the stressed hour itself (0.03 → 0.23 → 0.45), so lead time comes from the whole queue state,
  not from low-acuity holds rising first.
- **H3 (onsets):** onset recall 0.09 for the full model (persistence 0.00 by construction), 0.27
  for queue-aware; 380 of 4,123 onsets caught, 170 an hour early. The full model is a better
  ranker; the simpler queue models catch more fresh onsets at more false alerts.
- **Gate G3: passed.** Full model beats backlog-only logistic (0.430) and demand-only with
  intervals apart.
- **Policy lab (fleet calibrated to all-call p90 wait, arms watch the low-acuity queue, Brooklyn
  handover ×2 Wed 14–22, week of 2026-09-21, 20 seeds).** Historical demand: the shock lands on
  the low-acuity queue (worst-borough low-acuity P90 2.3 → 8.4 min, +6.1, CI +4.9 to +7.2) and
  barely on high-acuity (1.38 → 1.40 min). AI-warned reserves vs none: low-acuity mean wait
  −0.14 min (−0.20 to −0.08). AI vs reactive: reactive is better by 0.34 min but spends the whole
  36 unit-hour budget (6 activations) where the AI arm spends 13 (2.2 activations). **Demand
  ×1.5:** the fleet saturates (low-acuity P90 in the tens of hours); the shock adds +476 min to
  low-acuity P90; AI vs reactive shows no detectable difference; AI vs none cuts the
  worst-borough low-acuity P90 by 618 min (−1089 to −147) using 30 of 36 unit-hours. Reading:
  the warning buys a cheaper intervention with similar effect, not a better one.
- **Benchmark (laptop arm64, replace with VM):** replay 2.82 M events/s; scoring p50 0.78 ms,
  p99 1.06 ms.
- **Demo evening:** 2026-07-04 23:00 Brooklyn, p = 0.96 one hour before the median low-acuity
  dispatch wait reached 47 min against a 26-min p80 norm (`artifacts/demo_moments.json`).
