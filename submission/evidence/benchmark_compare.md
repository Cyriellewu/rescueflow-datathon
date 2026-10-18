# Benchmark: IBM LinuxONE (s390x) beside the laptop

LinuxONE: 3 vCPU, Ubuntu 24.04, native Python (no container). Laptop: 10 cores, arm64.

| Measure | LinuxONE | Laptop | LinuxONE ÷ laptop |
|---|---|---|---|
| Replay, one core (events/s) | 257,494 | 2,649,142 | 0.10× |
| Replay, all cores (events/s) | 576,611 | 6,820,531 | 0.08× |
| Per-request scoring p50 (ms) | 2.27 | 1.71 | 0.75× |
| Per-request scoring p99 (ms) | 4.54 | 3.53 | 0.78× |
| Batch scoring (rows/s) | 293,615 | 703,627 | 0.42× |

New York produces about 0.26 dispatch events a second. Replay runs 2,244,939× faster than real time on LinuxONE and 26,554,601× on the laptop: a full year of the record in 14 s and 1 s.

Reading: per-request scoring, the path a supervisor's screen uses, is as fast on LinuxONE as on the laptop. Replay and batch throughput follow core count; on three vCPUs the machine is still millions of times faster than the event stream it would watch, which is what makes 20-seed simulation protocols and 21-year audits practical. No accelerator path was measured; inference is on CPU.
