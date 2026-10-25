

Evolucentsphere · Om Sanchar · Communication Layer and API Gateway


# R&D Plan and Developer Handbook

One sovereign layer that unifies AI gateway, service mesh, peer-to-peer overlay, event bus, realtime media and policy-in-path.


**Positioning, honestly.** Google, Microsoft, Anthropic and Kimi mainly publish protocols and managed cloud services; none, to my knowledge, sells one self-hostable layer spanning all the planes below. The real comparators are AI/agent gateways and meshes: Kong AI Gateway (MCP in 3.12, A2A governance in 3.14, April 2026), Envoy AI Gateway / Tetrate Agent Router (Kubernetes-native, vendor-reported 1–3 ms overhead), Cloudflare AI Gateway (managed only, no in-VPC option), Bifrost and LiteLLM, plus Istio/Linkerd, NATS, libp2p and Tailscale. Om Sanchar wins by **unifying** what these split across products, running fully on your own metal, and reaching edge nodes and partner networks. Every performance number below is a **target to validate**, not a result.


Part A · R&D and architecture

## A1. Mandate and requirements


| Area         | Requirement / target                                                                                                                                                                                                                            |
|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Functional   | Route and govern LLM, MCP, A2A, AG-UI, gRPC, REST, WebSocket/WebTransport, events and media; translate between protocols; location-transparent addressing of agents, tools, models, devices; resumable streams; multi-tenant metering and audit |
| Latency      | Pass-through overhead p50 ≤ 1 ms, p99 ≤ 3 ms; first-token streaming overhead ≤ 2 ms; policy decision ≤ 0.3 ms (cached)                                                                                                                          |
| Scale        | 1M+ concurrent streams per region; 100k+ requests/s per cluster; 10k+ nodes in the overlay; linear scale-out of data plane                                                                                                                      |
| Availability | 99.99% data plane; control plane outage must not stop traffic (data plane keeps last-known config); zero-downtime upgrades                                                                                                                      |
| Security     | mTLS everywhere, hybrid post-quantum key exchange, capability-attenuated tokens, deny-by-default, tamper-evident audit                                                                                                                          |
| Operability  | One binary profile per role, GitOps config, OpenTelemetry native, replayable traffic, chaos-tested                                                                                                                                              |
| Portability  | Runs on bare metal, Kubernetes, edge boxes and cloud burst; no hard dependency on any vendor                                                                                                                                                    |


## A2. Architecture

                        Clients / Agents / Tools / Devices / Channels
                                        |
       [ Edge ]  anycast, DDoS, TLS/QUIC/HTTP3, WAF, channel adapters
                                        |
     +--------------------------- DATA PLANE (Rust) ---------------------------+
     | Protocol codecs: OpenAI-API | MCP | A2A | AG-UI | gRPC | REST | WS | SIP |
     | Pipeline: authn -> policy(WASM) -> quota -> route -> cache -> guard ->   |
     |           transform -> upstream -> stream-tee -> meter -> trace          |
     +--------+----------------+----------------+----------------+-------------+
              |                |                |                |
       [ Mesh ] SPIFFE/mTLS  [ Overlay ] libp2p + WireGuard   [ Bus ] NATS JetStream
       service-to-service    NAT traversal, device/edge/       events, queues, replay
                             partner reach, DHT discovery
              |                |                |                |
     +--------+----------------+----------------+----------------+-------------+
     | CONTROL PLANE: registry, policy store (OPA/Cedar), token authority,      |
     | routing brain, config (GitOps), metering ledger, audit chain, UI/API     |
     +--------------------------------------------------------------------------+
            Upstreams: Model Plane | Orchestration Core | MCP servers | SaaS | Nodes

**Planes:** (1) Edge, (2) Data plane gateway, (3) Mesh, (4) Overlay, (5) Event bus, (6) Media, (7) Control plane. All talk through the same envelope, identity and policy model, which is what makes the layer "all in one" instead of five products glued together.

## A3. Key decisions (ADR summaries)


| ADR              | Decision                                                                                                                                                                                          | Alternatives considered                       | Revisit when                                         |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------|------------------------------------------------------|
| 001 Data plane   | Phase 1: Envoy with AI-gateway filters plus Rust ext_proc/WASM extensions. Phase 2: purpose-built Rust data plane (Pingora/hyper/quinn based) only for agent-specific paths if benchmarks justify | Pure Envoy forever; Go proxy; Kong/nginx      | Benchmarks show \>20% gain or Envoy blocks a feature |
| 002 Overlay      | libp2p for discovery, pub/sub, hole-punching; WireGuard for bulk tunnels                                                                                                                          | Nebula, Tailscale/Headscale, custom QUIC mesh | NAT-traversal success \< 95% in field tests          |
| 003 Event bus    | NATS JetStream for streams and queues; Kafka bridge for analytics                                                                                                                                 | Kafka only; Pulsar; Redis Streams             | Retention or throughput limits hit                   |
| 004 Wire formats | Protobuf envelope; gRPC/Connect internally; HTTP/3 + SSE/WebTransport at the edge; JSON for public REST                                                                                           | JSON only; Cap'n Proto                        | Codec cost dominates profiles                        |
| 005 Identity     | SPIFFE workload identity + OAuth 2.1 token exchange + attenuable capability tokens (Biscuit-style); DPoP binding                                                                                  | Plain JWT; Macaroons; mTLS only               | Token size or verify cost too high                   |
| 006 Policy       | OPA/Cedar compiled to WASM, evaluated in the data plane with decision caching                                                                                                                     | Central PDP call per request                  | Policy complexity exceeds WASM budget                |
| 007 Streams      | Every stream has an ID and cursor; clients resume after disconnect; server dedupes by idempotency key                                                                                             | Best-effort SSE                               | —                                                    |


## A4. Differentiating capabilities

- **Universal addressing:** `om://tenant/kind/name` resolves agents, tools, models, nodes and channels; callers never hard-code hosts.
- **Capability-attenuated delegation:** an agent can hand a sub-agent a *weaker* token (fewer tools, lower budget, shorter expiry) offline, with no round trip; the gateway verifies the whole chain.
- **Token-aware QoS:** scheduling by tokens per second, queue depth and class (voice \> interactive \> batch), with per-tenant fairness and budget shaping, not just request counts.
- **Protocol translation:** MCP ↔ A2A ↔ OpenAI-style API ↔ gRPC ↔ REST ↔ WebSocket, with a fidelity test suite so nothing is silently lost.
- **Resumable, replayable streams:** reconnect mid-generation without loss; record traffic and replay it against new models, prompts or policies for evals.
- **Policy in the path:** every call is authorised, budgeted, guarded and metered before upstream contact; decisions are logged to a hash-chained audit trail.
- **Adaptive routing:** health-, latency- and cost-aware multi-path with hedged requests and learned (bandit) route selection; automatic failover across providers and sites.
- **Overlay reach:** consented edge nodes, client sites and partner networks join the same mesh with resource caps and revocable credentials.
- **Bulk artifact fabric:** content-addressed, chunked, resumable P2P distribution of model weights and datasets between sites, deduplicated and verified by hash.
- **Quantum-ready transport:** hybrid classical + ML-KEM handshakes by default.
- **Deterministic simulation testing:** the protocol core runs inside a simulator that injects network faults, clock skew and crashes reproducibly (FoundationDB/TigerBeetle style).

## A5. Research workstreams


| \#  | Question / hypothesis                                     | Experiment                                                     | Success / kill criteria                                |
|-----|-----------------------------------------------------------|----------------------------------------------------------------|--------------------------------------------------------|
| W1  | A Rust data plane can beat Envoy+filters on agent traffic | Same workload on both: streaming LLM, MCP tool calls, fan-out  | Win: ≥20% lower CPU or p99. Kill: \<10%, stay on Envoy |
| W2  | Resumable streams can be exact with idempotency + cursors | Fault-inject 10k disconnects per hour under load               | Zero lost or duplicated tokens in 1M streams           |
| W3  | Attenuable tokens are fast and small enough for every hop | Benchmark verify cost and size at depth 1–8                    | ≤50 µs verify, ≤1.5 KB at depth 4                      |
| W4  | libp2p + WireGuard reach \>95% of real-world devices      | Test across carriers, CGNAT, corporate firewalls, home routers | ≥95% direct or relayed in \<2 s                        |
| W5  | Token-aware scheduling improves tail latency              | Compare to request-count limits on mixed voice/batch load      | Voice p99 stays flat while batch saturates             |
| W6  | Protocol translation can be lossless for core features    | Conformance corpus for MCP/A2A/OpenAI/gRPC round-trips         | ≥99.9% semantic equivalence, gaps documented           |
| W7  | Hybrid post-quantum handshakes cost little                | Measure handshake CPU and size at scale, mobile included       | \<10% overhead at p99                                  |
| W8  | Deterministic simulation finds bugs tests miss            | Seeded fault simulation of routing and stream state machines   | Finds ≥10 real defects before first release            |
| W9  | Semantic cache saves cost without quality loss            | Shadow-compare cached vs fresh answers on golden sets          | ≥20% hit rate, \<1% quality regression                 |
| W10 | Learned routing beats static rules                        | Multi-armed bandit vs rule router on cost, latency, success    | ≥10% cost cut at equal quality                         |


## A6. Roadmap


| Phase                          | Scope                                                                                                | Exit criteria                                                        |
|--------------------------------|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| P0 · Spikes (6 wks)            | W1, W3, W4 prototypes; envelope and address spec draft; benchmark harness                            | Go/no-go on Rust data plane; spec v0.1 reviewed                      |
| P1 · Gateway MVP (3 mo)        | Envoy-based gateway: OpenAI-compatible API, MCP proxy, auth, quotas, metering, tracing, model router | Orchestration Core runs one workflow through it; SLO dashboards live |
| P2 · Mesh and policy (3 mo)    | SPIFFE mTLS, capability tokens, WASM policy, NATS bus, registry and addressing                       | Unauthorised call provably blocked; tenant isolation tested          |
| P3 · Overlay (3 mo)            | libp2p/WireGuard nodes, enrolment, resource caps, artifact fabric                                    | ≥95% reachability; model weights moved site-to-site by hash          |
| P4 · Channels and media (3 mo) | WhatsApp/email/SMS/SIP adapters, WebRTC voice, AG-UI streams                                         | Voice round trip \<800 ms; channel parity tests pass                 |
| P5 · Performance (3 mo)        | Custom Rust fast path (if W1 justified), semantic cache, learned routing, simulation testing         | Meets A1 latency and scale targets in load tests                     |
| P6 · GA hardening              | Chaos days, pen test, DR drills, docs complete, SDKs stable                                          | Zero critical findings; failover under 30 min                        |


Part B · Developer handbook

## B1. Documentation suite (who reads what)


| Document                                     | Audience                   | Contents                                                                                   |
|----------------------------------------------|----------------------------|--------------------------------------------------------------------------------------------|
| Overview and Concepts                        | Everyone                   | Planes, tenants, principals, addressing, streams, grants                                   |
| Quickstart                                   | App developers             | Running in 5 minutes: section B2                                                           |
| Protocol Spec (RFC-style)                    | Core and SDK authors       | Envelope, handshake, streams, errors, versioning: B3, B5, B6                               |
| API Reference                                | App developers             | OpenAPI + protobuf, examples per endpoint: B4                                              |
| Auth and Tokens Guide                        | App and security engineers | OAuth flow, capability tokens, attenuation: B7                                             |
| SDK Guides (TS, Python, Go, Rust)            | App developers             | Install, patterns, retries, streaming, testing                                             |
| Extension Guide                              | Plugin authors             | WASM filters, channel adapters, tool servers: B9                                           |
| Operations Runbooks                          | SRE                        | Deploy, upgrade, failover, incident response, capacity                                     |
| Contributor Guide                            | Core engineers             | Repo map, standards, review and release: B10                                               |
| ADR Index and Design Docs                    | Core engineers             | A3 plus new ADRs (template: context, decision, options, trade-offs, consequences, actions) |
| Security Guide and Threat Model              | Everyone                   | Boundaries, abuse cases, reporting process                                                 |
| Versioning and Deprecation Policy; Changelog | Everyone                   | B8                                                                                         |


## B2. Quickstart (target: under 5 minutes)

    # 1. Run a local gateway with a mock model and MCP server
    docker compose -f deploy/dev.yml up -d
    # 2. Create a tenant and mint an API credential
    omctl tenant create demo && omctl token mint --tenant demo --scope chat:invoke

    // 3. TypeScript: call a model through Om Sanchar (OpenAI-compatible)
    import { OmSanchar } from "@om/sanchar";
    const om = new OmSanchar({ url: "http://localhost:8443", token: process.env.OM_TOKEN });
    const stream = await om.chat.stream({
      model: "om://demo/model/default",
      messages: [{ role: "user", content: "Namaste" }],
      idempotencyKey: crypto.randomUUID(),     // safe retries
    });
    for await (const ev of stream) process.stdout.write(ev.delta ?? "");
    // stream.cursor lets you resume after a disconnect: om.chat.resume(stream.id, stream.cursor)

## B3. Concepts and addressing

- **Tenant:** isolation and billing boundary. **Principal:** user, service, agent or node, each with a cryptographic identity.
- **Address:** `om://{tenant}/{kind}/{name}[@version]`, with kinds `model, tool, agent, topic, node, channel`.
- **Stream:** ordered, resumable sequence of events with ID and cursor. **Topic:** pub/sub subject on the bus, with optional durable replay.
- **Grant:** capability token stating exactly what a caller may do, on what, until when, up to what budget.

## B4. API surface (v1)


| Endpoint                                                       | Purpose                                                               |
|----------------------------------------------------------------|-----------------------------------------------------------------------|
| `POST /v1/chat/completions`, `/v1/responses`, `/v1/embeddings` | OpenAI-compatible model access with routing, caching, budgets         |
| `/v1/mcp/{server}`                                             | Governed MCP proxy: filtered tool catalog per identity, quotas, audit |
| `/v1/a2a/{agent}`, `/.well-known/agent-card.json`              | Agent-to-agent tasks and capability cards                             |
| `/v1/streams/{id}` (GET resume, DELETE cancel)                 | Resumable stream control                                              |
| `/v1/events/publish`, `/v1/events/subscribe`                   | Pub/sub and durable queues (SSE/WebSocket/gRPC)                       |
| `/v1/routes`, `/v1/registry`                                   | Manage routes, models, tools, agents, nodes                           |
| `/v1/policies`, `/v1/tokens` (mint, attenuate, revoke)         | Policy bundles and capability tokens                                  |
| `/v1/nodes` (enrol, heartbeat, caps, revoke)                   | Overlay node lifecycle                                                |
| `/v1/usage`, `/v1/audit`                                       | Metering and audit queries                                            |
| `/healthz`, `/readyz`, `/metrics`                              | Ops endpoints                                                         |


## B5. Message envelope (protobuf sketch)

    message Envelope {
      uint32  version        = 1;   // protocol major; never reuse field numbers
      string  id             = 2;   // ULID, globally unique
      string  idempotency_key= 3;
      string  from           = 4;   // om:// address of sender principal
      string  to             = 5;   // om:// address of target
      string  kind           = 6;   // "chat.delta", "tool.call", "event", "a2a.task"...
      bytes   payload        = 7;   // typed body, schema by kind
      map<string,string> meta = 8; // traceparent, tenant, class, deadline_ms, budget
      bytes   grant          = 9;   // capability token (attenuable)
      uint64  seq            = 10;  // stream sequence for resume
      bytes   sig            = 11;  // optional end-to-end signature
    }

## B6. Errors, limits and retries


| Code                      | HTTP | Meaning                                    | Retry?                    |
|---------------------------|------|--------------------------------------------|---------------------------|
| OS-1001 unauthenticated   | 401  | Missing or invalid credential              | No                        |
| OS-1003 forbidden         | 403  | Policy or grant denies action              | No                        |
| OS-2004 not_found         | 404  | Address does not resolve                   | No                        |
| OS-2009 conflict          | 409  | Idempotency key reused with different body | No                        |
| OS-3029 quota_exceeded    | 429  | Rate, token or spend limit                 | Yes, honour `Retry-After` |
| OS-4000 upstream_error    | 502  | Upstream failed after failover attempts    | Yes, with backoff         |
| OS-4003 overloaded        | 503  | Shedding load for higher classes           | Yes, jittered             |
| OS-4008 deadline_exceeded | 504  | Request deadline hit                       | Maybe                     |


Responses carry `x-om-request-id`, `traceparent`, `x-om-route`, and `x-om-budget-remaining`. Clients use exponential backoff with jitter, always send idempotency keys on writes, and propagate deadlines.

## B7. Authentication and capability tokens

1.  Humans and apps authenticate via OAuth 2.1/OIDC; services and agents via SPIFFE identity (mTLS).
2.  The token authority issues a **root grant**: allowed addresses and actions, budget, expiry, tenant.
3.  Holders may **attenuate** a grant (add restrictions, never remove) and pass it on. Gateways verify the full chain and enforce the intersection.
4.  Tokens bind to the caller key (DPoP) so stolen tokens are useless; revocation lists propagate to the data plane in seconds.
5.  Never embed long-lived tokens in agents; request per-task grants with the shortest viable expiry.

## B8. Versioning, compatibility and deprecation

- Semantic versioning; API major in the path (`/v1`); protobuf rules: add fields only, never renumber or reuse, reserve removed fields.
- Additive changes ship any time; breaking changes need a new major, a migration guide and a 12-month overlap with deprecation headers and dashboard warnings.
- Every release publishes a changelog, SDK compatibility matrix and conformance results.

## B9. Building on top and extending

- **Agent calling a tool:** request a per-task grant, call `/v1/mcp/{server}`; the gateway filters tools by identity and logs the call.
- **Event-driven app:** publish to `om://tenant/topic/orders`; subscribers use durable consumers with ack and replay from sequence.
- **Streaming UI:** consume AG-UI style events over SSE/WebTransport; store the cursor to resume.
- **Plugins (WASM filters):** implement `on_request`, `on_stream_chunk`, `on_response`; receive a read-only context (identity, route, budget) and may allow, deny, transform or annotate; strict CPU/memory limits, signed and versioned, tested with the conformance kit.
- **Channel adapters:** map an external channel to the envelope; must implement identity linking, opt-in/out, rate limits, delivery receipts and media handling.
- **Tool servers:** ship as MCP servers with typed schemas, side-effect class and compensation action; register in the registry.

## B10. Contributor guide (core engineers)

- **Repo map:** `/spec` (protocol, protobuf, OpenAPI), `/dataplane` (Rust), `/controlplane` (Go), `/overlay` (Rust/Go), `/policy` (Rego/Cedar + WASM), `/sdk/{ts,py,go,rust}`, `/adapters`, `/sim` (deterministic simulator), `/bench`, `/deploy`, `/docs`, `/adr`.
- **Contract first:** change the spec and schemas in a PR before code; generated clients and stubs must be regenerated and committed.
- **Standards:** memory-safe languages for the data plane; no panics on network input; fuzz every parser; `clippy`/`golangci-lint` clean; dependency pinning, SBOM and licence scan in CI.
- **Review:** two approvals; security review for auth, crypto, policy and parser changes; ADR required for any architectural change.
- **Definition of done:** unit + property tests, conformance tests, simulation run green, benchmark within budget (no more than 5% regression), metrics and traces added, docs and changelog updated, runbook impact noted, feature flag and rollback plan.
- **Release:** trunk-based, canary by tenant percentage, automatic rollback on SLO breach, signed artifacts and provenance.

## B11. Testing and conformance kit

- **Layers:** unit, property-based, protocol conformance (golden envelopes per kind), translation fidelity corpus, deterministic simulation, load and soak, chaos (kill nodes, drop links, skew clocks), security fuzzing, SDK cross-language tests.
- **Conformance kit:** a downloadable test runner third parties use to certify channel adapters, plugins and SDKs; passing builds earn a "compatible" badge in the registry.
- **Performance budgets:** every PR runs the benchmark harness against the targets in A1.

## B12. What is deliberately not in this page

Full RFC text for each protocol message, per-language SDK reference, OpenAPI file, runbook step lists and the threat-model workbook. These are the next documents to generate; each follows the suite in B1 and should be written by the owning team against the spec as it stabilises in P0.
