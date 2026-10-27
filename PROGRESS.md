# Om Sanchar feature ledger

## Current slice

S1 Rust gateway streaming proxy. The runnable demo starts the Rust mock model and gateway, checks health, and streams three SSE chunks through the gateway with a request ID.

| Slice | Feature | Status | Demo command |
|---|---|---|---|
| S1 | Rust gateway: OpenAI-compatible SSE proxy, routes, request IDs, JSON logs, health, graceful shutdown | working and demoed | `make demo-s1` |
| S2 | Biscuit capability tokens: mint, attenuate, verify, revoke, cache, control-plane endpoints | not started | — |
| S3 | Budgets, metering, NATS, Postgres, audit | not started | — |
| S4 | JetStream durable stream resume with deduplication | not started | — |
| S5 | Model router and fallback | not started | — |
| S6 | MCP JSON-RPC tools | not started | — |
| S7 | Control plane | not started | — |
| S8 | OpenTelemetry observability | not started | — |
| S9 | Envoy edge | not started | — |
| S10 | SDKs | not started | — |
| S11 | Integration and hardening; one clean-checkout end-to-end CI job | not started | — |

## Decisions and constraints

- Initial development topology uses Envoy for edge TLS, routing, and coarse limits; the Rust `om-gateway` service owns the AI-specific request path. The ext_proc/WASM adapter is deferred. ADR-001's original feature-matched performance rule still governs eventual Envoy-versus-Rust data-plane selection.
- Only implemented S1 crates are workspace members. Add `om-token`, `om-control`, and `om-sdk-gen` when their slices contain working behavior.
- Keep the Python reference gateway until the Rust path covers the required authentication, quota, and resume behavior in S2-S4; Python remains available for tooling and reference checks.
- Keep every demo local and deterministic. A slice is complete only when its documented command runs and shows its behavior.
- D5 benchmarks, benchmark-host work, D7 overlay work, evidence-report expansion, and docs-pipeline changes are frozen during the implementation pivot.
- The current local Biscuit dependency pulls P256 unconditionally within its optional benchmark feature. The dated exception is tracked in `docs/security/security-exceptions.json`; it does not suppress scanner output.

## Known limitation

S1 resume state is process-local. Cross-restart resume is not available until S4's durable JetStream log is implemented.
