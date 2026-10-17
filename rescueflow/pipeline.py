"""End-to-end steps shared by the scripts and the API: features → train/evaluate → payloads."""
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

from rescueflow import briefing, model as m
from rescueflow.data import audit, clean
from rescueflow.features import DEMAND, FEATURES, QUEUE_AWARE, CROSS_BOROUGH, EXTERNAL, build_table


def build(raw: pd.DataFrame, out_dir: Path, clean_df: pd.DataFrame | None = None, target="dispatch") -> pd.DataFrame:
    """raw: a raw frame, or load_clean()'s checks dict when clean_df is already cleaned."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = clean(raw) if clean_df is None else clean_df
    table, stream_stats = build_table(df, target)
    table.to_csv(out_dir / "borough_hour.csv", index=False)
    (out_dir / "data_audit.json").write_text(json.dumps(
        {**audit(raw, df), "replay": stream_stats}, indent=2, default=str))
    return table


def load_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["hour"])


def train(table: pd.DataFrame, out_dir: Path, val_start=None, test_start=None, data_source="FDNY") -> dict:
    split = (m.split_by_dates(table, pd.Timestamp(val_start), pd.Timestamp(test_start))
             if val_start else m.split_by_fraction(table))
    hp, hp_trials = m.select_hp(split)            # validation only; test is never touched here
    clf = m.fit_xgb(split.train, hp=hp)
    thresholds = m.band_thresholds(m.predict(clf, split.val))

    # H1 control: same learner, demand features only (what a demand forecast would know)
    demand = m.fit_xgb(split.train, DEMAND, hp=hp)      # same learner and hp as the full model
    queue = m.fit_xgb(split.train, QUEUE_AWARE, hp=hp)
    cross = m.fit_xgb(split.train, CROSS_BOROUGH, hp=hp)
    # onset-weighted variant: same features, transitions normal->stressed weighted 3x (validation: PR-AUC
    # falls ~0.03, onset recall roughly triples); reported so the trade-off is visible
    onset = m.fit_xgb(split.train, FEATURES, hp={**hp, "onset_weight": 3.0})
    no_ext = [f for f in FEATURES if f not in EXTERNAL]
    noext = m.fit_xgb(split.train, no_ext, hp=hp)     # ablation: full model without call-type mix and road speed
    ladder = {"demand_only": (demand, DEMAND), "queue_aware": (queue, QUEUE_AWARE), "cross_borough": (cross, CROSS_BOROUGH),
              "without_external": (noext, no_ext), "onset_weighted": (onset, FEATURES)}
    val_scores = {"xgboost": m.predict(clf, split.val),
                  **{k: m.predict(c, split.val, f) for k, (c, f) in ladder.items()},
                  **m.baseline_scores(split.train, split.val)}
    test_scores = {"xgboost": m.predict(clf, split.test),
                   **{k: m.predict(c, split.test, f) for k, (c, f) in ladder.items()},
                   **m.baseline_scores(split.train, split.test)}
    # every model alerts on its own top-10% validation hours, so alert budgets are comparable
    cal = m.fit_calibrator(val_scores["xgboost"], split.val["stress"].astype(int))
    results = {name: m.evaluate(split.test, s, m.band_thresholds(val_scores[name]),
                                probs=m.calibrate(s, cal) if name == "xgboost" else None)
               for name, s in test_scores.items()}
    meta = {
        "model_version": f"xgb-{pd.Timestamp.now():%Y%m%d-%H%M}",
        "trained_on": platform.machine(),
        "data_source": data_source,
        "target": str(table["target"].iloc[0]) if "target" in table else "dispatch",
        "features": FEATURES,
        "hyperparameters": hp, "hp_trials_validation": hp_trials,
        "thresholds": thresholds,
        "calibration": cal,
        "windows": {k: [str(getattr(split, k)["hour"].min()), str(getattr(split, k)["hour"].max())]
                    for k in ["train", "val", "test"]},
        "test_start": str(split.test["hour"].min()),
        "evaluation": results,
        "cascade": m.cascade_test(split, hp=hp),
        "lead_time_profile": m.lead_time_profile(table[table["hour"] >= split.test["hour"].min()]).to_dict("records"),
    }
    m.save(clf, meta, out_dir)
    return meta


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


def payloads(clf, meta: dict, rows: pd.DataFrame, use_llm=False) -> list[dict]:
    """One /risk payload per hour for the given borough-hour rows (live inference)."""
    raw = m.predict(clf, rows)
    band = m.bands(raw, meta["thresholds"])          # bands rank on the raw score
    p = m.calibrate(raw, meta.get("calibration"))    # shown probability is calibrated
    band = np.where(rows["threshold_s"].isna(), "insufficient_data", band)
    factors = m.top_factors(clf, rows)
    out = {}
    for i, (_, r) in enumerate(rows.iterrows()):
        b = {
            "borough": r["borough"], "p_stress": round(float(p[i]), 3), "band": str(band[i]),
            "bottleneck": r["bottleneck"],
            "dispatch_dev": _num(round(float(r["dispatch_dev"]), 2)) if pd.notna(r["dispatch_dev"]) else None,
            "travel_dev": _num(round(float(r["travel_dev"]), 2)) if pd.notna(r["travel_dev"]) else None,
            **{k: int(r[k]) for k in ["pending_high", "pending_low", "held_pending_low", "at_hospital"]},
            "oldest_pending_age_s": int(r["oldest_pending_age_s"]),
            "top_factors": factors[i],
            "realized_stress": None if pd.isna(r["stress"]) else int(r["stress"]),
        }
        b["action"] = briefing.action_for(b)
        b.update(briefing.note_for(b, use_llm))
        out.setdefault(str(r["hour"]), []).append(b)
    return [{"at": at, "computed_on": platform.machine(), "model_version": meta["model_version"],
             "boroughs": bs} for at, bs in out.items()]


def benchmark(df: pd.DataFrame, clf, table: pd.DataFrame, n_score=2000) -> dict:
    """Replay throughput and per-request scoring latency on this machine (df = cleaned rows)."""
    from rescueflow.stream import backlog_snapshots
    from rescueflow.features import hour_grid
    _, stream = backlog_snapshots(df, hour_grid(df))
    labeled = table.dropna(subset=["stress"])
    rows = labeled.sample(min(n_score, len(labeled)), random_state=0)
    lat = []
    for i in range(len(rows)):
        t0 = time.perf_counter()
        m.predict(clf, rows.iloc[[i]])
        lat.append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    m.predict(clf, rows)
    batch_s = time.perf_counter() - t0
    return {"machine": platform.machine(), "processor": platform.processor(),
            "replay_events": stream["events"], "replay_events_per_s": round(stream["events_per_s"]),
            "score_p50_ms": round(float(np.percentile(lat, 50)), 3),
            "score_p99_ms": round(float(np.percentile(lat, 99)), 3),
            "batch_rows_per_s": round(len(rows) / batch_s)}
