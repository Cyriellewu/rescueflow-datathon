# RescueNYC — Methods: data, splits, label, features, models, evaluation

Everything below is produced by `scripts/run_pipeline.py` and `scripts/run_policy_lab.py` and can be
regenerated; the numbers are from the final laptop run of Oct 17 2026 (the VM run reproduces them).

## 1. Data

| Source | Range | Size | Used for |
|---|---|---|---|
| FDNY EMS Incident Dispatch (NYC Open Data 76xm-jjuj), 22 of 31 columns | 2023-01 → 2026-09 | 6,065,090 calls, 5,960,214 after cleaning | labels, features, replay, lab, audit |
| Same dataset, 18 columns | 2005-01 → 2022-12 | 22.6 M calls (28.6 M with 2023–2026) | long-run audit only (`docs/long_run_audit.md`): demand +35% 2005–2019 with a flat queue; flat demand and a 9× queue after 2022 |
| NYC DOT traffic speeds (i4gi-tjb9), aggregated server-side | 2023-01 → 2026-09 | 165 k borough-hours | features; travel-pressure split; simulator travel multipliers |
| Open-Meteo hourly weather, Central Park | 2023-01 → 2026-09 | 32,856 hours | features |
| Spatial layer: ZIP centroids, NYS DOH hospitals, assumed bases, fitted travel model | 3 months of FDNY for the fit | 229 ZIPs, 67 hospitals, 33 bases | map; cross-borough travel matrix |

Cleaning: drop reopened, transfer and standby incidents and rows with no usable borough or severity;
recompute every duration from timestamps (0.02% disagree with FDNY's published seconds by more than
1 s); keep durations only when FDNY flags them valid and they are under 3 hours. `final_*` columns are
never used (known only after the crew assesses the patient).

## 2. Unit of analysis and label

One row = one borough × one hourly cutoff T (5 boroughs × every hour, 164,285 rows; 144,224 with a
label). Features use only events timestamped before T; the label describes [T, T+1h).

**Label (primary):** `stress = 1` when the median dispatch wait (call created → first unit assigned)
of severity 4–8 calls created in [T, T+1h) exceeds that borough's 80th percentile for the same
hour of the week over the previous 8 weeks. Missing when fewer than 5 such calls. Why low acuity:
FDNY protects severity 1–3 (median dispatch under 30 s) by holding the rest; the queue lives in
severity 4–8 (p90 wait 20–50 min, held 35–56%). High-acuity dispatch, travel and response labels
are reported as sensitivity runs.

## 3. Splits (chronological, never random)

| Split | Window | Labelled rows | Stress rate | Used for |
|---|---|---|---|---|
| Train | 2023-01-29 → 2025-06-30 | 95,094 | 0.26 | fitting |
| Validation | 2025-07-01 → 2025-12-31 | 19,836 | 0.27 | hyperparameter choice, isotonic calibration, alert thresholds |
| Test | 2026-01-01 → 2026-09-30 | 29,294 | 0.27 | every reported metric, scored once |

Train starts four weeks after the data because the label and baselines need an 8-week trailing
window (minimum 4). No choice in this document was made by looking at the test window; the label
target was argued from the audit and the SPEC's question (see PLAN.md).

## 4. Features (41), all known at T

| Group | Features | Gain share in the final model |
|---|---|---|
| Already late | `stressed_now` (the current hour's own label as of T) | 51.1% |
| Flow and change (9) | assignments in the last 1 h / 3 h, calls closed last hour, net inflow, change in waiting / held / oldest wait / units at hospital over 1 h and 3 h | 15.0% |
| Queue state (7) | waiting high / low, held high / low, waiting > 10 min, oldest wait, units at hospitals | 14.3% |
| Demand (5) | calls last 1 h / 3 h / 24 h, high-acuity calls last hour, expected calls (8-week same-hour mean) | 6.2% |
| Recent durations (4) | as-of median dispatch and travel, their deviations from baseline (IQR units) | 4.4% |
| Call-type mix (6) | last hour's counts in psychiatric, intoxication, minor trauma, minor medical, serious groups; psychiatric share | 3.1% |
| Calendar and place (3) | hour of day, day of week, borough | 2.7% |
| Weather (4) | temperature and wind last hour, rain and snow over the last 3 h | 1.9% |
| Road speed (2) | previous hour's mean speed, deviation from the borough's trailing same-hour norm | 1.3% |

Gain share = the loss reduction attributable to each feature across all tree splits, normalised.
It describes what the trained model relies on; it is not a quality score and is not set by hand.
Cross-borough queue counts (3) were tested and dropped (PR-AUC +0.002); they remain a ladder rung.

## 5. Models, side by side (same features, same training window, same alert budget)

Each model alerts on its own top 10% of validation hours, so the alert budgets match. PR-AUC with a
95% interval from a bootstrap over whole test days (200 draws).

| Model | PR-AUC (95% CI) | Alert precision | Onset recall | False alerts/day | Brier |
|---|---|---|---|---|---|
| XGBoost, all 41 features (primary) | 0.567 (0.533–0.593) | 0.65 | 0.09 | 5.1 | 0.159 |
| Ensemble: mean rank of the four families below | 0.561 (0.530–0.588) | 0.68 | 0.06 | – | – |
| Histogram gradient boosting (scikit-learn), all features | 0.561 (0.531–0.587) | 0.64 | 0.10 | 5.1 | – |
| Random forest, all features | 0.542 (0.511–0.569) | 0.62 | 0.09 | 5.7 | – |
| XGBoost, onset-weighted (transitions ×3) | 0.539 (0.508–0.567) | 0.61 | **0.25** | 6.1 | 0.206 |
| Logistic regression, all features | 0.535 (0.503–0.563) | 0.61 | 0.15 | 5.8 | – |
| XGBoost, queue + flow + demand (no durations) | 0.528 (0.496–0.556) | 0.57 | 0.27 | 8.2 | – |
| XGBoost, demand features only (H1 control) | 0.471 (0.444–0.499) | 0.57 | 0.17 | 4.8 | – |
| Logistic regression, backlog only | 0.430 (0.399–0.457) | 0.48 | 0.25 | 9.7 | – |
| Persistence (stressed now) | 0.364 (0.341–0.385) | 0.47 | 0.00 | 5.5 | – |
| Hour-of-week history | 0.265 (0.247–0.283) | 0.26 | 0.11 | 7.9 | – |
| Random ranking (reference) | 0.27 | 0.27 | – | – | 0.19 |

Reading: averaging the families does not beat the best of them (0.561 vs 0.567); gradient boosting is the best ranker by a small margin over random forest and logistic
regression on the same inputs; the large gap is between any queue-aware model and demand-only.
The onset-weighted companion trades 0.03 of PR-AUC for nearly three times the onset recall and is
served alongside the primary score (`p_onset`).

Ablations on the primary model: without call-type, road-speed and weather features 0.567
(identical); trained from 2016 instead of 2023, 0.563; with other boroughs' queues, 0.568.

## 6. Hyperparameters and calibration

Grid on validation only (8 settings: 300/4/0.05, 500/4/0.03, 300/6/0.05, 600/3/0.05 trees/depth/rate,
each with onset weight 1 or 3), chosen by validation PR-AUC with onset recall as tie-break. Chosen:
600 trees, depth 3, learning rate 0.05, subsample 0.8, colsample 0.8, weight 1. Validation PR-AUC
was 0.604–0.607 for weight 1 and 0.569–0.571 for weight 3 (onset recall 0.05 vs 0.17), so the
trade-off was visible before the test set was touched.

Probabilities shown to users are isotonic-calibrated on validation (Brier 0.159 on test against 0.19
for always predicting the base rate). Bands: alert = top 10% of validation raw scores (p ≥ 0.42 after
calibration), watch = next 15%.

## 7. Metrics, defined

- **PR-AUC**: area under precision–recall over all alert budgets; random = base rate (0.27).
- **Alert precision / recall**: at the fixed 10% budget.
- **Onset recall**: among hours that turn from normal to late, the share flagged at the cutoff before.
- **Lead (h)**: consecutive alert hours ending at a caught onset.
- **False alerts per day**: citywide, at the budget.
- **Brier**: mean squared error of the calibrated probability.
- Intervals: day-block bootstrap, 200 draws, 2.5/97.5 percentiles.

## 8. Attribution: the bottleneck tag

`dispatch_dev` and `travel_dev` are last hour's as-of medians minus the borough's trailing
same-hour median, in IQR units; ≥ 1.0 means pressure. Travel pressure is split by road speed:
roads ≥ 10% slower than their norm → "travel pressure (roads)"; roads normal → "travel pressure
(units far)". In the 2026 test window 12.8% of borough-hours are "units far" and 3.7% "roads".
Next-hour stress rate by tag: normal 0.23, units far 0.34, roads 0.42, dispatch 0.41, both 0.54.

## 9. Route and traffic in the simulator

- **In-borough travel**: the borough's observed FDNY median travel time, log-normal noise.
- **Cross-borough travel (route)**: `spatial/spatial_data/borough_travel_matrix.json`, the
  expected time from the origin borough's assumed bases (one per FDNY dispatch area, at its busiest
  ZIP, weighted by call share) to the destination borough's ZIP centroids (weighted by call volume),
  from the spatial model (straight-line distance × a pace fitted on FDNY transport legs, hour-of-day
  multipliers; held-out ZIP validation correlation 0.73). Because that model was fitted on transport
  legs, which are slower than lights-and-sirens response, each cross-borough value is rescaled by the
  destination's observed/modelled in-borough ratio. Examples at 17:00: Bronx → Manhattan 13.7 min,
  Queens → Brooklyn 15.0, Queens → Bronx 34.9.
- **Traffic**: for the replayed week, each borough-hour's travel is multiplied by (median speed over
  the prior 8 weeks ÷ that hour's NYC DOT speed), clipped to [0.7, 2.0]. For the week of 2026-09-21
  the mean multiplier was Bronx 1.06, Queens 1.04, Manhattan 0.95.
- Not modelled: street-level routing and unit positions (no public source).

## 10. Policy lab design

Same real calls (week of 2026-09-21), same random draws per call across arms. Fleet per borough
calibrated so the simulated all-call p90 wait matches the 8 weeks before (Bronx 49, Brooklyn 63,
Manhattan 51, Queens 47, Staten Island 12 units); low-acuity calls held while idle units ≤ 10% of
the fleet; handover 20 min mean with 0.3 slots per unit; Brooklyn handover ×2 on Wednesday 14–22.
Arms: no reserves, reactive reserves (3 units for 2 h when ≥ 10 low-acuity calls wait), AI reserves
(when the warning model's next-hour risk crosses its training top-5% threshold); 36 reserve
unit-hours per week for both. 20 seeds, Student-t 95% intervals on paired differences.

Result: baseline low-acuity P90 19.4 min; shock +3.0 (CI +2.5 to +3.4); AI vs none −0.91 min mean
wait (−1.31 to −0.51) using 32 of 36 unit-hours; AI vs reactive −0.20 (−0.52 to +0.11), no clear
difference. High-acuity waits unchanged in every arm. At 1.5× demand the fleet saturates and the
scenario is uninformative.

## 10b. RB-01: pre-registered rebalancing protocol

Question: under normal observed demand, does forecasting next-hour congestion enable better cross-borough
rebalancing than reacting to the current queue, at equal budget and without harming high-acuity service?
Design: same calls, fleet, traffic and seeds as §10, no handover shock, decisions every 60 minutes, shared
budget of 100 moves and 2,000 relocation unit-minutes, at most 3 moves per decision, in-transit units
unavailable, 10% protected floor per borough, high-acuity priority. Arms: P0 none, P1 reactive (queue
threshold), P2 predictive (warning threshold), diagnostics (queue trigger with forecast-informed planner;
warning trigger with state-only planner), ablations (hour-of-week risk, demand-only risk), P3 oracle
(perfect knowledge of next hour's exogenous arrivals, never of simulated waits). Primary endpoint: paired
difference in low-acuity mean dispatch wait; 20 seeds (100 planned), Student-t 95% intervals.

Result (baseline 13.81 min): P1 +0.76 (−0.09 to +1.60), P2 −0.08 (−0.39 to +0.23), P2 − P1 = −0.83 (−1.61
to −0.05) with P2 moving 0.4 units a week against P1's 63; oracle −0.10 (−0.78 to +0.57). No relocation
policy, oracle included, beats no relocation. The same week's warning-triggered reserve activation gives
−0.84 (−1.12 to −0.57). Interpretation per the protocol: prediction quality is not the binding
constraint for rebalancing; transfer time and origin coverage are. Not done: 24-hour warm-up, 100 seeds,
right-censoring of calls pending at the week boundary, non-inferiority test on high-acuity endpoints (they
were unchanged to two decimals in every arm).

## 11. What is not evaluated here

Real-world minutes or lives saved; FDNY's actual dispatch decisions (no unit data); any effect of the
screen on supervisors (needs the stepped-wedge pilot in `docs/UX.md`).
