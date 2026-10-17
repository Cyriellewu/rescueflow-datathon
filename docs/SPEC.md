# RescueNYC — Shared Specification

This file is the contract between workstreams. Change it here first (coordinator approves),
then change code. Items marked **[verify P0]** are assumptions until `docs/data_audit.md`
confirms them against the real data.

## 1. Problem and user

- **User:** EMS operations manager / shift supervisor (decision support, human in the loop).
- **Question:** Is response performance in a borough about to deteriorate, is the pressure in
  *dispatch* (getting a unit assigned) or *travel* (getting it on scene), and where should I
  look first?
- **Theme fit:** Detect (elevated-delay risk), Decide (dispatch vs travel attribution, ranking),
  Respond (prioritized, explained alert for a human to act on).

## 2. Source data

NYC Open Data `76xm-jjuj` — EMS Incident Dispatch Data (FDNY). Timestamps are NYC local time.

Fields we use [verify P0 for definitions and validity flags]:

| Field | Meaning (per data dictionary) | Known at time T? |
|---|---|---|
| `incident_datetime` | call created in CAD | yes, if < T |
| `first_assignment_datetime` | first unit assigned | only if < T |
| `first_on_scene_datetime` | first unit on scene | only if < T |
| `dispatch_response_seconds_qy` | assignment − creation | only once assigned |
| `incident_travel_tm_seconds_qy` | on scene − assignment | only once on scene |
| `incident_response_seconds_qy` | on scene − creation | only once on scene |
| `valid_dispatch_rspns_time_indc`, `valid_incident_rspns_time_indc` | validity flags | with the value |
| `initial_severity_level_code` | 1 (most severe) … 8 | yes at creation |
| `final_severity_level_code` | after triage | **no** — leakage, don't use as a feature |
| `held_indicator` | call was held (no unit available) | only once resolved [verify P0] |
| `borough`, `incident_dispatch_area` | location | yes |

High acuity = `initial_severity_level_code` in {1, 2, 3}.

## 3. Leakage rules (non-negotiable)

A prediction issued at cutoff `T` (the start of hour `h+1`) may use:

1. Counts of incidents with `incident_datetime < T`.
2. A duration only if its end timestamp is `< T` (dispatch delay needs `first_assignment_datetime < T`,
   travel and response need `first_on_scene_datetime < T`).
3. **Pending backlog at T:** incidents created before `T` with no assignment before `T`. This is
   the most direct real-time dispatch-pressure signal and is computed from timestamps only.
4. Baselines fitted on the training period only.

Never use `final_*` fields, `incident_close_datetime`, or anything from hour `h+1` itself.
Splits are chronological: train → validation → test = final 4 weeks. No random splits.

## 4. Tables

Raw incident rows stay local (`data/raw/`, git-ignored). Only the aggregated table and a
small aggregated fixture are committed.

### `borough_hour` (one row per borough × hour; produced by `rescueflow/features.py`)

| Column | Type | Definition |
|---|---|---|
| `hour` | datetime | start of the hour (NYC local) |
| `borough` | str | one of 5 boroughs |
| `n_calls` | int | incidents created in the hour |
| `n_high` | int | high-acuity incidents created in the hour |
| `pending_at_end` | int | created before hour end, not assigned before hour end |
| `n_held` | int | incidents with `held_indicator = Y` created in the hour |
| `med_dispatch_s`, `med_travel_s`, `med_response_s` | float | medians over valid, high-acuity incidents created in the hour (target side) |
| `asof_med_dispatch_s`, `asof_med_travel_s` | float | medians over incidents whose end timestamp falls in the hour (feature side, leakage-safe) |

### Label `elevated_delay(b, h+1)`

1 if `med_response_s` of high-acuity incidents in `(b, h+1)` exceeds the training-period 80th
percentile for that borough × hour-of-week; 0 otherwise; missing if `n_high < 5`.
Threshold and minimum count are tunable in P2 but must be fixed before the test window is scored.

### Bottleneck indicators (per borough-hour, retrospective and as-of)

`dispatch_dev = (asof_med_dispatch_s − base_dispatch) / base_dispatch_iqr`, same for travel,
where the baseline is the training-period median/IQR for that borough × hour-of-week.
Label shown to user: "dispatch pressure", "travel pressure", "both", or "normal"
(threshold |dev| ≥ 1.0). These are **contributing indicators, not causes**.

## 5. Models (P2)

- **Baseline A:** hour-of-week historical rate of elevated delay per borough.
- **Baseline B:** persistence (this hour elevated → next hour elevated).
- **Model:** gradient boosting (LightGBM, sklearn `HistGradientBoostingClassifier` as a fallback
  if LightGBM won't build on s390x). Features: hour, dow, borough, lags of `n_calls`/`n_high`,
  `pending_at_end`, `asof_med_*`, rolling 3h/24h means, dispatch/travel deviations.
- **Metrics on test window:** PR-AUC, recall at top-k borough-hours (k = alerts an operator could
  act on), calibration plot, and the same for both baselines. Report honestly if it loses.

## 6. API contract (P3; frontend mocks this from day one)

`GET /health` → `{"status": "ok", "platform": "<uname -m>", "model_version": "<str>"}`

`GET /risk?at=2026-09-14T18:00` → risk for the next hour, using only data before `at`:
```json
{
  "at": "2026-09-14T18:00",
  "boroughs": [
    {
      "borough": "BROOKLYN",
      "risk": 0.71,
      "alert": true,
      "bottleneck": "dispatch pressure",
      "dispatch_dev": 1.8,
      "travel_dev": 0.2,
      "pending_now": 23,
      "top_factors": [{"feature": "pending_at_end", "value": 23, "direction": "up"}]
    }
  ],
  "computed_on": "s390x"
}
```

`GET /replay?start=...&end=...` → list of `/risk` payloads per hour (for the timeline), plus
the realized `elevated_delay` for each hour so the dashboard can show hits and misses.

## 7. Workstreams

| Workstream | Owns | First task |
|---|---|---|
| Coordinator | this spec, `PLAN.md`, merges | assign names, confirm deadline timezone |
| Data | `scripts/fetch_data.py`, `rescueflow/features.py`, `docs/data_audit.md`, fixture | run fetch locally, audit fields in §2 |
| ML/Evaluation | `rescueflow/model.py`, `rescueflow/baseline.py`, `docs/evaluation.md` | baselines on fixture |
| LinuxONE/API | `rescueflow/api.py`, `scripts/verify_linuxone.sh`, deployment notes | account + labs + dependency install on s390x |
| Frontend | `app/` dashboard | replay UI against mocked §6 payloads |
| Research/Pitch | README, video script, `submission/` | problem framing with Comptroller / Council sources |

## 8. Submission checklist

Submit at https://hack2skill.com/event/datathon-2026 (how-to video: https://youtu.be/3_L3T__zEco).

- [ ] Team of 4–6 registered on Hack2skill; title is `[Team Name]_IBM Z Datathon 2026 Project`
- [ ] Both mandatory AI labs completed (screenshots)
- [ ] Model inference runs on LinuxONE (log + screenshot of `computed_on: s390x`)
- [ ] Platform evidence screenshots: container running on s390x, VM resources, access controls
- [ ] GitHub repo with run instructions, data sources, and links to every open-source library used
- [ ] Optional but recommended: architecture flowchart, prototype link
- [ ] All code written during the event; no code copied from other projects (e.g. FirstWave)
- [ ] ≤ 3-minute video: problem, data, solution demo, IBM Z, evaluation and limitations
- [ ] Evaluation numbers in the video match `docs/evaluation.md`
