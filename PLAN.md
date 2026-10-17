# RescueNYC — Build Plan

**Project:** RescueNYC — EMS Bottleneck Intelligence & Early Warning on IBM LinuxONE
**Event:** IBM Z Datathon 2026 · Theme 1: Real-Time AI for Critical Decisions (Detect · Decide · Respond)
**Window:** Oct 17–18, 2026. Americas schedule lists Oct 18 10:00 AM as the end (table says "EST";
confirm timezone + Hack2skill cutoff with organizers). Internal deadline: Oct 18 08:30 NYC time.

## Scope (locked)

Detect when NYC EMS response performance is deteriorating, separate dispatch-related from
travel-related delay, warn one hour ahead where the data supports it, and tell an operator
where to look first. All model results come from real FDNY EMS Incident Dispatch Data
(NYC Open Data `76xm-jjuj`).

Out of scope unless the team explicitly re-decides: synthetic hospitals, bed-capacity
optimization, CP-SAT patient allocation, ambulance pre-positioning (already done by
GT Hacklytics' FirstWave), chat agents.

Honesty rules: replay of historical data is "near-real-time inference on replayed data", not a
live 911 feed. Bottleneck indicators are contributing signals, not causes. No claims of minutes
saved or lives saved. Synthetic data only in unit tests or a clearly labeled demo mode.

The detailed contracts (tables, label, leakage rules, API, ownership, acceptance) live in
[`docs/SPEC.md`](docs/SPEC.md). Change the spec first, then the code.

## Priorities

| P | Deliverable | Owner | Depends on | Gate / acceptance |
|---|---|---|---|---|
| P0 | Data schema verification: fields, null/invalid rates, timestamp semantics, leakage audit → `docs/data_audit.md` | Data | — | Every field used by features is documented with "known at time t?" |
| P0 | LinuxONE check: account under `SSF2026`, AI_LAB env, arch (`s390x`), Python + pandas/sklearn/lightgbm install, both mandatory labs done | LinuxONE/API | — | `scripts/verify_linuxone.sh` output + screenshots in `submission/evidence/` |
| P1 | `borough_hour` table + small real fixture committed (`data/fixtures/`) + historical baseline (borough × hour-of-week) | Data | P0 data | Fixture regenerates from `scripts/fetch_data.py`; no raw IDs committed |
| P2 | Next-hour elevated-delay risk model (chronological split, beats baseline on PR-AUC / recall@k) **or**, if the gate fails, retrospective anomaly detection labeled as such | ML/Eval | P1 | `docs/evaluation.md` with metrics on a held-out final 4 weeks |
| P2 | Bottleneck attribution: dispatch vs travel deviation from baseline per borough-hour | ML/Eval | P1 | Indicators reproducible from the table, documented formula |
| P3 | FastAPI inference service on LinuxONE (`/health`, `/risk`, `/replay`) | LinuxONE/API | P2 model artifact, API contract | Real request from dashboard hits LinuxONE; log captured |
| P4 | Historical replay dashboard: timeline, borough risk, dispatch/travel indicators, alerts | Frontend | API contract (can mock) | Replay at time t only shows data available at t |
| P5 | Integration, tests, README, 3-min video, Hack2skill submission (title includes team name) | Research/Pitch + all | P3, P4 | Submission checklist in `docs/SPEC.md` all ticked |

**Decision gate after P2 (target ~hour 12):** if the next-hour model does not beat the
hour-of-week baseline on the held-out window, ship "Historical Bottleneck Detection +
Decision Support" and say so in the pitch. Don't tune forever.

## Parallelism

Frontend and API start immediately against the contract in `docs/SPEC.md` with mocked
responses. ML starts on the fixture as soon as P1 lands. Each workstream uses its own branch /
worktree; the coordinator merges and owns the contracts.

## Open items

- [ ] Confirm submission cutoff timezone with organizers
- [ ] Confirm team member list on Hack2skill (4–6 people) and team name for the title
- [ ] Assign a named owner to each workstream
- [ ] Run `scripts/fetch_data.py` locally (NYC Open Data is not reachable from the cloud sandbox)
