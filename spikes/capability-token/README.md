# Capability token spike

Version 0.1.0 is a bounded Python prototype for the Om Sanchar D6 research spike. It follows the upstream handbook's requirement that a token holder can delegate weaker grants offline and that a gateway verifies the complete chain. The format is a small Macaroon-style HMAC chain, an implementation experiment rather than the final protocol choice (the handbook's ADR 005 says Biscuit-style).

## Prototype contract

- Issuer keys are at least 32 bytes. The issuer MAC authenticates the root claims; each appended caveat is chained from the previous MAC with HMAC-SHA256.
- A grant names one tenant and subject, a finite exact resource set, an action set, a non-negative signed 64-bit `budget_micros` ceiling, and an absolute Unix-millisecond expiry.
- Caveats may only reduce resource/action sets, budget, or expiry. Resource strings are exact opaque identifiers; wildcard or prefix matching is deliberately undefined.
- The verifier checks the issuer MAC and every caveat, then checks expiry and optional tenant/subject context. MAC checks use constant-time comparison.
- Maximum attenuation depth is 8 caveats; the complete ASCII token is capped at 4096 bytes. Depth in the benchmark counts appended delegation caveats, so it measures 1 through 8.
- Token payloads are integrity protected but not encrypted. This experiment does not implement DPoP or another proof-of-possession binding, key rotation, revocation, distributed spend accounting, or replay prevention. A budget ceiling is not by itself a concurrency-safe spend ledger; the gateway must enforce cumulative use separately.

The prototype must not be used to authorize production traffic. In particular, Python timing does not establish the upstream handbook's target of 50 microseconds verification or 1.5 KB at depth 4 on a Rust data plane.

## Run

From the repository root, using Python 3.12 or later:

```powershell
python -m unittest discover -s spikes/capability-token/tests -v
python spikes/capability-token/benchmark.py --iterations 1000 --warmup 100 --output spikes/capability-token/results/latest.json
```

The tests use a seeded standard-library generator for property-style attenuation coverage, so they need no optional property-testing dependency. The benchmark writes per-operation nanosecond samples, percentile summaries, workload metadata, runtime details, and the measurement timestamp as JSON. Run it on the target host for comparable measurements; results are not portable performance claims.

## Files

- `capability_token.py`: mint, attenuate, and full-chain verify API.
- `tests/test_capability_token.py`: validity, malformed-token, and non-widening property tests.
- `benchmark.py`: verifier benchmark at attenuation depths 1–8.
- `results/`: raw output captured during this spike.
