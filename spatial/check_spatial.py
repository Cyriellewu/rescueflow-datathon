"""
Sanity checks for the spatial model. Run after build_spatial.py:
    pip3 install matplotlib
    python3 check_spatial.py

Prints PASS / CHECK for each test and saves spatial_check_map.png.
"""

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from travel import TravelModel

D = "spatial_data"
tm = TravelModel(D, seed=0)
model = json.load(open(f"{D}/travel_model.json"))
zones, hosp, bases = tm.zones, tm.hospitals, tm.bases


def report(ok, msg):
    print(("PASS   " if ok else "CHECK  ") + msg)


print("\n--- 1. Data loaded ---")
report(150 <= len(zones) <= 250, f"{len(zones)} ZIP zones (NYC has roughly 180-200 residential ZIPs)")
report(40 <= len(hosp) <= 90, f"{len(hosp)} hospitals")
report(len(bases) >= 20, f"{len(bases)} assumed bases (one per dispatch area)")
in_nyc = zones["lat"].between(40.45, 40.95) & zones["lon"].between(-74.30, -73.65)
report(in_nyc.all(), f"{(~in_nyc).sum()} ZIP centroids fall outside the NYC bounding box")

print("\n--- 2. Fitted parameters are physically plausible ---")
for leg, max_over in [("response", 480), ("transport", 900)]:
    for b, p in model["legs"][leg]["by_borough"].items():
        kmh = 3600 / p["pace_s_per_km"] if p["pace_s_per_km"] > 0 else float("inf")
        report(5 <= kmh <= 60 and p["overhead_s"] <= max_over,
               f"{leg:9s} {b:28s} pace {p['pace_s_per_km']:4.0f}s/km (~{kmh:4.1f} km/h), "
               f"overhead {p['overhead_s']:.0f}s")
sev = model["legs"]["response"]["severity_multiplier"]
report(sev.get("1", 1) < sev.get("7", 1), f"severity 1 (most urgent) faster than 7: {sev.get('1')} vs {sev.get('7')}")

print("\n--- 3. Travel times behave sensibly ---")
z = zones.sort_values("n_calls", ascending=False).index
near, far = z[0], zones.index[((zones["lat"] - zones.at[z[0], "lat"]) ** 2
                               + (zones["lon"] - zones.at[z[0], "lon"]) ** 2).argmax()]
t_same = tm.travel_seconds(near, near, 12, noise=False)
t_far = tm.travel_seconds(near, far, 12, noise=False)
report(60 <= t_same <= 600, f"same-ZIP response trip: {t_same / 60:.1f} min")
report(t_far > t_same, f"farthest ZIP ({far}): {t_far / 60:.1f} min, longer than same-ZIP")
t_rush = tm.travel_seconds(near, far, 17, noise=False)
t_night = tm.travel_seconds(near, far, 3, noise=False)
report(t_rush >= t_night, f"5pm {t_rush / 60:.1f} min vs 3am {t_night / 60:.1f} min (rush hour should be slower)")
report(abs(tm.travel_seconds(near, far, 12, slowdown=1.5, noise=False) / t_far - 1.5) < 1e-6,
       "slowdown=1.5 makes trips exactly 1.5x longer")

h = tm.nearest_hospital(near)
t_tr = tm.travel_seconds(near, (h["lat"], h["lon"]), 12, noise=False, leg="transport")
report(120 <= t_tr <= 1800, f"transport from {near} to {h['name']}: {t_tr / 60:.1f} min")

print("\n--- 4. Validation: transport leg on held-out ZIPs ---")
v = model["validation"]
report(v["median_abs_error_s_by_zip"] <= 120,
       f"median error by ZIP: {v['median_abs_error_s_by_zip']:.0f}s (aim for under ~2 min)")
report(v["correlation_pred_vs_obs_by_zip"] >= 0.3,
       f"correlation predicted vs observed by ZIP: {v['correlation_pred_vs_obs_by_zip']}")

print("\n--- 5. Response leg: targets for the simulator ---")
ct = model["calibration_targets"]
print(pd.DataFrame(ct["by_borough"]).T.to_string())
for b, km in ct["implied_typical_response_km"].items():
    report(0.5 <= km <= 6, f"{b:28s} implied responding-unit distance {km:.1f} km "
                           f"(plausible if units are usually within a few km)")

# Map: if a point is in the water or outside NYC, something is wrong.
fig, ax = plt.subplots(figsize=(8, 9))
ax.scatter(zones["lon"], zones["lat"], s=zones["n_calls"] / zones["n_calls"].max() * 120,
           alpha=0.4, label="ZIP centroids (size = calls)")
ax.scatter(hosp["longitude"], hosp["latitude"], marker="+", s=60, color="red", label="hospitals")
ax.scatter(bases["lon"], bases["lat"], marker="^", s=40, color="black", label="assumed bases")
ax.set_aspect(1.3)
ax.legend(loc="upper left")
ax.set_title("RescueNYC spatial layer")
fig.savefig("spatial_check_map.png", dpi=130, bbox_inches="tight")
print("\nSaved spatial_check_map.png: open it and check the points form the shape of NYC.")
