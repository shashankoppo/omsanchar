# Error model

Errors use stable codes of the form `OS-xxxx`. Human-readable messages may change; clients branch on the code and retry attributes. The gateway must not expose upstream secrets or raw policy internals in error messages.

| Code | Name | Retry | Meaning |
|---|---|---|---|
| OS-0001 | INVALID_ENVELOPE | No | Envelope fields or address are invalid. |
| OS-0002 | UNSUPPORTED_VERSION | No | The envelope or protocol version is unsupported. |
| OS-0100 | UNAUTHENTICATED | No | Caller identity is missing or invalid. |
| OS-0101 | INVALID_GRANT | No | Capability grant is invalid, expired, or not bound to this request. |
| OS-0102 | POLICY_DENIED | No | Policy explicitly denied the operation. |
| OS-0200 | QUOTA_EXCEEDED | After reset | Tenant or identity quota is exhausted. May include `retry_after_ms`. |
| OS-0201 | BUDGET_EXCEEDED | No | Request would exceed its token, spend, or hop budget. |
| OS-3029 | HTTP_QUOTA_EXCEEDED | Conditional | Public HTTP 429 compatibility code from handbook B6 for rate, token, or spend exhaustion. Include `cause` as `OS-0200` for a resettable tenant/identity quota or `OS-0201` for a request-local hard budget; include `retry_after_ms` only when the quota can reset. |
| OS-0300 | ROUTE_UNAVAILABLE | Conditional | No eligible route is currently healthy. Retry only when `retryable=true`. |
| OS-0301 | UPSTREAM_TIMEOUT | Conditional | Upstream exceeded the propagated deadline. Retry only for idempotent operations and within budget. |
| OS-0302 | UPSTREAM_FAILURE | Conditional | Upstream failed. Retry only when explicitly marked retryable and idempotent. |
| OS-0400 | STREAM_CURSOR_EXPIRED | No | Requested cursor predates retained stream data. Start a new stream or use an application recovery path. |
| OS-0401 | IDEMPOTENCY_CONFLICT | No | An idempotency key was reused with a different payload. |
| OS-0402 | INVALID_CURSOR | No | Cursor is malformed, ahead of the stream, or regresses the acknowledged cursor. |
| OS-0403 | STREAM_BACKPRESSURE | After capacity | A bounded stream buffer is full. Retry after consumer acknowledgement or close the stream. |
| OS-0404 | STREAM_LIMIT_REACHED | No | A stream reached its configured event or dedupe-record limit and must be rotated. |
| OS-0500 | DEADLINE_EXCEEDED | No | The propagated relative deadline has expired according to a hop's monotonic clock. |
| OS-0503 | SERVICE_CAPACITY | After capacity | A configured in-memory stream or retained-state bound is full; the gateway failed admission before upstream work. |
| OS-0600 | INTERNAL | Conditional | Unexpected internal failure. Return a trace ID; retry only when explicitly marked retryable. |

Retryable errors may carry `retry_after_ms`, but clients must also honor their original deadline and remaining budget. A retry must reuse the same idempotency key. No error response itself implies that a side effect did not occur; callers must resolve ambiguous upstream outcomes with idempotency or status lookup.

`OS-0200` and `OS-0201` are the protocol/core classifications. HTTP bindings that expose handbook B6's `OS-3029` use it as the public 429 code and preserve the core classification in `cause`. In particular, an exhausted per-request `cost_limit_microcredits` is `cause: OS-0201` and is not retryable; a rolling tenant quota is `cause: OS-0200` and may be retried only when a reset time is provided.
