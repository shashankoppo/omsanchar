# Om Sanchar progress

## Current phase

**P0 - foundations and spikes**

Estimated P0 completion: **about 55%**. This is a rough deliverable-coverage estimate, not an effort measure. D1 has local scan evidence and passing hosted runs for tag `v0.1.0` and the docs-as-code branch. D2 is tagged; D3's stack configuration exists but runtime was not verified; D4 state bounds and WSL2 soaks are measured; D5 has a tested harness but no feature-matched paths or native Linux decision data; D6 correctness tests pass but the verifier failure remains unexplained and timing is withheld. No P0 exit criterion is met yet.

## Deliverable status

| ID | Status | Evidence / remaining work |
|---|---|---|
| D1 Repository scaffold and CI | Remote configured; hosted CI passed | `origin` points to `shashankoppo/omsanchar`. GitHub Actions run [40520340760](https://github.com/shashankoppo/omsanchar/actions/runs/40520340760) passed on Ubuntu and Windows; tag run [40471610379](https://github.com/shashankoppo/omsanchar/actions/runs/40471610379) passed for `v0.1.0`. Current WSL2 scans: Syft 1.55.0 (228 SPDX records), Grype 0 matches, cargo-audit 1 finding across 220 Rust packages. `RUSTSEC-2026-0387` remains open in optional Biscuit/P256 dependencies. |
| D2 Protocol spec v0.1 | Tagged; compatibility check previously passed | Relative deadlines, signed i64 microcredits, rational price and cumulative ceiling rounding, checked overflow, and cutoff behavior are specified. The deadline binding now subtracts rounded-up hop elapsed time plus a configurable safety margin and fails below minimum useful time. Rust and Python use shared vectors. |
| D3 One-command integrated dev environment | Configured; runtime unverified | Compose files and one-command Docker/Podman targets include Envoy, NATS JetStream, the Rust mock, and OTel Collector. Windows Docker engine is unavailable and the WSL2 Podman Compose provider is absent. |
| D4 First end-to-end resumable model slice | Bounded local reference; WSL2 soaks measured | Shared retained-state ceiling is 128 MiB with TTL/count caps, FIFO eviction, per-store eviction metrics, bounded rolling event windows, and `410 OS-0400` for evicted/expired cursors. The 300-second stream TTL fails/removes an open stream when expiry is observed. The one-million registry soak retained 10,000 streams with 18.8 MB accounted state and 81.8 MB process peak RSS. The separate 10k-client socket attempt had 9,114 accepted handler threads; this is below target and WSL2-only. Restart resume remains unsupported. |
| D5 Envoy/Rust benchmark spike | Harness tested; performance comparison inconclusive | Rust HdrHistogram open-loop harness, raw sample format, matrix driver, and paired confidence-interval summarizer exist. The D3 Envoy config lacks AI filters and no Rust proxy exists; no feature-matched comparison or native Linux run is available. ADR-001 selects Envoy plus Rust `ext_proc` as the Phase 1 default; the benchmark comparison is deferred to Phase 5. |
| D6 Capability token prototype | Rust correctness complete; performance inconclusive | Rust HMAC, Biscuit, and Ed25519 chain correctness/tamper tests pass at depths 1-8. The reported release verifier failure remains unreproduced; timing is withheld. ADR-005 selects a public-key ingress chain, token-hash cache, and short-lived internal credentials for P1. The 50 microsecond target remains inconclusive. |
| D7 Overlay lab and two-container prototype | Not started | No NAT reachability or peer overlay experiment yet. |
| D8 Architecture decisions | Partial | ADR-001 records the Phase 1 Envoy default and defers its performance comparison to Phase 5; ADR-005 records the public-key token trust topology; ADR-008 selects NATS JetStream for P1 durable resume. Implementations and measurement evidence remain open. |
| D9 Threat model and security test plan | Not started | Map identities, assets, trust boundaries, abuse cases, and controls to tests. |
| D10 Developer documentation | In progress | Added a MkDocs portal, pinned build dependencies, link/fence checks, an executed quickstart, and CI integration. WSL2 setup, bounded state and measured soaks, eviction behavior, authentication isolation, current scan findings, and restart-resume limitation are documented. The integrated environment remains runtime-unverified. |

## Session 4 docs-as-code continuation (2026-10-27)

- Added a strict MkDocs 1.6.1 site with the built-in ReadTheDocs theme, a navigable documentation portal, quickstart, authoring policy, and Phase 1 work-package plan. The site is a validation/preview output; no hosted docs deployment is configured.
- Locked all 17 docs builder and transitive Python packages in `requirements-docs.txt`; added their reviewed license records and source URLs to the dependency inventory. The exact-pin checker now covers both Python requirements files. The docs-only `pathspec` dependency is MPL-2.0 and is not used in the gateway or service images.
- Added first-party Markdown link/anchor checks, language-aware fenced-block validation, a Windows PowerShell parse job, and an executable quickstart smoke. The example test starts the actual reference gateway and runs the documented health and authenticated SSE commands.
- Local WSL2 `make docs` passed: links/fences across 24 Markdown files, quickstart response checks (health, two tokens, terminal event), and MkDocs strict build. Windows PowerShell parsed seven documented blocks; exact Python pin/inventory consistency and `git diff --check` passed. These are local/development results; hosted CI for this branch is pending.
- Updated ADR-001/005/008 with the selected P1 defaults and explicitly retained inconclusive performance classifications. WP8 remains incomplete until SDK/OpenAPI generation and execution of all runnable published examples are covered.
- Repository `origin` is configured; the docs branch was pushed at `fb74644`. Hosted Ubuntu and Windows CI passed as run [40520340760](https://github.com/shashankoppo/omsanchar/actions/runs/40520340760); the `v0.1.0` tag workflow also passed as run [40471610379](https://github.com/shashankoppo/omsanchar/actions/runs/40471610379).

## Session 3 continuation (2026-10-27 local; historical baseline before the remote was configured)

- Bounded stream retention now uses object-size reaccounting, a shared 128 MiB state budget, store count/TTL bounds, deterministic FIFO eviction, per-store eviction metrics, and a 16-event/4 KiB rolling resume window. The 300-second stream TTL fails/removes open streams when expiry is observed. Resume requests for evicted streams or expired cursors return HTTP 410 `OS-0400`; the waiting-SSE cursor race is tested.
- The million-entry registry soak passed on WSL2: 10,000 streams retained, 18,833,296 bytes accounted, 23,765,036-byte `tracemalloc` peak above start, and 81,813,504-byte process peak RSS. It exercises registry admission and immediate completion, not one million HTTP connections.
- The real-socket WSL2 soak connected 10,000 client sockets; peak accepted gateway handlers were 9,114. Incremental process RSS was 246,231,040 bytes, or an estimated 27,017 bytes per accepted idle handler. The 10,000 accepted-handler target was not met, and these results are development-only. Raw JSON is under `bench/results/`.
- Rust 1.88.0 is now the workspace minimum to use patched `time 0.3.47` (previously `time 0.3.45`). Syft 1.55.0 found 228 SPDX records, Grype 0 matches, and cargo-audit 0.22.2 found one remaining `RUSTSEC-2026-0387` in optional Biscuit/P256 dependencies. All raw results, versions, commands, checksums, and the RustSec archive snapshot are under `docs/security/reports/`.
- Aggregate `make test` passed under WSL2: spec 11, simulations 10, gateway 18 (including the million-stream soak), Python token 6, Rust core conformance 2, Rust token 3, Rust D5 harness 2, plus mock-model health/MCP/16-way fan-out/SSE smoke. `make lint` passed: style, 220-package dependency/license checks, Ruff, rustfmt, and Clippy.
- The release verifier failure is still unreproduced and its original scheme/depth/token/log were not preserved. Fixed-seed Biscuit token construction is now deterministic; verifier timing remains withheld and ADR-005 inconclusive.
- No D5 feature parity or native Linux evidence was produced. Envoy AI filters and a Rust proxy remain absent, so ADR-001 is undecided. D7 remains deferred.

## Upstream review and corrections

Copied all six supplied upstream documents into `docs/upstream/` and read its README first. Per that README, file 04 is authoritative for Om Sanchar; file 00 is platform context, files 01-03 describe consumers, channels/media, and deployment context. The earlier statement that upstream material was absent was stale and has been superseded.

Corrections applied from the latest prompt and file 04:

- Replaced the earlier absolute Unix `deadline_ms` assumption with a relative remaining duration. Each hop uses a monotonic clock, subtracts elapsed time rounded up plus a configurable safety margin, fails below the minimum useful remaining duration, and applies an outbound timeout/cancellation. Wall-clock skew does not affect the local deadline calculation.
- Replaced generic unsigned cost units with non-negative signed 64-bit microcredits. The spec defines rational price rates, cumulative ceiling rounding, overflow rejection, and withholding an unaffordable output before release. HTTP `OS-3029` preserves `OS-0200` tenant-quota or `OS-0201` request-budget cause.
- Added the executable Rust stream state machine and independent Python cross-check against shared JSON conformance vectors; the stream crate has explicit finite limits.
- Added locked Cargo dependency/license inventory checks, dependency SBOM generation, and a high-severity Grype CI gate. Local Syft, Grype, and cargo-audit scans now have committed raw reports. At this historical capture time, hosted CI had not run.
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

- Python spec: 11 tests passed; simulations: 10; gateway: 18 (including the million-entry soak); Python capability-token prototype: 6.
- Rust 1.88.0: 2 core conformance, 3 token, and 2 D5 load-generator tests passed; mock-model health, MCP, fan-out, and SSE smoke passed.
- Aggregate `make test` and `make lint` passed under WSL2 using Rust 1.88.0: style, installed Python license metadata, 220 Cargo package/source/license records, Ruff, rustfmt, and Clippy with warnings denied.
- WSL2 supply-chain scans are current for the lockfile: Syft 1.55.0, Grype 0 matches, cargo-audit 0.22.2 with one RustSec finding. See `docs/security/reports/README.md` and its raw evidence files.
- WSL2 Ubuntu 24.04, GNU Make 4.3, Podman, and `.venv-wsl` are installed. The Windows Docker engine is unavailable and Podman's Compose provider is absent, so integrated-stack runtime is unverified. At this historical capture time, no Git remote existed.

## Decisions, assumptions, and risks

- The local gateway is a reference integration, not a production service: bearer credential and one demo tenant, mock-only model, process-local stream/request/audit/trace maps, explicit bounded retention, and no durable resume across restart.
- The token prototype uses chained HMAC caveats to exercise narrowing. ADR-005 now selects a public-key ingress chain and short-lived internal credentials for P1. DPoP, key rotation, revocation, replay protection, and distributed spend prevention remain open design/implementation work.
- The Rust state machine is single-process protocol logic; durable storage, cross-process ownership, and transport integration remain unimplemented.
- CI configuration contains pinned supply-chain actions and scan gates. The `v0.1.0` tag workflow passed; current branch CI is pending. The local Grype scan found zero matches; cargo-audit retains one open finding in the optional Biscuit/P256 dependency chain.
- WSL2 is development-only for performance and capacity results. Current evidence used the Windows-mounted workspace; sustained Rust builds should use a WSL Linux-filesystem checkout when a repository remote is available.

## Next actions

1. Record an expiry-dated disposition for the remaining cargo-audit advisory after production-feature reachability review.
2. Reproduce and diagnose the historical token verifier failure before collecting qualified native Linux token timings.
3. Complete remaining P0 exit evidence and the P1 JetStream durable-resume implementation. Keep the preregistered D5 matrix in Phase 5 and D7 deferred until priorities 1-5 are complete.
