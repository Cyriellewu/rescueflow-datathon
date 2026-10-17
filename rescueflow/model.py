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


DEFAULT_HP = {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05, "onset_weight": 1.0}
# small grid, chosen on the validation window only (never on test); onset_weight up-weights hours
# that turn from normal to stressed, the event a supervisor most needs warned about
HP_GRID = [{"n_estimators": n, "max_depth": d, "learning_rate": lr, "onset_weight": w}
           for n, d, lr in [(300, 4, 0.05), (500, 4, 0.03), (300, 6, 0.05), (600, 3, 0.05)]
           for w in [1.0, 3.0]]


def _weights(train, onset_weight):
    if onset_weight == 1.0:
        return None
    onset = (train["stressed_now"] == 0) & (train["stress"] == 1)
    return np.where(onset, onset_weight, 1.0)


def fit_xgb(train, features=FEATURES, seed=0, hp=None):
    hp = {**DEFAULT_HP, **(hp or {})}
    X, y = train[features], train["stress"].astype(int)
    w = _weights(train, hp["onset_weight"])
    if xgb is None:
        return HistGradientBoostingClassifier(max_depth=hp["max_depth"], learning_rate=hp["learning_rate"],
                                              max_iter=hp["n_estimators"], random_state=seed).fit(X, y, sample_weight=w)
    return xgb.XGBClassifier(n_estimators=hp["n_estimators"], max_depth=hp["max_depth"], learning_rate=hp["learning_rate"],
                             subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", random_state=seed,
                             n_jobs=0).fit(X, y, sample_weight=w)


def select_hp(split: Split, features=FEATURES, seed=0, grid=HP_GRID) -> tuple[dict, list]:
    """Pick hyperparameters on the validation window: highest PR-AUC, ties broken by onset recall.
    Returns the chosen hp and the full trial table (saved to meta for the record)."""
    trials = []
    for hp in grid:
        clf = fit_xgb(split.train, features, seed, hp)
        s = predict(clf, split.val, features)
        thr = band_thresholds(s)
        ev = evaluate_fast(split.val, s, thr)
        trials.append({**hp, "val_pr_auc": ev["pr_auc"], "val_onset_recall": ev["onset_recall"],
                       "val_alert_precision": ev["alert_precision"]})
    best = max(trials, key=lambda t: (round(t["val_pr_auc"], 3), t["val_onset_recall"]))
    return {k: best[k] for k in DEFAULT_HP}, trials


def evaluate_fast(df, scores, thresholds, seed=0) -> dict:
    """evaluate() without the bootstrap, for model selection."""
    y = df["stress"].astype(int).to_numpy()
    s = np.asarray(scores, dtype=float)
    alert = tiebreak(s, seed + 1) >= thresholds["alert"]
    onset = (df["stressed_now"].to_numpy() == 0) & (y == 1)
    return {"pr_auc": _pr_auc(y, s), "alert_precision": float(y[alert].mean()) if alert.any() else float("nan"),
            "onset_recall": float(alert[onset].mean()) if onset.any() else float("nan")}


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


def tiebreak(scores, seed=0) -> np.ndarray:
    """Break ties randomly, so a model with few distinct scores (persistence, hour-of-week) can't
    put every tied hour into the alert band and exceed the shared alert budget."""
    s = np.asarray(scores, dtype=float)
    return s + np.random.default_rng(seed).uniform(0, 1e-9, len(s))


def band_thresholds(val_scores, seed=0) -> dict:
    s = tiebreak(val_scores, seed)
    return {"alert": float(np.quantile(s, 1 - ALERT_RATE)),
            "watch": float(np.quantile(s, 1 - ALERT_RATE - WATCH_RATE))}


def fit_calibrator(val_scores, y) -> dict:
    """Isotonic map from raw score to probability, fitted on validation; stored as JSON points."""
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(val_scores, y)
    return {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()}


def calibrate(scores, cal: dict | None) -> np.ndarray:
    s = np.asarray(scores, dtype=float)
    return np.interp(s, cal["x"], cal["y"]) if cal else s


def bands(scores, thresholds) -> np.ndarray:
    s = np.asarray(scores)
    return np.select([s >= thresholds["alert"], s >= thresholds["watch"]], ["alert", "watch"], "normal")


def _pr_auc(y, s):
    return float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def _day_blocks(df):
    days = df["hour"].dt.floor("D").to_numpy()
    uniq = np.unique(days)
    return uniq, {d: np.flatnonzero(days == d) for d in uniq}


def _bootstrap_pr_auc(df, y, s, rng):
    """Resample whole days so the CI respects within-day correlation. Runs on all cores (joblib)."""
    from joblib import Parallel, delayed
    uniq, pos = _day_blocks(df)
    draws = [rng.choice(uniq, len(uniq)) for _ in range(BOOTSTRAP)]
    def one(d):
        idx = np.concatenate([pos[k] for k in d])
        return _pr_auc(y[idx], s[idx])
    vals = Parallel(n_jobs=-1, prefer="threads")(delayed(one)(d) for d in draws)
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


def evaluate(df, scores, thresholds, seed=0, probs=None) -> dict:
    """scores rank hours (alerts, PR-AUC); probs, if given, are the calibrated probabilities (Brier).
    An onset is a stressed hour after an hour known to be normal; unknown current state is excluded."""
    y = df["stress"].astype(int).to_numpy()
    s = np.asarray(scores, dtype=float)
    alert = tiebreak(s, seed + 1) >= thresholds["alert"]
    now = df["stressed_now"].to_numpy()
    onset = (now == 0) & (y == 1)
    days = max(df["hour"].dt.floor("D").nunique(), 1)
    leads = lead_hours(df, alert, onset)
    return {
        "false_alerts_per_day": float((alert & (y == 0)).sum() / days),
        "mean_lead_h": float(np.mean(leads)) if leads else float("nan"),
        "n": int(len(y)), "base_rate": float(y.mean()),
        "pr_auc": _pr_auc(y, s),
        "pr_auc_ci95": _bootstrap_pr_auc(df, y, s, np.random.default_rng(seed)),
        "brier": float(brier_score_loss(y, (s if probs is None else np.asarray(probs)).clip(0, 1))),
        "alert_rate": float(alert.mean()),
        "alert_precision": float(y[alert].mean()) if alert.any() else float("nan"),
        "alert_recall": float(alert[y == 1].mean()) if (y == 1).any() else float("nan"),
        "onset_recall": float(alert[onset].mean()) if onset.any() else float("nan"),
        "n_onsets": int(onset.sum()),
    }


def cascade_test(split: Split, seed=0, hp=None) -> dict:
    """Does the low-acuity backlog add signal beyond everything else? Nested-model comparison."""
    without = [f for f in FEATURES if f not in LOW_ACUITY]
    full, reduced = fit_xgb(split.train, FEATURES, seed, hp), fit_xgb(split.train, without, seed, hp)
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


def _json_safe(x):
    """NaN/inf → None so the API can serve the file (JSON has no NaN)."""
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def save(model, meta: dict, out_dir: Path, onset_model=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    if xgb is not None:
        model.save_model(out_dir / "model.json")  # JSON is endian-safe; don't ship pickles to s390x
        if onset_model is not None:
            onset_model.save_model(out_dir / "model_onset.json")
    else:  # sklearn fallback (s390x without xgboost): joblib on the same machine only
        import joblib
        joblib.dump(model, out_dir / "model.joblib")
        if onset_model is not None:
            joblib.dump(onset_model, out_dir / "model_onset.joblib")
    (out_dir / "meta.json").write_text(json.dumps(_json_safe(meta), indent=2, default=str))


def _load_one(out_dir: Path, stem: str):
    if xgb is not None and (out_dir / f"{stem}.json").exists():
        model = xgb.XGBClassifier()
        model.load_model(out_dir / f"{stem}.json")
        return model
    if (out_dir / f"{stem}.joblib").exists():
        import joblib
        return joblib.load(out_dir / f"{stem}.joblib")
    return None


def load(out_dir: Path):
    meta = json.loads((out_dir / "meta.json").read_text())
    model = _load_one(out_dir, "model")
    return model, meta


def load_onset(out_dir: Path):
    """The onset-weighted companion model (transitions normal -> stressed weighted 3x), if saved."""
    return _load_one(out_dir, "model_onset")
