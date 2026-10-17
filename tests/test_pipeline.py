import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from rescueflow import briefing, model as m, pipeline
from rescueflow.data import TIME_COLS, clean
from rescueflow.features import FEATURES, build_table, hour_grid
from rescueflow.sim import synthetic_incidents
from rescueflow.stream import backlog_snapshots


@pytest.fixture(scope="module")
def raw():
    return synthetic_incidents(weeks=10, boroughs=("BROOKLYN", "QUEENS"), seed=1)


@pytest.fixture(scope="module")
def table(raw):
    return build_table(clean(raw))[0]


def test_backlog_matches_brute_force(raw):
    df = clean(raw)
    hours = hour_grid(df)[::37]
    snaps, _ = backlog_snapshots(df, hours)
    for _, s in snaps.sample(40, random_state=0).iterrows():
        t = s["hour"]
        calls = df[df["borough"] == s["borough"]]
        pending = calls[(calls["incident_datetime"] < t) & (calls["queue_end"] >= t)]
        assert s["pending_high"] == pending["high"].sum()
        assert s["pending_low"] == (~pending["high"]).sum()
        assert s["held_pending_low"] == (pending["held"] & ~pending["high"]).sum()
        assert s["n_pending_gt_10min"] == ((t - pending["incident_datetime"]).dt.total_seconds() > 600).sum()


def test_features_at_t_ignore_everything_after_t(raw, table):
    """Rewrite all of the future after cutoff C; features for the row at C must not change."""
    cutoff = pd.Timestamp(table["hour"].iloc[len(table) // 3]).floor("h")
    censored = raw.copy()
    created = pd.to_datetime(censored["incident_datetime"])
    censored = censored[created < cutoff].copy()
    later = (cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000")
    for c in TIME_COLS[1:]:
        t = pd.to_datetime(censored[c])
        censored.loc[t >= cutoff, c] = later  # "not happened yet": any time after C
    # new, different calls after the cutoff
    extra = synthetic_incidents(weeks=1, boroughs=("BROOKLYN", "QUEENS"), seed=99,
                                start=str(cutoff.date() + pd.Timedelta(days=2)))
    other, _ = build_table(clean(pd.concat([censored, extra], ignore_index=True)))

    key = ["borough", "hour"]
    a = table[table["hour"] == cutoff].set_index(key)[FEATURES]
    b = other[other["hour"] == cutoff].set_index(key)[FEATURES]
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index(), check_dtype=False)


def test_model_beats_hour_of_week_on_synthetic(table):
    split = m.split_by_fraction(table)
    clf = m.fit_xgb(split.train)
    thr = m.band_thresholds(m.predict(clf, split.val))
    ours = m.evaluate(split.test, m.predict(clf, split.test), thr)["pr_auc"]
    how = m.evaluate(split.test, m.baseline_scores(split.train, split.test)["hour_of_week_rate"], thr)["pr_auc"]
    assert ours > how


def test_verifier_rejects_unsupported_numbers():
    b = {"borough": "BROOKLYN", "p_stress": 0.71, "band": "alert", "bottleneck": "dispatch pressure",
         "pending_high": 9, "pending_low": 31, "held_pending_low": 12, "oldest_pending_age_s": 1140,
         "top_factors": []}
    note = briefing.template(b)
    assert briefing.verify(note, b)[0]
    assert not briefing.verify(note + " About 45 ambulances are free.", b)[0]
    assert not briefing.verify("Queens: alert.", b)[0]


def test_api_scores_live(tmp_path, raw, monkeypatch):
    table = pipeline.build(raw, tmp_path)
    pipeline.train(table, tmp_path)
    from rescueflow import api
    monkeypatch.setattr(api, "ART", tmp_path)
    api._state.clear()
    client = TestClient(api.app)
    assert client.get("/health").json()["status"] == "ok"
    at = str(table.dropna(subset=["stress"])["hour"].iloc[-1])
    body = client.get("/risk", params={"at": at}).json()
    assert {b["borough"] for b in body["boroughs"]} == {"BROOKLYN", "QUEENS"}
    for b in body["boroughs"]:
        assert 0 <= b["p_stress"] <= 1 and b["briefing_verified"]
    assert len(client.get("/replay", params={"start": at, "end": at}).json()) == 1
