"""Per-unit timelines for the dashboard from an already finished policy lab, without rerunning it.

Rebuilds the four shock arms (seed 0) from artifacts/policy_lab.json and lab_week_calls.csv and writes
policy_lab_tracks.json (rescueflow/tracks.py schema). The warning model is not saved with the lab, so the
AI arm replays the activations recorded in policy_lab_series.json as a fixed schedule: same reserves at the
same hours, labelled "shock_ai (replayed activations)".

    python scripts/export_lab_tracks.py --art artifacts --out artifacts
"""
import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import des  # noqa: E402
from rescueflow.hospital import load_week, scenario_from_json  # noqa: E402
from rescueflow.tracks import unit_tracks  # noqa: E402


def arms_from_lab(lab: dict, series: dict) -> dict:
    """name -> (label, policy, scenario) for the four shock arms, as the lab ran them (AI arm replayed)."""
    sc = scenario_from_json(lab["scenario"])
    sh = lab["shock"]
    shocked = des.with_shock(sc, sh["borough"], sh["start_h"], sh["end_h"], sh["factor"])
    fixed = tuple(tuple(x) for x in lab["rb03"]["fixed_schedule"])
    ai_sched = tuple((int(a["at_min"] // 60), a["borough"]) for a in series["shock_ai"]["activations"])
    return {"shock_baseline": ("shock_baseline", "baseline", shocked),
            "shock_fixed": ("shock_fixed", "reserve_fixed", replace(shocked, fixed_schedule=fixed)),
            "shock_reactive": ("shock_reactive", "reactive", shocked),
            "shock_ai": ("shock_ai (replayed activations)", "reserve_fixed", replace(shocked, fixed_schedule=ai_sched))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", type=Path, default=Path("artifacts"), help="folder with policy_lab.json, policy_lab_series.json, lab_week_calls.csv")
    ap.add_argument("--out", type=Path, default=None, help="where to write policy_lab_tracks.json (default: --art)")
    ap.add_argument("--minutes", action="store_true", help="named, float-minute form with a per-call block instead of the compact form (larger file)")
    args = ap.parse_args()
    out = args.out or args.art
    lab = json.loads((args.art / "policy_lab.json").read_text())
    series = json.loads((args.art / "policy_lab_series.json").read_text())
    calls = load_week(args.art / "lab_week_calls.csv")
    tracks = {}
    for name, (label, policy, scen) in arms_from_lab(lab, series).items():
        t = time.perf_counter()
        sim = des.Sim(calls, scen, policy, seed=0, log_events=True).run()
        tracks[name] = {"arm": label, "policy": policy, "seed": 0,
                        **unit_tracks(sim, compact=not args.minutes, calls=args.minutes)}
        s = des.summarize(sim.results(), sim)
        print(f"{label:32s} {len(sim.home):4d} units  {sum(len(u['segments']) for u in tracks[name]['units'].values()):7d} segments"
              f"  activations {len(sim.activations)}  low p90 wait {s['low_p90_wait_min']:.1f} min  ({time.perf_counter() - t:.1f}s)")
        saved = series.get(name, {}).get("summary", {}).get("low_p90_wait_min")
        if saved is not None:
            print(f"{'':32s} series file seed 0: low p90 wait {saved:.1f} min")
    out.mkdir(parents=True, exist_ok=True)
    p = out / "policy_lab_tracks.json"
    p.write_text(json.dumps(tracks, separators=(",", ":")))
    print(f"wrote {p} ({p.stat().st_size / 1e6:.1f} MB)")
