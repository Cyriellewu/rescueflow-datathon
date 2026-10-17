# Cross-borough rebalancing plan

`rescueflow/rebalance.py` turns the early-warning output into one plan for all five boroughs: how many
**free** units each borough should send to each other borough this hour. It is decision support built
on estimates, not an instruction to dispatchers.

## Model

Per borough: `capacity = fleet x horizon / cycle` calls, `demand = waiting + expected arrivals x (1 + 0.5 x risk)`.
Supply is a flow, not "units free now": a borough taking ~40 calls an hour turns a unit over about hourly, so
its idle units vanish in minutes; what matters is whether fleet x horizon / cycle covers demand.

One small integer program (HiGHS via `scipy.optimize.milp`) over all 20 directed pairs maximises
severity-weighted calls served (severity 1-3 weigh 10, 4-8 weigh 1), minus a fixed and a per-minute cost per unit
moved, plus a penalty when a borough's headroom falls below `1.0 x sqrt(demand)` calls (square-root staffing).
Constraints: a borough sends at most its free units minus one; a unit that needs T minutes counts
`1 - T/horizon` for the receiver; pairs slower than 40 min are not offered. Every borough can donate and
receive, so there is no fixed donor. Milliseconds per solve.

Transfer times come from `spatial/spatial_data` (busiest ZIP of each borough through the fitted response model);
flat 14 min if that layer is absent. Only the Bronx-Manhattan pair is under ~25 min.

## Where it runs

- `GET /plan?at=<hour>`: queue and expected arrivals from the replay table, risk from the warning model.
- Dashboard, Early warning tab: "Dispatch plan" panel under the borough cards.
- Simulator policies `rebalance` and `rebalance_ai` (`rescueflow/des.py`), Experiment 3 of
  `scripts/run_policy_lab.py --rebalance [--transfer spatial|flat]`.

## What is observed and what is estimated

Observed: queue sizes, arrivals, hospital load. **Not published:** fleet and free units. The estimates are
`fleet` = 99th percentile of calls with a unit assigned and not yet closed, over the last training year
(`active_responses` in `borough_hour.csv`, stored as `fleet_est` in `meta.json`), and `free = fleet - active now`.
Incident close is a proxy for the unit being free. Re-run `scripts/run_pipeline.py` to add both to older artifacts.

## Evidence so far (SYNTHETIC calls; not a real-data result)

Experiment 3, 20 seeds, Brooklyn handover shock, fleets calibrated to wait times, both transfer matrices:
about 225-250 units relocated per week, **no detectable change** in low-acuity mean or P90 wait, worst-borough
low-acuity P90 or high-acuity wait (all 95% intervals include zero; spatial: worst-borough low P90 +2.2 min,
-6.5 to +10.9). Passing the warning risk into the plan (`rebalance_ai`) moved more units and did not help either.
In an unpublished 3-seed exploration with uneven demand and uncalibrated fleets, the worst borough's low-acuity
P90 fell (127 to 68 min, 733 to 511 at 1.2x demand) only when the planner was allowed ~2 moves an hour; with
a higher move penalty the gain vanished. That is a hypothesis to test on real data, not a finding.
The simulator has no FDNY-style hold rule and is far slacker than the real system (PLAN.md, diagnosis), so
a real-data run on the VM is the test that matters.
