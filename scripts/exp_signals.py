"""Ablation: do hospital-side pressure (HOSPITAL) and calendar (CALENDAR) features add signal to the hourly features?

Same protocol as scripts/exp_subhour.py: develop and select on train + validation only (3 seeds, same HP);
`--test-read` scores the test window once for one chosen design.

HOSPITAL, all known at the cutoff T (events strictly before T):
  hosp_dwell_med_lag1   median minutes at hospital (arrival -> incident close) of units that LEFT in [T-1h, T)
  hosp_dwell_dev        that median minus the borough's trailing 8-week same-hour median, over its IQR
  hosp_arrivals_lag1    units that arrived at a hospital in [T-1h, T)
  hosp_stuck_45 / _60   units at a hospital at T that arrived more than 45 / 60 min before T
CALENDAR:
  is_holiday            US federal holiday (pandas USFederalHolidayCalendar) or Dec 31
  holiday_eve           the day before one
  month                 calendar month

    python scripts/exp_signals.py build --raw data/raw --out artifacts/signals
    python scripts/exp_signals.py validate --out artifacts/signals
    python scripts/exp_signals.py validate --out artifacts/signals --test-read "base+HOSPITAL"
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import model as m  # noqa: E402
from rescueflow.data import load_clean, raw_files  # noqa: E402
from rescueflow.features import FEATURES, MIN_IQR_S, _binned, _trailing, build_table, hour_grid  # noqa: E402

HP = {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.05, "onset_weight": 1.0}  # as scripts/exp_subhour.py
SEEDS = [0, 1, 2]
HOSPITAL = ["hosp_dwell_med_lag1", "hosp_dwell_dev", "hosp_arrivals_lag1", "hosp_stuck_45", "hosp_stuck_60"]
CALENDAR = ["is_holiday", "holiday_eve", "month"]


def covering(start, end, cutoffs):
    """How many intervals [start, end) are open at each cutoff T (start < T <= end); empty intervals dropped."""
    keep = ~(np.isnat(start) | np.isnat(end)) & (end > start)
    s, e = np.sort(start[keep]), np.sort(end[keep])
    return np.searchsorted(s, cutoffs, "left") - np.searchsorted(e, cutoffs, "left")


def hospital_features(df: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    hours = hour_grid(df)
    idx = pd.MultiIndex.from_product([sorted(map(str, df["borough"].unique())), hours], names=["borough", "hour"])
    h = df[df["hosp_arrival"].notna()].copy()
    h["dwell_min"] = (h["hosp_end"] - h["hosp_arrival"]).dt.total_seconds() / 60
    # binned by when the unit LEFT (known by then), shifted one hour below so only [T-1h, T) is used
    left = _binned(h, "hosp_end", "dwell_min", "median", hours, "_dwell_bin").reindex(idx)
    arr = _binned(h, "hosp_arrival", "dwell_min", "count", hours, "_arr_bin").reindex(idx).fillna(0)
    t = table.merge(pd.concat([left, arr], axis=1).reset_index(), on=["borough", "hour"], how="left")
    by_b = t.groupby("borough")
    t["hosp_dwell_med_lag1"] = by_b["_dwell_bin"].shift(1)
    t["hosp_arrivals_lag1"] = by_b["_arr_bin"].shift(1)
    med = _trailing(t, "_dwell_bin", lambda r: r.median())
    iqr = (_trailing(t, "_dwell_bin", lambda r: r.quantile(0.75)) - _trailing(t, "_dwell_bin", lambda r: r.quantile(0.25))).clip(lower=MIN_IQR_S / 60)
    t["hosp_dwell_dev"] = (t["hosp_dwell_med_lag1"] - med.groupby(t["borough"]).shift(1)) / iqr.groupby(t["borough"]).shift(1)
    # units still at a hospital at T that arrived long before T (arrival + k min < T <= leave)
    stuck = []
    for b, g in h.groupby(h["borough"].astype(str)):
        T = hours.values
        a, e = g["hosp_arrival"].values, g["hosp_end"].values
        stuck.append(pd.DataFrame({"borough": b, "hour": hours,
                                   "hosp_stuck_45": covering(a + np.timedelta64(45, "m"), e, T),
                                   "hosp_stuck_60": covering(a + np.timedelta64(60, "m"), e, T)}))
    t = t.merge(pd.concat(stuck), on=["borough", "hour"], how="left")
    return t.drop(columns=["_dwell_bin", "_arr_bin"])


def calendar_features(t: pd.DataFrame) -> pd.DataFrame:
    days = t["hour"].dt.normalize()
    hol = set(USFederalHolidayCalendar().holidays(days.min(), days.max() + pd.Timedelta(days=1)))
    hol |= {d for d in pd.date_range(days.min(), days.max()) if d.month == 12 and d.day == 31}
    t["is_holiday"] = days.isin(hol).astype(float)
    t["holiday_eve"] = (days + pd.Timedelta(days=1)).isin(hol).astype(float)
    t["month"] = t["hour"].dt.month
    return t


def build(args):
    args.out.mkdir(parents=True, exist_ok=True)
    df, _ = load_clean(raw_files(args.raw))
    print(f"clean rows: {len(df):,}", flush=True)
    table, _ = build_table(df, target=args.target)
    table = calendar_features(hospital_features(df, table))
    table.to_pickle(args.out / "table_signals.pkl")
    print("table", table.shape, flush=True)


def run(split, feats, seed):
    clf = m.fit_xgb(split.train, feats, seed, HP)
    s = m.predict(clf, split.val, feats)
    thr = m.band_thresholds(s)
    ev = m.evaluate_fast(split.val, s, thr, seed)
    gain = clf.get_booster().get_score(importance_type="gain")
    tot = sum(gain.values()) or 1.0
    ev["gain_share"] = {f: gain.get(f, 0.0) / tot for f in feats}
    return ev


def summarize(name, evs):
    row = {"design": name}
    for k in ["pr_auc", "alert_precision", "onset_recall"]:
        v = [e[k] for e in evs]
        row[k], row[k + "_seeds"] = float(np.mean(v)), [round(x, 4) for x in v]
    return row


def base_features(table):
    # columns that are entirely missing in this build (e.g. call-type mix without initial_call_type) are dropped
    return [f for f in FEATURES if table[f].notna().any()]


def evaluate(args):
    table = pd.read_pickle(args.out / "table_signals.pkl")
    split = m.split_by_dates(table, pd.Timestamp(args.val_start), pd.Timestamp(args.test_start))
    base = base_features(table)
    print(f"train {len(split.train):,}  val {len(split.val):,}  test {len(split.test):,} (test untouched); "
          f"base = {len(base)} features (dropped all-missing: {sorted(set(FEATURES) - set(base))})", flush=True)
    designs = {"base": base, "base+HOSPITAL": base + HOSPITAL, "base+CALENDAR": base + CALENDAR,
               "base+HOSPITAL+CALENDAR": base + HOSPITAL + CALENDAR}
    results, gains = {}, {}
    for name, feats in designs.items():
        evs = [run(split, feats, s) for s in SEEDS]
        results[name] = summarize(name, evs)
        gains[name] = {f: float(np.mean([e["gain_share"][f] for e in evs])) for f in feats}
        print(json.dumps(results[name]), flush=True)
    single = {}
    for f in HOSPITAL + CALENDAR:
        single[f] = summarize("base+" + f, [run(split, base + [f], s) for s in SEEDS])
        print(json.dumps(single[f]), flush=True)
    new = gains["base+HOSPITAL+CALENDAR"]
    print("gain share of new features:", {f: round(new[f], 4) for f in HOSPITAL + CALENDAR})
    out = {"hp": HP, "seeds": SEEDS, "base_features": base, "validation": results, "single_feature_adds": single,
           "gain_share_all": new}
    (args.out / "signals_validation.json").write_text(json.dumps(out, indent=2))


def test_read(args):
    """ONE confirmatory read of the test window: base and the chosen design, same seeds and thresholds rule."""
    table = pd.read_pickle(args.out / "table_signals.pkl")
    split = m.split_by_dates(table, pd.Timestamp(args.val_start), pd.Timestamp(args.test_start))
    base = base_features(table)
    extra = {"HOSPITAL": HOSPITAL, "CALENDAR": CALENDAR}
    chosen = base + [f for part in args.test_read.split("+")[1:] for f in (extra.get(part) or [part])]
    out = {}
    for name, feats in [("base", base), (args.test_read, chosen)]:
        rows = []
        for seed in SEEDS:
            clf = m.fit_xgb(split.train, feats, seed, HP)
            thr = m.band_thresholds(m.predict(clf, split.val, feats))
            ev = m.evaluate(split.test, m.predict(clf, split.test, feats), thr, seed)
            rows.append({k: ev[k] for k in ["pr_auc", "pr_auc_ci95", "alert_precision", "alert_recall", "onset_recall",
                                            "false_alerts_per_day"]})
            print(name, seed, json.dumps(rows[-1]), flush=True)
        out[name] = {"features": feats, "seeds": rows, "pr_auc_mean": float(np.mean([r["pr_auc"] for r in rows]))}
    out["note"] = "single confirmatory read of the test window"
    (args.out / "signals_test_read.json").write_text(json.dumps(out, indent=2))
    print({k: round(v["pr_auc_mean"], 4) for k, v in out.items() if isinstance(v, dict)})


def recency_weights(df, half_life_days):
    """exp decay by age relative to the newest row; None = equal weights."""
    if not half_life_days:
        return None
    age = (df["hour"].max() - df["hour"]).dt.total_seconds() / 86400
    return np.power(0.5, age / half_life_days).to_numpy()


def fit_weighted(train, feats, seed, half_life_days):
    import xgboost as xgb
    w = recency_weights(train, half_life_days)
    return xgb.XGBClassifier(n_estimators=HP["n_estimators"], max_depth=HP["max_depth"], learning_rate=HP["learning_rate"],
                             subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", random_state=seed, n_jobs=0
                             ).fit(train[feats], train["stress"].astype(int), sample_weight=w)


def recency(args):
    """Training-data use, not features. Step 1 (validation only): recency half-life. Step 2 (pre-declared, one test
    read): fit on train only (as the primary model) vs refit on train + validation, with the chosen half-life."""
    table = pd.read_pickle(args.out / "table_signals.pkl")
    split = m.split_by_dates(table, pd.Timestamp(args.val_start), pd.Timestamp(args.test_start))
    feats = base_features(table)
    from sklearn.metrics import average_precision_score as ap
    y_val = split.val["stress"].astype(int).to_numpy()
    val = {}
    for hl in [None, 90, 180, 365, 730]:
        v = [ap(y_val, fit_weighted(split.train, feats, s, hl).predict_proba(split.val[feats])[:, 1]) for s in SEEDS]
        val[str(hl)] = {"pr_auc": float(np.mean(v)), "seeds": [round(x, 4) for x in v]}
        print("validation half-life", hl, json.dumps(val[str(hl)]), flush=True)
    best = max(val, key=lambda k: val[k]["pr_auc"])
    # pre-declared rule: keep equal weights unless a half-life beats it by more than 0.002 on validation
    chosen = None if best == "None" or val[best]["pr_auc"] - val["None"]["pr_auc"] <= 0.002 else int(best)
    print("chosen half-life:", chosen, flush=True)
    out = {"validation_half_life": val, "chosen_half_life": chosen, "test": {}}
    if not args.test_read:
        (args.out / "recency_validation.json").write_text(json.dumps(out, indent=2))
        return
    y_te = split.test["stress"].astype(int).to_numpy()
    trval = pd.concat([split.train, split.val])
    for name, data, hl in [("train only, equal weights (as primary)", split.train, None),
                           ("train only, chosen half-life", split.train, chosen),
                           ("train + validation, equal weights", trval, None),
                           ("train + validation, chosen half-life", trval, chosen)]:
        v = [ap(y_te, fit_weighted(data, feats, s, hl).predict_proba(split.test[feats])[:, 1]) for s in SEEDS]
        out["test"][name] = {"pr_auc": float(np.mean(v)), "seeds": [round(x, 4) for x in v], "half_life": hl}
        print("TEST", name, json.dumps(out["test"][name]), flush=True)
    out["note"] = "single confirmatory read of the test window"
    (args.out / "recency_test_read.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "validate", "recency"])
    ap.add_argument("--raw", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, default=Path("artifacts/signals"))
    ap.add_argument("--target", default="dispatch_low")
    ap.add_argument("--val-start", default="2025-07-01")
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--test-read", default=None)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a)
    elif a.cmd == "recency":
        recency(a)
    elif a.test_read:
        test_read(a)
    else:
        evaluate(a)
