# Session handoff

Updated: 2026-10-27 (Asia/Calcutta)

## State

- Repository: `shashankoppo/omsanchar`; `origin` is configured. The working branch is `docs-as-code`, based on `main` at `6f776ba`, pushed at `fb74644`.
- GitHub Actions run [40520340760](https://github.com/shashankoppo/omsanchar/actions/runs/40520340760) passed on Ubuntu and Windows. The earlier `v0.1.0` tag run [40471610379](https://github.com/shashankoppo/omsanchar/actions/runs/40471610379) also passed.
- P0 deliverable coverage remains an approximate 55%; see [PROGRESS.md](../PROGRESS.md). This percentage is a planning estimate, not a measurement, and no P0 exit criterion is recorded as met.
- Follow the user's priority order. D7 remains deferred until priorities 1-5 are complete.

## Completed in this continuation

- Added a strict MkDocs portal, pinned the complete docs build dependency set, reviewed its licenses, and added docs dependencies to the existing exact-pin/license checker. The copied upstream materials, security scan reports, and handoff are excluded from the rendered site.
- Added local link/anchor and fenced-example validation, Linux Bash syntax checks, a Windows PowerShell parser job, and an executed quickstart smoke. The smoke starts the reference gateway and executes the documented health and authenticated SSE commands.
- WSL2 local `make docs` passed: 24 Markdown files validated, quickstart returned health plus two streamed tokens and a terminal event, and MkDocs 1.6.1 built the site with `--strict`. This is local development evidence; the branch CI run passed too.
- Windows PowerShell parser passed on seven documented PowerShell blocks. The Python pin/inventory consistency check and `git diff --check` also passed.
- Added a Phase 1 work-package plan. WP8 remains in progress: generated SDKs/OpenAPI and execution coverage for all runnable published examples are acceptance work, not complete.
- Updated ADR-001 to use Envoy plus Rust `ext_proc` as the Phase 1 default and defer the equal-feature D5 comparison to Phase 5. Updated ADR-005 to choose a public-key ingress chain plus token-hash cache and short-lived internal credentials. Updated ADR-008 to select NATS JetStream for P1 durable resume. These are architecture decisions, not measured performance results.
- Retained the Session 3 evidence: 1,000,000 registry admissions/completions on WSL2, 10,000 retained streams, 18,833,296 accounted bytes, 23,765,036-byte traced peak above start, and 81,813,504-byte process peak RSS. This is registry-path evidence, not one million HTTP connections. The separate socket soak accepted 9,114 of 10,000 clients; native Linux evidence remains outstanding.
- Latest local security reports (2026-10-26 UTC): Syft 1.55.0, 228 SPDX records; Grype 0 matches; cargo-audit 0.22.2, one open `RUSTSEC-2026-0387` finding for `crypto-bigint 0.5.5` in the optional Biscuit/P256 dependency chain. It is not suppressed. Reports and hashes are in [security reports](security/reports/README.md).

## Still open

- The Rust token verifier failure remains unreproduced; size and uncached/cached Rust timing are inconclusive. The 50 microsecond target is unchanged.
- D5 has no equal-feature Envoy/Rust proxy matrix and no qualified native Linux host. The preregistered comparison is Phase 5 work; CI and WSL2 measurements are development-only.
- The D3 integrated Compose stack remains runtime-unverified in this workspace. Process restart resume is unsupported until the P1 JetStream log is implemented and crash-tested.
- The native Linux 10,000-accepted-handler capacity target, the RUSTSEC advisory disposition, remaining P0 deliverables, and D7 remain open.

## Local docs workflow

From WSL2 at the repository root, with the exact docs toolchain installed:

```bash
python -m pip install --disable-pip-version-check --no-deps -r requirements-docs.txt
make docs
```

`make docs` validates first-party Markdown links and fences, runs the quickstart against the reference gateway, and builds the site strictly. `scripts/check_docs_powershell.ps1` parses Windows PowerShell blocks; GitHub runs it on `windows-2022`. The `site/` output is disposable and is not a deployment.

## Next three actions

1. Record an expiry-dated disposition for `RUSTSEC-2026-0387` after verifying production-feature reachability; keep the advisory visible in reports.
2. Reproduce the token verifier issue and gather qualified native Linux token evidence. Keep the D5 performance matrix in Phase 5 with its preregistered rule; WSL2 and CI numbers remain development-only.
3. Complete remaining P0 exit evidence and the P1 JetStream durable-resume implementation. Keep D7 deferred until priorities 1-5 are complete.
