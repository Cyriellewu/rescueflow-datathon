# Where RescueNYC would sit: next to the EMS CAD, not inside it

## The moment (sources checked Oct 17 2026)

- FDNY runs separate Fire and EMS computer-aided dispatch (CAD) systems. FireCAD replaced the
  45-year-old STARFIRE in August 2021 ([StateScoop](https://statescoop.com/?p=42326),
  [Business Wire](https://www.businesswire.com/news/home/20210805005682/en/Accenture-Helps-Fire-Department-of-New-York-City-Launch-New-Dispatch-System/)).
- EMS CAD was last updated in 2017, was not part of the FireCAD rebuild, and had three outages
  totalling about 4.5 hours in one reported period
  ([The Chief-Leader](https://thechiefleader.com/stories/dispatch-system-outages-spotlight-understaffing-union-leaders-say,49464)).
- March 2025, City Council Fire & Emergency Management committee: the Commissioner said the
  mayor's office gave FDNY the green light to build a new EMS CAD platform on FireCAD, calling the
  current one end-of-life; the same hearing had a segment on FDNY's plans for AI integration
  ([citymeetings.nyc](https://citymeetings.nyc/city-council/2025-03-14-1000-am-committee-on-fire-and-emergency-management/chapter/fdnys-plans-for-technological-improvements-and-ai-integration)).
- August 28 2026: FDNY awarded Peraton a sole-source **$10,625,538** EMS CAD maintenance contract
  to keep the current system running ([City Record](https://a856-cityrecord.nyc.gov/RequestDetail/20260820026)).
- **Not yet verified:** a November 2027 go-live date for the new EMS CAD (said to come from a
  September 2026 hearing), and a 1977 start date for EMS CAD. Don't put either in the video until
  someone reads the primary source.

## What that means for us

New York is specifying its next EMS dispatch system now. RescueNYC is a working prototype of an
**analytics layer that a new CAD could feed**: it doesn't dispatch, doesn't touch the call
workflow, and needs nothing from the CAD vendor beyond the event stream every CAD already
produces. It is a design for the AI layer around the system of record, not a pitch for FDNY to
adopt our code.

## Event contract

The replay engine (`rescueflow/stream.py`) already consumes exactly these events, reconstructed
from the public dataset's timestamps. A live CAD would send the same events instead.

| CAD event | Field in the public data | What RescueNYC does with it |
|---|---|---|
| `call_created` (borough, initial severity, held flag when known) | `incident_datetime`, `initial_severity_level_code` | add to the borough's waiting queue |
| `unit_assigned` | `first_assignment_datetime` | remove from the queue; dispatch delay becomes known |
| `unit_on_scene` | `first_on_scene_datetime` | travel time becomes known |
| `unit_at_hospital` | `first_hosp_arrival_datetime` | add to the at-hospital count |
| `call_closed` | `incident_close_datetime` | leave the queue (cancelled) or the hospital count |

```json
{"event": "unit_assigned", "call_id": "…", "borough": "BROOKLYN", "severity": 2, "ts": "2026-02-14T18:07:31"}
```

Hourly, the engine snapshots state, the model scores each borough, and the API serves the alert.
Nothing here needs patient details; the stream carries borough, severity and timestamps only.

## Why on LinuxONE

- **Next to the system of record.** Dispatch is a transactional, always-on workload; scoring
  beside it avoids shipping call events to another cloud.
- **Reliability.** The current EMS CAD's outages are part of the public record. An analytics
  layer for it should not add a less reliable dependency.
- **Measured, not asserted.** Replay throughput and scoring latency on the VM come from
  `/benchmark`. NYC's EMS volume is roughly 1.5M calls a year, about 3 events a minute per
  borough; the benchmark shows how much headroom that leaves.

Do not claim FDNY's CAD runs on IBM Z, that FDNY plans to use RescueNYC, or any go-live date we
haven't verified.
