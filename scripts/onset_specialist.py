"""Onset specialist: a model trained and scored ONLY on hours that are currently normal (stressed_now == 0),
label = stress in the next hour, i.e. "turns late from normal".

Everything is developed and selected on train + validation. The test window is scored exactly once, at the
end, for the final chosen design (a single confirmatory read), and labelled as such in the JSON.

    .venv/bin/python scripts/onset_specialist.py --csv artifacts/borough_hour.csv --out artifacts_onset/onset_specialist.json

Sections of the JSON:
  conditional     specialist vs primary vs onset-weighted model, scored on the same validation currently-normal
                  hours at the same alert count (top 5% / top 10% of those hours)
  grid            class weight x hyperparameters, selected on validation conditional PR-AUC
  seeds           the chosen config at 3 seeds
  dynamics        the chosen config with queue-dynamics features added (differences, clearance ratio)
  combination     two-model alert rule on all validation hours vs the primary at an equal alert rate
  test_read       the single confirmatory read on the test window (chosen design, validation thresholds)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.features import FEATURES  # noqa: E402

PRIMARY_HP = {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.05, "onset_weight": 1.0}  # served v5 model
ONSET_WEIGHTED_HP = {**PRIMARY_HP, "onset_weight": 3.0}                                           # served p_onset
POS_WEIGHTS = [1.0, 2.0, 4.0]
HP_GRID = [{"n_estimators": n, "max_depth": d, "learning_rate": 0.05}
           for n, d in [(300, 4), (600, 4), (300, 5), (600, 5), (600, 3)]]   # DEFAULT_HP first; (600, 3) = primary's
SEEDS = [0, 1, 2]
BUDGETS = [0.05, 0.10]
WARN_BUDGET = 0.05        # specialist warnings: top 5% of currently-normal validation hours
DYNAMICS = ["pending_low_diff2", "disp_low_diff1", "disp_low_diff2", "clearance_ratio_lag1", "pending_low_delta1_lag1"]
ADOPT_MAX_PRECISION_LOSS = 0.02


def add_dynamics(table: pd.DataFrame) -> pd.DataFrame:
    """Queue-dynamics features from existing columns only (per borough, previous hours; NaN across gaps)."""
    t = table.sort_values(["borough", "hour"]).copy()
    by_b = t.groupby("borough")
    contiguous = by_b["hour"].diff() == pd.Timedelta(hours=1)
    lag = lambda col: by_b[col].shift(1).where(contiguous)  # noqa: E731
    # pending_low_delta1 = pending_low(T) - pending_low(T-1) already exists; second difference is its change
    t["pending_low_delta1_lag1"] = lag("pending_low_delta1")
    t["pending_low_diff2"] = t["pending_low_delta1"] - t["pending_low_delta1_lag1"]
    t["disp_low_diff1"] = t["asof_med_dispatch_low_s"] - lag("asof_med_dispatch_low_s")
    t["disp_low_diff2"] = t["disp_low_diff1"] - lag("disp_low_diff1")
    t["clearance_ratio_lag1"] = t["assigned_lag1"] / (t["n_calls_lag1"] + 1)
    return t.sort_index()


def normal_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["stressed_now"] == 0]


def fit_specialist(train_normal, features, seed=0, hp=None, pos_weight=1.0):
    # on the currently-normal subset every positive is an onset, so fit_xgb's onset_weight is a positive-class weight
    return m.fit_xgb(train_normal, features, seed=seed, hp={**(hp or {}), "onset_weight": pos_weight})


def conditional_metrics(df_normal, scores, thresholds: dict | None = None, seed=0) -> dict:
    """PR-AUC and precision/recall among currently-normal hours at each budget.
    thresholds: {budget: score cut}; derived from these scores when None (validation), else applied as given (test)."""
    y = df_normal["stress"].astype(int).to_numpy()
    s = m.tiebreak(scores, seed + 1)
    thr = thresholds or {b: float(np.quantile(s, 1 - b)) for b in BUDGETS}
    out = {"n": int(len(y)), "n_onsets": int(y.sum()), "onset_rate": float(y.mean()), "pr_auc": m._pr_auc(y, s),
           "thresholds": {str(b): float(v) for b, v in thr.items()}}
    for b, cut in thr.items():
        flag = s >= cut
        out[f"at_{int(round(float(b) * 100))}pct"] = {
            "alert_rate": float(flag.mean()), "n_alerts": int(flag.sum()),
            "precision": float(y[flag].mean()) if flag.any() else float("nan"),
            "recall": float(flag[y == 1].mean()) if (y == 1).any() else float("nan")}
    return out


def _alert_metrics(df, alert) -> dict:
    y = df["stress"].astype(int).to_numpy()
    now = df["stressed_now"].to_numpy()
    onset = (now == 0) & (y == 1)
    days = max(df["hour"].dt.floor("D").nunique(), 1)
    return {"alert_rate": float(alert.mean()), "n_alerts": int(alert.sum()),
            "precision": float(y[alert].mean()) if alert.any() else float("nan"),
            "recall": float(alert[y == 1].mean()),
            "onset_recall": float(alert[onset].mean()) if onset.any() else float("nan"),
            "false_alerts_per_day": float((alert & (y == 0)).sum() / days)}


def combination(df, primary_scores, specialist_scores, primary_thr: float, warn_thr: float, seed=0,
                match_rate: float | None = None, primary_val_scores=None, other_warners: dict | None = None) -> dict:
    """(i) primary alone, (ii) primary + specialist warnings on currently-normal hours,
    (iii) primary with its budget raised to (ii)'s alert rate (quantile on validation scores when given; and
    at (ii)'s realized rate on this window), (iv) controls: the same rule with another model's scores as the
    warning source, other_warners = {name: (scores, warn_threshold)} - e.g. the primary's own scores."""
    normal = df["stressed_now"].to_numpy() == 0
    p = m.tiebreak(primary_scores, seed + 1)
    primary = p >= primary_thr

    def with_warnings(scores, thr):
        warn = normal & (m.tiebreak(scores, seed + 1) >= thr)
        return {**_alert_metrics(df, primary | warn), "n_warnings_added": int((warn & ~primary).sum())}

    out = {"primary_alone": _alert_metrics(df, primary), "primary_plus_warnings": with_warnings(specialist_scores, warn_thr)}
    realized = out["primary_plus_warnings"]["alert_rate"]
    rate = realized if match_rate is None else match_rate
    ref = m.tiebreak(primary_val_scores, seed + 1) if primary_val_scores is not None else p
    raised_thr = float(np.quantile(ref, 1 - rate))
    out["primary_raised_budget"] = {**_alert_metrics(df, p >= raised_thr), "threshold": raised_thr, "matched_alert_rate": rate}
    out["primary_raised_budget_equal_rate"] = _alert_metrics(df, p >= float(np.quantile(p, 1 - realized)))
    for name, (scores, thr) in (other_warners or {}).items():
        out[f"primary_plus_{name}_warnings"] = with_warnings(scores, thr)
    ii, iii = out["primary_plus_warnings"], out["primary_raised_budget_equal_rate"]
    out["adopt_worthy"] = bool(ii["onset_recall"] > iii["onset_recall"]
                               and ii["precision"] >= iii["precision"] - ADOPT_MAX_PRECISION_LOSS)
    out["onset_recall_gain_vs_raised"] = ii["onset_recall"] - iii["onset_recall"]
    out["precision_change_vs_raised"] = ii["precision"] - iii["precision"]
    if "primary_plus_primary_own_warnings" in out:
        iv = out["primary_plus_primary_own_warnings"]
        out["specialist_onset_recall_gain_vs_primary_own_warnings"] = ii["onset_recall"] - iv["onset_recall"]
        out["specialist_precision_change_vs_primary_own_warnings"] = ii["precision"] - iv["precision"]
    return out


def run(table: pd.DataFrame, val_start, test_start, quick=False, log=print) -> dict:
    table = add_dynamics(table)
    split = m.split_by_dates(table, pd.Timestamp(val_start), pd.Timestamp(test_start))
    tr_n, va_n, te_n = normal_only(split.train), normal_only(split.val), normal_only(split.test)
    hp_grid, weights, seeds = (HP_GRID[:1], POS_WEIGHTS[:1], SEEDS[:1]) if quick else (HP_GRID, POS_WEIGHTS, SEEDS)
    res = {"windows": {k: [str(getattr(split, k)["hour"].min()), str(getattr(split, k)["hour"].max()),
                           int(len(getattr(split, k))), int(len(normal_only(getattr(split, k))))]
                       for k in ["train", "val", "test"]},
           "features_primary": len(FEATURES), "dynamics_features": DYNAMICS, "budgets": BUDGETS}

    # --- reference models: primary (served) and onset-weighted (served as p_onset), trained on all hours
    log("fitting primary and onset-weighted reference models")
    primary = m.fit_xgb(split.train, FEATURES, hp=PRIMARY_HP)
    onsetw = m.fit_xgb(split.train, FEATURES, hp=ONSET_WEIGHTED_HP)
    p_val, ow_val = m.predict(primary, split.val), m.predict(onsetw, split.val)
    p_val_n, ow_val_n = m.predict(primary, va_n), m.predict(onsetw, va_n)

    # --- Q2: class weight x hp grid for the specialist, 45 features, selected on validation conditional PR-AUC
    log(f"grid: {len(hp_grid)} hp x {len(weights)} weights")
    trials = []
    for hp in hp_grid:
        for w in weights:
            clf = fit_specialist(tr_n, FEATURES, 0, hp, w)
            cm = conditional_metrics(va_n, m.predict(clf, va_n))
            trials.append({**hp, "pos_weight": w, "val_pr_auc": cm["pr_auc"],
                           "val_precision_5pct": cm["at_5pct"]["precision"], "val_recall_5pct": cm["at_5pct"]["recall"],
                           "val_precision_10pct": cm["at_10pct"]["precision"], "val_recall_10pct": cm["at_10pct"]["recall"]})
            log(f"  {hp['n_estimators']}t d{hp['max_depth']} w{w}: PR-AUC {cm['pr_auc']:.4f} "
                f"P@5 {cm['at_5pct']['precision']:.3f} R@5 {cm['at_5pct']['recall']:.3f}")
    best = max(trials, key=lambda t: (round(t["val_pr_auc"], 3), t["val_recall_5pct"]))
    chosen_hp = {k: best[k] for k in ["n_estimators", "max_depth", "learning_rate"]}
    chosen_w = best["pos_weight"]
    res["grid"] = {"trials": trials, "chosen_hp": chosen_hp, "chosen_pos_weight": chosen_w}

    # --- Q2: 3 seeds for the chosen config
    seed_rows, seed_scores = [], []
    for sd in seeds:
        clf = fit_specialist(tr_n, FEATURES, sd, chosen_hp, chosen_w)
        s = m.predict(clf, va_n)
        seed_scores.append(s)
        cm = conditional_metrics(va_n, s, seed=sd)
        seed_rows.append({"seed": sd, "pr_auc": cm["pr_auc"], "precision_5pct": cm["at_5pct"]["precision"],
                          "recall_5pct": cm["at_5pct"]["recall"], "precision_10pct": cm["at_10pct"]["precision"],
                          "recall_10pct": cm["at_10pct"]["recall"]})
    res["seeds"] = {"per_seed": seed_rows,
                    "mean": {k: float(np.mean([r[k] for r in seed_rows])) for k in seed_rows[0] if k != "seed"},
                    "std": {k: float(np.std([r[k] for r in seed_rows])) for k in seed_rows[0] if k != "seed"}}

    # --- Q2: queue-dynamics features added to the chosen config (seed 0)
    feats_dyn = FEATURES + DYNAMICS
    dyn = fit_specialist(tr_n, feats_dyn, 0, chosen_hp, chosen_w)
    cm_dyn = conditional_metrics(va_n, m.predict(dyn, va_n, feats_dyn))
    cm_base = conditional_metrics(va_n, seed_scores[0])
    res["dynamics"] = {"with_dynamics": cm_dyn, "without": cm_base,
                       "delta_pr_auc": cm_dyn["pr_auc"] - cm_base["pr_auc"],
                       "delta_recall_5pct": cm_dyn["at_5pct"]["recall"] - cm_base["at_5pct"]["recall"],
                       "adopted": bool(cm_dyn["pr_auc"] > cm_base["pr_auc"] + 0.005)}
    final_features = feats_dyn if res["dynamics"]["adopted"] else FEATURES
    final_val_scores = m.predict(dyn, va_n, feats_dyn) if res["dynamics"]["adopted"] else seed_scores[0]
    final_model = dyn if res["dynamics"]["adopted"] else fit_specialist(tr_n, FEATURES, 0, chosen_hp, chosen_w)

    # --- Q1: fair comparison on the same validation currently-normal hours, same alert count
    res["conditional"] = {"specialist": conditional_metrics(va_n, final_val_scores),
                          "primary_restricted": conditional_metrics(va_n, p_val_n),
                          "onset_weighted_restricted": conditional_metrics(va_n, ow_val_n)}

    # --- Q3: operational combination on all validation hours
    primary_thr = m.band_thresholds(p_val)["alert"]
    warn_thr = res["conditional"]["specialist"]["thresholds"][str(WARN_BUDGET)]
    spec_val_all = m.predict(final_model, split.val, final_features)
    # controls: the same two-tier rule, but the warning source is the primary's (or onset-weighted model's) own
    # scores among currently-normal hours at the same 5% budget - tells rule gain apart from model gain
    own_thr = res["conditional"]["primary_restricted"]["thresholds"][str(WARN_BUDGET)]
    ow_thr = res["conditional"]["onset_weighted_restricted"]["thresholds"][str(WARN_BUDGET)]
    res["combination"] = {"validation": combination(
        split.val, p_val, spec_val_all, primary_thr, warn_thr,
        other_warners={"primary_own": (p_val, own_thr), "onset_weighted": (ow_val, ow_thr)})}
    res["chosen_design"] = {"hp": chosen_hp, "pos_weight": chosen_w, "seed": 0, "features": final_features,
                            "n_features": len(final_features), "train_rows": int(len(tr_n)),
                            "warn_budget_among_normal": WARN_BUDGET, "warn_threshold": warn_thr,
                            "primary_alert_threshold": primary_thr}

    # --- Q5: the single confirmatory test read, validation thresholds applied as-is
    log("single confirmatory test read")
    spec_te_all = m.predict(final_model, split.test, final_features)
    te_mask = (split.test["stressed_now"] == 0).to_numpy()
    val_thr = {b: float(v) for b, v in res["conditional"]["specialist"]["thresholds"].items()}
    val_thr = {float(k): v for k, v in val_thr.items()}
    res["test_read"] = {
        "note": "scored once, after all selection; thresholds fixed on validation",
        "conditional": {"specialist": conditional_metrics(te_n, spec_te_all[te_mask], val_thr),
                        "primary_restricted": conditional_metrics(
                            te_n, m.predict(primary, te_n), {float(k): v for k, v in
                                                            res["conditional"]["primary_restricted"]["thresholds"].items()}),
                        "onset_weighted_restricted": conditional_metrics(
                            te_n, m.predict(onsetw, te_n), {float(k): v for k, v in
                                                           res["conditional"]["onset_weighted_restricted"]["thresholds"].items()})},
        "combination": combination(split.test, m.predict(primary, split.test), spec_te_all, primary_thr, warn_thr,
                                   match_rate=res["combination"]["validation"]["primary_plus_warnings"]["alert_rate"],
                                   primary_val_scores=p_val,
                                   other_warners={"primary_own": (m.predict(primary, split.test), own_thr),
                                                  "onset_weighted": (m.predict(onsetw, split.test), ow_thr)})}
    return m._json_safe(res)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="artifacts/borough_hour.csv")
    ap.add_argument("--out", default="artifacts_onset/onset_specialist.json")
    ap.add_argument("--val-start", default="2025-07-01")
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--quick", action="store_true", help="one hp, one weight, one seed (tests)")
    a = ap.parse_args(argv)
    table = pd.read_csv(a.csv, parse_dates=["hour"])
    res = run(table, a.val_start, a.test_start, quick=a.quick)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    c = res["conditional"]
    print(f"\nvalidation, currently-normal hours (n={c['specialist']['n']}, onsets={c['specialist']['n_onsets']})")
    for k, v in c.items():
        print(f"  {k:28s} PR-AUC {v['pr_auc']:.3f}  P@5 {v['at_5pct']['precision']:.3f} R@5 {v['at_5pct']['recall']:.3f}"
              f"  P@10 {v['at_10pct']['precision']:.3f} R@10 {v['at_10pct']['recall']:.3f}")
    comb = res["combination"]["validation"]
    for k, v in comb.items():
        if not isinstance(v, dict):
            continue
        print(f"  {k:36s} rate {v['alert_rate']:.3f} P {v['precision']:.3f} R {v['recall']:.3f} "
              f"onsetR {v['onset_recall']:.3f} FA/day {v['false_alerts_per_day']:.2f}")
    print(f"  adopt_worthy: {comb['adopt_worthy']}\nwrote {out}")


if __name__ == "__main__":
    main()
