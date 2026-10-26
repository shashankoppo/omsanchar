# ADR-001: Envoy versus a Rust fast path

- **Status:** Proposed; decision deferred until a hosted Linux benchmark is available.
- **Date:** 2026-10-25
- **Scope:** D5 equal-feature comparison only. This is the pre-registration and must be committed before collecting any D5 measurements.

## Decision rule (pre-registered)

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

The existing D4 Python/Windows loopback result is a smoke test, not D5 evidence. It has no feature-matched proxies, open-loop arrival process, TLS matrix, or native Linux host. It cannot prove or disprove the Rust target. No D5 decision measurements have been collected for this ADR.

## Consequences

The benchmark harness, mock model, Envoy configuration, Rust proxy, exact run matrix, and raw data must be versioned. The Rust proxy remains a research branch until this decision rule is met. The ADR is amended only after the complete registered matrix or an explicitly documented infrastructure blocker.
