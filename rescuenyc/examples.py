"""Real examples pulled out of the results: how a label is decided, and hour-by-hour segments where
the model and the simple rule are compared against what actually happened."""
import numpy as np
import pandas as pd

FULL = "Full model (trees, 20 inputs)"


def _fmt_s(x):
    return "–" if pd.isna(x) else f"{x:.0f}"


def label_examples(table, borough="BROOKLYN", dates=("2026-09-11", "2026-09-18", "2026-09-25"), hour=20):
    out = []
    t = table[table["borough"] == borough].set_index("hour")
    for d in dates:
        T = pd.Timestamp(f"{d} {hour:02d}:00")
        past = [T - pd.Timedelta(weeks=k) for k in range(8, 0, -1)]
        vals = [t["low_dispatch_median_s"].get(p, np.nan) for p in past]
        row = t.loc[T]
        verdict = "STRESSED (1)" if row["stressed"] == 1 else "normal (0)" if row["stressed"] == 0 else "not judged"
        when = f"{T:%a %Y-%m-%d %H}:00–{hour + 1:02d}:00"
        out.append(f"**{borough.title()}, {when}**\n\n"
                   f"| | |\n|---|---|\n"
                   f"| Same hour, previous 8 weeks (median low-acuity dispatch wait, s) | {', '.join(_fmt_s(v) for v in vals)} |\n"
                   f"| Threshold = 80th percentile of those | {_fmt_s(row['threshold_s'])} s |\n"
                   f"| This hour ({int(row['low_calls_with_wait'])} low-acuity calls) | {_fmt_s(row['low_dispatch_median_s'])} s |\n"
                   f"| Answer | **{verdict}** |\n")
    return "\n".join(out)


def briefing(row, p, alert):
    """The note a supervisor would see. Template only: every number comes from the row."""
    band = "ALERT" if alert else "normal"
    lines = [f"{row['borough'].title()} {row['hour']:%a %H:00} — stress risk next hour {p:.0%} ({band})."]
    lines.append(f"Waiting for a unit now: {int(row['pending_low'])} low-acuity ({int(row['held_pending_low'])} held), "
                 f"{int(row['pending_high'])} high-acuity; {int(row['pending_low_over_10min'])} waiting > 10 min; "
                 f"{int(row['units_at_hospital'])} units at hospitals.")
    if pd.notna(row["recent_low_dispatch_s"]) and pd.notna(row["low_dispatch_vs_usual"]):
        lines.append(f"Last hour low-acuity dispatch median {row['recent_low_dispatch_s'] / 60:.1f} min "
                     f"({row['low_dispatch_vs_usual']:.1f}x usual).")
    lines.append("Suggest: prepare cross-borough support / reserve units; a supervisor decides." if alert
                 else "Suggest: no action.")
    return " ".join(lines)


def _segment(test, scores, alerts, center, before=4, after=5):
    b, T = test.loc[center, "borough"], test.loc[center, "hour"]
    w = test[(test["borough"] == b) & (test["hour"] >= T - pd.Timedelta(hours=before))
             & (test["hour"] <= T + pd.Timedelta(hours=after))]
    rows = ["| Hour T | Waiting low-acuity (held) | Waiting > 10 min | Units at hospital | Rule: stressed now? | Model risk | Model alert | Actual median wait (s) | Threshold (s) | **Actual** |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in w.iterrows():
        actual = "**STRESSED**" if r["stressed"] == 1 else "normal"
        rule = "yes" if r["stressed_now"] == 1 else "no" if r["stressed_now"] == 0 else "–"
        mark = " ◀" if i == center else ""
        k = test.index.get_loc(i)
        rows.append(f"| {r['hour']:%a %m-%d %H:00}{mark} | {int(r['pending_low'])} ({int(r['held_pending_low'])}) | "
                    f"{int(r['pending_low_over_10min'])} | {int(r['units_at_hospital'])} | {rule} | "
                    f"{scores[FULL][k]:.0%} | {'🔴' if alerts[FULL][k] else '·'} | "
                    f"{_fmt_s(r['low_dispatch_median_s'])} | {_fmt_s(r['threshold_s'])} | {actual} |")
    return b, T, "\n".join(rows)


def pick_segments(test, scores, alerts, borough="BROOKLYN"):
    """Three honest cases from the test months: a caught onset, a missed onset, a false alarm."""
    p, a = scores[FULL], alerts[FULL]
    y = test["stressed"].to_numpy()
    # clean onset: rule says "not stressed now" AND, in hindsight, the previous hour really was normal
    onset = (test["stressed_now"].to_numpy() == 0) & (test["stressed_prev_hindsight"].to_numpy() == 0) & (y == 1)
    quiet_before = test["stressed_prev_hindsight"].to_numpy() == 0
    in_b = test["borough"].to_numpy() == borough
    cases = [
        ("Caught: a new episode starts, the model warned, the rule could not", onset & a & in_b, p),
        ("Missed: a new episode starts, the model stayed quiet", onset & ~a & in_b, test["low_dispatch_median_s"].to_numpy()),
        ("False alarm: the model warned, the hour stayed normal", a & (y == 0) & quiet_before & in_b, p),
    ]
    out = []
    for title, mask, rank in cases:
        if not mask.any():
            continue
        pos = np.flatnonzero(mask)[np.nanargmax(np.asarray(rank, float)[mask])]
        center = test.index[pos]
        b, T, tbl = _segment(test, scores, alerts, center)
        note = briefing(test.loc[center], p[pos], a[pos])
        out.append(f"### {title}\n\n{b.title()}, around {T:%a %Y-%m-%d %H:00} (◀ = the hour in question)\n\n{tbl}\n\n"
                   f"Briefing at ◀: _{note}_\n")
    return "\n".join(out), cases


def plot_window(test, scores, alerts, borough, start, days, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m = (test["borough"] == borough) & (test["hour"] >= start) & (test["hour"] < start + pd.Timedelta(days=days))
    w = test[m]
    idx = [test.index.get_loc(i) for i in w.index]
    p = scores[FULL][idx]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    for h, s in zip(w["hour"], w["stressed"]):
        if s == 1:
            ax.axvspan(h, h + pd.Timedelta(hours=1), color="#f4a261", alpha=0.35, lw=0)
    ax.plot(w["hour"], p, color="#264653", lw=1.6, label="Model risk for the next hour")
    al = alerts[FULL][idx]
    ax.scatter(w["hour"][al], p[al], color="#e63946", s=18, zorder=3, label="Model alert (top 10%)")
    ax.set_ylim(0, 1)
    ax.set_ylabel("risk")
    ax.set_title(f"{borough.title()}: model risk vs what happened (orange = hour was actually stressed)")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
