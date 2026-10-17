import pandas as pd
import pytest

from rescueflow import des
from rescueflow.data import clean
from rescueflow.sim import synthetic_incidents


@pytest.fixture(scope="module")
def calls():
    df = clean(synthetic_incidents(weeks=1, boroughs=("BROOKLYN", "QUEENS"), seed=3))
    return df[df["incident_datetime"] < df["incident_datetime"].min() + pd.Timedelta(days=2)]


@pytest.fixture(scope="module")
def tight(calls):
    sc = des.scenario_from_data(calls, units_per_call_h=0.9)
    return sc


def test_every_call_served_once(calls, tight):
    r = des.Sim(calls, tight, seed=0).run().results()
    assert len(r) == len(calls) and r["idx"].is_unique
    assert (r["wait_min"] >= 0).all() and (r["on_scene"] >= r["assign"]).all()


def test_same_seed_is_reproducible(calls, tight):
    a = des.summarize(des.Sim(calls, tight, seed=7).run().results())
    b = des.summarize(des.Sim(calls, tight, seed=7).run().results())
    assert a == b


def test_reserve_budget_respected(calls, tight):
    sim = des.Sim(calls, tight, "reactive", seed=0).run()
    assert sim.activations
    assert sim.reserve_unit_h <= tight.reserve_budget_unit_h
    assert sim.reserve_unit_h == len(sim.activations) * tight.reserve_units * tight.reserve_hours


def test_handover_shock_slows_dispatch(calls, tight):
    shocked = des.with_shock(tight, "BROOKLYN", 6, 30, 4.0)
    runs = des.experiment(calls, {"base": ("baseline", tight), "shock": ("baseline", shocked)}, range(5))
    assert des.compare(runs, "base", "shock", "p90_wait_min")["diff"] > 0


def test_no_unit_is_double_booked(calls, tight):
    sim = des.Sim(calls, tight, seed=1, log_events=True).run()
    busy = set()
    for e in sim.log:
        if e["event"] == "assign":
            assert e["unit"] not in busy
            busy.add(e["unit"])
        elif e["event"] == "free":
            busy.discard(e["unit"])


def test_common_random_numbers_across_arms(calls, tight):
    """Same call, same draws: in-borough travel is identical in both arms even after the shock."""
    shocked = des.with_shock(tight, "BROOKLYN", 6, 30, 4.0)
    a = des.Sim(calls, tight, seed=2).run().results().set_index("idx")
    b = des.Sim(calls, shocked, seed=2).run().results().set_index("idx")
    same = (~a["cross"]) & (~b["cross"].reindex(a.index))
    ta = (a["on_scene"] - a["assign"])[same]
    tb = (b["on_scene"] - b["assign"]).reindex(ta.index)
    assert same.sum() > 0.5 * len(a)
    assert (ta - tb).abs().max() < 1e-9
