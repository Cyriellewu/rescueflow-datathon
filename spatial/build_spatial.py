"""
RescueNYC spatial model: build the tables the simulator uses for travel times.

Run once (needs internet the first time):
    pip3 install pandas numpy requests pgeocode
    python3 build_spatial.py              # last 6 months of FDNY EMS data
    python3 build_spatial.py 3            # last 3 months (faster)

Writes to spatial_data/:
    ems_raw.csv            cached FDNY rows (delete to re-download)
    zip_centroids.csv      cached ZIP centroids
    zones.csv              one row per ZIP: centroid, borough, call volume, observed travel time
    hospitals.csv          NYC hospitals with coordinates (NYS DOH facility data)
    bases.csv              ASSUMED ambulance bases, one per FDNY dispatch area
    travel_model.json      fitted parameters, validation metrics, assumptions
    validation_by_zip.csv  predicted vs observed travel per held-out ZIP

MODEL. Every trip is point-to-point; there are two calibrated legs:
    seconds = (overhead_b + pace * km) * hour_mult_{b,h} * severity_mult_s * slowdown * noise
    km = straight-line distance, floored at MIN_KM for trips inside one ZIP.
    "pace" (seconds per straight-line km) absorbs road circuity.

  transport leg (incident -> hospital)
    Fitted on the time from leaving the scene to arriving at hospital, assuming the
    nearest hospital. This is the only leg where both ends are roughly known, so it is
    where pace (how time grows with distance) is learned.
    VALIDATION: fit on a random half of ZIP codes, tested on the other half.

  response leg  (unit -> incident, also used for returning to base)
    Same pace as the transport leg, an assumed 60 s overhead, and hour-of-day and
    call-severity multipliers measured from FDNY's observed response travel times.
    FDNY data doesn't record where the responding unit started, so response travel is
    matched at the simulation level: travel_model.json lists observed response-time
    targets, and the simulator's fleet size/positions are tuned to reproduce them.
"""

import json
import os
import sys

import numpy as np
import pandas as pd
import requests

OUT = "spatial_data"
MONTHS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
EMS_URL = "https://data.cityofnewyork.us/resource/76xm-jjuj.json"
HOSP_URL = "https://health.data.ny.gov/resource/vn5v-hh5r.json"
NYC_COUNTIES = ["New York", "Kings", "Queens", "Bronx", "Richmond"]
MIN_KM = 0.5          # assumed typical distance for a trip inside one ZIP
MIN_ZIP_CALLS = 30    # ZIPs with fewer valid calls are left out of ZIP-level fitting
PAGE = 50000

EMS_COLS = [
    "incident_datetime", "borough", "zipcode", "incident_dispatch_area",
    "final_severity_level_code", "valid_incident_rspns_time_indc",
    "incident_travel_tm_seconds_qy", "first_to_hosp_datetime", "first_hosp_arrival_datetime",
]


# ------------------------------------------------------------------ helpers

def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def socrata(url, params):
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ data

def fetch_ems():
    path = os.path.join(OUT, "ems_raw.csv")
    if os.path.exists(path):
        print(f"   using cached {path}")
        return pd.read_csv(path, dtype={"zipcode": str})

    latest = socrata(EMS_URL, {"$select": "max(incident_datetime) AS mx"})[0]["mx"]
    end = pd.Timestamp(latest)
    start = end - pd.DateOffset(months=MONTHS)
    print(f"   FDNY data ends {end.date()}; downloading {start.date()} to {end.date()}")

    where = f"incident_datetime >= '{start.strftime('%Y-%m-%dT%H:%M:%S')}'"
    rows, offset = [], 0
    while True:
        batch = socrata(EMS_URL, {"$select": ",".join(EMS_COLS), "$where": where,
                                  "$order": "incident_datetime", "$limit": PAGE, "$offset": offset})
        rows.extend(batch)
        offset += len(batch)
        print(f"   {offset:,} rows")
        if len(batch) < PAGE:
            break
    pd.DataFrame(rows, columns=EMS_COLS).to_csv(path, index=False)
    return pd.read_csv(path, dtype={"zipcode": str})


def fetch_hospitals():
    path = os.path.join(OUT, "hospitals.csv")
    if os.path.exists(path):
        return pd.read_csv(path)
    counties = ",".join(f"'{c}'" for c in NYC_COUNTIES)
    rows = socrata(HOSP_URL, {
        "$select": "fac_id,facility_name,county,latitude,longitude",
        "$where": f"description='Hospital' AND county in({counties})",
        "$limit": 1000,
    })
    h = pd.DataFrame(rows)
    h["latitude"] = pd.to_numeric(h["latitude"], errors="coerce")
    h["longitude"] = pd.to_numeric(h["longitude"], errors="coerce")
    h = h.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    h.to_csv(path, index=False)
    return h


def zip_centroids(zips):
    path = os.path.join(OUT, "zip_centroids.csv")
    if os.path.exists(path):
        return pd.read_csv(path, dtype={"zipcode": str})
    old = os.path.join(OUT, "zones.csv")            # reuse centroids from an earlier run
    if os.path.exists(old):
        out = pd.read_csv(old, dtype={"zipcode": str})[["zipcode", "lat", "lon"]]
    else:
        import pgeocode
        geo = pgeocode.Nominatim("us").query_postal_code(list(zips))
        out = pd.DataFrame({"zipcode": list(zips),
                            "lat": geo["latitude"].values, "lon": geo["longitude"].values})
        missing = out["lat"].isna().sum()
        if missing:
            print(f"   {missing} ZIP codes had no centroid and are dropped: "
                  f"{', '.join(out.loc[out.lat.isna(), 'zipcode'].head(10))}")
        out = out.dropna()
    out.to_csv(path, index=False)
    return out


# ------------------------------------------------------------------ building

def clean_ems(df):
    df = df.copy()
    df["zipcode"] = df["zipcode"].astype(str).str.extract(r"(\d{5})")[0]
    df = df.dropna(subset=["zipcode", "borough"])
    for c in ["incident_datetime", "first_to_hosp_datetime", "first_hosp_arrival_datetime"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["travel_s"] = pd.to_numeric(df["incident_travel_tm_seconds_qy"], errors="coerce")
    df["transport_s"] = (df["first_hosp_arrival_datetime"] - df["first_to_hosp_datetime"]).dt.total_seconds()
    df["severity"] = pd.to_numeric(df["final_severity_level_code"], errors="coerce")
    df["hour"] = df["incident_datetime"].dt.hour
    return df


def build_zones(ems, cents):
    valid = ems[(ems["valid_incident_rspns_time_indc"] == "Y") & ems["travel_s"].between(1, 3600)]
    z = (ems.groupby("zipcode")
         .agg(borough=("borough", lambda s: s.mode().iat[0]),
              dispatch_area=("incident_dispatch_area",
                             lambda s: s.mode().iat[0] if s.notna().any() else None),
              n_calls=("zipcode", "size"))
         .reset_index())
    obs = valid.groupby("zipcode")["travel_s"].median().rename("obs_median_travel_s")
    return z.merge(cents, on="zipcode").merge(obs, on="zipcode", how="left")


def build_bases(ems, zones):
    """ASSUMPTION: one base per dispatch area, at that area's busiest ZIP centroid,
    with fleet share proportional to the area's call volume."""
    counts = ems.groupby(["incident_dispatch_area", "zipcode"]).size().rename("n").reset_index()
    top = counts.sort_values("n", ascending=False).drop_duplicates("incident_dispatch_area")
    area_calls = ems.groupby("incident_dispatch_area").size().rename("area_calls")
    b = (top.merge(zones[["zipcode", "borough", "lat", "lon"]], on="zipcode")
         .merge(area_calls, left_on="incident_dispatch_area", right_index=True))
    b["fleet_share"] = b["area_calls"] / b["area_calls"].sum()
    return b.rename(columns={"incident_dispatch_area": "dispatch_area", "zipcode": "base_zip"})[
        ["dispatch_area", "base_zip", "borough", "lat", "lon", "area_calls", "fleet_share"]]


# ------------------------------------------------------------------ response leg (v2)
#
# Finding from the first real run: FDNY's observed response travel time is ~9 minutes in
# every ZIP and does NOT grow with distance from a fixed base (fitted pace came out at
# ~2 s/km). That is because FDNY sends the nearest *available* unit, wherever it happens
# to be, so the unit's origin is unknown. Response data therefore cannot tell us how
# speed relates to distance. So the response leg uses:
#   pace     <- transport leg (origin and destination both approximately known)
#   overhead <- RESPONSE_OVERHEAD_S assumption (finding the address, parking)
#   hour and severity multipliers <- response data (relative effects, distance-free)
# and the observed response-time distribution becomes the target the simulator is
# tuned to (fleet size / unit positions), reported under "calibration_targets".

RESPONSE_OVERHEAD_S = 60.0
RESPONSE_NOISE_SIGMA = 0.3     # assumption: trip-to-trip variation at a fixed distance


def response_multipliers(ems):
    v = ems[(ems["valid_incident_rspns_time_indc"] == "Y") & ems["travel_s"].between(1, 3600)]
    v = v.dropna(subset=["hour"])
    boro_med = v.groupby("borough")["travel_s"].transform("median")
    ratio = v["travel_s"] / boro_med
    hour_mult = ratio.groupby([v["borough"], v["hour"]]).median().clip(0.6, 1.8)
    hm = hour_mult.reindex(pd.MultiIndex.from_arrays([v["borough"], v["hour"]])).values
    sev = (ratio / hm).groupby(v["severity"]).median().clip(0.5, 2.0)
    targets = v.groupby("borough")["travel_s"].quantile([0.5, 0.9]).unstack()
    targets.columns = ["median_s", "p90_s"]
    return hour_mult, {int(s): round(float(m), 3) for s, m in sev.items()}, targets


def build_response(trans, hour_mult):
    params = {}
    for b, tp in trans.items():
        hb = hour_mult.loc[b] if b in hour_mult.index.get_level_values(0) else pd.Series(dtype=float)
        params[b] = {"overhead_s": RESPONSE_OVERHEAD_S, "pace_s_per_km": tp["pace_s_per_km"],
                     "hour_multiplier": {int(h): round(float(m), 3) for h, m in hb.items()},
                     "noise_sigma_log": RESPONSE_NOISE_SIGMA}
    return params


def validate_transport(ems, zones, hosp):
    """Fit the transport leg on half the ZIP codes, test on the other half."""
    zips = np.array(sorted(zones["zipcode"]))
    train = set(np.random.default_rng(0).choice(zips, len(zips) // 2, replace=False))
    p = fit_transport(ems[ems["zipcode"].isin(train)], zones, hosp, quiet=True)
    t = ems[~ems["zipcode"].isin(train)].dropna(subset=["transport_s"])
    t = t[t["transport_s"].between(60, 3600) & t["borough"].isin(p)].merge(
        zones[["zipcode", "lat", "lon"]], on="zipcode")
    d = haversine_km(t["lat"].values[:, None], t["lon"].values[:, None],
                     hosp["latitude"].values[None, :], hosp["longitude"].values[None, :]).min(axis=1)
    hrs = t["first_to_hosp_datetime"].dt.hour.fillna(12).astype(int)
    pred = [(p[b]["overhead_s"] + p[b]["pace_s_per_km"] * max(k, MIN_KM)) * p[b]["hour_multiplier"].get(h, 1.0)
            for b, k, h in zip(t["borough"], d, hrs)]
    t = t.assign(pred=pred)
    z = t.groupby("zipcode").agg(n=("transport_s", "size"), obs=("transport_s", "median"),
                                 pred=("pred", "median")).query("n >= @MIN_ZIP_CALLS")
    err = (z["pred"] - z["obs"]).abs()
    z.to_csv(os.path.join(OUT, "validation_by_zip.csv"))
    return {
        "leg": "transport (incident -> nearest hospital)",
        "method": "fit on 50% of ZIP codes, tested on the other 50%",
        "zips_evaluated": int(len(z)),
        "median_abs_error_s_by_zip": round(float(err.median()), 1),
        "correlation_pred_vs_obs_by_zip": round(float(z["pred"].corr(z["obs"])), 3),
    }


# ------------------------------------------------------------------ transport leg

def fit_transport(ems, zones, hosp, quiet=False):
    t = ems.dropna(subset=["transport_s"]).merge(zones[["zipcode", "lat", "lon"]], on="zipcode")
    t = t[t["transport_s"].between(60, 3600)]
    d = haversine_km(t["lat"].values[:, None], t["lon"].values[:, None],
                     hosp["latitude"].values[None, :], hosp["longitude"].values[None, :]).min(axis=1)
    t = t.assign(km=np.maximum(d, MIN_KM), thour=t["first_to_hosp_datetime"].dt.hour)
    params = {}
    for b, g in t.groupby("borough"):
        bins = pd.qcut(g["km"], q=min(10, g["km"].nunique()), duplicates="drop")
        med = g.groupby(bins, observed=True).agg(km=("km", "median"), s=("transport_s", "median"))
        pace, overhead = np.polyfit(med["km"], med["s"], 1) if len(med) >= 2 else (150.0, 300.0)
        pace, overhead = max(float(pace), 30.0), max(float(overhead), 0.0)
        ratio = g["transport_s"] / (overhead + pace * g["km"])
        hm = ratio.groupby(g["thour"]).median().clip(0.6, 1.8)
        params[b] = {"overhead_s": round(overhead, 1), "pace_s_per_km": round(pace, 1),
                     "hour_multiplier": {int(h): round(float(m), 3) for h, m in hm.items()},
                     "noise_sigma_log": round(float(np.log(ratio[ratio > 0]).std()), 3)}
    return params


# ------------------------------------------------------------------ main

def main():
    os.makedirs(OUT, exist_ok=True)

    print("1/6 FDNY EMS incidents")
    ems = clean_ems(fetch_ems())
    print(f"   {len(ems):,} incidents, {ems['zipcode'].nunique()} ZIP codes")

    print("2/6 ZIP centroids")
    zones = build_zones(ems, zip_centroids(sorted(ems["zipcode"].unique())))
    ems = ems[ems["zipcode"].isin(zones["zipcode"])]
    zones.to_csv(os.path.join(OUT, "zones.csv"), index=False)

    print("3/6 Hospitals")
    hosp = fetch_hospitals()
    print(f"   {len(hosp)} hospitals")

    print("4/6 Assumed bases")
    bases = build_bases(ems, zones)
    bases.to_csv(os.path.join(OUT, "bases.csv"), index=False)
    print(f"   {len(bases)} bases")

    print("5/6 Transport leg (incident -> nearest hospital), with holdout validation")
    metrics = validate_transport(ems, zones, hosp)
    trans = fit_transport(ems, zones, hosp)                 # final fit on all ZIP codes
    for b, p in trans.items():
        print(f"   {b:28s} overhead {p['overhead_s']:5.0f}s  pace {p['pace_s_per_km']:4.0f}s/km"
              f"  (~{3600 / p['pace_s_per_km']:4.1f} km/h straight-line)")
    print(json.dumps(metrics, indent=2))

    print("6/6 Response leg (unit -> incident)")
    hour_mult, sev, targets = response_multipliers(ems)
    resp = build_response(trans, hour_mult)
    print("   severity multipliers:", sev)
    print("   observed response travel (simulator calibration targets):")
    print(targets.round(0).to_string())
    implied = {b: round((targets.at[b, "median_s"] - RESPONSE_OVERHEAD_S) / resp[b]["pace_s_per_km"], 2)
               for b in resp if b in targets.index}
    print("   implied typical distance of the responding unit (km):", implied)

    model = {
        "legs": {"response": {"by_borough": resp, "severity_multiplier": sev},
                 "transport": {"by_borough": trans}},
        "min_km": MIN_KM,
        "validation": metrics,
        "calibration_targets": {
            "description": "Observed FDNY response travel (activation to on scene). Tune simulator "
                           "fleet size and unit positions until baseline simulated travel matches these.",
            "by_borough": targets.round(0).to_dict(orient="index"),
            "implied_typical_response_km": implied,
        },
        "data_window_months": MONTHS,
        "assumptions": [
            "FDNY EMS data locates incidents only to ZIP code; incidents are placed at ZIP centroids.",
            "Distances are straight-line; road circuity is absorbed into the fitted pace.",
            "Ambulance bases are assumed: one per FDNY dispatch area at its busiest ZIP; fleet share proportional to call volume.",
            "Speed vs distance (pace) is fitted on the transport leg, assuming the nearest hospital; real destination choice is not in the data.",
            "Response leg reuses that pace with an assumed 60 s overhead; FDNY data cannot identify where responding units started, so response travel is matched at the simulation level via calibration_targets.",
            "Response noise (log-sigma 0.3) is an assumption.",
            f"Trips within one ZIP use a minimum distance of {MIN_KM} km.",
            "Hospital list includes all NYS DOH 'Hospital' facilities in NYC; not all have emergency departments.",
        ],
    }
    with open(os.path.join(OUT, "travel_model.json"), "w") as f:
        json.dump(model, f, indent=2)
    print(f"\nDone. Outputs in {OUT}/")


if __name__ == "__main__":
    main()
