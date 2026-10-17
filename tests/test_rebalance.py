from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from rescueflow import des, rebalance as rb
from rescueflow.data import clean
from rescueflow.sim import _borough

A, B, C = "BRONX", "MANHATTAN", "RICHMOND / STATEN ISLAND"


def state(name, fleet=40, idle=6, qh=0, ql=0, arrivals=35.0, risk=0.0, inbound=0):
    return rb.BoroughState(name, fleet, idle, qh, ql, arrivals, risk, inbound)


def test_free_units_flow_to_the_borough_that_is_short():
    short, slack = state(A, fleet=30, idle=0, ql=12, arrivals=40), state(B, fleet=60, idle=10, arrivals=25)
    p = rb.plan([short, slack])
    assert [(m["from"], m["to"]) for m in p["moves"]] == [(B, A)]
    assert p["value_gain"] > 0
    by = {r["borough"]: r for r in p["boroughs"]}
    assert by[A]["unmet_after"] < by[A]["unmet_before"]
    assert by[B]["unmet_after"] <= by[B]["unmet_before"] + 1e-6  # the donor was not pushed into shortage


def test_every_borough_can_donate_and_receive():
    """Swap which borough is short: the plan reverses direction. Nothing is wired to a fixed donor."""
    p1 = rb.plan([state(A, fleet=30, idle=0, ql=12, arrivals=40), state(B, fleet=60, idle=10, arrivals=25)])
    p2 = rb.plan([state(A, fleet=60, idle=10, arrivals=25), state(B, fleet=30, idle=0, ql=12, arrivals=40)])
    assert [(m["from"], m["to"]) for m in p1["moves"]] == [(B, A)]
    assert [(m["from"], m["to"]) for m in p2["moves"]] == [(A, B)]


def test_several_donors_one_receiver_and_conservation():
    states = [state(A, fleet=25, idle=0, ql=20, arrivals=45), state(B, fleet=60, idle=9, arrivals=25),
              state(C, fleet=30, idle=7, arrivals=5)]
    p = rb.plan(states)
    sent = {r["borough"]: r["sends"] for r in p["boroughs"]}
    got = {r["borough"]: r["receives"] for r in p["boroughs"]}
    assert sum(sent.values()) == sum(got.values()) == p["units_moved"] > 0
    assert sent[A] == 0 and got[B] == got[C] == 0
    for s in states:  # never sends more free units than it has, and keeps min_keep
        assert sent[s.borough] <= max(s.idle - rb.PlanConfig().min_keep, 0)


def test_balanced_city_makes_no_moves():
    assert rb.plan([state(A), state(B), state(C)])["moves"] == []


def test_units_too_far_away_are_not_offered():
    far = {a: {b: 0.0 if a == b else 90.0 for b in (A, B)} for a in (A, B)}
    p = rb.plan([state(A, fleet=30, idle=0, ql=12, arrivals=40), state(B, fleet=60, idle=10, arrivals=25)], far)
    assert p["moves"] == []


def test_donor_keeps_headroom_for_its_own_forecast():
    """Same slack, but the donor's warning risk is high: it expects a surge and sends fewer units."""
    short = state(A, fleet=30, idle=0, ql=12, arrivals=40)
    calm = rb.plan([short, state(B, fleet=40, idle=10, arrivals=25, risk=0.0)])
    risky = rb.plan([short, state(B, fleet=40, idle=10, arrivals=25, risk=1.0)])
    assert calm["units_moved"] > 0 and risky["units_moved"] < calm["units_moved"]


def test_units_already_on_their_way_are_counted():
    short = state(A, fleet=33, idle=0, ql=5, arrivals=30)
    donor = state(B, fleet=60, idle=10, arrivals=25)
    first = rb.plan([short, donor])["units_moved"]
    again = rb.plan([replace(short, inbound=first), donor])["units_moved"]
    assert 0 < first < 9 and again < first


def test_spatial_matrix_is_symmetric_enough_and_sane():
    t = rb.transfer_minutes()
    assert set(t) == set(rb.BOROUGHS)
    assert all(t[a][a] == 0 for a in t)
    assert t["BRONX"]["MANHATTAN"] < t["BRONX"]["RICHMOND / STATEN ISLAND"]  # neighbours are closer than Staten Island


# ---- simulator ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def uneven():
    """Two boroughs, one three times busier, equal fleets: the quiet one has units to spare."""
    rng = np.random.default_rng(2)
    raw = pd.concat([_borough(rng, "BRONX", "2025-01-06", 72, 24, 40, 0.0),
                     _borough(rng, "MANHATTAN", "2025-01-06", 72, 8, 40, 0.0)], ignore_index=True)
    calls = clean(raw)
    sc = des.scenario_from_data(calls, units_per_call_h=1.0)
    return calls, replace(sc, units={"BRONX": 18, "MANHATTAN": 18}, handover_slots={"BRONX": 6, "MANHATTAN": 6})


def test_rebalance_policy_moves_units_and_serves_every_call_once(uneven):
    calls, sc = uneven
    sim = des.Sim(calls, sc, "rebalance", seed=0, log_events=True).run()
    r = sim.results()
    assert len(r) == len(calls) and r["idx"].is_unique
    assert sim.moves and all(src != dst for _, src, dst, _ in sim.moves)
    assert len(sim.home) == sum(sc.units.values())  # relocation never creates or destroys a unit
    in_transit, busy = set(), set()
    for e in sim.log:  # a unit on the road between boroughs is never assigned, and nobody is double-booked
        if e["event"] == "relocate":
            assert e["unit"] not in busy
            in_transit.add(e["unit"])
        elif e["event"] == "arrive_relocated":
            in_transit.discard(e["unit"])
        elif e["event"] == "assign":
            assert e["unit"] not in in_transit and e["unit"] not in busy
            busy.add(e["unit"])
        elif e["event"] == "free":
            busy.discard(e["unit"])


def test_rebalance_does_not_hurt_where_there_is_nothing_to_balance(uneven):
    calls, sc = uneven
    even = replace(sc, units={"BRONX": 40, "MANHATTAN": 40}, handover_slots={"BRONX": 12, "MANHATTAN": 12})
    runs = des.experiment(calls, {"none": ("baseline", even), "rebalance": ("rebalance", even)}, range(3))
    d = des.compare(runs, "none", "rebalance", "p90_wait_min")
    assert d["diff"] < 1.0  # minutes; ample fleets, so no queue to improve and no harm done


def test_rebalance_ai_uses_the_risk_function(uneven):
    calls, sc = uneven
    seen = []
    sim = des.Sim(calls, sc, "rebalance_ai", risk_fn=lambda f: seen.append(f) or 0.5, seed=0).run()
    assert seen and "pending_low" in seen[0]
    assert len(sim.results()) == len(calls)
