# Quarantined capability-token timing data

The 2026-10-25 WSL2 token timing artifact and its summary are retained for audit only. A previous release-mode run reported a verification failure without preserving the failing token or a complete error log. The cause has not been established, so none of these timings are accepted evidence for ADR-005. Do not use them for a performance target, design choice, or cross-platform comparison.

The format-size bytes in the artifact are also provisional because they came from the same unreconciled build. The new fixed-seed generator has a byte-for-byte reproducibility test that failed before the generator change and passes afterward. Fresh size and timing results require a successful fixed-seed release run with raw output and failure diagnostics.
