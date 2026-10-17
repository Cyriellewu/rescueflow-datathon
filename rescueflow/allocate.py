"""Case → hospital allocators for RescueFlow AI.

Two policies on the same Scenario:

* `nearest_assignment`  — baseline: every case goes to the hospital with the
  shortest simulated travel time, ignoring capacity (what a naive dispatcher does).
* `optimized_assignment` — OR-Tools CP-SAT: minimizes severity-weighted travel
  time plus a penalty for every case above a hospital's open beds.

Both operate on synthetic travel times and synthetic capacity (see hospitals.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .hospitals import travel_minutes
from .scenarios import Scenario

# Weight on travel minutes by severity: critical patients (1–2) count several
# times more than minor ones, so the optimizer keeps them close.
SEVERITY_WEIGHT: dict[int, float] = {1: 4.0, 2: 3.0, 3: 2.0, 4: 1.5, 5: 1.0, 6: 1.0, 7: 1.0, 8: 1.0}

# CP-SAT needs integer coefficients; minutes are scaled by this factor.
SCALE = 10

Assignment = dict[str, str]  # case_id -> hospital_id


@dataclass
class SolveInfo:
    status: str          # OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN
    wall_time_s: float
    objective: float     # severity-weighted minutes + penalty, in real (unscaled) units
    overload_penalty: float


def travel_table(scenario: Scenario) -> dict[tuple[str, str], float]:
    """Simulated travel minutes for every (case_id, hospital_id) pair."""
    return {
        (c.id, h.id): travel_minutes(c.lat, c.lon, h)
        for c in scenario.cases
        for h in scenario.hospitals
    }


def severity_weight(severity: int) -> float:
    return SEVERITY_WEIGHT.get(severity, 1.0)


def nearest_assignment(scenario: Scenario) -> Assignment:
    """Send each case to its lowest-travel-time hospital, ignoring capacity."""
    out: Assignment = {}
    for c in scenario.cases:
        best = min(scenario.hospitals, key=lambda h: travel_minutes(c.lat, c.lon, h))
        out[c.id] = best.id
    return out


def weighted_objective(scenario: Scenario, assignment: Assignment, overload_penalty: float = 30.0) -> float:
    """Σ travel_min × severity_weight + overload_penalty × Σ_h max(0, load_h − open_beds_h).

    Same objective the optimizer minimizes, evaluated for any assignment so the
    two policies can be compared on equal terms.
    """
    tt = travel_table(scenario)
    total = 0.0
    load: dict[str, int] = {h.id: 0 for h in scenario.hospitals}
    for c in scenario.cases:
        h = assignment[c.id]
        total += tt[(c.id, h)] * severity_weight(c.severity)
        load[h] += 1
    for h in scenario.hospitals:
        total += overload_penalty * max(0, load[h.id] - h.open_beds)
    return total


def optimized_assignment(
    scenario: Scenario,
    overload_penalty: float = 30.0,
    time_limit_s: float = 10,
) -> tuple[Assignment, SolveInfo]:
    """Capacity-aware allocation with CP-SAT.

    Variables:  x[c,h] ∈ {0,1}        case c goes to hospital h
                over[h] ≥ 0 (int)     cases at h beyond its open beds (soft capacity)
    Constraints: Σ_h x[c,h] = 1 for every case;  over[h] ≥ Σ_c x[c,h] − open_beds_h
    Objective:   min Σ_{c,h} travel_min(c,h)·w(sev_c)·x[c,h] + overload_penalty·Σ_h over[h]
    `overload_penalty` is in "severity-weighted minutes per excess patient"; 30 means
    one extra patient at a full ED costs as much as 30 minutes of extra travel for a
    routine case.
    """
    cases, hospitals = scenario.cases, scenario.hospitals
    tt = travel_table(scenario)

    m = cp_model.CpModel()
    x = {(c.id, h.id): m.NewBoolVar(f"x_{c.id}_{h.id}") for c in cases for h in hospitals}
    over = {h.id: m.NewIntVar(0, len(cases), f"over_{h.id}") for h in hospitals}

    for c in cases:
        m.AddExactlyOne(x[(c.id, h.id)] for h in hospitals)
    for h in hospitals:
        load = sum(x[(c.id, h.id)] for c in cases)
        m.Add(over[h.id] >= load - h.open_beds)

    travel_cost = sum(
        int(round(tt[(c.id, h.id)] * severity_weight(c.severity) * SCALE)) * x[(c.id, h.id)]
        for c in cases for h in hospitals
    )
    penalty_cost = sum(int(round(overload_penalty * SCALE)) * over[h.id] for h in hospitals)
    m.Minimize(travel_cost + penalty_cost)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_workers = 8
    t0 = time.perf_counter()
    status = solver.Solve(m)
    wall = time.perf_counter() - t0

    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Every case can always go somewhere, so this only happens on a 0-second limit.
        raise RuntimeError(f"CP-SAT returned {status_name}; no assignment available")

    assignment: Assignment = {
        c.id: next(h.id for h in hospitals if solver.Value(x[(c.id, h.id)]))
        for c in cases
    }
    info = SolveInfo(
        status=status_name,
        wall_time_s=round(wall, 4),
        objective=solver.ObjectiveValue() / SCALE,
        overload_penalty=overload_penalty,
    )
    return assignment, info
