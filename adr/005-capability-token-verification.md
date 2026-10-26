# ADR-005: Capability token verification profile

- **Status:** Proposed; Rust comparison measured in WSL2, native Linux verdict pending.
- **Date:** 2026-10-26

## Question

Select an attenuation format and verifier topology that can meet practical ingress and downstream verification budgets without making a gateway compromise equivalent to unrestricted token minting.

## Required comparison

The Rust prototype compares HMAC caveat chains, `biscuit-auth`, and Ed25519 attenuation chains at depths 1 through 8. It records serialized token bytes, uncached verification time, token-hash cache-hit time, and raw samples. A Python HMAC prototype is not evidence for or against a Rust target.

Use a native Linux host for a final target verdict. WSL2 results are development-only and cannot be pooled with native Linux. Report confidence intervals and classify each target as **met**, **not met**, or **inconclusive**. Do not omit a miss; revise the target only in this ADR and explain the evidence and trade-off.

## Trust model

An HMAC chain requires every verifier to hold the root secret. Compromise of any such gateway permits minting tokens for that root. Biscuit and public-key attenuation designs let gateways verify with public keys and reserve minting authority to the issuer, at additional verification and token-size cost. This security difference is a first-order decision input, not a benchmark footnote.

Evaluate a two-tier deployment: verify the public-key chain once at ingress; cache the verified authorization by cryptographic token hash with bounded TTL and issuer-key version checks; then issue a short-lived, audience-bound internal credential for downstream hops. Cache keys must not use bearer text in logs, and internal credentials must not outlive the parent grant or request deadline.

## Current evidence

The prior CPython HMAC prototype measured a depth-4 size of 1,029 bytes and an 81.4 microsecond median on Windows 11 / CPython 3.12.8. This is prototype evidence only and cannot decide the Rust target.

A Rust 1.85.0 release-mode comparison was measured on WSL2 Ubuntu, Linux kernel `6.18.33.2-microsoft-standard-WSL2`, AMD Ryzen 5 5600H, allowed CPU list `0-11`. Each scheme/depth/mode ran 10 repetitions of 1,000 verifications with 100 warmups per run. The 95% confidence intervals in the [WSL2 results report](../bench/results/capability-token-rust-wsl2-2026-10-25-summary.md) use 20,000 bootstrap resamples of the 10 run medians; raw per-operation samples are retained next to the summary.

At depth 4, token sizes were 160 bytes for HMAC, 818 bytes for Biscuit, and 608 bytes for Ed25519. All three measured sizes are below the 1.5 KB target. Uncached p50 was 1.185 microseconds for HMAC, 215.368 microseconds for Biscuit, and 148.444 microseconds for Ed25519. Cached p50, including SHA-256 token hashing, map lookup, a monotonic 10-minute TTL check, and issuer-key version check, was 0.156, 0.432, and 0.349 microseconds respectively.

The numeric 50 microsecond cold-verification target is **not met in WSL2 development measurements** by either public-key design; HMAC is below the target but has the unacceptable shared-root-secret trust model. The final Linux target status is **inconclusive** because these measurements are WSL2 development results. The prototype does not measure internal-credential minting or propagation.

## Decision

Use the public-key two-tier design as the preferred candidate for native Linux validation. Revise the performance target from one 50 microsecond bound to two provisional depth-4 targets: uncached public-key verification at ingress below 250 microseconds p50, and a downstream token-hash cache hit below 1 microsecond p50 including TTL and issuer-key version checks. The WSL2 measurements support those provisional budgets but do not establish a final verdict. Keep the 1.5 KB depth-4 size target; measured WSL2 sizes met it for all three encodings.

Classify the provisional cached target as **met in WSL2 development measurements** for both public-key designs (0.432 and 0.349 microseconds p50). Classify the provisional cold ingress target as **met in WSL2 development measurements** for both public-key designs (215.368 and 148.444 microseconds p50). Classify both final native Linux target statuses as **inconclusive** until the same Rust release binary, workload, confidence method, and toolchain are measured on a pinned native Linux host. The former 50 microsecond uncached bound remains recorded as a development miss for Biscuit and Ed25519; do not erase it when reporting the provisional budgets.

Keep the token interface replaceable and do not treat HMAC as a production delegation format. Before production selection, measure the complete internal-credential issue/verify path, expiry propagation, bounded cache eviction, and revocation/key-rotation behavior on the native host.
