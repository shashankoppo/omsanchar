# ADR-005: Capability token verification profile

- **Status:** Accepted for the P1 trust topology; Rust performance targets remain inconclusive pending qualified measurements.
- **Date:** 2026-10-27

## Question

Select an attenuation format and verifier topology that can meet practical ingress and downstream verification budgets without making a gateway compromise equivalent to unrestricted token minting.

## Required comparison

Compare Rust implementations of HMAC caveat chains, `biscuit-auth`, and Ed25519 attenuation chains at depths 1 through 8. Record serialized token bytes, uncached verification time, token-hash cache-hit time, and raw samples. A Python HMAC prototype cannot decide a Rust target.

Use native Linux for a final target verdict. WSL2 results are development-only and must not be pooled with native Linux. Report confidence intervals and classify each target as **met**, **not met**, or **inconclusive**. Do not omit a miss; revise a target only in this ADR and explain the evidence and trade-off.

## Trust model

An HMAC chain requires every verifier to hold the root secret. Compromise of any such gateway permits minting tokens for that root. Biscuit and public-key attenuation designs let gateways verify with public keys and reserve minting authority to the issuer, at additional verification and token-size cost. This security difference is a first-order decision input, not a benchmark footnote.

Evaluate a two-tier deployment: verify the public-key chain once at ingress; cache the verified authorization by cryptographic token hash with bounded TTL and issuer-key version checks; then issue a short-lived, audience-bound internal credential for downstream hops. Cache keys must not use bearer text in logs, and internal credentials must not outlive the parent grant or request deadline.

## Failure investigation and evidence

The earlier CPython HMAC prototype reported a depth-4 token size of 1,029 bytes and an 81.4 microsecond median on Windows 11 / CPython 3.12.8. It is prototype-only and cannot decide a Rust target.

A prior Rust release timing attempt reported a verification failure, but its failing scheme, depth, token bytes, and complete error log were not retained. The committed 2026-10-25 WSL2 timing artifact is quarantined and must not be used to set a target or select a format.

Investigation found that Biscuit token construction was not reproducible: convenience `build` and `append` APIs draw fresh attenuation keys from the OS RNG. The byte-for-byte reproducibility test failed before the change and passes after the benchmark uses a fixed `StdRng` seed for issuer and attenuation keys. Verification and tamper tests pass at depths 1 through 8. This explains token-byte instability, but does **not** establish the cause of the reported verification failure. A separate release-mode 100-sample-per-run diagnostic passed before deterministic construction; the original failure remains unreproduced. Do not publish new timing until a fixed-seed release reproduction completes without verifier errors.

The previously captured correctness checks ran on Rust 1.85.0 under WSL2 Ubuntu, Linux kernel `6.18.33.2-microsoft-standard-WSL2`, AMD Ryzen 5 5600H, allowed CPU list `0-11`. The workspace now requires Rust 1.88.0 to use security-patched `time` 0.3.47. WSL2 is development-only. Native Linux performance status is **inconclusive**. The older raw timing artifact and report are retained under `bench/quarantine/` for audit and are not accepted evidence.

## Decision

Use a public-key attenuation chain (Biscuit-style) at ingress, cache verified authorization by token hash with bounded TTL and issuer-key version checks, then issue short-lived audience-bound internal credentials. HMAC chains are not accepted across a gateway trust boundary: each verifier would hold the root minting secret, so compromise of any gateway would expose minting authority.

Keep the 50 microsecond target unchanged until uncached and cached Rust measurements are available from a qualified native Linux host. The target classification is **inconclusive**; no miss or success is claimed. The CPython prototype miss is not evidence about Rust performance. The quarantined WSL2 timing artifact is not accepted evidence. Token size, cold verification, cache-hit verification, and the full internal-credential path must each be reported separately with confidence intervals and platform/tool versions.

Keep the token interface replaceable and do not treat HMAC as a production delegation format. Before production selection, measure the complete internal-credential issue/verify path, expiry propagation, bounded cache eviction, and revocation/key-rotation behavior on the native host.
