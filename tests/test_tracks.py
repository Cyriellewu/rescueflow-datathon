import pandas as pd

from rescueflow import des
from rescueflow.data import clean
from rescueflow.sim import synthetic_incidents
from rescueflow.tracks import STATES, check_contiguous, expand, unit_tracks


def _calls():
    df = clean(synthetic_incidents(weeks=1, boroughs=("BROOKLYN", "QUEENS"), seed=3))
    return df[df["incident_datetime"] < df["incident_datetime"].min() + pd.Timedelta(hours=18)]


def test_unit_tracks_are_contiguous_and_every_assigned_call_has_a_unit():
    calls = _calls()
    sc = des.scenario_from_data(calls, units_per_call_h=0.9)
    sc = des.with_shock(sc, "BROOKLYN", 4, 12, 4.0)   # a shock so some units wait for a handover bay
    sim = des.Sim(calls, sc, "reactive", seed=0, log_events=True).run()
    assert sim.activations  # reserve units appear and go off shift in this run
    tr = unit_tracks(sim)
    check_contiguous(tr)
    assert len(tr["units"]) == len(sim.home)
    assert any(u["reserve"] for u in tr["units"].values())
    seen = {s[2] for u in tr["units"].values() for s in u["segments"]}
    assert seen <= set(STATES) and {"idle", "to_scene", "on_scene", "to_hospital", "handover", "off"} <= seen
    r = sim.results().set_index("idx")
    assert len(tr["calls"]) == len(calls)
    for idx, c in tr["calls"].items():
        assert c["assign"] is not None and c["unit"] is not None and c["on_scene"] >= c["assign"] >= c["t"]
        assert abs(c["assign"] - r.loc[idx, "assign"]) < 0.06 and abs(c["on_scene"] - r.loc[idx, "on_scene"]) < 0.06
        # the unit the call names works that call (an on-scene stay shorter than 0.05 min rounds away, so to_scene counts)
        segs = tr["units"][c["unit"]]["segments"]
        assert any(s[2] in ("to_scene", "on_scene") and s[4] == idx for s in segs)
    # every unit starts idle (initial fleet at minute 0, reserves at their activation) and ends at the last minute
    for uid, u in tr["units"].items():
        assert u["segments"][0][2] in ("idle", "to_scene") and u["segments"][-1][1] == tr["end_min"]  # idle may round away
        assert (u["segments"][0][0] > 0) == u["reserve"]
    # a reserve unit is never on a call after it went off shift
    for u in tr["units"].values():
        states = [s[2] for s in u["segments"]]
        if "off" in states:
            assert set(states[states.index("off"):]) == {"off"}
    # the compact form carries the same timeline
    ti = unit_tracks(sim, compact=True, calls=False)
    check_contiguous(ti)
    assert "calls" not in ti and ti["time_unit"] == "0.1 min"
    ex = expand(ti)
    for uid in tr["units"]:
        assert [s[:4] for s in ex["units"][uid]["segments"]] == [s[:4] for s in tr["units"][uid]["segments"]]


def test_event_log_does_not_change_results():
    calls = _calls()
    sc = des.scenario_from_data(calls, units_per_call_h=0.9)
    a = des.Sim(calls, sc, "reactive", seed=4).run()
    b = des.Sim(calls, sc, "reactive", seed=4, log_events=True).run()
    pd.testing.assert_frame_equal(a.results(), b.results())
    assert a.activations == b.activations
