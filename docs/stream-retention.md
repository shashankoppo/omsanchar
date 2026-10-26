# Process-local stream and request retention

The P0 Python gateway is a development reference. Its resumable state is bounded and process-local; a restart loses it. A client that resumes while an eviction tombstone is retained receives HTTP `410` with `OS-0400` (`STREAM_CURSOR_EXPIRED`). Once that bounded tombstone expires, the gateway returns `404 OS-2004` because it can no longer distinguish an unknown ID from an old ID. Resume after process restart is not supported. See [ADR-008](../adr/008-durable-stream-log.md) for the P1 durable-log proposal.

## Limits

The default retained-state accounting budget is **128 MiB per gateway process**, shared by all stores. In addition, at most 128 streams may be active at once. Admission observes the following retained-store caps:

| Store | Maximum entries | TTL from insertion | Per-entry accounting |
|---|---:|---:|---:|
| Streams | 4,096 | 300 s | 1,064,960-byte reservation |
| Idempotency requests | 8,192 | 60 s | deep object-size estimate plus 256 bytes |
| Audit records | 8,192 | 900 s | 8,192 bytes maximum |
| Trace records | 8,192 | 300 s | 8,192 bytes maximum |
| Evicted-stream tombstones | 4,096 | 300 s | bounded by the charge released with the stream |

Each stream may retain at most 130 events. Each event is limited to 4,096 serialized bytes and 4,096 estimated object bytes. Its reservation is twice that event size to cover Python object/container overhead. The reservation is charged when the stream is admitted, so later event appends do not need to increase the global budget.

Request records retain SHA-256, body length, and stream ID instead of the request body or a second stream reference. The 128-byte idempotency-key limit is enforced at the HTTP boundary. TTL is fixed at insertion and does not slide on reads. Eviction order is FIFO by insertion sequence. When a store reaches its own count cap, its oldest eligible entry is evicted; global byte pressure otherwise evicts the oldest eligible entry across stores. Active streams are not eviction candidates. Admission fails with `503 OS-0503` before contacting the model if no entry can be evicted to satisfy a bound. Evictions are exposed by the fixed-cardinality `om_gateway_state_evictions_total{store=...}` metrics.

`om_gateway_state_memory_bytes` is conservative retained-state accounting based on Python object sizes plus fixed/reserved overhead. It is not a replacement for process RSS monitoring. The million-stream soak also records the actual `tracemalloc` peak and Linux process peak RSS and asserts each is at most 128 MiB in the WSL2 test process. WSL2 results validate this reference implementation only; they do not establish native Linux capacity.
