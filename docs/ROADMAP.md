# RescueNYC — Roadmap after the datathon

Principle: what the public record contains is used as data; what it does not contain is a
labelled simulation assumption, never presented as an observation. Five layers, each with its
own provenance. Status column is as of the Oct 18 submission.

| Layer | Contents | Status |
|---|---|---|
| 1. Raw | FDNY EMS Incident Dispatch (76xm-jjuj), 18 of 31 columns, 2016–2026 on the laptop, 2023–2026 on the VM | done |
| 2. Historical feature store | borough × hour: queue state, held calls, hospital load, demand lags, recent durations, labels | done (hourly) |
| 3. Spatial reference | ZIP boundaries, NYS hospital locations, OSM road graph, NYC DOT traffic speeds | not started |
| 4. Simulation state | scenario fleet per borough, dispatch queue, hospital handover, reserves; counts only, no coordinates | done (borough grain) |
| 5. Experiments and evaluation | model ladder with CIs, two policy-lab experiments, stress sensitivity | done |

## What the record cannot give, and how we treat it

Ambulance positions, unit availability, ALS/BLS status, incident street addresses and actual
routes are not in any public NYC dataset. They are not a missing download; they are unobserved.
Everything that needs them lives in the simulator, is labelled SIMULATION, and is calibrated to
the real wait-time distributions rather than claimed as FDNY's state.

## Next increments, in order

1. **Re-fetch with four more columns**: `incident_id`, `initial_call_type`, `zipcode`,
   `incident_dispatch_area`. Keep the id so later columns can be joined safely; re-pull whole
   months rather than merging on timestamps. One line in `scripts/fetch_data.py`, ~12 min for
   2023–2026.
2. **Cross-borough features**: neighbouring boroughs' pending and held counts at T. Motivated by
   the finding that stress is local (49% of stressed hours involve one borough) while slack
   usually exists next door. One feature group, one rerun of the model ladder.
3. **Finer grain**: 30-minute cutoffs first (no new data), then FDNY dispatch areas (~30 zones,
   needs increment 1). Label support thins quickly; check `n_low_valid` per cell before trusting it.
4. **Historical traffic**: check NYC DOT speed coverage for 2023–2026 before downloading the
   110 M rows; if adequate, build a segment × hour-of-week profile and use it to separate
   "roads slower" from "units farther away" in the travel-time rise.
5. **Spatial simulation layer**: sample incident points inside ZIP polygons, route a scenario
   fleet on the OSM graph with traffic-adjusted speeds calibrated to FDNY travel times, and
   expose per-unit state tables (`simulated_vehicles`, `simulation_snapshots`). Visualisation
   and policy testing only; it cannot be scored against FDNY's actual dispatch decisions.
6. **Dashboard**: a pending-queue column per borough (needs `initial_call_type`), then a
   ZIP-level incident map clearly separated from the simulated fleet view.

## Two targets, kept separate

- Primary: next-hour median dispatch wait of severity 4–8 calls above the borough's trailing
  p80. This is where FDNY's queueing lands (P0 audit §4, Findings 5–11).
- Secondary: the same for severity 1–3. Reported as the "FDNY protects severe calls" result;
  little signal remains to predict there.

Prediction metrics (`docs/evaluation.md`), simulation metrics (`artifacts/policy_lab*.json`) and
experiment parameters (scenario, demand multiplier, shock, seeds, model version) stay in separate
tables so no simulated number can be mistaken for an observed one.
