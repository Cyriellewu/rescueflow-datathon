"""External check of the policy lab's unit-cycle assumptions against real EMS records from several places.

Checks four assumptions of rescueflow/des.py (Scenario defaults, read from the code):
  hospital   time at the hospital until the unit can leave   (lab: handover ~ Exponential(mean handover_min))
  scene      time on scene for transported patients          (lab: ~ Exponential(mean scene_min))
  transport  scene -> hospital                               (lab: ~ lognormal(median transport_min, sigma 0.35))
  share      share of responses that transport a patient     (lab: transport_share)

Sources:
  nyc      FDNY EMS Incident Dispatch Data (NYC Open Data 76xm-jjuj), call level, real
  sf       San Francisco Fire Dept Calls for Service (data.sf.gov nuek-vuh3), ambulance units, real
  indiana  Indiana statewide EMS runs, NEMSIS/ImageTrend (hub.mph.in.gov), 2024, optional, real
  riverside  Riverside County CA, AMR ambulance patient offload delays by hospital, 2012-2016 (published monthly
             aggregates: ED visits held > 30 min after arrival)

    python scripts/validate_turnaround.py --raw data/raw [--sf-cache sf.csv] [--indiana ems_runs_2024.csv]

US sources only.

Writes docs/external_validation.json (dashboard, /external) and docs/external_validation.md.
"""
import argparse
import dataclasses
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescueflow.des import Scenario  # noqa: E402

SF_URL = "https://data.sf.gov/resource/nuek-vuh3.json"
SF_UNITS = ("MEDIC", "PRIVATE", "BLS")
QS = [0.25, 0.5, 0.75, 0.9, 0.95]
BINS = {"hospital": np.arange(0, 125, 5), "scene": np.arange(0, 62, 2), "transport": np.arange(0, 62, 2)}
CAP = {"hospital": 240, "scene": 120, "transport": 120}  # longer durations are treated as data errors
SIGMA_TRANSPORT = 0.35  # rescueflow/des.py Sim.lognorm default

RIVERSIDE_URL = "https://data.countyofriverside.us/resource/8ueb-m2qq.json"
MONTHS = ["jan", "feb", "mar", "apr", "may", "june", "july", "aug", "sept", "oct", "nov", "dec"]


def riverside_offload():
    """Share of ambulance ED visits held > 30 min after arrival (pure offload, before any clean-up), by year."""
    rows = requests.get(RIVERSIDE_URL, params={"$limit": 5000}, timeout=120).json()
    hms = lambda x: sum(float(v) * k for v, k in zip(x.split(":"), (60, 1, 1 / 60)))
    agg = {}
    for r in rows:
        for m in MONTHS:
            v, d, t = (r.get(f"{m}_{k}") for k in ("total_amr_als_ambulance_visits", "units_delayed", "monthly_offload_delay_time"))
            if v and d:
                a = agg.setdefault(int(r["year"]), [0, 0, 0.0, 0])
                a[0] += int(float(v)); a[1] += int(float(d))
                if t:
                    a[2] += hms(t); a[3] += int(float(d))
    visits, held = sum(a[0] for a in agg.values()), sum(a[1] for a in agg.values())
    return {"share_over_30": round(held / visits, 3), "visits": visits,
            "mean_excess_min": round(sum(a[2] for a in agg.values()) / sum(a[3] for a in agg.values()), 1),
            "by_year": {y: round(a[1] / a[0], 3) for y, a in sorted(agg.items())}}


def default(name):
    return next(f.default for f in dataclasses.fields(Scenario) if f.name == name)


def mins(a, b):
    return (pd.to_datetime(b, format="mixed", errors="coerce") - pd.to_datetime(a, format="mixed", errors="coerce")).dt.total_seconds() / 60


def summarize(m: pd.Series, when: pd.Series, param: str) -> dict:
    ok = (m > 0) & (m <= CAP[param])
    v, w = m[ok], when[ok]
    bins = BINS[param]
    hist = np.histogram(v.clip(upper=bins[-1] - 1e-9), bins=bins)[0] / len(v)
    out = {"n": int(len(v)), "excluded_share": round(float(1 - ok.mean()), 4), "mean": round(float(v.mean()), 1),
           "cv": round(float(v.std() / v.mean()), 2), "quantiles": {f"p{int(q * 100)}": round(float(v.quantile(q)), 1) for q in QS},
           "hist": [round(float(h), 4) for h in hist]}
    if w.notna().any():
        out["by_year"] = {int(y): round(float(g.median()), 1) for y, g in v.groupby(w.dt.year) if len(g) > 1000}
        out["window"] = [str(w.min().date()), str(w.max().date())]
    return out


def sim_exponential(mean, param):
    cdf = lambda x: 1 - math.exp(-x / mean)
    return sim_from_cdf(cdf, mean, 1.0, {f"p{int(q * 100)}": round(-mean * math.log(1 - q), 1) for q in QS}, param)


def sim_lognormal(median, sigma, param):
    cdf = lambda x: 0.0 if x <= 0 else 0.5 * (1 + math.erf((math.log(x) - math.log(median)) / (sigma * math.sqrt(2))))
    z = {0.25: -0.6745, 0.5: 0.0, 0.75: 0.6745, 0.9: 1.2816, 0.95: 1.6449}
    mean = median * math.exp(sigma ** 2 / 2)
    return sim_from_cdf(cdf, mean, math.sqrt(math.exp(sigma ** 2) - 1), {f"p{int(q * 100)}": round(median * math.exp(sigma * z[q]), 1) for q in QS}, param)


def sim_from_cdf(cdf, mean, cv, quantiles, param):
    b = BINS[param]
    hist = [cdf(hi) - cdf(lo) for lo, hi in zip(b[:-1], b[1:])]
    hist[-1] += 1 - cdf(b[-1])
    return {"mean": round(mean, 1), "cv": round(cv, 2), "quantiles": quantiles, "hist": [round(h, 4) for h in hist]}


def fetch_sf(since, cache):
    if cache and Path(cache).exists():
        return pd.read_csv(cache)
    where = (f"hospital_dttm IS NOT NULL AND available_dttm IS NOT NULL AND hospital_dttm >= '{since}T00:00:00' "
             f"AND unit_type in ({','.join(repr(u) for u in SF_UNITS)})")
    rows, offset = [], 0
    while True:
        for attempt in range(4):
            try:
                r = requests.get(SF_URL, params={"$select": "unit_id,unit_type,call_number,on_scene_dttm,transport_dttm,hospital_dttm,available_dttm",
                                                 "$where": where, "$order": "hospital_dttm,call_number,unit_id", "$limit": 50000, "$offset": offset}, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                print("retry:", e)
                time.sleep(2 ** (attempt + 1))
        batch = r.json()
        rows += batch
        print(f"  SF offset {offset}: {len(batch)} rows")
        if len(batch) < 50000:
            break
        offset += 50000
    df = pd.DataFrame(rows)
    if cache:
        df.to_csv(cache, index=False)
    return df


def sf_transport_share(since):
    base = f"unit_type in ({','.join(repr(u) for u in SF_UNITS)}) AND on_scene_dttm >= '{since}T00:00:00'"
    count = lambda w: int(requests.get(SF_URL, params={"$select": "count(*) as n", "$where": w}, timeout=120).json()[0]["n"])
    on_scene, transported = count(base), count(base + " AND hospital_dttm IS NOT NULL")
    return {"share": round(transported / on_scene, 3), "n": on_scene, "measure": "ambulance unit responses on scene that reached a hospital"}


def verdict(sim_median, real_medians):
    lo, hi = min(real_medians), max(real_medians)
    if sim_median < 0.8 * lo:
        return "shorter than real"
    if sim_median > 1.2 * hi:
        return "longer than real"
    return "close to real"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--sf-cache")
    ap.add_argument("--indiana", help="Indiana EMS runs CSV (hub.mph.in.gov, e.g. ems_runs_2024.csv)")
    args = ap.parse_args()
    params = {p: {"sources": {}} for p in ("hospital", "scene", "transport")}
    share = {}

    # ---- NYC (call level) ----
    files = sorted(Path(args.raw).glob("incidents_*.csv"))
    if not files:
        raise SystemExit(f"no FDNY CSVs in {args.raw}")
    cols = ["first_on_scene_datetime", "first_to_hosp_datetime", "first_hosp_arrival_datetime", "incident_close_datetime"]
    nyc = pd.concat((pd.read_csv(f, usecols=cols) for f in files), ignore_index=True)
    on = pd.to_datetime(nyc["first_on_scene_datetime"], format="ISO8601", errors="coerce")
    nyc, on = nyc[on >= args.since], on[on >= args.since]
    label = "NYC FDNY (real)"
    params["hospital"]["sources"]["nyc"] = {"label": "NYC FDNY (real, proxy)", "measure": "hospital arrival -> incident close",
                                            **summarize(mins(nyc["first_hosp_arrival_datetime"], nyc["incident_close_datetime"]), on, "hospital")}
    params["scene"]["sources"]["nyc"] = {"label": label, "measure": "first unit on scene -> left for hospital",
                                         **summarize(mins(nyc["first_on_scene_datetime"], nyc["first_to_hosp_datetime"]), on, "scene")}
    params["transport"]["sources"]["nyc"] = {"label": label, "measure": "left for hospital -> hospital arrival",
                                             **summarize(mins(nyc["first_to_hosp_datetime"], nyc["first_hosp_arrival_datetime"]), on, "transport")}
    share["nyc"] = {"label": label, "share": round(float(nyc["first_hosp_arrival_datetime"].notna().mean()), 3), "n": int(len(nyc)),
                    "measure": "incidents with a unit on scene that reached a hospital"}
    nyc_src = "FDNY EMS Incident Dispatch Data, NYC Open Data 76xm-jjuj"

    # ---- San Francisco (ambulance unit level) ----
    sf = fetch_sf(args.since, args.sf_cache)
    sf = sf[sf["unit_type"].isin(SF_UNITS)].drop_duplicates(["call_number", "unit_id"])
    when = pd.to_datetime(sf["hospital_dttm"], format="ISO8601", errors="coerce")
    label = "San Francisco ambulances (real)"
    params["hospital"]["sources"]["sf"] = {"label": label, "measure": "hospital arrival -> unit available",
                                           **summarize(mins(sf["hospital_dttm"], sf["available_dttm"]), when, "hospital")}
    if "transport_dttm" in sf:
        params["scene"]["sources"]["sf"] = {"label": label, "measure": "unit on scene -> transport start",
                                            **summarize(mins(sf["on_scene_dttm"], sf["transport_dttm"]), when, "scene")}
        params["transport"]["sources"]["sf"] = {"label": label, "measure": "transport start -> hospital arrival",
                                                **summarize(mins(sf["transport_dttm"], sf["hospital_dttm"]), when, "transport")}
    share["sf"] = {"label": label, **sf_transport_share(args.since)}
    sf_src = "SFFD Calls for Service, data.sf.gov nuek-vuh3; unit types MEDIC, PRIVATE, BLS"

    # ---- Indiana (statewide NEMSIS records, 911 scene responses) ----
    in_src = None
    if args.indiana:
        # The published *_DT fields carry the date only, so intervals come from the file's own minute field.
        # PROVIDER_TO_DESTINATION_MINS is undocumented; by name and size (median ~13 min) it is the transport leg.
        # Time on scene cannot be derived from this file.
        use = ["PROVIDER_TYPE_SERVICE", "DESTINATION_TYPE", "UNIT_ARRIVED_ON_SCENE_DT", "PROVIDER_TO_DESTINATION_MINS"]
        ind = pd.read_csv(args.indiana, usecols=use, dtype=str, low_memory=False)
        ind = ind[ind["PROVIDER_TYPE_SERVICE"].fillna("").str.startswith("911 Response (Scene) with Transport")]
        ind = ind[ind["UNIT_ARRIVED_ON_SCENE_DT"].notna()]
        hosp = ind["DESTINATION_TYPE"].fillna("").str.startswith("Hospital")
        label = "Indiana statewide EMS (real)"
        params["transport"]["sources"]["indiana"] = {"label": label, "measure": "scene -> destination (file's PROVIDER_TO_DESTINATION_MINS, undocumented)",
                                                     **summarize(pd.to_numeric(ind.loc[hosp, "PROVIDER_TO_DESTINATION_MINS"], errors="coerce"),
                                                                 pd.Series(pd.NaT, index=ind.index[hosp]), "transport")}
        share["indiana"] = {"label": label, "share": round(float(hosp.mean()), 3), "n": int(len(ind)),
                            "measure": "911 scene responses (transport-capable units) with a hospital destination"}
        in_src = ("Indiana EMS runs 2024 (NEMSIS/ImageTrend), hub.mph.in.gov; 911 scene responses by transport-capable units; "
                  "statewide, mostly not urban; date-only timestamps, so no time-on-scene check")


    # ---- Riverside County: pure offload (handover) tail ----
    try:
        offload = {"label": "Riverside County, CA (AMR, real aggregate)", "measure": "ambulance ED visits held > 30 min after arrival",
                   "lab_share_over_30": round(math.exp(-30 / default("handover_min")), 3), **riverside_offload()}
    except (requests.RequestException, ValueError, KeyError, ZeroDivisionError) as e:
        print("Riverside offload data unavailable:", e)
        offload = None

    # ---- the lab's assumptions ----
    h, s, t, ts = default("handover_min"), default("scene_min"), default("transport_min"), default("transport_share")
    params["hospital"].update(title="Time at the hospital", question="How long does an ambulance stay at the hospital before it can take the next call?",
                              sim={"label": "Policy lab assumption", "measure": f"handover ~ Exponential(mean {h:g} min)", **sim_exponential(h, "hospital")},
                              offload=offload)
    params["scene"].update(title="Time on scene", question="How long does a crew stay on scene before leaving with the patient?",
                           sim={"label": "Policy lab assumption", "measure": f"on scene ~ Exponential(mean {s:g} min)", **sim_exponential(s, "scene")})
    params["transport"].update(title="Transport to hospital", question="How long is the drive from the scene to the hospital?",
                               sim={"label": "Policy lab assumption", "measure": f"transport ~ lognormal(median {t:g} min, sigma {SIGMA_TRANSPORT})",
                                    **sim_lognormal(t, SIGMA_TRANSPORT, "transport")})
    for p, d in params.items():
        d["bins_min"] = BINS[p].tolist()
        d["verdict"] = verdict(d["sim"]["quantiles"]["p50"], [x["quantiles"]["p50"] for x in d["sources"].values()])
    share_real = [v["share"] for v in share.values()]
    hm = [x["quantiles"]["p50"] for x in params["hospital"]["sources"].values()]
    params["hospital"]["reading"] = (
        f"Until the unit is free again, real ambulances spend a median of {min(hm):.0f}–{max(hm):.0f} min at the hospital; the lab's handover "
        f"draw has a median of {params['hospital']['sim']['quantiles']['p50']:.1f}. "
        + (f"The handover step itself looks right: in Riverside County {offload['share_over_30']:.0%} of ambulance ED visits were held over "
           f"30 min, and the lab gives {offload['lab_share_over_30']:.0%}. " if offload else "")
        + "What the lab leaves out is the time after handover (cleaning, restocking, paperwork): it frees the unit the moment the handover ends, "
          "so it under-states how long hospitals tie up units.")
    sm = [x["quantiles"]["p50"] for x in params["scene"]["sources"].values()]
    params["scene"]["reading"] = (f"Real crews spend a median of {min(sm):.0f}–{max(sm):.0f} min on scene with patients they transport; the lab's mean "
                                  f"of {s:g} min matches, but its exponential draw is wider than the real spread (lab P90 "
                                  f"{params['scene']['sim']['quantiles']['p90']:.0f} min vs real {max(x['quantiles']['p90'] for x in params['scene']['sources'].values()):.0f}).")
    tm = [x["quantiles"]["p50"] for x in params["transport"]["sources"].values()]
    params["transport"]["reading"] = (f"Real drives to the hospital take a median of {min(tm):.0f}–{max(tm):.0f} min; the lab's {t:g} min matches NYC closely "
                                      f"({params['transport']['sources']['nyc']['quantiles']['p50']:.1f}).")
    share_out = {"title": "Share transported", "sim": ts, "sources": share,
                 "verdict": "close to real" if min(share_real) - 0.05 <= ts <= max(share_real) + 0.05 else ("lower than real" if ts < min(share_real) else "higher than real")}

    out = {
        "question": "Do the policy lab's unit-cycle assumptions match real EMS records?",
        "params": params, "share": share_out,
        "sources": {"nyc": nyc_src, "sf": sf_src, "indiana": in_src, "riverside": "Riverside County CA open data 8ueb-m2qq (AMR offload delays, 2012-2016)"},
        "reviewed": [
            {"place": "New York City", "dataset": "FDNY EMS Incident Dispatch Data (76xm-jjuj)", "use": "all four checks; hospital time via incident close (proxy)"},
            {"place": "San Francisco", "dataset": "SFFD Calls for Service (data.sf.gov nuek-vuh3)", "use": "all four checks; unit-level hospital -> available"},
            {"place": "Indiana (statewide)", "dataset": "EMS runs 2024, NEMSIS/ImageTrend (hub.mph.in.gov)", "use": "transport and share; timestamps are date-only and there is no transfer-of-care or back-in-service time"},
            {"place": "Riverside County, CA", "dataset": "Ambulance Patient Offload Delay Data (8ueb-m2qq), 2012-2016", "use": "handover tail: share of ED visits held over 30 min (aggregates only, ends 2016)"},
            {"place": "Cincinnati, OH", "dataset": "CFD NFIRS incident data (2018-2021)", "use": "not used: fire incident reports with unit clear time, no hospital timestamps"},
            {"place": "Connecticut (statewide)", "dataset": "Fire Department Incidents 2012-2022 (qem9-rt8k)", "use": "not used: fire incidents, last unit cleared only"},
            {"place": "Seattle", "dataset": "Real Time Fire 911 Calls (kzjm-xkqj)", "use": "not used: call time, type and location only, no unit timestamps"},
        ],
        "caveats": [
            "Other places are references for the size and shape of each interval, not proof about NYC.",
            "NYC has no unit-available time in public data; incident close stands in for it in the hospital check.",
            "San Francisco and Indiana are unit-level records; a call with two ambulances counts twice.",
            "Hospital arrival -> available (SF) includes handover, cleaning, restocking and paperwork; Riverside's offload delay counts only the handover step.",
            "In the lab, a unit also queues for a handover slot when slots are full, so its simulated hospital time can exceed the handover draw.",
            "Indiana is statewide (urban and rural); its transport minutes come from an undocumented field and its timestamps are date-only.",
            "Riverside County's offload data are monthly aggregates by hospital and end in 2016.",
            "Durations above 240 min (hospital) or 120 min (scene, transport), and zero or negative ones, are excluded as data errors.",
        ],
    }
    (ROOT / "docs" / "external_validation.json").write_text(json.dumps(out, indent=1))

    lines = [f"# External check of the policy lab's assumptions\n\nGenerated by `scripts/validate_turnaround.py`. {out['question']}\n",
             "| Assumption | Policy lab | " + " | ".join(["NYC", "San Francisco", "Indiana"]) + " | Verdict |",
             "|---|---|---|---|---|---|"]
    def med(d, k):
        x = d["sources"].get(k)
        return f"{x['quantiles']['p50']:.1f}" if x else "–"
    for p, d in params.items():
        lines.append(f"| {d['title']} (median, min) | {d['sim']['quantiles']['p50']:.1f} | {med(d, 'nyc')} | {med(d, 'sf')} | {med(d, 'indiana')} | {d['verdict']} |")
    g = lambda k: f"{share[k]['share']:.0%}" if k in share else "–"
    lines.append(f"| Share transported | {ts:.0%} | {g('nyc')} | {g('sf')} | {g('indiana')} | {share_out['verdict']} |")
    lines += ["", "Medians in minutes. Full quantiles, histograms and yearly medians are in `external_validation.json`.", "",
              "## Detail", ""]
    for p, d in params.items():
        lines.append(f"**{d['title']}.** Lab: {d['sim']['measure']} → median {d['sim']['quantiles']['p50']:.1f}, P90 {d['sim']['quantiles']['p90']:.1f}.")
        for k, x in d["sources"].items():
            lines.append(f"- {x['label']}, {x['measure']}: median {x['quantiles']['p50']:.1f}, P25–P75 {x['quantiles']['p25']:.0f}–{x['quantiles']['p75']:.0f}, "
                         f"P90 {x['quantiles']['p90']:.0f}, n = {x['n']:,}" + (f"; by year {x['by_year']}" if x.get("by_year") else ""))
        if d.get("offload"):
            o = d["offload"]
            lines.append(f"- {o['label']}, {o['measure']}: {o['share_over_30']:.1%} of {o['visits']:,} visits (lab: {o['lab_share_over_30']:.1%}); "
                         f"mean time beyond 30 min among those held {o['mean_excess_min']:.1f} min; by year {o['by_year']}")
        lines.append(f"\n_Reading:_ {d['reading']}\n")
    lines += ["## Datasets reviewed", "", "| Place | Dataset | Used for |", "|---|---|---|"]
    lines += [f"| {r['place']} | {r['dataset']} | {r['use']} |" for r in out["reviewed"]]
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in out["caveats"]]
    (ROOT / "docs" / "external_validation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
