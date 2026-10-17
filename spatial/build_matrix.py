"""Borough-to-borough expected response travel (minutes) by hour of day, from the fitted spatial model.

For each origin borough, units start at that borough's ASSUMED bases (weighted by fleet share); for each
destination borough, incidents sit at its ZIP centroids (weighted by call volume). The expected
noise-free travel time of every base->ZIP pair is averaged. Written to spatial_data/borough_travel_matrix.json
and consumed by rescueflow.des.travel_minutes for cross-borough responses (in-borough medians stay as
observed in FDNY data). Run from the repo root:

    python spatial/build_matrix.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from travel import TravelModel  # noqa: E402

tm = TravelModel(str(HERE / "spatial_data"), seed=0)
zones, bases = tm.zones.reset_index(), tm.bases
boroughs = sorted(zones["borough"].unique())
out = {}
for o in boroughs:
    ob = bases[bases["borough"] == o]
    wo = (ob["fleet_share"] / ob["fleet_share"].sum()).to_numpy()
    for d in boroughs:
        dz = zones[zones["borough"] == d]
        wd = (dz["n_calls"] / dz["n_calls"].sum()).to_numpy()
        by_hour = []
        for h in range(24):
            t = np.array([[tm.travel_seconds((a.lat, a.lon), (z.lat, z.lon), hour=h, noise=False)
                           for z in dz.itertuples()] for a in ob.itertuples()])
            by_hour.append(round(float(wo @ t @ wd) / 60.0, 2))
        out[f"{o}|{d}"] = by_hour
meta = {"minutes_by_hour": out, "boroughs": boroughs,
        "note": "Expected response-leg travel in minutes, origin bases (ASSUMED, one per FDNY dispatch area) to "
                "destination ZIP centroids (real), from the spatial model fitted on FDNY transport legs "
                "(validation: corr 0.73 across held-out ZIPs). Straight-line distance x calibrated pace."}
(HERE / "spatial_data" / "borough_travel_matrix.json").write_text(json.dumps(meta, indent=1))
df = pd.DataFrame({k: v for k, v in out.items()}).T
df.columns = [f"h{h}" for h in range(24)]
print(df[["h3", "h8", "h17"]].round(1).to_string())
