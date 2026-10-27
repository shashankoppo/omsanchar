# Phase 1 Gateway MVP execution plan

Phase 1 starts after the P0 exit criteria in [PROGRESS.md](https://github.com/shashankoppo/omsanchar/blob/main/PROGRESS.md) are either met or explicitly deferred. Work packages are ordered because later packages depend on the earlier data path, stream store, and identity surfaces.

| Order | Work package | Status | Acceptance evidence |
|---:|---|---|---|
| 1 | Envoy data path and Rust `ext_proc`: authn, quota, metering, tracing, policy hook, OpenAI-compatible chat/responses/embeddings, SSE pass-through | Planned | Contract tests and end-to-end smoke against the Rust mock and a compatible external upstream when available |
| 2 | Durable resumable streams backed by NATS JetStream | Planned | Kill gateway during a stream, restart it, and resume with no lost or duplicate sequence numbers |
| 3 | Config-driven model router, fallback, health checks, integer budgets, deadline margins, priority/back-pressure and load shedding | Planned | Route, budget, deadline, overload, and failover tests with metrics and audit evidence |
| 4 | MCP Streamable HTTP and JSON-RPC proxy with filtered catalog, schema validation, quotas, audit, and side-effect classes | Planned | Per-identity authorization, malformed schema, quota, and side-effect policy tests |
| 5 | API keys, OAuth 2.1/JWKS through the existing auth interface, and capability token mint/attenuate/revoke | Planned | Positive and negative identity tests, bounded cache, and revocation propagation within the stated seconds budget |
| 6 | Go control-plane MVP with tenants, tokens, routes, registry, admin API, config distribution, usage/audit queries, Postgres, and hash-chained audit | Planned | Migration, authorization, persistence, and data-plane configuration conformance tests |
| 7 | OpenTelemetry GenAI traces, Prometheus metrics, and provisioned Grafana dashboards | Planned | Trace propagation and dashboard smoke tests; metric definitions tied to contracts |
| 8 | Generated TypeScript/Python SDKs, OpenAPI, and executable documentation examples | In progress: docs-as-code foundation | Regenerate without diffs, client tests, and run every runnable published example in CI |
| 9 | Reference agent workflow across gateway and MCP, survives gateway kill, emits usage and trace | Planned | Full integration demonstration on a clean CI checkout |
| 10 | Authorization bypass, parser/header fuzz, load smoke, NATS/gateway chaos, known limitations | Planned | Security and chaos suites with linked evidence and explicit environment labels |

## Phase 1 exit job

One clean-checkout CI job must start the stack, create a tenant and scoped attenuated token, stream a completion, invoke an MCP tool, kill and restart the gateway, resume without loss or duplication, show usage/audit/trace evidence, and reject unauthorized and over-budget calls with documented error codes.

All performance and capacity evidence records platform, tool versions, run count, and confidence intervals. Shared GitHub-hosted runner measurements are labeled **development only** and do not replace the dedicated native-host D5 result.
