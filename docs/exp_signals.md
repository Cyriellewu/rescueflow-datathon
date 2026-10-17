# Experiment: hospital-side pressure and calendar features (recorded as null)

Script: `scripts/exp_signals.py` (same protocol as `scripts/exp_subhour.py`: XGBoost, HP {'n_estimators': 600, 'max_depth': 3, 'learning_rate': 0.05, 'onset_weight': 1.0}, seeds [0, 1, 2],
selection on the validation window 2025-07-01 → 2025-12-31 only, one confirmatory read of the test window 2026).
Data: `data/raw` (18 columns, no `initial_call_type`), so the base is the 39 features with the
all-missing call-type mix dropped. Label: next-hour low-acuity dispatch stress, as in the primary model.

**New candidates.** HOSPITAL (all known before T): median minutes at hospital of units that left in the last hour,
its deviation from the borough's trailing same-hour median, hospital arrivals in the last hour, units at a hospital
for more than 45 / 60 min at T. CALENDAR: US federal holiday (or Dec 31), holiday eve, month.

## Validation (mean of 3 seeds)

| Design | PR-AUC | vs base | seeds |
|---|---|---|---|
| base | 0.6228 | +0.0000 | 0.6220, 0.6235, 0.6228 |
| base+HOSPITAL | 0.6228 | +0.0000 | 0.6231, 0.6221, 0.6232 |
| base+CALENDAR | 0.6265 | +0.0037 | 0.6265, 0.6269, 0.6261 |
| base+HOSPITAL+CALENDAR | 0.6263 | +0.0036 | 0.6268, 0.6257, 0.6264 |

| Single feature added | PR-AUC | vs base |
|---|---|---|
| +hosp_dwell_med_lag1 | 0.6234 | +0.0006 |
| +hosp_dwell_dev | 0.6234 | +0.0006 |
| +hosp_arrivals_lag1 | 0.6227 | -0.0001 |
| +hosp_stuck_45 | 0.6233 | +0.0006 |
| +hosp_stuck_60 | 0.6228 | +0.0000 |
| +is_holiday | 0.6226 | -0.0002 |
| +holiday_eve | 0.6226 | -0.0002 |
| +month | 0.6260 | +0.0032 |

Rule fixed before the test read: the smallest set within 0.001 of the best validation PR-AUC → **base + month**.

## Test, one read (mean of 3 seeds)

| Design | PR-AUC | alert precision | onset recall | false alerts / day |
|---|---|---|---|---|
| base | 0.5939 | 0.688 | 0.096 | 4.02 |
| base + month | 0.5932 | 0.690 | 0.098 | 3.96 |

## Reading

- **Hospital-side pressure adds nothing** (validation +0.0000). The model already sees how many units are at
  hospitals and how that count moved; how long they have stayed carries no extra information about next hour's queue.
- **Calendar**: the validation gain (+0.003, every seed) came almost entirely from `month` and **did not transfer**
  to the test window (−0.0007): the validation window is July–December, so month learned that half-year's
  seasonality rather than a stable pattern. Holiday flags add nothing (holidays are few and the trailing
  baselines already absorb most of their effect).
- Primary model unchanged. Same conclusion as the other post-v5 experiments: the information in the public record,
  not the algorithm or the feature list, sets the ceiling.
