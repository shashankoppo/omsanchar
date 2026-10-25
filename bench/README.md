# Benchmark notes

`smoke_gateway.py` is the first measured D4 baseline. It records end-to-end
headers, first-token, and completion latency for one mock output token over
HTTP/1.1 loopback. The script writes timestamped metadata, raw nanosecond samples,
and source hashes under `bench/results/`.

Latest run: 2026-10-25 11:15 UTC, Windows 11 build 26200, CPython 3.12.8,
AMD64 Family 25 Model 80 Stepping 0 (AuthenticAMD), 12 logical CPUs, 16 GB RAM.
It used 10 warmups and 100 measured requests at concurrency 1, with two input
tokens, one mock output token, and no model delay.

| Measure | Median (ms) | 95% CI for median (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|
| Response headers | 1.143 | 1.105-1.165 | 13.534 | 18.651 |
| First token | 1.228 | 1.190-1.264 | 13.672 | 18.790 |
| Complete | 1.281 | 1.259-1.315 | 13.778 | 18.812 |

Raw samples, machine metadata, and source hashes are in
[`gateway-smoke-windows-python312-100x10.json`](results/gateway-smoke-windows-python312-100x10.json).

This smoke result is not a dataplane comparison. It does not measure Envoy, a Rust
proxy, TLS, MCP tool calls, fan-out, concurrent load, or production model latency.
Do not compare its values with the handbook's pass-through or first-token targets.
The D5 harness still needs those implementations and workloads before a comparative
result is valid.

Run it from the repository root:

```powershell
python bench/smoke_gateway.py --iterations 100 --warmup 10
```

Every result records its own runtime, machine, workload, sample count, raw samples,
and source hashes. Re-run on each target host; results are not portable between
machines.
