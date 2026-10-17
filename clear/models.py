"""The full model and the simple methods it has to beat. Each returns a score per row; higher = more
likely stressed next hour."""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from clear.config import SEED
from clear.table import DEMAND_ONLY, FEATURES, QUEUE


def boosted_trees(train, features):
    """Gradient-boosted decision trees (same idea as XGBoost; pure scikit-learn, so it also installs
    on s390x). Handles missing inputs natively."""
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                          random_state=SEED).fit(train[features], train["stressed"].astype(int))


def fit_all(train):
    keys = ["borough", "day_of_week", "hour_of_day"]
    hour_rate = train.groupby(keys)["stressed"].mean()
    base_rate = train["stressed"].mean()
    queue_logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(
        train[QUEUE].fillna(0), train["stressed"].astype(int))
    demand = boosted_trees(train, DEMAND_ONLY)
    full = boosted_trees(train, FEATURES)

    methods = {
        "Usual for this hour (history)": lambda d: d[keys].merge(
            hour_rate.rename("r"), left_on=keys, right_index=True, how="left")["r"].fillna(base_rate).to_numpy(),
        "Stressed now -> stressed next (rule)": lambda d: d["stressed_now"].fillna(0).to_numpy(),
        "Queue length only (logistic)": lambda d: queue_logit.predict_proba(d[QUEUE].fillna(0))[:, 1],
        "Call volume only (trees)": lambda d: demand.predict_proba(d[DEMAND_ONLY])[:, 1],
        "Full model (trees, 20 inputs)": lambda d: full.predict_proba(d[FEATURES])[:, 1],
    }
    return methods, full
