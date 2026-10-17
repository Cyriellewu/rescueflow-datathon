import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from rescueflow.overview import historical_profiles
from rescueflow.stream import replay_borough


def test_aggregated_queue_matches_event_replay_across_year_boundary():
    """Check event bins against the existing exact event replay, including boundary timestamps."""
    created = pd.to_datetime(["2023-12-31 22:10", "2023-12-31 23:00", "2024-01-01 00:00", "2024-01-01 02:15"])
    ended = pd.to_datetime(["2024-01-01 01:00", "2023-12-31 23:00", "2024-01-01 03:01", "2024-01-01 02:30"])
    calls = pd.DataFrame({"incident_datetime": created, "queue_end": ended, "high": False, "held": False,
                          "hosp_arrival": pd.NaT, "hosp_end": pd.NaT,
                          "first_assignment_datetime": pd.NaT, "busy_end": pd.NaT})
    hours = pd.date_range("2023-12-31", "2024-01-02", freq="h", inclusive="left")
    exact, _ = replay_borough(calls, hours)

    def bins(times, arrivals=False):
        rows = []
        for timestamp, n in pd.Series(times).dt.floor("h").value_counts().items():
            r = {"borough": "QUEENS", "day": str(timestamp.normalize()), "hod": str(timestamp.hour), "n_low": str(n)}
            if arrivals:
                r["n_calls"] = str(n)
            rows.append(r)
        return rows

    result = historical_profiles(bins(created, True), bins(ended), hours[0], "2024-01-02")
    for year in (2023, 2024):
        want = exact[exact.hour.dt.year == year].set_index("hour").pending_low
        assert result["pending_low_by_hour"]["QUEENS"][str(year)] == want.tolist()
    # Entire days contribute to the denominator, including hours with zero calls.
    assert sum(result["calls_by_hour"]["QUEENS"]["2023"]) == 2
    assert result["pending_low_by_hour"]["QUEENS"]["2024"][1] == 2


def test_inconsistent_event_counts_are_rejected():
    with pytest.raises(ValueError, match="negative reconstructed queue"):
        historical_profiles(
            [{"borough": "QUEENS", "day": "2025-01-01", "hod": "1", "n_calls": "1", "n_low": "0"}],
            [{"borough": "QUEENS", "day": "2025-01-01", "hod": "1", "n_low": "1"}],
            "2025-01-01", "2025-01-02")


@pytest.fixture
def local_api(monkeypatch, tmp_path):
    from rescueflow import api
    table = pd.DataFrame([
        {"hour": pd.Timestamp("2025-01-01"), "borough": b, "n_calls": 2,
         "pending_low": 1, "held_pending_low": 0, "stress": 1 if b == "QUEENS" else 0}
        for b in ("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS")
    ]).set_index("hour")
    monkeypatch.setattr(api, "_state", {"table": table, "meta": {"test_start": "2025-01-01", "data_source": "SYNTHETIC"}})
    path = tmp_path / "overview.json"
    monkeypatch.setattr(api, "OVERVIEW", path)
    return TestClient(api.app), path


def test_overview_without_export_reports_only_actual_local_year(local_api):
    client, _ = local_api
    o = client.get("/overview").json()
    assert set(o["calls_by_hour"]["QUEENS"]) == {"2025"}
    assert o["metric_provenance"]["calls_by_hour"]["data_source"] == "SYNTHETIC"


def test_historical_export_does_not_change_replay_or_stress_source(local_api):
    client, path = local_api
    years = {str(y): [float(y)] * 24 for y in range(2023, 2027)}
    provenance = {"data_source": "FDNY", "start": "2023-01-01", "end_exclusive": "2026-10-01"}
    path.write_text(json.dumps({
        "calls_by_hour": {"QUEENS": years}, "pending_low_by_hour": {"QUEENS": years},
        "metric_provenance": {key: provenance for key in ("calls_by_hour", "pending_low_by_hour")}}))
    o = client.get("/overview").json()
    assert set(o["pending_low_by_hour"]["QUEENS"]) == {"2023", "2024", "2025", "2026"}
    assert o["metric_provenance"]["calls_by_hour"]["data_source"] == "FDNY"
    assert o["replay_data_source"] == "SYNTHETIC"
    assert o["stressed_hours"] == 1


def test_export_without_provenance_cannot_silently_replace_local_data(local_api):
    client, path = local_api
    path.write_text(json.dumps({"calls_by_hour": {"QUEENS": {"2026": [99] * 24}}}))
    o = client.get("/overview").json()
    assert set(o["calls_by_hour"]["QUEENS"]) == {"2025"}
