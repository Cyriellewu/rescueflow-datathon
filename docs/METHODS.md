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

## 4. Features (45), all known at T

| Group | Features | Gain share in the final model |
|---|---|---|
| The label's own stage (4) | last hour's completed low-acuity dispatch wait, its deviation from the trailing baseline (IQR units), its ratio to the label line, hours already late in a row | 35.8% |
| Flow and change (9) | assignments in the last 1 h / 3 h, calls closed last hour, net inflow, change in waiting / held / oldest wait / units at hospital over 1 h and 3 h | 22.2% |
| Queue state (7) | waiting high / low, held high / low, waiting > 10 min, oldest wait, units at hospitals | 17.7% |
| Demand (5) | calls last 1 h / 3 h / 24 h, high-acuity calls last hour, expected calls (8-week same-hour mean) | 7.5% |
| Recent high-acuity durations (4) | as-of median dispatch and travel, their deviations | 5.4% |
| Call-type mix (6) | last hour's counts in psychiatric, intoxication, minor trauma, minor medical, serious groups; psychiatric share | 4.2% |
| Weather (4) | temperature and wind last hour, rain and snow over the last 3 h | 2.6% |
| Calendar and place (3) | hour of day, day of week, borough | 2.1% |
| Road speed (2) | previous hour's mean speed, deviation from the borough's trailing same-hour norm | 1.4% |
| Already late, binary | `stressed_now` | 1.2% |

Gain share = the loss reduction attributable to each feature across all tree splits, normalised.
It describes what the trained model relies on; it is not a quality score and is not set by hand.
Cross-borough queue counts (3) were tested and dropped (PR-AUC +0.002); they remain a ladder rung. Adding the label's own stage was the change that moved the model: validation PR-AUC 0.604 → 0.624, test 0.567 → 0.595.

## 5. Models, side by side (same features, same training window, same alert budget)

Each model alerts on its own top 10% of validation hours, so the alert budgets match. PR-AUC with a
95% interval from a bootstrap over whole test days (200 draws).

| Model | PR-AUC (95% CI) | Alert precision | Onset recall | False alerts/day | Brier |
|---|---|---|---|---|---|
| XGBoost, all 45 features (primary) | 0.595 (0.563–0.621) | 0.69 | 0.09 | 4.0 | 0.153 |
| Histogram gradient boosting (scikit-learn), all features | 0.594 (0.564–0.619) | 0.69 | 0.10 | 4.1 | 0.154 |
| Random forest, all features | 0.577 (0.545–0.602) | 0.66 | 0.05 | 4.4 | 0.158 |
| XGBoost, onset-weighted (transitions ×3) | 0.572 (0.539–0.598) | 0.67 | **0.22** | 4.4 | 0.184 |
| Logistic regression, all features | 0.556 (0.523–0.582) | 0.65 | 0.13 | 4.8 | 0.161 |
| XGBoost, queue + flow + demand (no durations) | 0.528 (0.496–0.556) | 0.57 | 0.27 | 8.2 | – |
| XGBoost, demand features only (H1 control) | 0.471 (0.444–0.499) | 0.57 | 0.17 | 4.8 | 0.174 |
| Logistic regression, backlog only | 0.430 (0.399–0.457) | 0.48 | 0.25 | 9.7 | 0.197 |
| Persistence (stressed now) | 0.364 (0.341–0.385) | 0.47 | 0.00 | 5.5 | – |
| Hour-of-week history | 0.265 (0.247–0.283) | 0.26 | 0.11 | 7.9 | – |
| Random ranking (reference) | 0.27 | 0.27 | – | – | 0.19 |

Reading: the two boosting implementations tie; averaging the families does not beat the best of them; gradient boosting is the best ranker by a small margin over random forest and logistic
regression on the same inputs; the large gap is between any queue-aware model and demand-only.
The onset-weighted companion trades 0.03 of PR-AUC for nearly three times the onset recall and is
served alongside the primary score (`p_onset`).

Ablations: without call-type, road-speed and weather features the earlier 41-feature model scored the same (0.567 vs 0.567); trained from 2016 instead of 2023, 0.563; from 2005, 0.568; with other boroughs' queues, +0.002.

Four further changes were tried after v5, each selected on the validation window only, with the test window read
once at the end, and all recorded as null:

| Change (validation 2025-07 → 2025-12) | Val PR-AUC | Test PR-AUC (95% CI) | Note |
|---|---|---|---|
| Primary XGBoost v5, 45 features, citywide 10% budget | 0.6236 | 0.5955 (0.563–0.621) | precision 0.69, onset recall 0.09, 4.0 false alerts/day |
| LightGBM (8 configs, early stopping on validation) | 0.6232 | 0.5964 (0.565–0.621) | leaves 15, rate 0.03, 741 trees |
| CatBoost (8 configs) | 0.6250 | 0.5960 (0.564–0.621) | depth 6, rate 0.03, 1,113 iterations |
| Probability ensemble XGB + LGBM + CatBoost, weights 0.2 / 0.2 / 0.6 searched on validation | 0.6255 | 0.5974 (0.566–0.622) | paired day-block delta vs XGBoost +0.002 (+0.0003 to +0.0034); precision and false alerts unchanged |
| Per-borough alert budgets (each borough's own top 10% of validation scores) | 0.6236 (same scores) | precision 0.69 → 0.70, onset recall 0.09, 3.9 false alerts/day | evens alert rates (Bronx 17% → 12%, Staten Island 4% → 14% of hours) without helping onset recall |
| Two-stage demand: next-hour call-volume regressor (train-only, out-of-fold) as a feature plus its gap to the expected count | 0.6251 (+0.002, three seeds +0.001 to +0.003) | 0.596 (0.564–0.621) | the regressor beats the trailing mean (RMSE 7.1 vs 7.8 calls/h) but the stress model already has its inputs |
| Low-acuity throughput: assignments last hour, how many had waited > 10 min, as-of p90 wait, minutes since the last assignment | 0.6241 (+0.001) | 0.595 (0.564–0.620) | no single feature moves validation by more than ±0.0005 |
| Sub-hour leading indicators: ten 15/30-minute windows before T (calls, assignments, clearance ratio, low-acuity pending change, as-of 30-min median wait, fresh share of the backlog), hourly label kept | 0.6246 (+0.001; best three-feature subset +0.002) | not scored | onset recall −0.003; the hour-before snapshot already carries the short-term dynamics |
| Onset specialist: XGBoost trained only on currently-normal hours (class weights, hp grid, dynamics features, three seeds), compared on the same hours at equal budgets | conditional PR-AUC 0.429 vs 0.431 for the primary | 0.428 vs 0.430 | the rule it was tested inside is adopted (§7, onset warning); the model is not |

The three gradient-boosting families are interchangeable on this label, and the ensemble's reliable +0.002 does not
clear the pre-set +0.005 validation bar, would add two dependencies to the s390x deployment and would lose the single
booster's per-row explanations. The model family and the alert budget are not where the remaining headroom is; the
information ceiling is unit availability, which the public record does not contain.

## 6. Hyperparameters and calibration

Grid on validation only (8 settings: 300/4/0.05, 500/4/0.03, 300/6/0.05, 600/3/0.05 trees/depth/rate,
each with onset weight 1 or 3), chosen by validation PR-AUC with onset recall as tie-break. Chosen:
600 trees, depth 3, learning rate 0.05, subsample 0.8, colsample 0.8, weight 1. Validation PR-AUC
was 0.624 for weight 1 (final features) and about 0.03 lower for weight 3 with roughly three times the onset
recall, so the trade-off was visible before the test set was touched.

Probabilities shown to users are isotonic-calibrated on validation (Brier 0.153 on test against 0.19
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

Two alert tiers, one model. The acting budget is the top 10% of validation scores (12% of test hours alert). Inside
it, the top 5% of validation scores is "High alert" and the next 5% is "Watch"; everything else is "Normal". Both
cut-offs are score quantiles fixed on the validation window, not probabilities. Test, 2026-01 → 2026-09:

| Tier | Share of test hours | Precision | Recall | Onset recall | False alerts / day | Use |
|---|---|---|---|---|---|---|
| High alert (top 5%) | 5.7% | 0.78 | 0.17 | 0.02 | 1.4 | evaluate reserve capacity now |
| High alert + Watch (top 10%) | 12.0% | 0.69 | 0.31 | 0.09 | 4.0 | watch closely, prepare |

On validation the same tiers read 0.85 / 0.16 (high) and 0.76 / 0.31 (both). The top tier's higher precision is a
precision-recall choice at a smaller budget, not a more accurate model, and its onset recall shows what it buys:
High alert flags hours that are already late; a borough turning late from a normal hour is caught by the Watch tier
and the onset score. A caveat on independence: the budget table below was read on the test window before the 5% tier
was chosen, so the 0.78 is not a fully independent confirmation; the cut-off itself is fixed on validation and the
next unseen months are the clean check. RB-03's reserve results were run with the 10% warning threshold of the
lab's own model and do not transfer to a 5% trigger without rerunning the lab.

The onset warning, a second and conditional budget. An onset specialist (XGBoost trained only on currently-normal
hours, with class weights, an hp grid, queue-dynamics features and three seeds) ranks currently-normal validation
hours no better than the primary model's own scores on those hours (conditional PR-AUC 0.429 vs 0.431; identical
precision and onset recall at equal budgets), so no new model is served. What the experiment did establish is a
rule: flag a borough that is normal now when its served onset score (the onset-weighted companion, `p_onset`) is in
the top 5% of currently-normal validation hours, in addition to the primary alert. The control is the primary model
alerting just as often by lowering its own line:

| Validation (cut-offs fixed here) | Alert rate | Precision | Recall | Onset recall | False alerts / day |
|---|---|---|---|---|---|
| Primary alone (top 10%) | 10.0% | 0.758 | 0.280 | 0.074 | 2.6 |
| Primary + onset warning | 12.2% | 0.719 | 0.324 | **0.162** | 3.7 |
| Primary raised to 12.2% | 12.2% | 0.726 | 0.327 | 0.099 | 3.6 |
| **Test, one confirmatory read** | | | | | |
| Primary alone | 12.0% | 0.688 | 0.311 | 0.094 | 4.0 |
| Primary + onset warning | 14.9% | 0.660 | 0.369 | **0.202** | 5.4 |
| Primary raised to 14.9% | 14.9% | 0.658 | 0.368 | 0.139 | 5.5 |

At the same alert rate the warning finds roughly half again as many onsets as simply alerting more, at the same
precision. It is served as a flag on the risk payload and shown as "Onset warning" (a Watch-tier item) on the
dashboard; the acting budget's own numbers above are unchanged. The warning uses the onset model's raw score and the
borough's known current state, both already computed, so inference cost does not change.

Precision is a budget choice, not a model property. Moving the line, same model, same test window:

| Share of validation hours alerted | Test alert rate | Precision | Recall |
|---|---|---|---|
| 3% | 3.5% | 0.83 | 0.11 |
| 5% | 5.7% | 0.78 | 0.17 |
| 8% | 9.4% | 0.72 | 0.25 |
| 10% (default) | 12.0% | 0.69 | 0.31 |
| 15% | 17.6% | 0.63 | 0.42 |
| 20% | 23.1% | 0.59 | 0.51 |

A confirmation rule (alert only when this hour and the previous hour both score above the 10% line) reaches precision
0.74 at a 6.8% alert rate, but simply raising the line to the same alert rate gives 0.77, so confirmation is not
adopted. The dashboard's bands expose the same trade-off: "alert" is the top band, "watch" the next, and a supervisor
who wants fewer, surer alerts acts on alert only. What cannot be bought with the line is ranking quality: every model
family tried (§5) sits at precision 0.686–0.689 at the default budget.

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
−0.84 (−1.12 to −0.57). Under the handover shock (RB-02) the pattern repeats: P1 +0.80, P2 +0.45, oracle +0.04, reserves −0.91.
Interpretation per the protocol: prediction quality is not the binding
constraint for rebalancing; transfer time and origin coverage are. Not done: 24-hour warm-up, 100 seeds,
right-censoring of calls pending at the week boundary, non-inferiority test on high-acuity endpoints (they
were unchanged to two decimals in every arm).

## 10c. RB-03: the same reserve budget, five ways

Arms share 36 reserve unit-hours per week (3 units for 2 hours per activation): no reserves; a fixed
schedule at the six (hour-of-week, borough) cells with the highest late-share in the training weeks; reactive
(activate when ≥ 10 low-acuity calls wait); AI-timed (activate when the warning model's risk crosses its
training top-5% threshold); an oracle timed by perfect knowledge of next hour's exogenous arrivals. Same
calls, draws, fleet, traffic and seeds as §10.

| Arm | Normal week, Δ mean low-acuity wait (min) | Handover shock, Δ | Unit-hours used |
|---|---|---|---|
| Fixed schedule | −0.36 (−0.49 to −0.24) | −0.33 (−0.43 to −0.24) | 30 |
| Reactive | −0.94 | −0.71 | 36 |
| AI-timed | −0.84 (−1.12 to −0.57) | −0.91 (−1.31 to −0.51) | 24 / 32 |
| Arrivals oracle | −0.72 (−1.21 to −0.23) | −0.52 (−0.94 to −0.10) | 36 |

Paired differences: AI − fixed = −0.48 (−0.79 to −0.17) normal, −0.58 (−0.97 to −0.19) shock; AI − reactive
= +0.10 (−0.30 to +0.50) normal, −0.20 (−0.52 to +0.11) shock; oracle − AI = +0.13 (−0.33 to +0.58) normal,
+0.39 (+0.05 to +0.73) shock (AI better). High-acuity P90 and share within 10 minutes unchanged in all arms.
Reading: the timing decision is where the forecast adds value; a queue-state forecast outperforms a
schedule and an arrivals-only oracle, and equals reaction at lower cost.

### 10c-bis. Replication on IBM LinuxONE (s390x)

The whole pipeline and the lab were rerun natively on the LinuxONE VM (3 vCPU, Ubuntu 24.04, no container) with the
latest code (two alert tiers, onset warning, per-unit tracks). xgboost has no s390x wheel, so the primary model and
the lab's warning model there are scikit-learn HistGradientBoosting with the same features and hyperparameters.
Model quality is unchanged: test PR-AUC 0.596 (0.564–0.621), precision 0.69, 4.0 false alerts/day, top tier
precision 0.78 at 5.7% of hours; onset recall with the onset warning 0.205 against 0.140 for an equally frequent
raised line. The laptop's xgboost gave 0.595. The lab replication (20 seeds, 140 runs in 131 s) keeps the direction
of RB-03 but not all of its separations: AI-timed reserves vs none −0.46 min (−0.81 to −0.11, apart); fixed schedule
vs none −0.31 (−0.42 to −0.21, apart); AI vs fixed −0.15 (−0.55 to +0.25, not separable); AI vs reactive and vs the
arrivals oracle not separable. The laptop run (xgboost warning model) had AI vs fixed −0.58 (−0.97 to −0.19).
Reading: "reserves on the warning beat doing nothing" replicates across machines and models; the edge over a fixed
schedule depends on the warning model and is reported as such. Benchmark on the VM: replay 255 k events/s on one
core, 574 k on three (2.25×), 2.2 million times faster than the city's event stream, a year of the record in 14 s;
per-request scoring p50 2.3 ms, p99 5.3 ms with the sklearn model (laptop xgboost 1.7 / 3.5 ms).

Accelerator: the Telum on-chip AI accelerator is present (`nnpa` in /proc/cpuinfo). Two attempts to use it: a small
MLP through TensorFlow/PyTorch (not installed on the VM) and a Snap ML boosted-tree model compiled to the zDNN tensor
format. Snap ML installed and ran on CPU (600 trees, depth 3: 20.5 ms per 5,000 rows, 0.24 ms per single row, test
PR-AUC 0.591, fit in 6.2 s), but the zDNN path failed with "zDNN library supported only in Z systems": the Community
Cloud VM does not expose the zDNN library. No accelerator path ran; inference is on CPU
(`submission/evidence/snapml_bench_s390x.json`, `nnpa_bench.json`).

## 10d. Sensitivity: hospital time at its real value

The outside check (`docs/external_validation.md`) found that real ambulances are tied up a median of 41–43 minutes
at the hospital, against the lab's handover draw with a median of 13.9 (exponential, mean 20). RB-03 was rerun with
the mean raised to 59 minutes (median 41), everything else unchanged (`scripts/run_policy_lab.py --handover-min 59
--calib-max 5`, 20 seeds, outputs in `artifacts_h41/` and `artifacts_h41b/`, not the official run):

- The fleet needed to reproduce FDNY's all-call p90 dispatch wait roughly doubles (Bronx 49 → 102 units, Brooklyn
  63 → 122, Manhattan 51 → 106, Queens 47 → 94, Staten Island 12 → 22), and the calibration then fits where the
  original search ceiling (twice the demand estimate) had not let it.
- The handover shock does 2.7× the damage: +5.3 min low-acuity mean wait (4.2 to 6.4) against +2.0 in the official run.
- At the original 36 reserve unit-hours, the ranking of RB-03 holds with intervals apart but the effects shrink to a
  fifth: AI-timed vs none −0.16 min (−0.20 to −0.11), fixed vs none −0.09, AI vs fixed −0.06 (−0.11 to −0.01),
  AI vs reactive 0.00, arrivals oracle +0.13 worse than the model. Three units are a smaller share of a fleet twice
  the size.
- At the same share of the fleet (6 units per activation, 72 unit-hours): AI-timed vs none −0.35 (−0.43 to −0.26),
  fixed vs none −0.18, AI vs fixed −0.17 (−0.27 to −0.07), AI vs reactive −0.04 (−0.14 to +0.07), oracle +0.31 worse.

Reading: the direction of every RB-03 finding survives a realistic hospital time; the size of the reserve effect
depends on the reserve's share of the fleet, not on the hospital assumption. The lab under-states hospital tie-up,
so its baseline fleet is too small by about half, which is stated on the dashboard.

## 11. What is not evaluated here

Real-world minutes or lives saved; FDNY's actual dispatch decisions (no unit data); any effect of the
screen on supervisors (needs the stepped-wedge pilot in `docs/UX.md`).
