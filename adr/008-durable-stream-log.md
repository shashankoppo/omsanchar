# ADR-008: Durable stream log for restart-safe resume

- **Status:** Accepted for P1; implementation and crash-recovery conformance remain pending.
- **Date:** 2026-10-25

## Context

The P0 reference gateway stores stream events and idempotency state in process memory. A restart loses both, so resume across process restart is unsupported. Bounded in-memory retention addresses resource exhaustion but does not provide durability or cross-process ownership.

## Decision for P1

Use NATS JetStream as the durable stream log for sequenced stream events, idempotency records, and terminal state. Preserve cursor semantics, define acknowledgement and retention behavior, and test crash points around event append, billing, and client delivery. Include multi-instance ownership, replay deduplication, compaction, encryption/residency, and recovery time in implementation validation. This is the selected design, not a measured comparison against an embedded log.

## Consequences

Do not claim restart-safe resume until the chosen log passes crash/restart conformance tests. The current gateway returns a bounded-retention error when a process-local stream has expired or been evicted.
