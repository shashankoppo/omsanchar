# Process-local stream and request retention

The P0 Python gateway is a development reference. Its resumable state is bounded and process-local; a restart loses it. A resume request for an evicted stream, or a cursor older than that stream's retained event window, returns HTTP `410` with `OS-0400` (`STREAM_CURSOR_EXPIRED`). Once the bounded tombstone expires or is itself evicted to honor its count/byte limits, the gateway returns `404 OS-2004` because it can no longer distinguish an unknown ID from an old ID. Resume after process restart is not supported. See [ADR-008](../adr/008-durable-stream-log.md) for the P1 durable-log proposal.

## Limits and accounting

The default retained-state budget is **128 MiB per gateway process**, shared across streams, idempotency requests, audit records, trace records, and eviction tombstones. Store limits and TTLs are:

| Store | Maximum entries | TTL from insertion | Byte accounting |
|---|---:|---:|---|
| Streams | 10,000 | 300 s | current `deep_size(stream) + 256` bytes |
| Idempotency requests | 8,192 | 60 s | current `deep_size(value) + 256` bytes |
| Audit records | 8,192 | 900 s | current `deep_size(value) + 256` bytes; each record must be ≤8 KiB |
| Trace records | 8,192 | 300 s | current `deep_size(value) + 256` bytes; each record must be ≤8 KiB |
| Evicted-stream tombstones | 4,096 | 300 s | bounded ID record charge |

At most 10,000 streams may be active. Each stream keeps up to 16 events and at most 4 KiB of serialized SSE event data, retaining the newest events as a rolling window. A single event's serialized data and estimated Python object size may not exceed 2 KiB. The event count and byte limits can be set on `EventStream`; `GatewayService` exposes `stream_resume_events` and `stream_resume_window_bytes` constructor parameters.

Stream admission charges the current object size. Before publishing an event, the gateway reserves a 4 KiB growth upper bound, appends the bounded event, then remeasures the retained object with `deep_size`. This keeps the shared budget conservative while charging the actual retained window instead of reserving a maximum-size log for every stream. Audit and trace records also charge their current object sizes rather than reserving their full 8 KiB per record.

Request records retain SHA-256, body length, and stream ID instead of the request body or a second stream reference. Idempotency keys are limited to 128 bytes. TTL starts at insertion and does not slide on reads; expiry is applied on the next state operation. The 300-second stream TTL is hard: an open stream is failed and removed when expiry is observed. Eviction order is FIFO by insertion sequence. When a store reaches its count cap, its oldest eligible entry is evicted; global byte pressure otherwise evicts the oldest eligible entry across stores. Active streams are protected from capacity eviction until their TTL. If no entry can be evicted to satisfy a bound, admission fails with `503 OS-0503` before contacting the model. Evictions from every store, including tombstones, are exposed by `om_gateway_state_evictions_total{store=...}`.

`om_gateway_state_memory_bytes` reports retained object-size accounting plus fixed and temporary reservation overhead. It is not process RSS. The million-admission test records registry retention separately from the real-socket soak. The socket soak reports process RSS growth and bytes per accepted idle handler; those figures include Python thread and HTTP handler overhead and are not part of the retained-state budget. WSL2 results are development-only and cannot establish native Linux capacity.

## Development evidence (WSL2)

The registry soak was rerun on 2026-10-27 local; the TCP socket soak was measured on 2026-10-26. Both used Python 3.12.3 on kernel `6.18.33.2-microsoft-standard-WSL2`, AMD Ryzen 5 5600H, allowed CPUs `0-11`; CPU frequency was a single snapshot (3293.7 MHz), with no core pinning. These are **measured WSL2 development results**, not native Linux capacity evidence.

| Measurement | Result |
|---|---:|
| Registry soak (2026-10-27), streams admitted then abandoned | 1,000,000 |
| Retained streams / retained entries at end | 10,000 / 14,096 |
| Accounted retained state / configured 128 MiB budget | 18,833,296 / 134,217,728 bytes |
| Stream store charge / average per retained stream | 18,010,000 / 1,801 bytes |
| `tracemalloc` peak above start / process peak RSS | 23,765,036 / 81,813,504 bytes |
| Real TCP client sockets connected (2026-10-26) | 10,000 |
| Highest simultaneously accepted gateway handler threads | 9,114 |
| Socket-soak process RSS increase / peak RSS | 246,231,040 / 270,278,656 bytes |
| RSS increase per accepted idle handler / extrapolated handlers per GiB | 27,017 / 39,743 |

The million-entry test exercises stream construction, registry admission, immediate producer completion, and eviction. It does not open HTTP sockets or run model streams. Its accounted state, traced allocation peak, and process peak RSS stayed below 128 MiB. The socket soak connected 10,000 client sockets, but only 9,114 were simultaneously accepted by gateway handler threads; the 10,000-accepted-handler target was **not met**. At that load process RSS exceeded 128 MiB because the state budget excludes live socket and Python thread overhead. The extrapolated handlers-per-GiB value is an **estimate** from this WSL2 idle-connection measurement, not active-stream capacity.

Exact commands from the repository root (the WSL2 socket run temporarily raised the soft descriptor limit from 10,240 to 30,000; hard limit was 1,048,576):

```sh
.venv-wsl/bin/python -m unittest gateway.tests.test_bounded_state.BoundedStateTests.test_million_open_then_abandoned_streams_stay_under_memory_ceiling -v
ulimit -n 30000 && .venv-wsl/bin/python scripts/soak_gateway_connections.py --connections 10000 --batch-size 100 --thread-stack-bytes 131072 --output bench/results/bounded-state-socket-soak-wsl2.json
```

Reports: [`bench/results/bounded-state-registry-soak-wsl2.json`](../bench/results/bounded-state-registry-soak-wsl2.json) and [`bench/results/bounded-state-socket-soak-wsl2.json`](../bench/results/bounded-state-socket-soak-wsl2.json). Neither result substitutes for the requested native Linux run with CPU pinning and documented kernel settings.
