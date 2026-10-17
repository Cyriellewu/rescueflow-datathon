"""P0: Historical EMS performance audit. Where does NYC lose time, before any model is chosen?

Measures FDNY's historical operational performance from the public data (not the accuracy of
FDNY's CAD, which we cannot see): dispatch, travel and response by year, borough and severity;
how much of the rise comes from dispatch vs travel; whether delay tracks call volume; when the
unassigned backlog is largest. Ends with a recommended label target for run_pipeline.py.

    python scripts/performance_audit.py --raw data/raw [--art artifacts]
Writes docs/performance_audit.md, submission/where_time_is_lost.png, <art>/performance_audit.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescueflow.data import load_clean, raw_files  # noqa: E402
from rescueflow.model import _json_safe  # noqa: E402

MIN = 60.0


def q(s, p):
    return float(s.quantile(p) / MIN) if s.notna().any() else float("nan")


def stage_table(d: pd.DataFrame, by) -> pd.DataFrame:
    g = d.groupby(by, observed=True)
    return pd.DataFrame({
        "calls": g.size(),
        "dispatch_med": g["dispatch_s"].median() / MIN, "dispatch_p90": g["dispatch_s"].quantile(0.9) / MIN,
        "travel_med": g["travel_s"].median() / MIN, "travel_p90": g["travel_s"].quantile(0.9) / MIN,
        "response_med": g["response_s"].median() / MIN, "response_p90": g["response_s"].quantile(0.9) / MIN,
        "response_p95": g["response_s"].quantile(0.95) / MIN,
        "held_share": g["held"].mean(),
    }).round(2)


def decompose(d: pd.DataFrame, first, last) -> dict:
    """Change in mean high-acuity response between two years, split into dispatch and travel.
    Only calls with both stages valid, so the parts add up (response = dispatch + travel)."""
    both = d.dropna(subset=["dispatch_s", "travel_s"])
    a, b = both[both["year"] == first], both[both["year"] == last]
    dd = (b["dispatch_s"].mean() - a["dispatch_s"].mean()) / MIN
    dt = (b["travel_s"].mean() - a["travel_s"].mean()) / MIN
    tot = dd + dt
    return {"from": int(first), "to": int(last), "delta_mean_min": tot, "delta_dispatch_min": dd,
            "delta_travel_min": dt, "dispatch_share_of_change": dd / tot if tot else float("nan"),
            "mean_dispatch_min": [a["dispatch_s"].mean() / MIN, b["dispatch_s"].mean() / MIN],
            "mean_travel_min": [a["travel_s"].mean() / MIN, b["travel_s"].mean() / MIN]}


def volume_vs_delay(df: pd.DataFrame) -> dict:
    """Per borough-hour: call volume vs median high-acuity dispatch. Within the same volume decile
    (relative to the borough's own mean), how much does delay still vary?"""
    hour = df["incident_datetime"].dt.floor("h")
    n = df.groupby(["borough", hour], observed=True).size().rename("n")
    hi = df[df["high"]]
    med = hi.groupby(["borough", hi["incident_datetime"].dt.floor("h")], observed=True)["dispatch_s"].median().rename("med")
    t = pd.concat([n, med], axis=1).dropna()
    t["rel"] = t["n"] / t.groupby(level=0)["n"].transform("mean")
    t["decile"] = pd.qcut(t["rel"], 10, labels=False, duplicates="drop")
    by = t.groupby("decile")["med"]
    rows = pd.DataFrame({"rel_volume": t.groupby("decile")["rel"].median(), "median_dispatch_min": by.median() / MIN,
                         "p10_min": by.quantile(0.1) / MIN, "p90_min": by.quantile(0.9) / MIN})
    rows["p90_over_p10"] = rows["p90_min"] / rows["p10_min"]
    rho = t["n"].rank().corr(t["med"].rank())
    return {"spearman_volume_vs_dispatch": float(rho), "deciles": rows.round(2).reset_index().to_dict("records"),
            "median_within_decile_spread": float(rows["p90_over_p10"].median())}


def md_table(t: pd.DataFrame, index=True) -> str:
    """Markdown table without the optional tabulate dependency."""
    t = t.reset_index() if index else t
    fmt = lambda v: f"{v:.2f}" if isinstance(v, float) else str(v)
    rows = [" | ".join(map(str, t.columns)), " | ".join("---" for _ in t.columns)]
    rows += [" | ".join(fmt(v) for v in r) for r in t.itertuples(index=False)]
    return "\n".join(f"| {r} |" for r in rows)


def chart(by_year: pd.DataFrame, by_borough: pd.DataFrame, out: Path, partial_year, synthetic=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.3, 1]})
    for ax, t, labels, title in [
        (axes[0], by_year, [f"{y}{' YTD' if y == partial_year else ''}" for y in by_year.index], "By year"),
        (axes[1], by_borough, [b.replace("RICHMOND / ", "") for b in by_borough.index], "By borough, last 12 months")]:
        x = np.arange(len(t))
        ax.bar(x, t["dispatch_mean"], color="#d1495b", label="Waiting for a unit (dispatch)")
        ax.bar(x, t["travel_mean"], bottom=t["dispatch_mean"], color="#9aa5b1", label="Travel to scene")
        for i, (dv, tv) in enumerate(zip(t["dispatch_mean"], t["travel_mean"])):
            ax.text(i, dv + tv + 0.1, f"{dv + tv:.1f}", ha="center", fontsize=9)
        ax.set_xticks(x, labels, rotation=0 if len(t) <= 6 else 30, fontsize=9)
        ax.set_title(title, fontsize=11, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_ylabel("minutes (mean, severity 1–3)")
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=9, loc="upper right", ncol=2)
    if synthetic:
        fig.text(0.5, 0.5, "SYNTHETIC — NOT FDNY DATA", fontsize=40, color="#d1495b", alpha=0.25,
                 ha="center", va="center", rotation=12, weight="bold")
    fig.suptitle("Where does NYC lose time on life-threatening EMS calls?", fontsize=14, x=0.01, ha="left", weight="bold")
    fig.text(0.01, 0.005, "FDNY EMS Incident Dispatch Data (NYC Open Data 76xm-jjuj). Dispatch + travel as recorded by FDNY; "
             "not the Comptroller's end-to-end measure (excludes call-taking).", fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    fig.savefig(out, dpi=180)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="+", required=True)
    ap.add_argument("--art", type=Path, help="artifacts dir with borough_hour.csv (for backlog by hour)")
    ap.add_argument("--synthetic", action="store_true", help="mark outputs as SYNTHETIC")
    args = ap.parse_args()
    df, _ = load_clean(raw_files(args.raw))
    df["year"] = df["incident_datetime"].dt.year
    hi = df[df["high"]]
    last_ts = df["incident_datetime"].max()
    partial = int(last_ts.year) if last_ts.month < 12 else None
    years = sorted(df["year"].unique())
    full = [y for y in years if y != partial] or years

    by_year = stage_table(hi, "year")
    recent = hi[hi["incident_datetime"] > last_ts - pd.Timedelta(days=365)]
    by_borough = stage_table(recent, "borough")
    sev = stage_table(df[df["incident_datetime"] > last_ts - pd.Timedelta(days=365)], "severity")
    dec = decompose(hi, full[0], years[-1]) if len(years) > 1 else None
    vol = volume_vs_delay(df)

    means = lambda d, by: d.groupby(by, observed=True)[["dispatch_s", "travel_s"]].mean().div(MIN).rename(
        columns={"dispatch_s": "dispatch_mean", "travel_s": "travel_mean"})
    out_png = ROOT / "submission" / "where_time_is_lost.png"
    chart(means(hi.dropna(subset=["dispatch_s", "travel_s"]), "year"),
          means(recent.dropna(subset=["dispatch_s", "travel_s"]), "borough"), out_png, partial, args.synthetic)

    backlog = None
    if args.art and (args.art / "borough_hour.csv").exists():
        t = pd.read_csv(args.art / "borough_hour.csv", parse_dates=["hour"])
        t["hour_of_day"] = t["hour"].dt.hour
        backlog = {"by_hour_of_day": t.groupby("hour_of_day")[["pending_high", "pending_low", "held_pending_low"]]
                   .mean().round(2).reset_index().to_dict("records"),
                   "top_borough_hours": t.assign(dow=t["hour"].dt.day_name().str[:3])
                   .groupby(["borough", "dow", "hour_of_day"])["pending_low"].mean().nlargest(5).round(1)
                   .reset_index().to_dict("records")}

    # which stage to predict: the one behind most of the rise; if the rise is too small to say,
    # the one whose hourly median varies more (a stage that never moves can't be warned about)
    hour = hi["incident_datetime"].dt.floor("h")
    hourly = hi.groupby(["borough", hour], observed=True)[["dispatch_s", "travel_s"]].median()
    cv = (hourly.std() / hourly.mean()).rename({"dispatch_s": "dispatch", "travel_s": "travel"})
    if dec and abs(dec["delta_mean_min"]) >= 0.25 and np.isfinite(dec["dispatch_share_of_change"]):
        target, why = ("dispatch" if dec["dispatch_share_of_change"] >= 0.5 else "travel"), "share of the rise"
    else:
        target, why = cv.idxmax(), "hour-to-hour variability (rise too small to attribute)"

    res = {"data_source": "SYNTHETIC" if args.synthetic else "FDNY", "rows": len(df), "high_acuity_rows": len(hi),
           "range": [str(df["incident_datetime"].min()), str(last_ts)], "partial_year": partial,
           "by_year_high": by_year.reset_index().to_dict("records"),
           "by_borough_high_last_12m": by_borough.reset_index().to_dict("records"),
           "by_severity_last_12m": sev.reset_index().to_dict("records"),
           "decomposition": dec, "volume_vs_delay": vol, "backlog": backlog, "recommended_target": target,
           "target_reason": why, "hourly_cv": cv.round(3).to_dict()}
    if args.art:
        args.art.mkdir(parents=True, exist_ok=True)
        (args.art / "performance_audit.json").write_text(json.dumps(_json_safe(res), indent=2, default=str))

    md = ["# RescueNYC — Historical EMS performance audit (P0)\n"]
    # keep a hand-written "## Findings" block (answers to the P0 gate questions) across reruns
    md_path = ROOT / "docs" / "performance_audit.md"
    if md_path.exists():
        found = re.search(r"(## Findings.*?)(?=\n## |\nGenerated by )", md_path.read_text(), re.S)
        if found:
            md.append(found.group(1).rstrip() + "\n")
    if args.synthetic:
        md.append("> **SYNTHETIC PLACEHOLDER.** Numbers come from the test simulator. Do not quote them.\n")
    md += [f"Generated by `scripts/performance_audit.py`. {len(df):,} calls, {res['range'][0][:10]} → {res['range'][1][:10]}; "
           f"severity 1–3 = {len(hi):,}. This measures FDNY's historical operational performance from public "
           "records; it is not an accuracy score for FDNY's CAD, whose internal predictions and unit states are not public. "
           "Dispatch + travel as FDNY records them, not the Comptroller's end-to-end time.\n",
           "![Where time is lost](../submission/where_time_is_lost.png)\n", "## 1. High-acuity (severity 1–3) by year (minutes)\n",
           md_table(by_year), ""]
    if dec:
        md += ["## 2. Where did the added time come from?\n",
               f"Mean high-acuity response changed by **{dec['delta_mean_min']:+.2f} min** from {dec['from']} to {dec['to']}: "
               f"dispatch {dec['delta_dispatch_min']:+.2f} min, travel {dec['delta_travel_min']:+.2f} min "
               + (f"(dispatch = {dec['dispatch_share_of_change']:.0%} of the change; calls with both stages valid).\n"
                  if abs(dec["delta_mean_min"]) >= 0.25 else "— too small a change to attribute to either stage.\n")]
    md += ["## 3. By borough, last 12 months (severity 1–3, minutes)\n", md_table(by_borough), "",
           "## 4. By severity, last 12 months (all calls, minutes)\n",
           "If low-acuity calls wait far longer and are held more, the queue absorbs pressure there first "
           "(the severity-cascade hypothesis).\n", md_table(sev), "",
           "## 5. Is delay just demand?\n",
           f"Spearman rank correlation between a borough-hour's call volume and its median high-acuity dispatch "
           f"time: **{vol['spearman_volume_vs_dispatch']:.2f}**. Within the same volume decile (relative to each "
           f"borough's mean), the slowest 10% of hours are a median **{vol['median_within_decile_spread']:.1f}×** "
           "the fastest 10%. Volume alone leaves most of the variation unexplained, which is what the queue state "
           "is meant to capture.\n",
           md_table(pd.DataFrame(vol["deciles"]), index=False), ""]
    if backlog:
        md += ["## 6. When is the unassigned backlog largest?\n",
               md_table(pd.DataFrame(backlog["by_hour_of_day"]), index=False), "",
               "Top borough × weekday × hour by mean low-acuity calls waiting:\n",
               md_table(pd.DataFrame(backlog["top_borough_hours"]), index=False), ""]
    md += ["## Decision\n",
           f"Recommended label target: **`{target}`**, by {why} "
           f"(hour-to-hour CV: dispatch {cv['dispatch']:.2f}, travel {cv['travel']:.2f}). "
           f"`python scripts/run_pipeline.py --target {target} ...`. "
           "Rule: predict the stage that accounts for most of the rise in mean high-acuity response; check it against "
           "sections 3–5 before committing, and record the choice in PLAN.md.\n"]
    (ROOT / "docs" / "performance_audit.md").write_text("\n".join(md))
    print(f"wrote docs/performance_audit.md and {out_png.relative_to(ROOT)}; recommended target: {target} ({why})")
    if dec:
        print(f"  Δ mean high-acuity response {dec['delta_mean_min']:+.2f} min "
              f"(dispatch {dec['delta_dispatch_min']:+.2f}, travel {dec['delta_travel_min']:+.2f})")
    print(f"  volume vs delay rho {vol['spearman_volume_vs_dispatch']:.2f}; within-decile p90/p10 "
          f"{vol['median_within_decile_spread']:.1f}x")


if __name__ == "__main__":
    main()
