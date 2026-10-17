"""
RescueNYC travel-time interface for the simulator and the map.

    from travel import TravelModel
    tm = TravelModel("spatial_data")

    tm.travel_seconds(base, "10001", hour=17, severity=2)           # unit -> incident (random draw)
    tm.travel_seconds(base, "10001", hour=17, noise=False)          # expected value
    tm.travel_seconds("10001", hosp, hour=17, leg="transport")      # incident -> hospital
    tm.travel_seconds(a, b, hour=17, slowdown={"BROOKLYN": 1.5})    # traffic-slowdown scenario
    tm.nearest_unit(units, "10001", hour=17)                        # which free unit arrives first
    tm.nearest_hospital("10001")                                    # destination for transport
    tm.route_points(a, b, n=20)                                     # coordinates to animate a trip
    tm.initial_fleet(40)                                            # starting unit positions

Locations can be a ZIP code string ("11217") or a (lat, lon) tuple.
Legs: "response" (unit -> incident; also use for returning to base) and "transport"
(incident -> hospital). `severity` is FDNY's final severity code (1 = most severe);
it only affects the response leg.
"""

import json
import os

import numpy as np
import pandas as pd


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


class TravelModel:
    def __init__(self, data_dir="spatial_data", seed=None):
        with open(os.path.join(data_dir, "travel_model.json")) as f:
            m = json.load(f)
        self.legs = m["legs"]
        self.severity_mult = self.legs["response"].get("severity_multiplier", {})
        self.min_km = m["min_km"]
        self.zones = pd.read_csv(os.path.join(data_dir, "zones.csv"), dtype={"zipcode": str}).set_index("zipcode")
        self.hospitals = pd.read_csv(os.path.join(data_dir, "hospitals.csv"))
        self.bases = pd.read_csv(os.path.join(data_dir, "bases.csv"), dtype={"base_zip": str})
        self.rng = np.random.default_rng(seed)

    # -------------------------------------------------------------- points

    def point(self, p):
        """ZIP code -> (lat, lon); (lat, lon) passes through."""
        if isinstance(p, str):
            z = self.zones.loc[p]
            return float(z["lat"]), float(z["lon"])
        return float(p[0]), float(p[1])

    def borough_of(self, p):
        """The ZIP's borough, or the nearest ZIP's borough for a raw point."""
        if isinstance(p, str) and p in self.zones.index:
            return self.zones.at[p, "borough"]
        lat, lon = self.point(p)
        d = _haversine_km(lat, lon, self.zones["lat"].values, self.zones["lon"].values)
        return self.zones["borough"].iat[int(d.argmin())]

    # -------------------------------------------------------------- travel time

    def travel_seconds(self, origin, dest, hour=12, slowdown=1.0, noise=True,
                       leg="response", severity=None):
        """Seconds to drive from origin to dest.
        Response leg uses the destination's borough (where the incident is);
        transport leg uses the origin's borough (where the patient is picked up)."""
        (lat1, lon1), (lat2, lon2) = self.point(origin), self.point(dest)
        km = max(float(_haversine_km(lat1, lon1, lat2, lon2)), self.min_km)
        boro = self.borough_of(dest if leg == "response" else origin)
        table = self.legs[leg]["by_borough"]
        p = table.get(boro) or next(iter(table.values()))
        t = (p["overhead_s"] + p["pace_s_per_km"] * km) * p["hour_multiplier"].get(str(int(hour) % 24), 1.0)
        if leg == "response" and severity is not None:
            t *= self.severity_mult.get(str(int(severity)), 1.0)
        t *= slowdown.get(boro, 1.0) if isinstance(slowdown, dict) else slowdown
        if noise:
            sigma = p["noise_sigma_log"]
            t *= self.rng.lognormal(mean=-sigma ** 2 / 2, sigma=sigma)   # mean-preserving noise
        return float(t)

    def nearest_unit(self, units, dest, hour=12, slowdown=1.0):
        """units: dict {unit_id: location}. Returns (unit_id, expected_seconds) of the fastest
        unit, using expected (noise-free) times so the choice is deterministic."""
        if not units:
            return None, None
        times = {u: self.travel_seconds(loc, dest, hour, slowdown, noise=False) for u, loc in units.items()}
        best = min(times, key=times.get)
        return best, times[best]

    def nearest_hospital(self, p):
        lat, lon = self.point(p)
        d = _haversine_km(lat, lon, self.hospitals["latitude"].values, self.hospitals["longitude"].values)
        h = self.hospitals.iloc[int(d.argmin())]
        return {"name": h["facility_name"], "lat": float(h["latitude"]), "lon": float(h["longitude"])}

    # -------------------------------------------------------------- map support

    def route_points(self, origin, dest, n=20):
        """Straight-line path for animation (lat, lon pairs). Placeholder until road routing."""
        (lat1, lon1), (lat2, lon2) = self.point(origin), self.point(dest)
        f = np.linspace(0, 1, n)
        return [(float(a), float(b)) for a, b in zip(lat1 + f * (lat2 - lat1), lon1 + f * (lon2 - lon1))]

    def initial_fleet(self, n_units):
        """Distribute n_units across the assumed bases by fleet share. Returns {unit_id: base_zip}."""
        counts = np.floor(self.bases["fleet_share"] * n_units).astype(int)
        leftover = n_units - counts.sum()
        order = np.argsort(-(self.bases["fleet_share"] * n_units - counts).values)
        counts.iloc[order[:leftover]] += 1
        fleet = {}
        for (_, b), k in zip(self.bases.iterrows(), counts):
            for i in range(k):
                fleet[f"{b['dispatch_area']}-{i + 1}"] = b["base_zip"]
        return fleet
