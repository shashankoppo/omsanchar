# D5 open-loop benchmark harness

`d5_loadgen` is a Rust async client. The measured path does not use CPython. It schedules each arrival against a fixed monotonic clock, continues scheduling while earlier requests are in flight, counts arrivals refused at the concurrency cap, and measures latency from the scheduled arrival time. It consumes complete SSE bodies before recording completion. Latencies are stored in HdrHistogram 7.5.4 with three significant digits; every request sample and the percentile distribution are retained in JSON.

Workloads are a 500-token SSE stream, an MCP JSON-RPC tool call, and a 1-to-16 fan-out call. TLS is selected by using `https://` endpoints and can use a supplied PEM CA. The report records the endpoint, command, rate, duration, in-flight cap and observed peak, dropped/late arrivals, errors, kernel, CPU model/frequency snapshot, affinity, governor, cgroup limits, and the load generator's own peak RSS. The target service CPU/request and RSS fields remain null unless measured externally; do not substitute client-process resource use for target resource use.

## Smoke command

Start the Rust mock model on port 8081, then run one development-only workload:

```bash
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:$PATH \
  cargo +1.88.0 run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml \
  --features d5-bench --bin d5_loadgen -- \
  http://127.0.0.1:8081 sse500 10 2 100 bench/results/d5/wsl2-development-smoke/sse500.json
```

The command above was run on WSL2 with the three workload variants. The committed [SSE500](../results/d5/wsl2-development-smoke/sse500.json), [MCP](../results/d5/wsl2-development-smoke/mcp.json), and [fan-out](../results/d5/wsl2-development-smoke/fanout.json) reports retain every request sample and HdrHistogram distribution. Offered/completed/error counts were 20/20/0, 10/10/0, and 10/10/0. These are direct mock harness checks, not Envoy-versus-Rust results. WSL2 is development-only. A decision-grade run requires a native Linux host, CPU pinning and frequency/governor capture, cgroup and kernel settings, at least ten runs per cell, and externally collected target CPU and RSS.

## Registered matrix driver

`run-matrix.sh` runs 3 paths × 3 workloads × 4 in-flight caps × 2 TLS states × 10 repetitions. Configure six endpoint variables before running:

- `D5_BASELINE_HTTP`, `D5_BASELINE_HTTPS`
- `D5_ENVOY_HTTP`, `D5_ENVOY_HTTPS`
- `D5_RUST_HTTP`, `D5_RUST_HTTPS`

Set `D5_RATE_RPS`, `D5_DURATION_SECS`, and `D5_CA_CERT` to the pre-registered fixed offered rate, duration, and test CA. All paths use the same values. `run-matrix.sh` writes individual raw JSON files under the selected output directory. `summarize.py` computes paired proxy-minus-baseline p50, p99, and p99.9 deltas and percentile-bootstrap 95% confidence intervals from ten run pairs. It refuses mixed host metadata.

## Feature-parity and implementation status

The current D3 Envoy file is a routing and tracing development config. It has no AI gateway filters, ext_proc/WASM extension, token validation, quota, or metering. The `sanchar-core` crate also has no D5 proxy implementation. The matrix driver deliberately requires those three endpoints; it cannot manufacture equal features by routing to the current D3 stack. Until feature parity exists, D5 data is not valid evidence for ADR-001. Do not use this harness's throughput alone to choose a dataplane.

The registered decision rule remains in [ADR-001](../../adr/001-dataplane-choice.md): keep Envoy unless the feature-matched Rust proxy has at least 20% lower CPU/request or a lower p99 overhead with a 95% interval excluding no improvement and no material p99.9, correctness, or memory regression. Without a qualifying native Linux host and all feature-matched paths, ADR-001 stays undecided.
