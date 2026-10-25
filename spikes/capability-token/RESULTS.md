# D6 verifier benchmark result

Measured 2026-10-25 11:15:23 UTC with spike version 0.1.0 and token format v1. The source was uncommitted, so the raw JSON records `source_revision: null`; it includes SHA-256 hashes for the implementation and benchmark source files.

## Environment and workload

- Windows 11 build 26200, CPython 3.12.8, 64-bit AMD64
- Processor reported by Python: AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD; 12 logical CPUs; 16,487,870,464 bytes RAM
- HMAC-SHA256, 33-byte benchmark issuer key, eight root resources, four actions, 5,000,000 micro-credits
- Single-threaded successful full-chain verification; `perf_counter_ns` surrounds only `verify`
- 200 warmups and 2,000 measured verifications at each depth, run sequentially from depth 1 to 8
- Raw per-operation nanosecond samples and full metadata: [`windows-python312-2000x200.json`](results/windows-python312-2000x200.json)

| Caveat depth | Token bytes | Median (µs) | p95 (µs) | p99 (µs) |
|---:|---:|---:|---:|---:|
| 1 | 797 | 59.30 | 68.80 | 88.40 |
| 2 | 874 | 67.80 | 77.80 | 96.90 |
| 3 | 952 | 75.50 | 85.60 | 98.40 |
| 4 | 1,029 | 81.40 | 93.40 | 110.50 |
| 5 | 1,106 | 88.70 | 102.60 | 122.10 |
| 6 | 1,184 | 96.60 | 111.70 | 166.50 |
| 7 | 1,261 | 102.40 | 116.50 | 156.20 |
| 8 | 1,338 | 111.30 | 161.50 | 246.50 |

The depth-4 token is below the handbook's 1.5 KB size target. Its Python median verification time is above the 50 µs target. This is a Python prototype measurement on one Windows host, not a Rust dataplane result; it does not establish whether the target is met or missed by the intended production implementation. The spread, especially in p99, also means these values should be treated as a local baseline rather than stable capacity figures.
