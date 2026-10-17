# RescueNYC — Shared Specification

Contract between workstreams. Change it here first (L approves), then change code.
Items marked **[verify P0]** are assumptions until `docs/data_audit.md` confirms them.

## 1. User and question

- **User:** EMS shift supervisor (decision support; a human decides).
- **Question at each hour boundary T:** in which borough is the dispatch queue about to back up
  for high-acuity calls in the next hour, is the pressure in dispatch or travel, and what is
  driving it?

## 2. Source data

NYC Open Data `76xm-jjuj` (FDNY EMS Incident Dispatch). NYC local timestamps. Use 2023-01-01 →
latest (severity coding more stable; check code set per year). Data is published with a lag of
months, so this is always a **replay**, never live.

| Field | Use | Known at T? |
|---|---|---|
| `incident_datetime` | call created in EMS CAD | if < T |
| `first_assignment_datetime` | first unit assigned | if < T |
| `first_activation_datetime` | unit en route | if < T |
| `first_on_scene_datetime` | first unit on scene | if < T |
| `incident_close_datetime` | close; only to drop cancelled calls from the backlog | if < T |
| `dispatch_response_seconds_qy`, `incident_travel_tm_seconds_qy`, `incident_response_seconds_qy` | durations; **recompute from timestamps and report mismatch rate** [verify P0] | once their end time < T |
| `valid_dispatch_rspns_time_indc`, `valid_incident_rspns_time_indc` | keep durations only when `Y` and inside histogram-justified bounds | with the value |
| `initial_severity_level_code` | 1 most severe; high acuity = 1–3; low = 4–8 | at creation |
| `held_indicator` | held for no available unit [verify P0: held calls should have much larger dispatch time] | resolved later — only used as "held and still pending at T" |
| `reopen_indicator`, `transfer_indicator`, `standby_indicator` | drop rows = `Y` | — |
| `borough` | grain | yes |

Never use `final_*` fields as features. FDNY's response measure is not the Comptroller's
end-to-end time (IBO: ~2.5 min gap); never plot them on one axis.

## 3. Leakage rules

At cutoff T a feature may use only events timestamped before T. Durations only once their end
timestamp is before T. Backlog at T = created before T, not assigned before T, **not closed
before T**. Baselines and thresholds use only weeks before T. Splits are chronological:
train 2023-01→2025-06, validation 2025-07→2025-12, test 2026-01→latest (frozen before scoring).

## 4. Pipeline

Laptop (little-endian): `scripts/fetch_data.py` → `data/raw/incidents.csv` → DuckDB/pandas →
`data/borough_hour.csv` and `data/backlog_snapshots.csv`. Only these CSVs go to the VM (scp).
On the LinuxONE VM: pandas + xgboost (sklearn `HistGradientBoostingClassifier` fallback) from the
L1CC jupyter-lab-ml image. Train, calibrate, infer and replay on the VM; save xgboost as JSON.
No pickles, parquet or DuckDB across the endianness boundary. Commit aggregates only, never raw
rows.

## 5. Model

**Unit:** borough b × hourly cutoff T; predicts the hour [T, T+1).

**Features (all known before T):**
- backlog: `pending_high`, `pending_low`, `held_pending_low`, `held_pending_high`,
  `oldest_pending_age_s`, `n_pending_gt_10min`
- hospital load: `at_hospital` = units with `first_hosp_arrival_datetime < T` whose incident is
  not closed before T (proxy for handover load; close ≠ unit available, check in P0)
- recent volume: `n_calls` lag 1h / 3h / 24h, `n_high` lag 1h, `expected_calls` (trailing
  8-week same-hour-of-week mean; this is the only place demand enters)
- recent durations (ended before T): `asof_med_dispatch_s`, `asof_med_travel_s`, and their
  deviations `dispatch_dev`, `travel_dev` from the trailing baseline
- context: hour, day of week, borough, `stressed_now` (current-hour label as of T)

**Label:** `stress = 1` if the median dispatch seconds of severity 1–3 calls created in [T, T+1)
exceeds that borough's same-hour-of-week p80 over the 8 weeks before T. Missing if fewer than 5
such calls (Staten Island nights often). Secondary: same with response seconds.

**Hypotheses:**
- H1: queue state beats demand. xgboost on all features vs the same learner on `DEMAND` only
  (volume lags, expected calls, calendar, borough).
- H2: severity mix matters. Cascade test below (low-acuity backlog on/off).
- H3: earlier detection of new episodes. Onset recall and lead time vs persistence.

**Baselines:** hour-of-week rate, persistence (`stressed_now`), logistic regression on backlog
only, demand-only xgboost. Each model alerts on its own top 10% of validation hours, so alert
budgets match. If xgboost can't beat backlog-only logistic or demand-only, say so.

**Metrics (test window):** PR-AUC (day-block bootstrap CI), Brier, alert precision/recall,
**onset recall** (normal → stressed, which persistence misses by construction), **lead time**
(consecutive alert hours ending at a detected onset), **false alerts per day**.

**Cascade test:** nested models with/without `pending_low` + `held_pending_low`; report ΔPR-AUC
and lead time (does low-acuity backlog rise before high-acuity delay?).

**Known bias (documented, not leakage):** `asof_*`, `dispatch_dev` and `stressed_now` only see
calls already assigned by T, so during a surge they understate pressure; the backlog features
(`oldest_pending_age_s`, `n_pending_gt_10min`) carry that signal instead.

**Calibration and bands:** alerts rank on the raw score; ties are broken randomly so every model
spends the same alert budget (top 10% of validation hours). The shown `p_stress` and the Brier
score use an isotonic calibration fitted on validation. Labels need ≥ 5 high-acuity calls with a
valid dispatch time; valid dispatches over the 3 h cap are counted in the audit.
Bands: `alert` (top 10%) / `watch` (next 15%) / `normal`, or `insufficient_data` when there is no baseline yet.

**Bottleneck label:** `dispatch_dev`, `travel_dev` ≥ 1.0 → "dispatch pressure" / "travel
pressure" / "both" / "normal". Contributing indicators, not causes.

## 6. Briefing (predictive + generative)

A template (or cached local LLM output, llama.cpp with a big-endian GGUF) turns one `/risk`
payload into a ≤3-line operator note. `verify_briefing(note, payload)` extracts every number and
borough name from the note and fails if any is not in the payload. Report the rejection rate.
The LLM never sees row-level data.

## 7. API contract (F mocks this from the start)

`GET /health` → `{"status": "ok", "computed_on": "s390x", "model_version": "..."}`

`GET /risk?at=2026-02-14T18:00`
```json
{
  "at": "2026-02-14T18:00",
  "computed_on": "s390x",
  "model_version": "xgb-2026-10-17a",
  "boroughs": [
    {
      "borough": "BROOKLYN",
      "p_stress": 0.71,
      "band": "alert",
      "bottleneck": "dispatch pressure",
      "dispatch_dev": 1.8,
      "travel_dev": 0.2,
      "pending_high": 9,
      "pending_low": 31,
      "held_pending_low": 12,
      "oldest_pending_age_s": 1140,
      "top_factors": [{"feature": "held_pending_low", "value": 12, "direction": "up"}],
      "briefing": "Brooklyn: dispatch pressure, 12 low-acuity calls held, oldest waiting 1140 s.",
      "briefing_verified": true
    }
  ]
}
```

`GET /replay?start=...&end=...` → list of `/risk` payloads per hour plus realized `stress` per
borough-hour (hits and misses), served from precomputed JSON for 2–4 test weeks.

`GET /benchmark` → replay events/sec, p50/p99 scoring latency, CPU, measured on the VM.

## 8. Platform evidence (screenshots into `submission/evidence/`)

`uname -m` + `lscpu`; `grep nnpa /proc/cpuinfo` (claim acceleration only if present and timed);
`podman|docker ps` + image architecture s390x; `/health` showing `computed_on: s390x`; benchmark
output + `top`; Jupyter on the VM with the training notebook; SSH-key login, firewall rule,
non-root container user; both mandatory labs; architecture diagram.

## 9. Submission checklist

Submit at https://hack2skill.com/event/datathon-2026 (how-to: https://youtu.be/3_L3T__zEco).

- [ ] 4–6 members on Hack2skill; title `[Team Name]_IBM Z Datathon 2026 Project`
- [ ] Both mandatory AI labs completed
- [ ] Model trained and served on LinuxONE; evidence per §8
- [ ] Repo with run instructions, data sources, links to every open-source library used
- [ ] All code written during the event; nothing from other projects (e.g. FirstWave)
- [ ] ≤3-min video: problem, data, demo, IBM Z stack + LinuxONE instance and model, evaluation, limits
- [ ] Numbers in the video match `docs/evaluation.md`
- [ ] Optional: architecture flowchart, prototype link

## 10. Policy lab (`rescueflow/des.py`, `scripts/run_policy_lab.py`)

- **Input:** real call arrivals for one held-out week (creation time, borough, initial severity).
- **SCENARIO parameters (saved with every result):** units per borough (calibrated to the
  pre-evaluation median dispatch wait), on-scene mean 20 min, transport share 0.65, transport
  12 min, handover mean 20 min, handover slots = 0.3 × units, cross-borough travel 14 min,
  in-borough travel = FDNY median travel. Mutual aid for severity 1–3 only.
- **Arms:** `baseline`, `reactive` (activate 3 reserve units for 2 h when ≥ 3 high-acuity calls
  wait), `ai` (activate when the warning model's next-hour risk ≥ its training-top-5% threshold).
  Same budget (36 reserve unit-hours per week) for reactive and ai.
- **Warning model:** xgboost on online state (`des.SIM_FEATURES`) from training weeks with random
  handover shocks; label = next-hour median high-acuity wait above the training 80th percentile.
- **Common random numbers:** each call's dispatcher delay, travel, scene time, transport flag and
  handover time are drawn up front by call id, so arms differ only through the policy. CIs use
  Student's t over seeds. Scenario rates and travel medians come from before the evaluation week.
- **Metrics:** high-acuity P90/mean wait, all-call P90 wait, high-acuity share on scene ≤ 10 min,
  worst-borough high-acuity P90 (fairness). Paired differences across ≥ 20 seeds, 95% CI.
- **Outputs:** `artifacts/policy_lab.json` (results + parameters + calibration) and
  `artifacts/policy_lab_series.json` (per arm, seed 0, every 10 min per borough: `q_high`,
  `q_low`, `idle`, `busy`, `at_hospital`, `hosp_queue`, `reserve_active`), served at `/lab` and
  `/lab/series`.
