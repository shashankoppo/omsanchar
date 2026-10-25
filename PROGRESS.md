# Om Sanchar progress

## Current phase

**P0 - foundations and spikes**

Estimated P0 completion: **about 40%**. This is a rough deliverable-coverage estimate, not an effort measure. D1, D4, and D6 have local evidence; D2 is review-ready pending its baseline tag; D5 has a smoke result but no comparison. No P0 exit criterion is met yet.

## Deliverable status

| ID | Status | Evidence / remaining work |
|---|---|---|
| D1 Repository scaffold and CI | Complete locally; hosted CI pending | `make dev-native` ran in WSL2; the verification image built and passed its spec tests; the gateway image built and returned healthy under Podman. The CI workflow includes Docker/Compose builds, dependency SBOM, Grype high-severity gate, and license checks. This checkout has no remote, so no hosted CI run is available. |
| D2 Protocol spec v0.1 | Review-ready; tag pending | Relative remaining-millisecond deadlines, signed i64 microcredits, rational price and cumulative ceiling rounding, checked overflow, and cutoff behavior are specified. Rust and Python use shared JSON vectors. Need create `v0.1.0` and run Buf breaking against it. |
| D3 One-command integrated dev environment | Not started | `make dev-native` runs the D4 gateway. The larger Envoy, NATS JetStream, SPIRE, mock MCP, OTel Collector, and dashboard stack is not assembled. |
| D4 First end-to-end resumable model slice | Complete as a local reference | Native Python gateway to deterministic mock stream has bearer auth, tenant quota, per-token microcredit metering, trace propagation, metrics, audit events, graceful SIGTERM, and resume by stream ID/cursor. Automated TCP disconnect/resume test receives six sequenced outputs exactly once. In-memory only; not a production gateway. |
| D5 Envoy/Rust benchmark spike | Partial | D4 loopback smoke measurement and raw data exist. No Envoy-versus-Rust comparison, TLS, MCP tool call, fan-out, or concurrent workload has run. |
| D6 Capability token prototype | Complete as a prototype | Mint, attenuate, and verify plus depth 1-8 narrowing property tests and raw verification samples are in `spikes/capability-token`. Prototype is not the final ADR005 Biscuit-style format. |
| D7 Overlay lab and two-container prototype | Not started | No NAT reachability or peer overlay experiment yet. |
| D8 ADRs 001-007 | Not started | Existing upstream summaries remain inputs; implementation evidence and alternatives have not been turned into full ADRs. |
| D9 Threat model and security test plan | Not started | Map identities, assets, trust boundaries, abuse cases, and controls to tests. |
| D10 Developer documentation skeleton | In progress | WSL2 setup and runnable local commands are documented; integrated environment and release operations still need working examples. |

## Upstream review and corrections

Copied all six supplied upstream documents into `docs/upstream/` and read its README first. Per that README, file 04 is authoritative for Om Sanchar; file 00 is platform context, files 01-03 describe consumers, channels/media, and deployment context. The earlier statement that upstream material was absent was stale and has been superseded.

Corrections applied from the latest prompt and file 04:

- Replaced the earlier absolute Unix `deadline_ms` assumption with a relative remaining duration. Each hop uses a monotonic clock, rounds the forwarded remainder down, and applies an outbound timeout/cancellation. Wall-clock skew does not affect the local deadline calculation.
- Replaced generic unsigned cost units with non-negative signed 64-bit microcredits. The spec defines rational price rates, cumulative ceiling rounding, overflow rejection, and withholding an unaffordable output before release. HTTP `OS-3029` preserves `OS-0200` tenant-quota or `OS-0201` request-budget cause.
- Added the executable Rust stream state machine and independent Python cross-check against shared JSON conformance vectors; the stream crate has explicit finite limits.
- Added locked Cargo dependency/license inventory checks, dependency SBOM generation, and a high-severity Grype CI gate. These configured scans have not yet run in CI.
- Pointed Buf breaking compatibility at `v0.1.0`; the tag and check still need to be executed.
- Kept this session focused on the D4 vertical slice and D6 token spike. The broader platform blueprint's peer fabric, channels/media, learned routing, and artifact fabric remain outside this session's scope.

Open contract question: a relative duration forwarded between hosts does not include time spent in the network. The sender must bound its own outbound attempt with its monotonic deadline and propagate cancellation; transport behavior and retry semantics need explicit binding-level review.

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
