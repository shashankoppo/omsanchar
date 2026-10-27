# Local supply-chain scan reports

All results below are **measured** on WSL2 Ubuntu, Linux kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64. They describe the local source tree at scan time and are not native Linux performance measurements.

## 2026-10-26

- Syft `1.55.0`, Rust/Cargo `1.88.0`: generated the raw SPDX SBOM with 228 package records; exit code 0.
- Grype `0.121.0`: 0 matches; exit code 0.
- cargo-audit `0.22.2`: audited 220 locked Rust packages against 1,378 advisories; 1 vulnerability; exit code 1.
- RustSec `RUSTSEC-2026-0009` (`time 0.3.45`, stack exhaustion in RFC 2822 parsing) was fixed by updating to `time 0.3.47` and raising the workspace minimum/toolchain to Rust 1.88.0. The [official RustSec advisory](https://github.com/RustSec/advisory-db/blob/main/crates/time/RUSTSEC-2026-0009.md) states the patched floor is `>= 0.3.47`.
- Remaining: [RUSTSEC-2026-0387](https://github.com/RustSec/advisory-db/blob/main/crates/crypto-bigint/RUSTSEC-2026-0387.md), `crypto-bigint 0.5.5`, pulled by the optional `token-bench` dependency `biscuit-auth 6.0.0` through its P256 stack. The benchmark selects Biscuit's Ed25519 algorithm; P256 is not part of its measured code path, but the lockfile advisory remains open and cargo-audit correctly exits 1. No lockfile suppression was added. The advisory's patched floor is `crypto-bigint >= 0.7.6`, which is incompatible with the current `elliptic-curve 0.13` / `p256 0.13` requirements.
- License review: the inventory checker now evaluates SPDX `OR` choices separately from required `AND` terms and accepts the reviewed ISC and CDLA-Permissive-2.0 identifiers. The CDLA license is declared by `webpki-roots`, which packages Mozilla root-certificate data; the [CDLA FAQ](https://cdla.dev/faq-resources/faq/) describes the permissive data terms.

The raw files, exact commands, exit codes, tool versions, archive checksum, and hashes are recorded in [`manifest-2026-10-26.json`](manifest-2026-10-26.json): [`syft-2026-10-26.spdx.json`](syft-2026-10-26.spdx.json), [`grype-2026-10-26.json`](grype-2026-10-26.json), [`cargo-audit-2026-10-26.json`](cargo-audit-2026-10-26.json), and [`rustsec-advisory-db-snapshot-2026-10-26.json`](rustsec-advisory-db-snapshot-2026-10-26.json).

## 2026-10-25

- Syft `1.55.0`, Rust/Cargo `1.75.0`: generated an SPDX JSON inventory with 19 package records; exit code 0.
- Grype `0.121.0`, vulnerability database schema `v6.1.10`, built 2026-10-25 06:27:34 UTC: 0 matches; exit code 0.
- cargo-audit `0.22.2`, RustSec advisory snapshot commit [`21d909e4c8bd4e14c7aea58bf980c881a0053ab1`](rustsec-advisory-db-snapshot-2026-10-25.json): audited 12 locked crates against 1,352 advisories; 0 vulnerabilities; exit code 0.

Git's upload-pack endpoint for `RustSec/advisory-db` failed in this WSL environment. The scan runner therefore downloaded the official commit-pinned source archive, recorded its SHA-256, initialized it as a local Git database, and ran cargo-audit with `--no-fetch`. This preserves the exact advisory source commit without suppressing or filtering findings.

## Files

- [`manifest-2026-10-25.json`](manifest-2026-10-25.json) records tool versions, exact commands, exit codes, platform, and report hashes.
- [`syft-2026-10-25.spdx.json`](syft-2026-10-25.spdx.json) is the raw SPDX SBOM.
- [`grype-2026-10-25.json`](grype-2026-10-25.json) is the raw Grype result.
- [`cargo-audit-2026-10-25.json`](cargo-audit-2026-10-25.json) is the raw cargo-audit result.
- [`rustsec-advisory-db-snapshot-2026-10-25.json`](rustsec-advisory-db-snapshot-2026-10-25.json) records the exact upstream RustSec database snapshot.

The binaries were downloaded from their official GitHub release pages and verified against the published SHA-256 digests before use. Run `python3 scripts/run_local_security_scans.py` from WSL2 to regenerate the reports.
