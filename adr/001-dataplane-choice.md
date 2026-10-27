# ADR-001: Envoy versus a Rust fast path

- **Status:** Accepted for the Phase 1 default (Envoy plus Rust ext_proc); the D5 performance comparison is deferred to Phase 5 and remains inconclusive.
- **Date:** 2026-10-27
- **Scope:** D5 equal-feature comparison only. This is the pre-registration and must be committed before collecting any D5 measurements.

## Phase 1 decision

Use Envoy with a Rust `ext_proc` extension for Phase 1. This is the default architecture decision; it is not a claim that a performance comparison has been measured. D5 is a Phase 5 research comparison and does not block the Phase 1 Gateway MVP.

## Decision rule (pre-registered for the Phase 5 comparison)

Keep Envoy as the default data plane unless the Rust proxy, with the same token verification, quota checks, metering, and trace propagation, demonstrates either:

1. at least **20% lower CPU time per completed request**, or
2. a lower p99 end-to-end proxy overhead,

with a 95% confidence interval excluding no improvement and no material regression at p99.9, correctness, or memory. If neither condition is established, choose Envoy. A result whose interval overlaps no improvement is inconclusive, not a Rust win. A lower p99 with a worse p99.9 is not sufficient.

## Registered protocol

Compare three paths against the same Rust mock upstream and request generator:

1. direct client to mock (baseline);
2. Envoy with AI gateway HTTP filters and one Rust ext_proc or WASM extension;
3. a minimal Hyper/Tokio Rust proxy.

Every proxy path performs the same token verification, tenant quota decision, integer metering, trace-context validation/propagation, and response handling. Publish the feature-parity checklist and source revision before accepting results.

Use an open-loop Rust load generator that schedules arrivals at fixed rates and records raw HdrHistogram samples. Run SSE with 500 tokens, one MCP JSON-RPC tool call, and one 1-to-N fan-out request. Exercise 1, 100, 1,000, and 10,000 simultaneous streams, with TLS disabled and enabled. Use the same offered request rate and payloads for every implementation in a cell; record dropped/late arrivals and errors. Run at least 10 independent repetitions per cell. Publish exact commands, per-run histograms, raw samples, p50/p99/p99.9, CPU time per completed request, resident memory, throughput, and bootstrap 95% confidence intervals for proxy-minus-baseline deltas.

The decision host must be a native Linux machine. Record model and stepping, microcode, governor and observed CPU frequency, pinned cores and IRQ policy, RAM, kernel, cgroup limits, and relevant socket settings. WSL2 measurements are labeled **development only**, are never pooled with native Linux results, and cannot decide this ADR. If no qualifying host is available, status remains inconclusive.

## Evidence and limits

The D4 Python/Windows loopback result is not D5 evidence. A Rust open-loop/HdrHistogram harness and paired-run summarizer now cover the registered workloads and matrix dimensions. On WSL2, each mock workload completed a small direct-path smoke with zero errors; these are harness checks only, not overhead measurements.

The current Envoy development config provides routing and trace export but no AI-gateway filters, token verification, quota, metering, or ext_proc/WASM extension. The Rust core has no feature-matched D5 proxy. There is no qualifying native Linux host in this workspace evidence. Therefore no D5 overhead, CPU/request, RSS, confidence-interval, or decision measurement has been collected. The Phase 5 comparison is **inconclusive**; WSL2 smoke results cannot prove or disprove either path.

## Consequences

The benchmark harness, mock model, Envoy configuration, Rust proxy, exact run matrix, and raw data must be versioned. The Rust proxy remains a research branch until this decision rule is met. The ADR is amended only after the complete registered matrix or an explicitly documented infrastructure blocker. CI and WSL2 measurements are development-only and do not decide this ADR.
