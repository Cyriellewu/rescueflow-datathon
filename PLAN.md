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

Standalone demand forecast, ambulance staging, hospital/bed allocation, per-call scoring,
maps, free-form chat, dispatch-area grain, Isolation Forest, ONNX, LightGBM, any
"minutes/lives saved" claim.

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

## Roles (5 people)

**L** lead / integration / pitch · **D** data · **M** ML & evaluation · **O** LinuxONE & API · **F** frontend

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
