# Rust capability-token comparison (WSL2 development only)

All values below are **measured** on WSL2 Ubuntu and are not native Linux target evidence. The final 50 µs target verdict is **inconclusive** until the same matrix is run on a native Linux host.

- Platform: `6.18.33.2-microsoft-standard-WSL2`, `AMD Ryzen 5 5600H with Radeon Graphics`, allowed CPUs `0-11`.
- Rust: `rustc 1.85.0 (4d91de4e4 2025-02-17)`; `10` runs × `1000` measured samples per scheme/depth/mode, plus `100` warmups per run.
- Each cell shows token bytes / uncached p50 µs with a 95% bootstrap CI over run medians / cached p50 µs. The summary JSON includes p95, p99, and raw run distributions; the adjacent raw JSON retains every sample.
- Cache hit timing includes SHA-256 token hashing, a hash-map lookup, a monotonic 10-minute TTL check, and issuer-key version check. It excludes cache insertion and internal-credential minting.

| Depth | HMAC chain | Biscuit 6.0.0 | Ed25519 chain |
|---:|---:|---:|---:|
| 1 | 109 B / 0.716 [0.716, 0.721] / 0.129 | 365 B / 97.031 [96.782, 97.278] / 0.248 | 269 B / 60.138 [59.614, 61.005] / 0.220 |
| 2 | 126 B / 0.873 [0.872, 0.877] / 0.165 | 516 B / 136.329 [135.934, 136.815] / 0.331 | 382 B / 89.150 [88.929, 89.270] / 0.275 |
| 3 | 143 B / 1.038 [1.037, 1.042] / 0.156 | 667 B / 174.012 [173.736, 174.259] / 0.386 | 495 B / 118.962 [118.516, 119.183] / 0.294 |
| 4 | 160 B / 1.185 [1.176, 1.194] / 0.156 | 818 B / 215.368 [214.927, 216.002] / 0.432 | 608 B / 148.444 [148.085, 148.727] / 0.349 |
| 5 | 177 B / 1.350 [1.345, 1.354] / 0.156 | 969 B / 255.406 [254.221, 257.055] / 0.523 | 721 B / 178.300 [177.850, 178.806] / 0.413 |
| 6 | 194 B / 1.497 [1.492, 1.515] / 0.184 | 1120 B / 295.086 [294.283, 296.606] / 0.579 | 834 B / 207.451 [206.720, 207.896] / 0.468 |
| 7 | 211 B / 1.653 [1.653, 1.653] / 0.184 | 1271 B / 335.496 [333.788, 337.572] / 0.634 | 947 B / 237.474 [237.226, 237.883] / 0.496 |
| 8 | 228 B / 1.810 [1.809, 1.823] / 0.184 | 1422 B / 375.309 [373.463, 377.201] / 0.716 | 1060 B / 266.891 [266.478, 267.239] / 0.551 |

## Depth-4 target reading

At depth 4 the HMAC token is 160 B at 1.185 µs uncached p50, Biscuit is 818 B at 215.368 µs, and the Ed25519 chain is 608 B at 148.444 µs. Their cached p50 values are 0.156, 0.432, and 0.349 µs, respectively. The 1.5 KB depth-4 size target is measured as met for all three encodings. The 50 µs uncached verification target is missed by both public-key designs on this WSL2 run; HMAC meets the numeric target but has the root-secret trust problem below.

## Trust and two-tier design

Every HMAC verifier needs the root secret; compromise of any gateway holding it permits minting valid tokens for that root. Biscuit and the Ed25519 attenuation chain verify from public keys, so gateway compromise does not expose issuer minting authority. The public-key verification cost is higher in this prototype. The two-tier design remains the preferred direction for evaluation: verify the public-key chain once at ingress, cache the verified authorization by token hash with TTL and issuer-key version checks, then mint an audience-bound, short-lived internal credential bounded by the parent expiry and request deadline. This benchmark measures cache-hit lookup only; it does not measure internal-credential minting or propagation.

## Exact commands

```bash
RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:$PATH \
  cargo +1.85.0 run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml \
  --features token-bench --bin capability_token_bench -- 1000 10 \
  bench/results/capability-token-rust-wsl2-2026-10-25.json
python spikes/capability-token/summarize_rust_results.py \
  bench/results/capability-token-rust-wsl2-2026-10-25.json
```

Confidence intervals are estimated with `percentile bootstrap over 10 independent run medians, 20,000 resamples; reported intervals are estimates`. These are development results, so they do not replace the native Linux measurement required by ADR-005.
