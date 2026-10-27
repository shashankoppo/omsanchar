# ADR-009: Rust AI gateway behind Envoy

- **Status:** Accepted
- **Date:** 2026-10-27

For the initial implementation, use Envoy for edge TLS, routing, and coarse limits, then route AI requests to a Rust `om-gateway` service for the AI-specific pipeline. This keeps streaming and future token, quota, metering, and resume behavior in a testable Rust service while avoiding an ext_proc/WASM integration during the current slices; ADR-001's pre-registered, feature-matched rule still governs eventual Envoy-versus-Rust data-plane selection, and this decision makes no performance claim.
