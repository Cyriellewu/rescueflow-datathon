"""Surge scenario generator for RescueFlow AI.

A scenario is "a mass-casualty event in ZIP X producing N cases". Case locations
are scattered around an approximate ZIP centroid (synthetic). Case severities are
sampled from the *real* distribution of `final_severity_level_code` in the 2026
Manhattan FDNY sample (NYC Open Data 76xm-jjuj), hardcoded below so the package
works without the data/ CSVs; `load_severity_dist()` can recompute it from the
CSV when it is present.

Severity codes: 1 = most critical … 8 = least critical.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .hospitals import DEFAULT_HOSPITALS, Hospital

# Approximate centroids of the top-10 Manhattan incident ZIPs in the 2026 sample.
# Hand-placed from a map, accurate to a few hundred metres — good enough to seed a
# synthetic surge, not a geocoding source.
ZIP_CENTROIDS: dict[str, tuple[float, float]] = {
    "10029": (40.7917, -73.9439),  # East Harlem
    "10035": (40.8013, -73.9346),  # East Harlem (north)
    "10002": (40.7157, -73.9863),  # Lower East Side
    "10001": (40.7506, -73.9971),  # Chelsea / Penn Station
    "10027": (40.8116, -73.9535),  # Harlem / Morningside
    "10025": (40.7986, -73.9668),  # Upper West Side
    "10036": (40.7596, -73.9898),  # Midtown West / Times Square
    "10019": (40.7656, -73.9856),  # Midtown West / Columbus Circle
    "10003": (40.7318, -73.9887),  # East Village / Gramercy
    "10032": (40.8389, -73.9427),  # Washington Heights
}

# Real severity mix from the 2026 Manhattan sample (fractions of incidents).
# Source: final_severity_level_code in data/manhattan_sample.csv (~290k rows).
SEVERITY_DIST: dict[int, float] = {
    1: 0.014, 2: 0.211, 3: 0.157, 4: 0.127,
    5: 0.253, 6: 0.126, 7: 0.109, 8: 0.004,
}

# Rough degrees-per-km conversions at Manhattan's latitude (~40.8° N).
_KM_PER_DEG_LAT = 111.0
_KM_PER_DEG_LON = 111.0 * 0.757  # cos(40.8°)


@dataclass(frozen=True)
class Case:
    id: str
    lat: float
    lon: float
    severity: int      # 1 (most critical) … 8
    arrival_min: float  # minutes after the surge starts that the call comes in


@dataclass
class Scenario:
    cases: list[Case]
    hospitals: list[Hospital] = field(default_factory=lambda: list(DEFAULT_HOSPITALS))
    label: str = ""


def load_severity_dist(csv_path: str | Path = "data/manhattan_sample.csv") -> dict[int, float]:
    """Recompute SEVERITY_DIST from the FDNY sample if the CSV exists.

    Falls back to the hardcoded default when the file is missing, so tests and
    the demo never depend on the download.
    """
    path = Path(csv_path)
    if not path.exists():
        return dict(SEVERITY_DIST)
    counts: Counter[int] = Counter()
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = row.get("final_severity_level_code")
            if raw in (None, ""):
                continue
            try:
                counts[int(float(raw))] += 1
            except ValueError:
                continue
    total = sum(counts.values())
    if total == 0:
        return dict(SEVERITY_DIST)
    return {k: v / total for k, v in sorted(counts.items())}


def make_surge(
    n_cases: int,
    zipcode: str,
    seed: int = 0,
    jitter_km: float = 0.5,
    hospitals: list[Hospital] = DEFAULT_HOSPITALS,
    severity_dist: dict[int, float] | None = None,
) -> Scenario:
    """Build a deterministic surge of `n_cases` around `zipcode`.

    Locations: centroid + isotropic Gaussian jitter with std `jitter_km`.
    Severities: sampled from `severity_dist` (default: real 2026 Manhattan mix).
    Arrival minutes: uniform over the first 30 minutes, sorted so case ids are
    in arrival order. Same seed → identical scenario.
    """
    if zipcode not in ZIP_CENTROIDS:
        raise KeyError(f"unknown zip {zipcode!r}; known: {sorted(ZIP_CENTROIDS)}")
    dist = severity_dist or SEVERITY_DIST
    levels = sorted(dist)
    probs = np.array([dist[k] for k in levels], dtype=float)
    probs /= probs.sum()  # the published percentages round to 100.1%

    rng = np.random.default_rng(seed)
    lat0, lon0 = ZIP_CENTROIDS[zipcode]
    dlat = rng.normal(0.0, jitter_km, n_cases) / _KM_PER_DEG_LAT
    dlon = rng.normal(0.0, jitter_km, n_cases) / _KM_PER_DEG_LON
    sev = rng.choice(levels, size=n_cases, p=probs)
    arrival = np.sort(rng.uniform(0.0, 30.0, n_cases))

    cases = [
        Case(
            id=f"C{i + 1:03d}",
            lat=round(float(lat0 + dlat[i]), 6),
            lon=round(float(lon0 + dlon[i]), 6),
            severity=int(sev[i]),
            arrival_min=round(float(arrival[i]), 2),
        )
        for i in range(n_cases)
    ]
    return Scenario(cases=cases, hospitals=list(hospitals),
                    label=f"{n_cases}-case surge in {zipcode} (seed {seed})")
