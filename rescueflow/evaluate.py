"""Metrics for comparing allocations on a Scenario.

All times are simulated (see hospitals.py); the queue-delay estimate is a crude
load/beds × service-time heuristic, not a queueing model or a clinical outcome.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .allocate import (
    Assignment,
    nearest_assignment,
    optimized_assignment,
    travel_table,
    weighted_objective,
)
from .scenarios import Scenario

HIGH_ACUITY_MAX_SEVERITY = 2  # severity 1–2 counts as high acuity


def metrics(scenario: Scenario, assignment: Assignment, overload_penalty: float = 30.0) -> dict[str, Any]:
    tt = travel_table(scenario)
    cases = scenario.cases
    n = len(cases)

    travel = [tt[(c.id, assignment[c.id])] for c in cases]
    high = [tt[(c.id, assignment[c.id])] for c in cases if c.severity <= HIGH_ACUITY_MAX_SEVERITY]

    load: dict[str, int] = {h.id: 0 for h in scenario.hospitals}
    for c in cases:
        load[assignment[c.id]] += 1

    per_hospital = []
    violations = 0
    overloaded = 0
    queue_delay_total = 0.0  # summed over cases, averaged below
    for h in scenario.hospitals:
        excess = max(0, load[h.id] - h.open_beds)
        # Synthetic heuristic: each excess patient waits roughly one service slot
        # spread across the hospital's open beds. Applied to every case sent there.
        delay = excess * h.avg_service_min / h.open_beds if h.open_beds > 0 else excess * h.avg_service_min
        violations += excess
        overloaded += int(excess > 0)
        queue_delay_total += delay * load[h.id]
        per_hospital.append({
            "hospital_id": h.id,
            "name": h.name,
            "open_beds": h.open_beds,
            "load": load[h.id],
            "excess": excess,
            "est_queue_delay_min": round(delay, 1),
        })

    return {
        "n_cases": n,
        "mean_travel_min": round(sum(travel) / n, 2) if n else 0.0,
        "max_travel_min": round(max(travel), 2) if n else 0.0,
        "high_acuity_mean_travel_min": round(sum(high) / len(high), 2) if high else None,
        "high_acuity_cases": len(high),
        "capacity_violations": violations,
        "hospitals_overloaded": overloaded,
        "est_queue_delay_min": round(queue_delay_total / n, 2) if n else 0.0,
        "weighted_objective": round(weighted_objective(scenario, assignment, overload_penalty), 1),
        "per_hospital": per_hospital,
    }


def compare(scenario: Scenario, overload_penalty: float = 30.0, time_limit_s: float = 10) -> dict[str, dict[str, Any]]:
    """Run both allocators and return {"nearest": metrics, "optimized": metrics}."""
    near = nearest_assignment(scenario)
    opt, info = optimized_assignment(scenario, overload_penalty=overload_penalty, time_limit_s=time_limit_s)
    out = {
        "nearest": metrics(scenario, near, overload_penalty),
        "optimized": metrics(scenario, opt, overload_penalty),
    }
    out["optimized"]["solver"] = asdict(info)
    return out


def summary_table(result: dict[str, dict[str, Any]]) -> str:
    """Plain-text side-by-side table of the scalar metrics from compare()."""
    keys = [
        "mean_travel_min", "max_travel_min", "high_acuity_mean_travel_min",
        "capacity_violations", "hospitals_overloaded", "est_queue_delay_min", "weighted_objective",
    ]
    lines = [f"{'metric':<30}{'nearest':>12}{'optimized':>12}"]
    for k in keys:
        a, b = result["nearest"][k], result["optimized"][k]
        lines.append(f"{k:<30}{str(a):>12}{str(b):>12}")
    s = result["optimized"].get("solver")
    if s:
        lines.append(f"{'solver':<30}{'':>12}{s['status'] + ' ' + str(s['wall_time_s']) + 's':>12}")
    return "\n".join(lines)
