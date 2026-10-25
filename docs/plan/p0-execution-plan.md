# P0 execution plan

Estimates are engineering effort, not calendar commitments. Parallel work can fit the roadmap's approximately six-week estimate; D4 and evidence-backed spike decisions form the critical path.

| Order | Deliverable | Estimate | Dependencies | Risks | Evidence to publish |
|---|---|---:|---|---|---|
| 1 | D1 repository scaffold and CI | 3–5 days | None | Toolchains and scanners may be absent locally; CI scope must avoid unpinned tools | CI workflow/configuration, passing local checks, dependency/license report, SPDX SBOM, protobuf compatibility check, container build log |
| 2 | D2 protocol spec v0.1 | 5–7 days | D1 layout | Address canonicalization, deadline meaning, budget units, replay/ack semantics need explicit review | Buf build/lint, parser and state-machine tests, conformance vectors, cross-document consistency review |
| 3 | D3 one-command developer stack | 4–6 days | D1, D2 | Multi-service configuration and image availability | `make dev` startup, service health checks, documented teardown and a clean startup run |
| 4 | D4 authenticated resumable model slice | 6–8 days | D2, D3 | Disconnect/resume races, quota and dedupe semantics | Automated kill-and-resume test proving no loss/duplication, traces and metering evidence |
| 5 | D5 Envoy/Rust benchmark spike | 5–7 days | D1, D3 | Results vary with workload, hardware, and stream duration | Harness, workload definitions, raw data, hardware/methodology, confidence intervals, ADR-001 go/no-go |
| 6 | D6 capability-token prototype | 4–6 days | D1, D2 | Token format and cryptographic choices need security review | Mint/attenuate/verify prototype, depth 1–8 size/latency data, property tests that authority never widens |
| 7 | D7 overlay lab and two-container prototype | 5–8 days | D1, D2 | NAT/firewall behavior is environment-dependent | Reproducible topology, seeded scenarios, measured direct/relay success, failure analysis |
| 8 | D8 ADRs 001–007 | 3–4 days | D2, D5–D7 | Accepted decisions may need revision after evidence | Seven ADRs with context, options, trade-offs, consequences, action items, and spike links |
| 9 | D9 threat model and security plan | 3–4 days | D2 and baseline architecture | Trust boundaries evolve as implementation begins | STRIDE assets/boundaries/abuse cases/mitigations and mapped unit/property/conformance/simulation/load/chaos/fuzz tests |
| 10 | D10 developer documentation skeleton | 4–6 days | D2–D4 | Quickstart cannot be validated before D3/D4 | Overview, quickstart, protocol/API, auth/tokens, SDK/extension guides, runbooks, contributor/security/versioning/changelog docs; execute quickstart |

## Ordering and exit controls

- D1 and D2 begin together on the empty repository. The protobuf contract is written before production implementation.
- D3 follows D2 review. D4 follows a working D3 stack.
- D5, D6, and D7 may run in parallel after their prerequisites are available.
- D8 uses measured spike results; it must not state estimates as benchmark facts.
- D9 and D10 can be drafted earlier, but must be reviewed against the final P0 design and runnable stack.
- P0 is complete only when the supplied exit criteria are evidenced in `PROGRESS.md`: D4 CI passes; spike reports and ADR-001 go/no-go are published; the spec is self-consistent and reviewed; and the threat model is reviewed.
