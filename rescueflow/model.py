"""Dispatch-stress model, baselines, evaluation and the severity-cascade test (docs/SPEC.md §5)."""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from rescueflow.features import BACKLOG, FEATURES, LOW_ACUITY

try:
    import xgboost as xgb
except ImportError:  # sklearn fallback if xgboost won't install on the target machine
    xgb = None
    from sklearn.ensemble import HistGradientBoostingClassifier

ALERT_RATE = 0.10  # share of validation borough-hours that get "alert"
WATCH_RATE = 0.15  # next share that gets "watch"
BOOTSTRAP = 200


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def split_by_dates(table, val_start, test_start) -> Split:
    lab = table[table["stress"].notna()]
    return Split(lab[lab["hour"] < val_start], lab[(lab["hour"] >= val_start) & (lab["hour"] < test_start)],
                 lab[lab["hour"] >= test_start])


def split_by_fraction(table, val=0.2, test=0.2) -> Split:
    hours = np.sort(table["hour"].unique())
    v, t = hours[int(len(hours) * (1 - val - test))], hours[int(len(hours) * (1 - test))]
    return split_by_dates(table, v, t)


def fit_xgb(train, features=FEATURES, seed=0):
    X, y = train[features], train["stress"].astype(int)
    if xgb is None:
        return HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300,
                                              random_state=seed).fit(X, y)
    return xgb.XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, eval_metric="logloss", random_state=seed).fit(X, y)


def predict(model, df, features=FEATURES):
    return model.predict_proba(df[features])[:, 1]


def baseline_scores(train, df) -> dict:
    keys = ["borough", "day_of_week", "hour_of_day"]
    rate = train.groupby(keys)["stress"].mean().rename("r")
    how = df[keys].merge(rate, left_on=keys, right_index=True, how="left")["r"]
    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(
        train[BACKLOG].fillna(0), train["stress"].astype(int))
    return {
        "hour_of_week_rate": how.fillna(train["stress"].mean()).to_numpy(),
        "persistence": df["stressed_now"].fillna(0).to_numpy(),
        "backlog_logistic": logit.predict_proba(df[BACKLOG].fillna(0))[:, 1],
    }


def band_thresholds(val_scores) -> dict:
    return {"alert": float(np.quantile(val_scores, 1 - ALERT_RATE)),
            "watch": float(np.quantile(val_scores, 1 - ALERT_RATE - WATCH_RATE))}


def bands(scores, thresholds) -> np.ndarray:
    s = np.asarray(scores)
    return np.select([s >= thresholds["alert"], s >= thresholds["watch"]], ["alert", "watch"], "normal")


def _pr_auc(y, s):
    return float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def _bootstrap_pr_auc(df, y, s, rng):
    """Resample whole days so the CI respects within-day correlation."""
    days = df["hour"].dt.floor("D").to_numpy()
    uniq = np.unique(days)
    pos = {d: np.flatnonzero(days == d) for d in uniq}
    vals = []
    for _ in range(BOOTSTRAP):
        idx = np.concatenate([pos[d] for d in rng.choice(uniq, len(uniq))])
        vals.append(_pr_auc(y[idx], s[idx]))
    return [float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))]


def lead_hours(df, alert, onset, max_h=6) -> list:
    """For each detected onset, consecutive alert hours for that borough ending at the onset row.

    1 = warned only at the cutoff right before the stressed hour; 2 = also an hour earlier, etc.
    Earlier hours without a label count as no alert.
    """
    flagged = set(zip(df["borough"][alert], df["hour"][alert]))
    out = []
    for b, h in zip(df["borough"][onset & alert], df["hour"][onset & alert]):
        k = 1
        while k < max_h and (b, h - pd.Timedelta(hours=k)) in flagged:
            k += 1
        out.append(k)
    return out


def evaluate(df, scores, thresholds, seed=0) -> dict:
    y = df["stress"].astype(int).to_numpy()
    s = np.asarray(scores, dtype=float)
    alert = s >= thresholds["alert"]
    onset = (df["stressed_now"].fillna(0).to_numpy() == 0) & (y == 1)
    days = max(df["hour"].dt.floor("D").nunique(), 1)
    leads = lead_hours(df, alert, onset)
    return {
        "false_alerts_per_day": float((alert & (y == 0)).sum() / days),
        "mean_lead_h": float(np.mean(leads)) if leads else float("nan"),
        "n": int(len(y)), "base_rate": float(y.mean()),
        "pr_auc": _pr_auc(y, s),
        "pr_auc_ci95": _bootstrap_pr_auc(df, y, s, np.random.default_rng(seed)),
        "brier": float(brier_score_loss(y, s.clip(0, 1))),
        "alert_precision": float(y[alert].mean()) if alert.any() else float("nan"),
        "alert_recall": float(alert[y == 1].mean()) if (y == 1).any() else float("nan"),
        "onset_recall": float(alert[onset].mean()) if onset.any() else float("nan"),
        "n_onsets": int(onset.sum()),
    }


def cascade_test(split: Split, seed=0) -> dict:
    """Does the low-acuity backlog add signal beyond everything else? Nested-model comparison."""
    without = [f for f in FEATURES if f not in LOW_ACUITY]
    full, reduced = fit_xgb(split.train, FEATURES, seed), fit_xgb(split.train, without, seed)
    y = split.test["stress"].astype(int).to_numpy()
    s_full, s_red = predict(full, split.test, FEATURES), predict(reduced, split.test, without)
    rng = np.random.default_rng(seed)
    days = split.test["hour"].dt.floor("D").to_numpy()
    uniq = np.unique(days)
    pos = {d: np.flatnonzero(days == d) for d in uniq}
    deltas = []
    for _ in range(BOOTSTRAP):
        idx = np.concatenate([pos[d] for d in rng.choice(uniq, len(uniq))])
        deltas.append(_pr_auc(y[idx], s_full[idx]) - _pr_auc(y[idx], s_red[idx]))
    return {"pr_auc_full": _pr_auc(y, s_full), "pr_auc_without_low_acuity": _pr_auc(y, s_red),
            "delta": _pr_auc(y, s_full) - _pr_auc(y, s_red),
            "delta_ci95": [float(np.nanpercentile(deltas, 2.5)), float(np.nanpercentile(deltas, 97.5))]}


def lead_time_profile(table, col="pending_low", lags=range(-6, 2)) -> pd.DataFrame:
    """Mean z-score of `col` in the hours around each stress onset (onset at lag 0).

    If the low-acuity backlog rises before high-acuity dispatch delay, the curve climbs at
    negative lags. Labels at lag 0 come from the hour [T, T+1); the feature at lag 0 is as of T.
    """
    t = table.sort_values(["borough", "hour"]).reset_index(drop=True)
    z = t.groupby("borough")[col].transform(lambda s: (s - s.mean()) / (s.std() or 1))
    onset = (t["stress"] == 1) & (t["stressed_now"] == 0)
    rows = []
    for lag in lags:
        shifted = z.groupby(t["borough"]).shift(-lag)
        rows.append({"lag_h": lag, "mean_z_at_onset": float(shifted[onset].mean()),
                     "mean_z_all": float(shifted.mean())})
    return pd.DataFrame(rows)


def top_factors(model, df, features=FEATURES, k=3) -> list:
    if xgb is None:
        return [[] for _ in range(len(df))]
    contrib = model.get_booster().predict(xgb.DMatrix(df[features]), pred_contribs=True)[:, :-1]
    out = []
    for row, vals in zip(contrib, df[features].to_numpy()):
        order = np.argsort(-np.abs(row))[:k]
        out.append([{"feature": features[j], "value": None if np.isnan(vals[j]) else float(vals[j]),
                     "direction": "up" if row[j] > 0 else "down"} for j in order])
    return out


def save(model, meta: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    if xgb is not None:
        model.save_model(out_dir / "model.json")  # JSON is endian-safe; don't ship pickles to s390x
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))


def load(out_dir: Path):
    meta = json.loads((out_dir / "meta.json").read_text())
    model = xgb.XGBClassifier()
    model.load_model(out_dir / "model.json")
    return model, meta
