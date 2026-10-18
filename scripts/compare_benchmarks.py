"""Side-by-side benchmark table: LinuxONE (s390x) vs the laptop, from the two benchmark.json files.
Honest framing: absolute replay throughput is a core-count story; the operational number is per-request scoring
latency, and the real-time multiple says whether either machine is fast enough (both are, by a wide margin)."""
import argparse
import json
from pathlib import Path

NYC_EVENTS_PER_S = 1.62e6 * 5 / (365 * 24 * 3600)   # ~1.6 M incidents a year, five replay events each (create, assign, on scene, hospital, close)

ap = argparse.ArgumentParser()
ap.add_argument("--vm", type=Path, default=Path("submission/evidence/benchmark_s390x.json"))
ap.add_argument("--laptop", type=Path, default=Path("submission/evidence/benchmark_laptop_arm64.json"))
ap.add_argument("--out", type=Path, default=Path("submission/evidence/benchmark_compare.md"))
a = ap.parse_args()
vm, lt = json.loads(a.vm.read_text()), json.loads(a.laptop.read_text())

def row(label, key, fmt="{:,.0f}", lower_better=False):
    v, l = vm.get(key), lt.get(key)
    if v is None or l is None:
        return f"| {label} | {fmt.format(v) if v is not None else 'n/a'} | {fmt.format(l) if l is not None else 'n/a'} | |"
    ratio = (l / v) if lower_better else (v / l)
    return f"| {label} | {fmt.format(v)} | {fmt.format(l)} | {ratio:.2f}× |"

lines = ["# Benchmark: IBM LinuxONE (s390x) beside the laptop", "",
         f"LinuxONE: {vm.get('cores', 3)} vCPU, Ubuntu 24.04, native Python (no container). Laptop: {lt.get('cores')} cores, {lt.get('machine')}.", "",
         "| Measure | LinuxONE | Laptop | LinuxONE ÷ laptop |", "|---|---|---|---|",
         row("Replay, one core (events/s)", "replay_events_per_s_single_core"),
         row("Replay, all cores (events/s)", "replay_events_per_s"),
         row("Per-request scoring p50 (ms)", "score_p50_ms", "{:.2f}", lower_better=True),
         row("Per-request scoring p99 (ms)", "score_p99_ms", "{:.2f}", lower_better=True),
         row("Batch scoring (rows/s)", "batch_rows_per_s"), ""]
rt_vm, rt_lt = vm["replay_events_per_s"] / NYC_EVENTS_PER_S, lt["replay_events_per_s"] / NYC_EVENTS_PER_S
lines += [f"New York produces about {NYC_EVENTS_PER_S:.2f} dispatch events a second. Replay runs {rt_vm:,.0f}× faster than real time on LinuxONE and {rt_lt:,.0f}× on the laptop: a full year of the record in {365*24*3600/rt_vm:.0f} s and {365*24*3600/rt_lt:.0f} s.", "",
          "Reading: per-request scoring, the path a supervisor's screen uses, is as fast on LinuxONE as on the laptop. Replay and batch throughput follow core count; on three vCPUs the machine is still millions of times faster than the event stream it would watch, which is what makes 20-seed simulation protocols and 21-year audits practical. No accelerator path was measured; inference is on CPU."]
a.out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
