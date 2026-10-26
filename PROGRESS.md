# Om Sanchar progress

## Current phase

**P0 - foundations and spikes**

Estimated P0 completion: **about 45%**. This is a rough deliverable-coverage estimate, not an effort measure. D1 has local security-scan evidence but still lacks a GitHub remote and hosted CI; D2 is tagged; D4 now has bounded process-local state; D5 has only its pre-registered protocol; and D6 still needs the Rust comparison. No P0 exit criterion is met yet.

## Deliverable status

| ID | Status | Evidence / remaining work |
|---|---|---|
| D1 Repository scaffold and CI | Local gates and scans run; remote/hosted CI pending | Existing local container and test gates remain green from Session 2. Syft, Grype, and cargo-audit reports are under `docs/security/reports`; no GitHub repository exists yet, so hosted CI cannot run. |
| D2 Protocol spec v0.1 | Tagged; compatibility check previously passed | Relative deadlines, signed i64 microcredits, rational price and cumulative ceiling rounding, checked overflow, and cutoff behavior are specified. The deadline binding now subtracts rounded-up hop elapsed time plus a configurable safety margin and fails below minimum useful time. Rust and Python use shared vectors. |
| D3 One-command integrated dev environment | Not started | The Envoy, NATS JetStream, Rust mock, and OTel Collector stack is not assembled in native and Podman modes. |
| D4 First end-to-end resumable model slice | Bounded local reference; soak verified in WSL2 | The gateway has an accounted 128 MiB process-local budget, per-store count/TTL limits, deterministic FIFO eviction, bounded event logs, eviction metrics, a 128-active-stream cap, and a defined `410 OS-0400` response while an eviction tombstone remains. Resume across restart is still unsupported. |
| D5 Envoy/Rust benchmark spike | Pre-registered; measurements inconclusive | ADR-001 records feature parity, the open-loop/HdrHistogram matrix, native Linux host metadata, and the decision rule before D5 measurements. No eligible native Linux host or complete feature-matched implementations are available; the earlier Python/Windows smoke result is not D5 evidence. |
| D6 Capability token prototype | Python prototype complete; Rust decision inconclusive | The prior HMAC prototype remains in `spikes/capability-token`. ADR-005 now requires Rust HMAC, Biscuit, and Ed25519 measurements at depth 1-8 and records the trust implications and two-tier cache proposal. |
| D7 Overlay lab and two-container prototype | Not started | No NAT reachability or peer overlay experiment yet. |
| D8 ADRs 001-007 | Partial | ADR-001 and ADR-005 are drafted; ADR-008 proposes a P1 durable stream log. Other ADRs remain open. |
| D9 Threat model and security test plan | Not started | Map identities, assets, trust boundaries, abuse cases, and controls to tests. |
| D10 Developer documentation skeleton | In progress | WSL2 setup, bounded-state behavior, eviction errors, authentication isolation, security-report procedure, and restart-resume limitation are documented. The integrated environment remains open. |

## Session 3 status (2026-10-25)

- WSL2 supply-chain scans: Syft 1.55.0 found 19 package records, Grype 0.121.0 found zero matches using DB schema v6.1.10, and cargo-audit 0.22.2 found zero Rust advisories across 12 locked crates and 1,352 advisories. Raw reports, command vectors, tool versions, dates, hashes, and the commit-pinned RustSec database snapshot are in `docs/security/reports/`.
- The direct RustSec Git upload-pack fetch failed; the official archive at commit `21d909e4c8bd4e14c7aea58bf980c881a0053ab1` was downloaded and hash-recorded, initialized as a local Git snapshot, then audited with `--no-fetch`.
- Added ADR-001's pre-registered D5 decision rule and ADR-005's token comparison protocol. No D5 or Rust token performance numbers are claimed.
- Added ADR-008 for P1 restart-safe resume storage. The gateway currently returns `410 OS-0400` for retained eviction tombstones and `404 OS-2004` after that tombstone is gone.
- Added relative deadline safety-margin arithmetic and conformance/simulation scenarios. Static bearer auth is now behind an `Authenticator` interface for later SPIFFE/OAuth 2.1 plus DPoP work.

## Upstream review and corrections

Copied all six supplied upstream documents into `docs/upstream/` and read its README first. Per that README, file 04 is authoritative for Om Sanchar; file 00 is platform context, files 01-03 describe consumers, channels/media, and deployment context. The earlier statement that upstream material was absent was stale and has been superseded.

Corrections applied from the latest prompt and file 04:

- Replaced the earlier absolute Unix `deadline_ms` assumption with a relative remaining duration. Each hop uses a monotonic clock, subtracts elapsed time rounded up plus a configurable safety margin, fails below the minimum useful remaining duration, and applies an outbound timeout/cancellation. Wall-clock skew does not affect the local deadline calculation.
- Replaced generic unsigned cost units with non-negative signed 64-bit microcredits. The spec defines rational price rates, cumulative ceiling rounding, overflow rejection, and withholding an unaffordable output before release. HTTP `OS-3029` preserves `OS-0200` tenant-quota or `OS-0201` request-budget cause.
- Added the executable Rust stream state machine and independent Python cross-check against shared JSON conformance vectors; the stream crate has explicit finite limits.
- Added locked Cargo dependency/license inventory checks, dependency SBOM generation, and a high-severity Grype CI gate. Local Syft, Grype, and cargo-audit scans now have committed raw reports; hosted CI has not run.
- Pointed Buf breaking compatibility at `v0.1.0`; the annotated tag was created and the local compatibility check passed.
- Kept this session focused on the D4 vertical slice and D6 token spike. The broader platform blueprint's peer fabric, channels/media, learned routing, and artifact fabric remain outside this session's scope.

Resolved deadline policy: each route configures a per-hop safety margin and minimum useful downstream duration. A hop subtracts its rounded-up local elapsed time and margin before forwarding and fails fast with `OS-0500` when the remainder is too small. Transit time remains unencoded; the margin reserves time for transit and transport cancellation bounds the outbound attempt.

## Measured results

### D4 gateway smoke

Raw samples and source hashes: `bench/results/gateway-smoke-windows-python312-100x10.json`.

- Windows 11 build 26200, CPython 3.12.8, AMD64 Family 25 Model 80 Stepping 0 (AuthenticAMD), 12 logical CPUs, 16,487,870,464 bytes RAM.
- 10 warmups, 100 measured requests; HTTP/1.1 loopback, one client at a time, two input tokens, one mock output token, no model delay.
- Median headers: 1.143 ms; first token: 1.228 ms; completion: 1.281 ms. First-token 95% bootstrap CI for the median: 1.190-1.264 ms. First-token p95/p99: 13.672/18.790 ms.
- High outliers are present. This is a single-host Python gateway smoke result, not a dataplane comparison or production latency claim.

### D6 verifier

Raw samples and host metadata: `spikes/capability-token/results/windows-python312-2000x200.json`.

- Same Windows 11 / CPython 3.12.8 / AMD64 host, 200 warmups and 2,000 measured verifications at each depth, HMAC-SHA256, sequential successful verification.
- At delegation depth 1-8, token size ranges 797-1,338 bytes and median verification ranges 59.3-111.3 microseconds. At depth 4: 1,029 bytes, 81.4 microsecond median, 93.4 microsecond p95, 110.5 microsecond p99.
- The depth-4 size is below the handbook's 1.5 KB target. This Python prototype's median exceeds 50 microseconds; it says nothing about Rust dataplane performance. Raw source hashes are recorded; the source revision was uncommitted when measured.

## Tests and environment evidence

- Python spec: 10 tests passed.
- Python simulation: 5 tests passed, including skew injection and shared deadline vectors.
- Gateway integration: 6 tests passed, including mid-stream disconnect/resume, no missing/duplicate event sequences, request budget cutoff, and error-cause fields.
- Rust `sanchar-core`: 2 conformance tests passed; rustfmt 1.75.0 and Clippy with warnings denied passed. The complete `make test` and `make lint` targets passed in WSL2.
- Python style, Ruff lint/format, installed Python license metadata, and all 11 locked Cargo package license/source records passed.
- WSL2 Ubuntu 24.04, Rust/Cargo 1.75.0, GNU Make 4.3, Podman, and a separate `.venv-wsl` are installed. Both images built locally; the verification image's 10 spec tests passed; the development image health route and graceful stop passed. The Windows Docker engine is unavailable, and the workspace has no Git remote, so hosted CI cannot be triggered.

## Decisions, assumptions, and risks

- The local gateway is a reference integration, not a production service: bearer credential and one demo tenant, mock-only model, process-local stream/request/audit/trace maps, no durable resume across restart, and no retention bound across streams.
- The token prototype uses chained HMAC caveats to exercise narrowing. Upstream ADR005 calls for Biscuit-style grants and DPoP; format choice, proof-of-possession, key rotation, revocation, replay protection, and distributed spend prevention remain undecided.
- The Rust state machine is single-process protocol logic; durable storage, cross-process ownership, and transport integration remain unimplemented.
- CI configuration contains pinned supply-chain actions and scan gates, but no workflow has run in this repository yet. No container or vulnerability scan result is claimed.
- WSL2 is the intended Rust/Linux environment. Current evidence used the Windows-mounted workspace; sustained Rust builds should use a WSL Linux-filesystem checkout when a repository remote is available.

## Next actions

1. Run WSL `make test` and `make lint`, get a container build and SBOM/vulnerability scan through CI or Podman, then record the actual results.
2. Finish D5 with measured Envoy and Rust proxy implementations over streaming-LLM, MCP, and fan-out workloads, preserving raw samples and host/version metadata.
3. Continue in requested order with D7 overlay reachability, then D8 ADRs, D9 threat model, and D10 runnable integrated developer documentation.
