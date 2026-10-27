# ADR-001: Envoy edge and Rust AI gateway

- **Status:** Accepted for initial service boundaries; comparative performance question remains pending.
- **Date:** 2026-10-27
- **Scope:** Initial architecture and the pre-registered D5 comparison for any future Envoy AI-filter fast path.

## Initial architecture decision

Use Envoy at the network edge for TLS termination, routing, and coarse request limits. Route AI requests to the Rust `om-gateway` service, which owns token verification, quota and metering stages as they are implemented. Defer an Envoy AI-gateway filter plus Rust ext_proc/WASM adapter until the equal-feature comparison below can justify its additional integration surface. This sets the initial architecture and does not claim that either implementation has a measured performance advantage.

## Decision rule (pre-registered for a future fast-path decision)

Keep the Rust gateway service as the AI request path unless an Envoy AI-filter plus Rust ext_proc/WASM implementation, with the same token verification, quota checks, metering, and trace propagation, demonstrates either:

1. at least **20% lower CPU time per completed request**, or
2. a lower p99 end-to-end proxy overhead,

with a 95% confidence interval excluding no improvement and no material regression at p99.9, correctness, or memory. If neither condition is established, keep the Rust service path. A result whose interval overlaps no improvement is inconclusive, not an Envoy fast-path win. A lower p99 with a worse p99.9 is not sufficient.

## Registered protocol

Compare three paths against the same Rust mock upstream and request generator:

1. direct client to mock (baseline);
2. Envoy with AI gateway HTTP filters and one Rust ext_proc or WASM extension;
3. a minimal Hyper/Tokio Rust proxy.

Every proxy path performs the same token verification, tenant quota decision, integer metering, trace-context validation/propagation, and response handling. Publish the feature-parity checklist and source revision before accepting results.

Use an open-loop Rust load generator that schedules arrivals at fixed rates and records raw HdrHistogram samples. Run SSE with 500 tokens, one MCP JSON-RPC tool call, and one 1-to-N fan-out request. Exercise 1, 100, 1,000, and 10,000 simultaneous streams, with TLS disabled and enabled. Use the same offered request rate and payloads for every implementation in a cell; record dropped/late arrivals and errors. Run at least 10 independent repetitions per cell. Publish exact commands, per-run histograms, raw samples, p50/p99/p99.9, CPU time per completed request, resident memory, throughput, and bootstrap 95% confidence intervals for proxy-minus-baseline deltas.

The decision host must be a native Linux machine. Record model and stepping, microcode, governor and observed CPU frequency, pinned cores and IRQ policy, RAM, kernel, cgroup limits, and relevant socket settings. WSL2 measurements are labeled **development only**, are never pooled with native Linux results, and cannot decide this ADR. If no qualifying host is available, status remains inconclusive.

## Evidence and limits

The D4 Python/Windows loopback result is not D5 evidence. A Rust open-loop/HdrHistogram harness and paired-run summarizer cover the registered workloads and matrix dimensions. On WSL2, each mock workload completed a small direct-path smoke with zero errors; these are harness checks only, not overhead measurements.

The current Envoy development config provides routing and trace export but no AI-gateway filters, token verification, quota, metering, or ext_proc/WASM extension. The Rust gateway now provides an initial streamed AI request path, but it does not yet have feature parity with the registered D5 comparison. No qualifying native Linux host is available in this workspace evidence. Therefore no D5 overhead, CPU/request, RSS, confidence-interval, or performance-decision measurement has been collected. The architecture boundary is accepted; the comparative performance question remains **inconclusive**. WSL2 smoke results cannot prove or disprove either implementation's performance.

## Consequences

The benchmark harness, mock model, Envoy configuration, Rust gateway, exact run matrix, and raw data must be versioned. Do not replace the chosen Rust service boundary with an Envoy fast path until this decision rule is met. Revisit the performance question only after equal-feature implementations and a qualifying Linux host are available.
