"""Small historical aggregates, independent of the model/replay installed on a laptop."""
import pandas as pd


def historical_profiles(arrivals, departures, start, end):
    """Rebuild hourly means from event counts without downloading incident-level records.

    Matches stream.replay_borough: consume events strictly before the snapshot hour.
    A timestamp on an hour boundary belongs to that hour's bin and is consumed at
    the following snapshot. Arrivals and departures cancel zero-duration calls.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    output = {"calls_by_hour": {}, "pending_low_by_hour": {}}
    boroughs = sorted({r["borough"] for r in arrivals})

    def counts(rows, borough, field):
        series = pd.Series(0.0, index=hours)
        for r in rows:
            if r["borough"] != borough:
                continue
            hour = pd.Timestamp(r["day"]) + pd.Timedelta(hours=int(r["hod"]))
            if hour in series.index:
                series.loc[hour] += int(r[field])
        return series

    for b in boroughs:
        calls = counts(arrivals, b, "n_calls")
        queue = (counts(arrivals, b, "n_low") - counts(departures, b, "n_low")).cumsum().shift(1, fill_value=0)
        if (queue < 0).any():
            raise ValueError(f"negative reconstructed queue for {b}")
        for metric, values in [("calls_by_hour", calls), ("pending_low_by_hour", queue)]:
            grouped = values.groupby([hours.year, hours.hour]).mean().round(2)
            output[metric][b] = {
                str(year): [float(grouped.loc[year, h]) for h in range(24)]
                for year in sorted(hours.year.unique())
            }
    return output
