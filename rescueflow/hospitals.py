"""Synthetic Manhattan hospital network for RescueFlow AI.

EVERYTHING IN THIS MODULE IS SIMULATED. The hospitals are fictional: their names
are placeholders, their coordinates are only *roughly* where real Manhattan
emergency departments cluster, and their bed counts / service times are invented
so that capacity actually binds during a demo surge. None of these numbers come
from a real hospital, a real bed census, or any clinical source. Research/demo
only — not for clinical dispatch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Flag read by the rest of the package / dashboard to label capacity as synthetic.
SIMULATED = True

# Travel-time model (also synthetic). Manhattan surface traffic is slow, so we use
# ~25 km/h (2.4 min per km) plus a 2-minute fixed cost for turnout / hand-off.
# Calibrated so typical in-borough trips land around 4–15 minutes, which roughly
# matches the real FDNY median travel time of ~8 min in the 2026 Manhattan sample.
MIN_PER_KM = 2.4
BASE_MIN = 2.0
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class Hospital:
    id: str
    name: str
    lat: float
    lon: float
    ed_beds: int          # total ED treatment spaces (synthetic)
    open_beds: int        # currently free spaces at the start of the surge (synthetic)
    avg_service_min: float  # average ED occupancy time per patient, minutes (synthetic)


# Six fictional hospitals placed near where real Manhattan EDs cluster.
# open_beds is deliberately small and uneven (2–10) so the nearest-hospital policy
# overloads the closest ED and the capacity-aware allocator has something to fix.
DEFAULT_HOSPITALS: list[Hospital] = [
    Hospital("H1", "Hospital A – Upper East", 40.7645, -73.9550, ed_beds=40, open_beds=6, avg_service_min=180),
    Hospital("H2", "Hospital B – Upper West", 40.8050, -73.9615, ed_beds=35, open_beds=8, avg_service_min=170),
    Hospital("H3", "Hospital C – Midtown West", 40.7700, -73.9870, ed_beds=30, open_beds=4, avg_service_min=160),
    Hospital("H4", "Hospital D – Midtown East", 40.7395, -73.9750, ed_beds=45, open_beds=10, avg_service_min=190),
    Hospital("H5", "Hospital E – Lower East", 40.7220, -73.9820, ed_beds=25, open_beds=3, avg_service_min=150),
    Hospital("H6", "Hospital F – Washington Heights", 40.8400, -73.9420, ed_beds=30, open_beds=2, avg_service_min=175),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def travel_minutes(lat: float, lon: float, hospital: Hospital) -> float:
    """Simulated ambulance travel time (minutes) from a point to a hospital.

    Straight-line distance × MIN_PER_KM + BASE_MIN. Ignores the street grid,
    one-way avenues, traffic and time of day — it is a demo approximation.
    """
    return BASE_MIN + MIN_PER_KM * haversine_km(lat, lon, hospital.lat, hospital.lon)


def hospital_by_id(hospitals: list[Hospital] | None = None) -> dict[str, Hospital]:
    return {h.id: h for h in (hospitals if hospitals is not None else DEFAULT_HOSPITALS)}
