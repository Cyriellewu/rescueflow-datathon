"""Score every method on the held-out test months, with the same alert budget for all."""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from rescuenyc.config import ALERT_RATE, BOOTSTRAP_REPS, SEED


def jitter(scores, seed=SEED):
    """Tiny random tie-break, so a yes/no rule can't put every tied hour into its alert budget."""
    return np.asarray(scores, float) + np.random.default_rng(seed).uniform(0, 1e-9, len(scores))


def alert_threshold(val_scores):
    return float(np.quantile(jitter(val_scores), 1 - ALERT_RATE))


def pr_auc_ci(df, y, s, reps=BOOTSTRAP_REPS):
    """95% interval by resampling whole days (hours within a day are not independent)."""
    rng = np.random.default_rng(SEED)
    day = df["hour"].dt.floor("D").to_numpy()
    days = np.unique(day)
    rows = {d: np.flatnonzero(day == d) for d in days}
    vals = []
    for _ in range(reps):
        idx = np.concatenate([rows[d] for d in rng.choice(days, len(days))])
        vals.append(average_precision_score(y[idx], s[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def score(df, scores, threshold):
    y = df["stressed"].astype(int).to_numpy()
    s = np.asarray(scores, float)
    alert = jitter(s, SEED + 1) >= threshold
    onset = (df["stressed_now"].to_numpy() == 0) & (y == 1)   # normal now, stressed next hour
    n_days = df["hour"].dt.floor("D").nunique()
    lo, hi = pr_auc_ci(df, y, s)
    return {
        "pr_auc": float(average_precision_score(y, s)), "pr_auc_lo": lo, "pr_auc_hi": hi,
        "alerts": int(alert.sum()),
        "alert_precision": float(y[alert].mean()) if alert.any() else float("nan"),
        "alert_recall": float(alert[y == 1].mean()),
        "onset_recall": float(alert[onset].mean()) if onset.any() else float("nan"),
        "false_alerts_per_day": float((alert & (y == 0)).sum() / n_days),
    }, alert


def evaluate(methods, val, test):
    rows, alerts, scores = [], {}, {}
    for name, f in methods.items():
        thr = alert_threshold(f(val))
        s = f(test)
        m, a = score(test, s, thr)
        rows.append({"method": name, **m})
        alerts[name], scores[name] = a, s
    return pd.DataFrame(rows), alerts, scores
