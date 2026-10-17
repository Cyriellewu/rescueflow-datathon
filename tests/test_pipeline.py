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


def test_active_responses_matches_brute_force(raw):
    df = clean(raw)
    hours = hour_grid(df)[::41]
    snaps, _ = backlog_snapshots(df, hours)
    for _, s in snaps.sample(40, random_state=1).iterrows():
        t = s["hour"]
        calls = df[df["borough"] == s["borough"]]
        active = calls[(calls["first_assignment_datetime"] < t) & (calls["busy_end"] >= t)]
        assert s["active_responses"] == len(active)


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
    plan = client.get("/plan", params={"at": at}).json()
    assert {r["borough"] for r in plan["boroughs"]} == {"BROOKLYN", "QUEENS"}
    assert sum(r["sends"] for r in plan["boroughs"]) == sum(r["receives"] for r in plan["boroughs"]) == plan["units_moved"]
    assert plan["value_after"] >= plan["value_before"] - 1e-6 and plan["actions"]
    assert set(tmp_path.glob("meta.json")) and set(pipeline.m.load(tmp_path)[1]["fleet_est"]) == {"BROOKLYN", "QUEENS"}


def test_chunked_load_matches_whole(tmp_path, raw):
    from rescueflow.data import audit, load_clean
    half = len(raw) // 2
    raw.iloc[:half].to_csv(tmp_path / "incidents_a.csv", index=False)
    raw.iloc[half:].to_csv(tmp_path / "incidents_b.csv", index=False)
    from rescueflow.data import raw_files
    df, checks = load_clean(raw_files([tmp_path]), chunksize=5000)
    whole = clean(raw)
    pd.testing.assert_frame_equal(df, whole, check_dtype=False)
    assert audit(checks, df)["rows_raw"] == len(raw)


def test_llm_note_rejected_falls_back_to_template(monkeypatch):
    b = {"borough": "BROOKLYN", "p_stress": 0.71, "band": "alert", "bottleneck": "dispatch pressure",
         "pending_high": 9, "pending_low": 31, "held_pending_low": 12, "oldest_pending_age_s": 1140,
         "top_factors": []}
    monkeypatch.setenv("RESCUENYC_LLM", "fake.gguf")
    monkeypatch.setattr(briefing, "llm_note", lambda b: ("Brooklyn alert at 71%; 45 units free.", 0.1))
    out = briefing.note_for(b, use_llm=True)
    assert out["briefing_source"] == "template" and out["llm_rejected"] == ["45"]
    monkeypatch.setattr(briefing, "llm_note", lambda b: ("Brooklyn: alert, 71% risk, dispatch pressure; 9 high-acuity and 31 low-acuity calls waiting.", 0.1))
    assert briefing.note_for(b, use_llm=True)["briefing_source"] == "llm"


def test_alert_budget_holds_for_tied_scores(table):
    split = m.split_by_fraction(table)
    base = m.baseline_scores(split.train, split.val)
    test = m.baseline_scores(split.train, split.test)
    for name in ["persistence", "hour_of_week_rate"]:
        r = m.evaluate(split.test, test[name], m.band_thresholds(base[name]))
        assert abs(r["alert_rate"] - m.ALERT_RATE) < 0.06, (name, r["alert_rate"])


def test_low_acuity_target_labels_the_low_queue(raw):
    df = clean(raw)
    low = build_table(df, target="dispatch_low")[0]
    high = build_table(df, target="dispatch")[0]
    assert (low["target"] == "dispatch_low").all()
    assert low["stress"].notna().sum() > 0
    # the label is built from severity 4-8 calls, so it must not be identical to the high-acuity one
    both = low["stress"].notna() & high["stress"].notna()
    assert (low.loc[both, "stress"] != high.loc[both, "stress"]).any()
    # same feature columns for every target, so model comparisons stay like for like
    assert set(FEATURES) <= set(low.columns)
