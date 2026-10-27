# Session handoff

Updated: 2026-10-27 (Asia/Calcutta)

## State

- Branch: `wip/session3`. This handoff covers the retention, supply-chain, and documentation continuation and its verification below.
- No Git remote is configured and no repository-creation capability is available through the connected GitHub tools. The requested GitHub repository, push, and hosted CI remain incomplete.
- P0 rough deliverable coverage is about 52%; see [PROGRESS.md](../PROGRESS.md).
- Keep the user's priority order. Do not begin D7 until priorities 1-5 are complete.

## Completed in this continuation

- Replaced the per-stream maximum reservation with retained-object reaccounting under a shared 128 MiB state budget. Added TTL and count bounds, deterministic FIFO eviction, per-store eviction metrics, and a rolling 16-event/4 KiB resume window. The 300-second stream TTL fails/removes open streams when expiry is observed. Stale/evicted cursors return HTTP 410 `OS-0400`; a cursor that expires during an SSE wait is rejected. Restart resume remains unsupported; [ADR-008](../adr/008-durable-stream-log.md) proposes the P1 durable log.
- WSL2 registry soak: 1,000,000 admissions/completions, 10,000 retained streams, 18,833,296 accounted bytes, 23,765,036-byte traced peak above start, 81,813,504-byte process peak RSS. This is registry-path evidence, not one million HTTP connections. Raw report: [bounded-state-registry-soak-wsl2.json](../bench/results/bounded-state-registry-soak-wsl2.json).
- WSL2 socket soak: 10,000 client TCP sockets connected, peak 9,114 accepted handler threads, 246,231,040-byte RSS increase, 27,017 estimated bytes per accepted idle handler. The 10,000-accepted-handler target was not met. Total process RSS exceeded 128 MiB under this socket load; the state-map accounting budget excludes socket/thread RSS. Raw report: [bounded-state-socket-soak-wsl2.json](../bench/results/bounded-state-socket-soak-wsl2.json).
- WSL2 only, kernel `6.18.33.2-microsoft-standard-WSL2`, Python 3.12.3, AMD Ryzen 5 5600H, allowed CPUs `0-11`; CPU frequency was a snapshot, not pinned. All capacity numbers are development-only; native Linux evidence remains required.
- Raised the Rust workspace minimum/tooling pin to 1.88.0 to update `time` from vulnerable 0.3.45 to patched 0.3.47. The Cargo license inventory now reflects 220 packages and its checker handles SPDX `OR` versus `AND`, reviewed ISC, and CDLA-Permissive-2.0.
- Latest local scans (2026-10-26 UTC): Syft 1.55.0, 228 SPDX package records; Grype 0 matches; cargo-audit 0.22.2, one remaining finding (`RUSTSEC-2026-0387`, `crypto-bigint 0.5.5`) in optional Biscuit/P256 dependencies. The token benchmark selects Biscuit Ed25519; the lockfile finding remains open and is not suppressed. Raw reports and hashes are in [security reports](security/reports/README.md).
- Aggregate `make test` passed under WSL2: spec 11, simulations 10, gateway 18 (including the million-stream soak), Python token 6, Rust core conformance 2, Rust token 3, Rust D5 harness 2, plus mock-model health/MCP/16-way fan-out/SSE smoke. `make lint` passed: style, 220-package dependency/license checks, Ruff, rustfmt, and Clippy.

## Still open

- The historical release token verifier failure remains unreproduced; its scheme, depth, serialized token, and log were not preserved. Deterministic Biscuit token construction is now tested, but that does not explain the verifier failure. Do not publish Rust token timing until the failure is diagnosed. ADR-005 performance status is inconclusive.
- D5 has a tested Rust open-loop HdrHistogram harness, WSL2 direct-mock smoke reports, and a 720-cell driver. It has no equal-feature direct/Envoy/Rust paths, no Rust proxy, no Envoy AI filters, and no qualified Linux host. WSL2 smoke is development-only. ADR-001 remains undecided.
- The D3 Compose configurations and Docker/Podman commands exist, but the Windows Docker engine is unavailable and the WSL2 Podman Compose provider is absent; stack runtime is unverified.
- No GitHub repository/remote or hosted CI; no native Linux 10,000-accepted-handler soak; no D7 work.

## Commands

Run from the repository root in WSL2:

```bash
export RUSTUP_HOME=/tmp/omsanchar-rustup
export CARGO_HOME=/home/shashank_patel/.cargo
export PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin
export RUSTUP_TOOLCHAIN=1.88.0

PYTHON=.venv-wsl/bin/python CARGO=cargo make test
PYTHON=.venv-wsl/bin/python CARGO=cargo make lint
PYTHON=.venv-wsl/bin/python scripts/run_local_security_scans.py
PYTHON=.venv-wsl/bin/python scripts/soak_gateway_connections.py --connections 10000 --batch-size 100 --thread-stack-bytes 131072 --output bench/results/bounded-state-socket-soak-wsl2.json
```

The million-entry test is `gateway.tests.test_bounded_state.BoundedStateTests.test_million_open_then_abandoned_streams_stay_under_memory_ceiling`; expect about 3.5 minutes on the Windows-mounted WSL2 checkout.

## Next three actions

1. Create/configure the GitHub remote, push the branch, and run hosted CI; track the remaining cargo-audit advisory until the Biscuit/P256 dependency chain has a patched compatible release or is replaced.
2. Obtain a qualified native Linux host, complete D5 feature parity, and run the pre-registered open-loop matrix; repeat the accepted 10,000-handler capacity test there.
3. Diagnose the historical Rust token verifier failure, then run the depth 1-8 token matrix. Keep D7 deferred until priorities 1-5 are complete.
