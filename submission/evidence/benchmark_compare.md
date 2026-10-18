# Benchmark: IBM LinuxONE (s390x) beside the laptop

LinuxONE: 3 vCPU, Ubuntu 24.04, native Python (no container). Laptop: 10 cores, arm64.

| Measure | LinuxONE | Laptop | LinuxONE ÷ laptop |
|---|---|---|---|
| Replay, one core (events/s) | n/a | 2,649,142 | |
| Replay, all cores (events/s) | 358,373 | 6,820,531 | 0.05× |
| Per-request scoring p50 (ms) | 1.60 | 1.71 | 1.07× |
| Per-request scoring p99 (ms) | 2.66 | 3.53 | 1.33× |
| Batch scoring (rows/s) | 458,794 | 703,627 | 0.65× |

New York produces about 0.26 dispatch events a second. Replay runs 1,395,266× faster than real time on LinuxONE and 26,554,601× on the laptop: a full year of the record in 23 s and 1 s.

Reading: per-request scoring, the path a supervisor's screen uses, is as fast on LinuxONE as on the laptop. Replay and batch throughput follow core count; on three vCPUs the machine is still millions of times faster than the event stream it would watch, which is what makes 20-seed simulation protocols and 21-year audits practical. No accelerator path was measured; inference is on CPU.
