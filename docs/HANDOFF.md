# Session handoff

Updated: 2026-10-27 (Asia/Calcutta)

## Preserved state

- Working branch: `wip/session3`; latest committed checkpoint `4ae9363` records the token investigation. The D5 harness, matrix driver, and WSL2 raw smoke reports are validated and ready for a checkpoint commit.
- No Git remote is configured. The GitHub repository `om-sanchar` and hosted CI have not been created/run.
- The Session 3 handoff reports a release-mode verification failure, but the failing scheme/depth/token and complete log were not saved. A seeded-RNG byte reproducibility test failed before and passes after deterministic Biscuit key generation. This identifies token construction nondeterminism, not the verifier-failure cause. The old timing report was moved to `bench/quarantine/` and is not accepted evidence.
- Security reports currently describe an older Cargo lockfile and are stale after the bytes/Tokio pin changes. Rerun Syft, Grype, and cargo-audit before reporting them as current.

## Current implementation

- Bounded process-local gateway retention, TTL/count caps, FIFO eviction, eviction metrics, expired resume behavior, static bearer auth interface, deadline margin policy, D3 compose/config files, Rust mock model, Rust token-format benchmark, ADRs 001/005/008, soak and benchmark artifacts are in the working tree.
- The million-admission soak is registry-path evidence; it did not open one million gateway sockets. The original stream reservation is about 1 MiB per stream, so the 128 MiB budget retains only about 126 streams. This must be reduced and separately measured.
- Token tests pass in WSL2 debug and release: three tests, including verification across depths 1-8, tamper rejection, and byte-for-byte deterministic token construction. The original verifier failure is still unreproduced and has no preserved token/log; no new token timing is publishable until its cause is resolved.
- Existing raw token results are WSL2 development-only; they cannot decide ADR-005's native Linux target.
- D5 has no eligible measurements. ADR-001's pre-registered decision rule remains: Rust requires at least 20% lower CPU/request or lower p99 at equal features, with confidence excluding no improvement and no material p99.9/correctness/memory regression; otherwise keep Envoy.
- The Rust D5 load generator uses HdrHistogram 7.5.4 and Reqwest 0.12.28; `.cargo/config.toml` selects Rust 1.85-compatible transitives. Rust format check and two D5 unit tests pass. It tested SSE500, MCP, and fan-out against the Rust mock on WSL2 with 20/20, 10/10, and 10/10 requests completed and zero drops/errors. Raw HdrHistogram distributions and all request samples are in `bench/results/d5/wsl2-development-smoke/`. This is measured harness smoke only. Envoy AI gateway filters, ext_proc/WASM, a Rust D5 proxy, native Linux data, and target CPU/RSS remain missing.

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
  cargo +1.85.0 test --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features d5-bench --bin d5_loadgen
bash -n bench/d5/run-matrix.sh
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:/usr/bin:/bin \
  cargo +1.85.0 run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features token-bench --bin capability_token_bench -- 1000 10 bench/results/capability-token-rust-wsl2-2026-10-25.json
python spikes/capability-token/summarize_rust_results.py bench/results/capability-token-rust-wsl2-2026-10-25.json
python scripts/refresh_cargo_inventory.py --write
python scripts/check_dependencies.py
python scripts/run_local_security_scans.py
```

The benchmark command's existing artifact is not accepted until its release verification failure is understood. Capture failing scheme, depth, serialized token, and a fixed-seed reproduction. Add a regression test that fails before and passes after the fix.

## Next three actions

1. The fixed-seed token correctness suite passed in release. The earlier verification failure remains unreproduced and its cause unknown; collect detailed failure output if it recurs, and withhold timing meanwhile.
2. D5 open-loop HdrHistogram harness and three WSL2 direct mock smokes pass; checkpoint it, then continue feature parity only if practical. ADR-001 remains undecided.
3. Replace the 1 MiB stream reservation with actual retained-byte accounting and a small resume window, then add real-socket concurrency evidence and refresh the all-feature security scans.

## Pending failures and known limits

- GitHub create/push/hosted CI is unavailable until a repository creation capability and credentials are available. The local Git remote is empty.
- Native Linux D5 and retention measurements are unavailable; WSL2 can produce development-only harness evidence.
- Podman Compose provider is missing.
- D7 is deferred until priorities 1-4 have been handled and budget remains.
