"""Build spatial_data/geo.json: simplified NYC borough and ZIP (MODZCTA) boundaries for the dashboard map,
joined with the real FDNY ZIP metrics from zones.csv (call volume, median travel to scene).

    python3 spatial/build_geo.py                 # downloads both layers from NYC Open Data
    python3 spatial/build_geo.py --src DIR       # or reads DIR/modzcta.geojson and DIR/boroughs.geojson

Sources (real): NYC DOHMH Modified ZIP Code Tabulation Areas (pri4-ifjk) and NYC DCP Borough Boundaries
(gthc-hcne), both on NYC Open Data. Polygons are simplified (Douglas-Peucker, ~10 m) for the browser.
"""
import argparse
import json
import math
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent / "spatial_data"
URL = "https://data.cityofnewyork.us/api/geospatial/{}?method=export&format=GeoJSON"
LAYERS = {"modzcta": "pri4-ifjk", "boroughs": "gthc-hcne"}
BOROUGH = {"Bronx": "BRONX", "Brooklyn": "BROOKLYN", "Manhattan": "MANHATTAN", "Queens": "QUEENS",
           "Staten Island": "RICHMOND / STATEN ISLAND"}
TOL = 0.0001  # degrees, about 10 m


def simplify(pts, tol=TOL):
    """Douglas-Peucker on a line or ring of [lon, lat] points. A closed ring (first point == last) is
    split in two halves first, otherwise the start-end segment has zero length and nothing is kept."""
    if len(pts) < 4:
        return pts
    if pts[0] == pts[-1]:
        mid = len(pts) // 2
        return simplify_line(pts[:mid + 1], tol) + simplify_line(pts[mid:], tol)[1:]
    return simplify_line(pts, tol)


def simplify_line(pts, tol):
    if len(pts) < 3:
        return [[round(p[0], 5), round(p[1], 5)] for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = 0.0, None
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [[round(p[0], 5), round(p[1], 5)] for p, k in zip(pts, keep) if k]


def simplify_geom(g):
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = []
    for poly in polys:
        rings = [simplify(r) for r in poly]
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            out.append(rings)
    return {"type": "MultiPolygon", "coordinates": out}


def load(name, src):
    if src:
        return json.loads((Path(src) / f"{name}.geojson").read_text())
    r = requests.get(URL.format(LAYERS[name]), timeout=300)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="folder with modzcta.geojson and boroughs.geojson")
    args = ap.parse_args()
    zones = pd.read_csv(OUT / "zones.csv", dtype={"zipcode": str})

    boroughs = []
    for f in load("boroughs", args.src)["features"]:
        boroughs.append({"type": "Feature", "properties": {"borough": BOROUGH[f["properties"]["boroname"]]},
                         "geometry": simplify_geom(f["geometry"])})

    zctas = []
    for f in load("modzcta", args.src)["features"]:
        p = f["properties"]
        zips = sorted({z.strip() for z in (p.get("label") or "").split(",") + (p.get("zcta") or "").split(",") if z.strip()})
        z = zones[zones["zipcode"].isin(zips)]
        n = int(z["n_calls"].sum())
        tv = z.dropna(subset=["obs_median_travel_s"])
        travel = float((tv["obs_median_travel_s"] * tv["n_calls"]).sum() / tv["n_calls"].sum()) if len(tv) else None
        zctas.append({"type": "Feature", "geometry": simplify_geom(f["geometry"]), "properties": {
            "modzcta": p["modzcta"], "zips": zips, "pop": int(float(p.get("pop_est") or 0)),
            "borough": z.groupby("borough")["n_calls"].sum().idxmax() if n else None,
            "n_calls": n, "travel_s": round(travel, 1) if travel is not None else None,
            "calls_per_1k": round(n / (int(float(p.get("pop_est") or 0)) / 1000), 1) if n and float(p.get("pop_est") or 0) > 0 else None}})

    geo = {"boroughs": {"type": "FeatureCollection", "features": boroughs},
           "zctas": {"type": "FeatureCollection", "features": zctas},
           "provenance": {"zctas": "NYC DOHMH Modified ZIP Code Tabulation Areas (NYC Open Data pri4-ifjk), real",
                          "boroughs": "NYC DCP Borough Boundaries (NYC Open Data gthc-hcne), real",
                          "metrics": "FDNY EMS incidents aggregated to ZIP (zones.csv): calls and call-weighted median travel to scene, real",
                          "simplified": f"Douglas-Peucker, tolerance {TOL} degrees (~10 m)"}}
    out = OUT / "geo.json"
    out.write_text(json.dumps(geo, separators=(",", ":")))
    matched = sum(1 for f in zctas if f["properties"]["n_calls"])
    print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} kB): {len(boroughs)} boroughs, {len(zctas)} ZIP areas, {matched} with FDNY calls")


if __name__ == "__main__":
    main()
