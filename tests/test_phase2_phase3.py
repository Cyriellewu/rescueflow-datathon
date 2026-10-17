"""Tests for the synthetic hospital network, surge generator, allocators and metrics.

No data/ CSVs are needed: SEVERITY_DIST is hardcoded in rescueflow.scenarios.
"""
import pytest

from rescueflow.allocate import (
    nearest_assignment,
    optimized_assignment,
    travel_table,
    weighted_objective,
)
from rescueflow.evaluate import compare, metrics
from rescueflow.hospitals import DEFAULT_HOSPITALS, SIMULATED, travel_minutes
from rescueflow.scenarios import SEVERITY_DIST, ZIP_CENTROIDS, load_severity_dist, make_surge


@pytest.fixture(scope="module")
def scenario():
    return make_surge(15, "10029", seed=1)


# ---------- Phase 2: hospitals + scenarios ----------

def test_capacity_is_flagged_synthetic():
    assert SIMULATED is True
    assert len(DEFAULT_HOSPITALS) == 6
    assert all(2 <= h.open_beds <= 10 for h in DEFAULT_HOSPITALS)
    assert len({h.id for h in DEFAULT_HOSPITALS}) == 6


def test_travel_minutes_sane_range_and_symmetric():
    # Every top-10 zip centroid to every hospital: between the 2-min base and an
    # end-to-end Manhattan ride (~40 min). The trip to the *nearest* hospital is
    # what the model was calibrated for: a few minutes when a zip sits on top of
    # an ED, averaging 4–15 min across zips, near the real ~8 min median.
    all_pairs = [
        travel_minutes(lat, lon, h)
        for (lat, lon) in ZIP_CENTROIDS.values()
        for h in DEFAULT_HOSPITALS
    ]
    assert all(2.0 <= t <= 40.0 for t in all_pairs)
    nearest = [
        min(travel_minutes(lat, lon, h) for h in DEFAULT_HOSPITALS)
        for (lat, lon) in ZIP_CENTROIDS.values()
    ]
    assert all(2.0 <= t <= 15.0 for t in nearest)
    assert 4.0 <= sum(nearest) / len(nearest) <= 15.0

    # Zero distance → just the base cost.
    h = DEFAULT_HOSPITALS[0]
    assert travel_minutes(h.lat, h.lon, h) == pytest.approx(2.0)

    # Symmetric: travel from A's location to B equals travel from B's location to A.
    a, b = DEFAULT_HOSPITALS[0], DEFAULT_HOSPITALS[3]
    assert travel_minutes(a.lat, a.lon, b) == pytest.approx(travel_minutes(b.lat, b.lon, a), rel=1e-9)


def test_severity_dist_is_a_distribution():
    assert set(SEVERITY_DIST) == set(range(1, 9))
    assert sum(SEVERITY_DIST.values()) == pytest.approx(1.0, abs=0.01)
    # With no CSV present we get the hardcoded default back.
    assert load_severity_dist("data/does_not_exist.csv") == SEVERITY_DIST


def test_make_surge_shape(scenario):
    assert len(scenario.cases) == 15
    assert len({c.id for c in scenario.cases}) == 15
    lat0, lon0 = ZIP_CENTROIDS["10029"]
    for c in scenario.cases:
        assert 1 <= c.severity <= 8
        assert 0.0 <= c.arrival_min <= 30.0
        # Within ~2.5 km of the centroid (5 sigma of the 0.5 km jitter).
        assert abs(c.lat - lat0) < 2.5 / 111.0
        assert abs(c.lon - lon0) < 2.5 / 84.0
    arrivals = [c.arrival_min for c in scenario.cases]
    assert arrivals == sorted(arrivals)


def test_make_surge_deterministic_by_seed():
    a = make_surge(15, "10029", seed=1)
    b = make_surge(15, "10029", seed=1)
    c = make_surge(15, "10029", seed=2)
    assert a.cases == b.cases
    assert a.cases != c.cases


def test_make_surge_unknown_zip():
    with pytest.raises(KeyError):
        make_surge(5, "99999", seed=0)


# ---------- Phase 3: allocators + metrics ----------

def test_nearest_is_true_argmin(scenario):
    near = nearest_assignment(scenario)
    tt = travel_table(scenario)
    assert set(near) == {c.id for c in scenario.cases}
    for c in scenario.cases:
        best = min(scenario.hospitals, key=lambda h: tt[(c.id, h.id)])
        assert near[c.id] == best.id


def test_optimized_one_hospital_per_case_and_no_worse(scenario):
    near = nearest_assignment(scenario)
    opt, info = optimized_assignment(scenario, overload_penalty=30.0, time_limit_s=10)

    hospital_ids = {h.id for h in scenario.hospitals}
    assert set(opt) == {c.id for c in scenario.cases}
    assert all(h in hospital_ids for h in opt.values())
    assert info.status in ("OPTIMAL", "FEASIBLE")
    assert info.wall_time_s >= 0

    m_near = metrics(scenario, near)
    m_opt = metrics(scenario, opt)
    assert m_opt["capacity_violations"] <= m_near["capacity_violations"]
    assert weighted_objective(scenario, opt) <= weighted_objective(scenario, near) + 1e-6
    # Reported solver objective matches our independent evaluation (up to int rounding).
    assert info.objective == pytest.approx(weighted_objective(scenario, opt), abs=0.1 * len(scenario.cases))


def test_optimizer_relieves_nearest_overload(scenario):
    # 15 cases in East Harlem all crowd the nearest ED under the baseline; the
    # optimizer should spread them so fewer hospitals exceed their open beds.
    m_near = metrics(scenario, nearest_assignment(scenario))
    m_opt = metrics(scenario, optimized_assignment(scenario)[0])
    assert m_near["capacity_violations"] > 0
    assert m_opt["capacity_violations"] < m_near["capacity_violations"]


def test_metrics_keys_and_consistency(scenario):
    m = metrics(scenario, nearest_assignment(scenario))
    for k in ("mean_travel_min", "max_travel_min", "high_acuity_mean_travel_min",
              "capacity_violations", "hospitals_overloaded", "est_queue_delay_min", "per_hospital"):
        assert k in m
    assert m["mean_travel_min"] <= m["max_travel_min"]
    assert sum(r["load"] for r in m["per_hospital"]) == 15
    assert sum(r["excess"] for r in m["per_hospital"]) == m["capacity_violations"]
    assert sum(r["excess"] > 0 for r in m["per_hospital"]) == m["hospitals_overloaded"]
    assert m["est_queue_delay_min"] >= 0


def test_compare_returns_both(scenario):
    out = compare(scenario)
    assert set(out) == {"nearest", "optimized"}
    assert "solver" in out["optimized"]
    assert out["optimized"]["capacity_violations"] <= out["nearest"]["capacity_violations"]
