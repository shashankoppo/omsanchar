# Session handoff

Updated: 2026-10-26 (Asia/Calcutta)

## Preserved state

- Starting branch: `master`, HEAD `688425b` (`docs: record v0.1 compatibility result`). The Session 3 work was present as 34 changed/untracked paths and had not yet been committed at handoff. Preserve it on `wip/session3` before making further changes.
- No Git remote is configured. The GitHub repository `om-sanchar` and hosted CI have not been created/run.
- The current token benchmark source and WSL2 raw result are present, but the Session 3 handoff reports a release-mode verification failure. Do not treat any timing output as accepted until the failure is reproduced, diagnosed, regression-tested, fixed, and the complete matrix rerun.
- Security reports currently describe an older Cargo lockfile and are stale after the bytes/Tokio pin changes. Rerun Syft, Grype, and cargo-audit before reporting them as current.

## Current implementation

- Bounded process-local gateway retention, TTL/count caps, FIFO eviction, eviction metrics, expired resume behavior, static bearer auth interface, deadline margin policy, D3 compose/config files, Rust mock model, Rust token-format benchmark, ADRs 001/005/008, soak and benchmark artifacts are in the working tree.
- The million-admission soak is registry-path evidence; it did not open one million gateway sockets. The original stream reservation is about 1 MiB per stream, so the 128 MiB budget retains only about 126 streams. This must be reduced and separately measured.
- Existing raw token results are WSL2 development-only; they cannot decide ADR-005's native Linux target.
- D5 has no eligible measurements. ADR-001's pre-registered decision rule remains: Rust requires at least 20% lower CPU/request or lower p99 at equal features, with confidence excluding no improvement and no material p99.9/correctness/memory regression; otherwise keep Envoy.

## Toolchains and platform limits

- Windows workspace path: `C:\Users\Shashank patel\Desktop\Evolucentsphere_DB\Evolucentsphere Pvt Ltd\omsanchar`.
- WSL2 environment previously used: Ubuntu 24.04, kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, Ryzen 5 5600H, allowed CPUs `0-11`.
- Rust/Cargo 1.85.0 is pinned in CI and the mock container because `biscuit-auth 6.0.0` needs Rust syntax beyond the previously pinned 1.75 toolchain. Toolchain was installed under `/tmp/omsanchar-rustup`; Cargo home is `/home/shashank_patel/.cargo`; shim path is `/tmp/omsanchar-rust-cargo/bin`.
- No native Linux host is available in the recorded evidence. WSL2 results must be labeled development-only and never pooled with native Linux.
- Podman is installed in WSL2 but its Compose provider is absent. Docker Compose config parsing was previously successful; full engine runtime was not confirmed.

## Commands

Run in WSL2 from the repository root, preserving the pinned Rust environment:

```bash
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin \
  make test PYTHON=.venv-wsl/bin/python CARGO='cargo +1.85.0'
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin \
  make lint PYTHON=.venv-wsl/bin/python CARGO='cargo +1.85.0'
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin \
  cargo +1.85.0 test --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features token-bench --bin capability_token_bench
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin \
  cargo +1.85.0 run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features token-bench --bin capability_token_bench -- 1000 10 bench/results/capability-token-rust-wsl2-2026-10-25.json
python spikes/capability-token/summarize_rust_results.py bench/results/capability-token-rust-wsl2-2026-10-25.json
python scripts/refresh_cargo_inventory.py --write
python scripts/check_dependencies.py
python scripts/run_local_security_scans.py
```

The benchmark command's existing artifact is not accepted until its release verification failure is understood. Capture failing scheme, depth, serialized token, and a fixed-seed reproduction. Add a regression test that fails before and passes after the fix.

## Next three actions

1. Reproduce and diagnose the release token-verifier failure; add a regression test, fix it, and regenerate the complete 10-run Rust matrix only after the test passes.
2. Correct stream memory accounting/resume-window size, add real-socket Linux concurrency evidence, and publish bytes per retained stream/connection and estimated streams per GiB with platform labels.
3. Refresh all-feature dependency inventory and local security scans; then prepare the D5 open-loop HdrHistogram harness and record that ADR-001 remains undecided if no native Linux host is available.

## Pending failures and known limits

- GitHub create/push/hosted CI is unavailable until a repository creation capability and credentials are available. The local Git remote is empty.
- Native Linux D5 and retention measurements are unavailable; WSL2 can produce development-only harness evidence.
- Podman Compose provider is missing.
- D7 is deferred until priorities 1-4 have been handled and budget remains.
