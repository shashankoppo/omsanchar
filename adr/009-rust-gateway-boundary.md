# ADR-009: Rust AI gateway behind Envoy

- **Status:** Accepted
- **Date:** 2026-10-27

Use Envoy for edge TLS, routing, and coarse limits, then route AI requests to a Rust `om-gateway` service for the AI-specific pipeline. This keeps streaming and future token, quota, metering, and resume behavior in a testable Rust service while avoiding an ext_proc/WASM integration before it has demonstrated value; ADR-001 retains the pre-registered, feature-matched rule for reconsidering that boundary, and this decision makes no unsupported performance claim.
