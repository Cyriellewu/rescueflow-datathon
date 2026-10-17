"""Per-unit timelines from the simulator's event log (rescueflow/des.py, `log_events=True`).

The dashboard animates ambulances; this turns `sim.log` into one contiguous sequence of states per unit so an
animated vehicle can be bound to a real simulated unit. SIMULATION: the simulator has no positions, only the
borough a unit is in or heading to, so a segment carries a borough, never coordinates.

Schema (`unit_tracks`):
    {"t0": "<wall clock of sim minute 0>", "end_min": <last minute>, "time_unit": "min" | "0.1 min",
     "states": [...], "boroughs": [...], "compact": bool,
     "units": {uid: {"home": borough, "reserve": bool,
                     "segments": [[start, end, state, borough, call_or_null], ...]}},
     "calls": {idx: {"t": created, "borough": ..., "severity": ..., "assign": min|null,
                     "on_scene": min|null, "unit": uid|null}}}
compact=False: times are minutes with 1 decimal, state and borough are the names.
compact=True (the lab's export, about half the size): times are integer tenths of a minute, state and borough
are indices into "states" and "boroughs"; `expand()` turns such a block back into the named form.

States: idle, to_scene (dispatch -> at scene, dispatcher processing included), on_scene, to_hospital,
handover_wait (at the hospital, no bay free), handover, returning (a free unit relocating between boroughs:
it is on the road, unavailable until it arrives), off (reserve activation ended). Segments are contiguous per
unit: each starts where the previous one ended. A segment shorter than the time resolution is dropped after
rounding; the next one still starts where the last ended.
"""
STATES = ["idle", "to_scene", "on_scene", "to_hospital", "handover_wait", "handover", "returning", "off"]


def unit_tracks(sim, compact: bool = False, calls: bool = True) -> dict:
    if sim.log is None:
        raise ValueError("run the Sim with log_events=True")
    tenths = compact
    boroughs = sorted(sim.sc.units)
    code = {**{s: i for i, s in enumerate(STATES)}, **{b: i for i, b in enumerate(boroughs)}} if compact else {}
    name = (lambda x: code[x]) if compact else (lambda x: x)
    events = sorted(enumerate(sim.log), key=lambda e: (e[1]["sim_min"], e[0]))  # future-stamped emits in time order
    end = max((e["sim_min"] for _, e in events), default=0.0)
    if sim.calls:
        end = max(end, max(c[0] for c in sim.calls))

    def q(t):  # time quantiser: tenths of a minute as int, or the same tenths as minutes with 1 decimal
        k = int(round(float(t) * 10))
        return k if tenths else k / 10

    units = {}      # uid -> {"home", "reserve", "segments", "_cur": [start, state, borough, call]}
    for uid, home in enumerate(sim.home):
        reserve = bool(sim.expires[uid] < float("inf"))
        units[uid] = {"home": home, "reserve": reserve, "segments": [],
                      "_cur": None if reserve else [0.0, "idle", home, None]}  # reserve units start at activation
    call_rows = {}

    def switch(uid, t, state, borough, call):
        u = units[uid]
        cur = u["_cur"]
        if cur is not None:
            s, e = q(cur[0]), q(t)
            if e > s:  # a segment empty after rounding is dropped; the next one still starts where the last ended
                u["segments"].append([s, e, name(cur[1]), name(cur[2]), cur[3]])
        u["_cur"] = None if state is None else [t, state, borough, call]

    for _, e in events:
        k, t, uid = e["event"], e["sim_min"], e.get("unit")
        if k == "call":
            if calls:
                call_rows[e["call"]] = {"t": q(t), "borough": e["borough"], "severity": e["severity"],
                                        "assign": None, "on_scene": None, "unit": None}
        elif k == "dispatch":
            switch(uid, t, "to_scene", e["borough"], e["call"])
        elif k == "assign":
            if calls and e["call"] in call_rows:
                call_rows[e["call"]].update(assign=q(t), unit=uid)
        elif k == "on_scene":
            switch(uid, t, "on_scene", e["borough"], e["call"])
            if calls and e["call"] in call_rows:
                call_rows[e["call"]]["on_scene"] = q(t)
        elif k == "leave_scene":
            if e.get("transport"):
                switch(uid, t, "to_hospital", e["borough"], e["call"])
        elif k == "handover_wait":
            switch(uid, t, "handover_wait", e["borough"], e["call"])
        elif k == "handover_start":
            switch(uid, t, "handover", e["borough"], e["call"])
        elif k == "free":
            if not e.get("off"):
                switch(uid, t, "idle", e["borough"], None)
        elif k == "off":
            switch(uid, t, "off", e["borough"], None)
        elif k == "reserve_unit":
            switch(uid, t, "idle", e["borough"], None)
        elif k == "relocate":
            switch(uid, t, "returning", e["dst"], None)
        elif k == "arrive_relocated":
            switch(uid, t, "idle", e["borough"], None)
        # arrive_hospital, handover_done, activate_reserve: no state change of their own (the next event has it)

    for uid in units:
        switch(uid, end, None, None, None)
        del units[uid]["_cur"]
    out = {"t0": str(sim.t0), "end_min": q(end), "time_unit": "0.1 min" if tenths else "min", "states": STATES,
           "boroughs": boroughs, "compact": compact, "units": units}
    if calls:
        out["calls"] = call_rows
    return out


def expand(tracks: dict) -> dict:
    """A compact block (integer tenths, indexed names) in the named, float-minute form."""
    if not tracks.get("compact"):
        return tracks
    st, bo = tracks["states"], tracks["boroughs"]
    units = {uid: {**u, "segments": [[s / 10, e / 10, st[k], bo[b], c] for s, e, k, b, c in u["segments"]]}
             for uid, u in tracks["units"].items()}
    out = {**tracks, "compact": False, "time_unit": "min", "end_min": tracks["end_min"] / 10, "units": units}
    if "calls" in tracks:
        out["calls"] = {i: {**c, **{k: (None if c[k] is None else c[k] / 10) for k in ("t", "assign", "on_scene")}}
                        for i, c in tracks["calls"].items()}
    return out


def check_contiguous(tracks: dict) -> None:
    """Raise if any unit's segments are not back to back (used by the tests)."""
    tracks = expand(tracks)
    for uid, u in tracks["units"].items():
        segs = u["segments"]
        for a, b in zip(segs, segs[1:]):
            if a[1] != b[0]:
                raise AssertionError(f"unit {uid}: segment ends at {a[1]} but the next starts at {b[0]}")
        for s in segs:
            if s[2] not in STATES or s[1] <= s[0]:
                raise AssertionError(f"unit {uid}: bad segment {s}")
