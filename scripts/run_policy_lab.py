"""Policy lab: two controlled experiments on the same call stream (docs/SPEC.md §10).

Experiment 1 (vulnerability): baseline vs baseline + hospital handover shock.
Experiment 2 (does warning help): under the shock, reactive vs AI-triggered reserves with the
same reserve budget, plus baseline. Same calls and seeds in every arm.

The warning model is trained on *other* weeks (with random shocks) and evaluated on the held-out
week. Fleet, handover and cross-borough travel are SCENARIO assumptions, saved with the results.

    python scripts/run_policy_lab.py --raw data/raw --eval-week 2026-02-09
    python scripts/run_policy_lab.py --synthetic        # SYNTHETIC calls
"""
import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import des  # noqa: E402
from rescueflow.model import _json_safe  # noqa: E402
from rescueflow.data import clean, load_clean, raw_files  # noqa: E402

METRICS = ["high_p90_wait_min", "high_mean_wait_min", "high_share_within_10min", "worst_borough_high_p90_wait_min",
           "low_p90_wait_min", "low_mean_wait_min", "low_share_within_30min", "worst_borough_low_p90_wait_min",
           "p90_wait_min"]


def week(df, start):
    s = pd.Timestamp(start)
    return df[(df["incident_datetime"] >= s) & (df["incident_datetime"] < s + pd.Timedelta(days=7))]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, nargs="+", help="incident CSV(s) or a directory of them")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--eval-week", help="Monday of the held-out week (default: last full week)")
    ap.add_argument("--train-weeks", type=int, default=4)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--shock-borough", default="BROOKLYN")
    ap.add_argument("--shock-day", type=int, default=2, help="day of the week the shock starts (0=Mon)")
    ap.add_argument("--shock-hours", default="14-22")
    ap.add_argument("--shock-factor", type=float, default=2.0)
    ap.add_argument("--demand-factor", type=float, default=1.0,
                    help="SCENARIO demand multiplier applied to training and evaluation weeks (1.5 = +50%%)")
    ap.add_argument("--watch", choices=["low", "high"], default="low",
                    help="queue the reactive trigger and the warning model watch: low-acuity (default; where queueing "
                         "lands under priority dispatch) or high-acuity")
    ap.add_argument("--reactive-queue", type=int, default=None,
                    help="reactive trigger: watched calls waiting (default 3 for high, 10 for low)")
    ap.add_argument("--calib", choices=["all_p90", "high_median"], default="all_p90",
                    help="fleet calibration target: all-call p90 dispatch wait (default) or high-acuity median")
    ap.add_argument("--out", type=Path, default=Path("artifacts"))
    args = ap.parse_args()

    if args.synthetic:
        from rescueflow.sim import synthetic_incidents
        raw = synthetic_incidents(weeks=6, boroughs=("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"), seed=5)
        args.out = args.out / "synthetic"
        df = clean(raw)
    else:
        df, _ = load_clean(raw_files(args.raw))
    first = df["incident_datetime"].min().normalize()
    first += pd.Timedelta(days=(7 - first.dayofweek) % 7)          # first Monday
    last = df["incident_datetime"].max().normalize()
    eval_start = pd.Timestamp(args.eval_week) if args.eval_week else last - pd.Timedelta(days=last.dayofweek + 7)
    train_starts = [eval_start - pd.Timedelta(weeks=k) for k in range(1, args.train_weeks + 1)
                    if eval_start - pd.Timedelta(weeks=k) >= first]

    if not train_starts:
        raise SystemExit(f"no full training week before {eval_start.date()}; pick a later --eval-week")
    if args.seeds < 20:
        print(f"note: {args.seeds} seeds; SPEC §10 asks for at least 20 for reported results")
    past = df[df["incident_datetime"] < eval_start]
    sc = des.scenario_from_data(past)  # call rates and travel medians from before the eval week only
    sc = replace(sc, watch=args.watch, reactive_queue=args.reactive_queue or (10 if args.watch == "low" else 3))
    # calibrate fleet size so the simulated dispatch wait matches the data (one training week, 1x demand)
    if args.calib == "all_p90":
        target = (past.groupby("borough")["dispatch_s"].quantile(0.9) / 60).to_dict()
        sc, calib = des.calibrate_units(week(df, train_starts[0]), sc, target, q=0.9)
    else:
        target = (past[past["high"]].groupby("borough")["dispatch_s"].median() / 60).to_dict()
        sc, calib = des.calibrate_units(week(df, train_starts[0]), sc, target, q=0.5)
    print(f"calibrated units ({args.calib})", sc.units, "target wait (min)", {k: round(v, 2) for k, v in target.items()})
    demand = lambda calls, k: des.scale_demand(calls, args.demand_factor, seed=1000 + k)  # noqa: E731
    h0, h1 = map(int, args.shock_hours.split("-"))
    day = args.shock_day * 24
    shocked = des.with_shock(sc, args.shock_borough, day + h0, day + h1, args.shock_factor)

    # warning model: training weeks only, each with a random handover shock somewhere
    rng = np.random.default_rng(123)
    boroughs = list(sc.units)
    train_windows, train_scen = [], []
    for s in train_starts:
        for _ in range(2):
            d, h = int(rng.integers(0, 7)), int(rng.integers(6, 18))
            train_windows.append(demand(week(df, s), len(train_windows)))
            train_scen.append(des.with_shock(sc, boroughs[int(rng.integers(len(boroughs)))],
                                             d * 24 + h, d * 24 + h + 8, float(rng.uniform(2, 4))))
    t = time.perf_counter()
    clf, wait_thr, rows = des.train_warning_model(train_windows, train_scen, seeds=range(100, 103))
    train_s = time.perf_counter() - t
    risk = des.risk_fn_for(clf)
    # alert threshold: top 5% of training hours
    p_train = clf.predict_proba(rows[des.SIM_FEATURES])[:, 1]
    alert_thr = float(np.quantile(p_train, 0.95))

    calls = demand(week(df, eval_start), 999)
    arms1 = {"baseline": ("baseline", sc), "handover_shock": ("baseline", shocked)}
    arms2 = {"shock_baseline": ("baseline", shocked), "shock_reactive": ("reactive", shocked),
             "shock_ai": ("ai", shocked)}
    seeds = range(args.seeds)
    t = time.perf_counter()
    exp1 = des.experiment(calls, arms1, seeds)
    exp2 = des.experiment(calls, arms2, seeds, risk, alert_thr)
    sim_s = time.perf_counter() - t

    result = {
        "data_source": "SYNTHETIC" if args.synthetic else "FDNY",
        "computed_on": platform.machine(),
        "eval_week": str(eval_start.date()), "train_weeks": [str(s.date()) for s in train_starts],
        "scenario": asdict(sc), "shock": shocked.shock, "seeds": args.seeds,
        "demand_factor": args.demand_factor, "eval_calls": int(len(calls)),
        "calibration_target": args.calib, "calibration": calib.to_dict("records"),
        "watch": args.watch, "reactive_queue": sc.reactive_queue,
        "warning_model": {"label": f"next-hour median {'low' if args.watch == 'low' else 'high'}-acuity wait > {wait_thr:.1f} min",
                          "alert_threshold": alert_thr, "train_rows": len(rows), "train_s": round(train_s, 2)},
        "experiment1": [des.compare(exp1, "baseline", "handover_shock", m) for m in METRICS],
        "experiment2": [des.compare(exp2, a, b, m) for a, b in
                        [("shock_reactive", "shock_ai"), ("shock_baseline", "shock_ai")] for m in METRICS],
        "reserve_use": exp2.groupby("arm")[["reserve_unit_h", "activations"]].mean().to_dict("index"),
        "sim_runs": len(exp1) + len(exp2), "sim_seconds": round(sim_s, 2),
    }
    # one run per arm (seed 0) sampled every 10 minutes for the dashboard
    series = {}
    for name, (policy, scen) in {**arms1, **arms2}.items():
        sim = des.Sim(calls, scen, policy, risk, alert_thr, seed=0, snapshot_min=10).run()
        snaps = pd.DataFrame(sim.snaps)
        series[name] = {
            "t0": str(sim.t0), "step_min": 10, "t": sorted(snaps["t"].unique().tolist()),
            "boroughs": {b: {c: g[c].astype(int).tolist() for c in
                             ["q_high", "q_low", "idle", "busy", "at_hospital", "hosp_queue", "reserve_active"]}
                         for b, g in snaps.groupby("borough")},
            "activations": sim.activations, "summary": des.summarize(sim.results(), sim)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_lab.json").write_text(json.dumps(_json_safe(result), indent=2, default=float))
    (args.out / "policy_lab_series.json").write_text(json.dumps(_json_safe(series), default=float))
    for block in ["experiment1", "experiment2"]:
        print(block)
        for c in result[block]:
            print(f"  {c['b']:15s} vs {c['a']:15s} {c['metric']:32s} {c['mean_a']:7.2f} → {c['mean_b']:7.2f}"
                  f"  diff {c['diff']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}]")
    print("reserve use", result["reserve_use"])
    print(f"{result['sim_runs']} runs in {sim_s:.1f}s on {platform.machine()}")
