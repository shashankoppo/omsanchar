

Evolucentsphere · ELSx Global · Confidential


# Om Sanchar Platform Master Blueprint

A sovereign, model-agnostic, MCP-native AI platform: communication backbone, orchestration core, opt-in compute fabric, and the document suite to build it.


**Honest framing first.** Nobody makes Google, Anthropic or OpenAI "look like children"; they spend billions on models. You will not win on raw model power. You win on **what they structurally cannot offer**: (1) data sovereignty and self-hosting for Indian and global businesses, (2) any model plugged in, swappable in a day, (3) one policy-governed layer where every tool and agent is connected, audited and billable, (4) India-first operations and languages. This blueprint is built around that moat.


## 1. Vision and principles

- **Model-agnostic:** LLMs are replaceable engines (Ollama/vLLM local, or paid APIs). Nothing in the platform depends on one vendor.
- **Nothing talks directly:** every tool, agent, and model connects only through Om Sanchar and the orchestration core.
- **Policy before power:** every action passes identity, permission, budget and audit checks. Agents can do only what policy allows.
- **API-first, contract-first:** schemas are written before code; frontend and backend are fully decoupled.
- **Adapter, not fork:** use open-source frameworks behind your own adapter interface so any one can be replaced without a rewrite.
- **Measured:** nothing ships without traces, evals and cost metrics.

## 2. Layered architecture



**L6**Experience: web console, desktop agent, mobile, embeddable widgets decoupled frontend, talks only to L3 gateway



**L5**Tools and Apps: your SaaS, ERP/CRM, CMS, MCP servers, third-party APIs each exposed as an MCP server



**L4**Model Plane: Ollama, vLLM, external LLM APIs, embedding and vision models routing, fallback, cost caps



**L3**Orchestration Core: agents, workflows, memory, RAG, evals, guardrails adapter layer over LangGraph, CrewAI, LlamaIndex etc.



**L2**Control Plane: identity, policy engine, secrets, API gateway, billing/metering



**L1**Om Sanchar: LibP2P mesh, secure tunnels, service mesh, event bus mTLS everywhere, gRPC + streams



**L0**Infrastructure and opt-in Node Fabric: servers, Kubernetes, storage, consented user-device compute



Cross-cutting on every layer: observability (OpenTelemetry), security, data governance, and CI/CD.

## 3. Layer specifications

### L1: Om Sanchar (build first)

- Transport: LibP2P for peer discovery and NAT traversal; gRPC for service calls; NATS or Kafka for the event bus.
- Identity: every node, service and agent has a cryptographic identity (SPIFFE/SPIRE style); mTLS on all links; short-lived tokens.
- Tunnels: WireGuard-based private tunnels for servers and domains; declarative routing rules.
- Multimodal streaming: chunked, back-pressured streams for audio, video, screen frames; payload encryption end to end.
- SLOs to define up front: p99 latency, reconnect time, message loss (target zero for control messages).

### L2: Control Plane

- Policy engine (OPA or Cedar) deciding: which agent, which tool, which data, what spend limit, what needs human approval.
- Secrets in Vault/KMS; agents never see raw credentials, only scoped, expiring grants.
- Metering per tenant, agent, model and tool so the platform can be sold as a service with usage billing.

### L3: Orchestration Core

- **Adapter interface:** define your own `Agent`, `Tool`, `Memory`, `Workflow` contracts. Write thin adapters for LangGraph (stateful graphs), CrewAI (multi-agent roles), LlamaIndex (data/RAG). Start with one, prove the interface, add others.
- Durable execution: long-running tasks survive restarts (Temporal or equivalent); every step is checkpointed and resumable.
- Memory: short-term (state), long-term (vector DB plus relational), per-tenant isolation.
- Sub-agent spawning with budgets: max depth, max cost, max time, tool allow-list per child.
- Guardrails: input/output filters, prompt-injection defences, human-in-the-loop gates on destructive actions.
- Evaluation: Ragas and custom golden sets run in CI; regressions block release.

### L4: Model Plane

- Unified gateway (OpenAI-compatible API) in front of Ollama, vLLM and paid providers.
- Router chooses model by task, cost, latency and data-sensitivity (sensitive data stays on self-hosted models).
- Semantic cache, fallback chains, per-tenant rate limits, full request logging.

### L5: Tools via MCP

- Every internal product (CRM, BPO dashboards, SaaS, CMS) ships an MCP server with typed, minimal, permissioned actions.
- Computer-use (screen analysis, clicking) runs in sandboxed VMs or containers, never on the host, with recorded sessions.

### L6: Experience

- Custom decoupled frontend (React/Next.js) on the gateway API; Grafana only for operator dashboards.
- Screen-share and voice via WebRTC; Indian-language voice and text as a first-class feature.

## 4. The opt-in Node Fabric (L0): read this carefully


Turning users' devices into your compute or mining nodes is the highest-risk idea in the plan. As specified in earlier discussion (root access, activated on accepting terms, mining crypto) it would **be treated as malware**: Google Play and the App Store ban background mining, India's DPDP Act 2023 requires specific, informed, revocable consent, and hidden resource use is a legal and reputational liability. Root access is also never needed.


**Build it this way instead:**

- **Explicit enrolment:** separate screen, plain language, default off, revocable anytime; never bundled into general T&C.
- **Sandboxed agent, no root:** runs in user space or a WASM/container sandbox with hard caps on CPU, RAM, bandwidth, battery and temperature; plugged-in and idle only on mobile.
- **Useful work over mining:** phone mining is economically negligible. Contribute small-model inference, storage shards, relay/bandwidth or data-labelling, and reward users with credits or tokens.
- **Verifiable work:** redundancy or proofs so untrusted nodes cannot corrupt results; never send sensitive data to consumer nodes.
- **Reference designs:** Render Network, Filecoin, Golem, Akash (study licences before reusing code); get legal review before any token issuance.
- **Fleet dashboard:** node count, capacity, health, earnings, opt-out rate, all visible to users and operators.

## 5. Recommended technology stack


| Concern          | Choice                                                                       | Why                                                           |
|------------------|------------------------------------------------------------------------------|---------------------------------------------------------------|
| Core services    | Go or Rust (Om Sanchar), Python (orchestration)                              | Performance and safety for networking; AI ecosystem in Python |
| Transport        | LibP2P, gRPC, WireGuard, NATS                                                | Mesh, low latency, secure tunnels, event bus                  |
| Orchestration    | LangGraph + CrewAI + LlamaIndex behind your adapter; Temporal for durability | Best of each, replaceable                                     |
| Models           | Ollama (dev), vLLM (prod), LiteLLM-style gateway                             | Self-hosted plus API fallback                                 |
| Data             | Postgres, pgvector or Qdrant, Redis, object storage                          | Simple, proven, per-tenant isolation                          |
| Policy/secrets   | OPA or Cedar, Vault, SPIFFE                                                  | Zero-trust by default                                         |
| Observability    | OpenTelemetry, LangSmith or Langfuse, Grafana, Loki                          | Trace every agent step                                        |
| Guardrails/evals | NeMo Guardrails, Ragas, custom golden sets                                   | Safety and regression control                                 |
| Platform         | Kubernetes, Terraform, GitHub Actions                                        | Repeatable, auditable delivery                                |


Dify, Langflow and Flowise are useful for fast prototypes and internal demos, but keep them outside the core so you are never locked in.

## 6. Build roadmap with exit criteria


| Phase                                                 | Scope                                                                                 | Exit criteria                                                                      |
|-------------------------------------------------------|---------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| **0 · Foundation** (2–3 wks)                          | Monorepo, CI/CD, ADRs, threat model, API contracts, environments                      | Contracts reviewed; pipeline green; threat model signed off                        |
| **1 · Om Sanchar** (6–8 wks)                          | LibP2P mesh, mTLS identity, tunnels, event bus, gateway                               | 3+ nodes discover and communicate; failure and reconnect tests pass; SLOs measured |
| **2 · Control Plane** (4–6 wks)                       | Policy engine, secrets, tenancy, metering                                             | Unauthorised action provably blocked; usage per tenant visible                     |
| **3 · Model Plane** (3–4 wks)                         | Model gateway, routing, caching, local and API models                                 | Swap a model with zero client change; cost dashboard live                          |
| **4 · Orchestration Core** (8–10 wks)                 | Adapter interfaces, first framework, durable workflows, memory/RAG, guardrails, evals | Golden-set pass rate agreed; resumable multi-step agent runs                       |
| **5 · Tools and MCP** (6 wks)                         | MCP servers for your top 5 internal products; sandboxed computer-use                  | Agents complete real workflows end to end with audit trail                         |
| **6 · Experience** (6–8 wks)                          | Custom frontend, voice/screen, Indian languages                                       | Pilot users complete tasks unaided                                                 |
| **7 · Node Fabric pilot** (8 wks, after legal review) | Opt-in client, sandbox, credits, fleet dashboard                                      | Consent flow approved; measurable useful work; opt-out works instantly             |
| **8 · Harden and launch**                             | Pen test, load test, DR drills, SOC 2/ISO 27001 prep, docs, pricing                   | No critical findings; recovery drill under target RTO                              |


Timelines assume a focused team of roughly 6 to 10 engineers; adjust to your capacity. Phases 2 and 3 can overlap.

## 7. Security and compliance

- Zero-trust: no implicit trust between any two components; every call authenticated, authorised and logged.
- Defend against prompt injection, tool abuse and data exfiltration: least-privilege tools, output filtering, egress allow-lists, human approval for destructive steps.
- Tenant isolation at network, data and model-cache level; encryption at rest and in transit; key rotation.
- Compliance map: DPDP Act 2023, GDPR for global clients, SOC 2, ISO 27001; data-residency options per tenant.
- Supply chain: pin dependencies, SBOM, licence review for every imported repo (Apache/MIT fine; check AGPL and non-commercial terms before merging).

## 8. Quality, observability and cost control

- Trace every agent step, tool call, token and rupee; alert on cost spikes and loops.
- Three eval tiers: unit (tools), scenario (workflows), golden-set (answer quality); run on every merge.
- Red-team suite for jailbreaks and injections run weekly.
- SLOs: availability, p95 latency per layer, task success rate, cost per task.

## 9. Risks and mitigations


| Risk                                           | Mitigation                                                           |
|------------------------------------------------|----------------------------------------------------------------------|
| Scope explosion (building everything at once)  | Strict phase gates; ship one vertical workflow before adding breadth |
| Merging many repos creates unmaintainable code | Adapter contracts; each framework isolated in its own module         |
| Licence contamination                          | Licence scan in CI; legal sign-off before reuse                      |
| Node Fabric legal and store rejection          | Opt-in design above; legal review; pilot on desktop/servers first    |
| Model cost and latency                         | Routing, caching, small local models for routine tasks               |
| Key-person dependency                          | ADRs, runbooks, pair ownership per layer                             |


## 10. Documentation suite to produce


| Document                             | Purpose                                                       | Owner / phase          |
|--------------------------------------|---------------------------------------------------------------|------------------------|
| Product Requirements (PRD)           | Users, use cases, success metrics, non-goals                  | Product · 0            |
| Architecture Decision Records        | One page per major choice, with alternatives and consequences | Tech lead · continuous |
| Threat Model (STRIDE)                | Assets, trust boundaries, abuse cases, mitigations            | Security · 0           |
| API and event contracts              | OpenAPI, protobuf, MCP tool schemas, versioning rules         | Each layer · 0–5       |
| Om Sanchar protocol spec             | Identity, handshake, tunnels, streams, failure semantics      | Network · 1            |
| Policy catalogue                     | Roles, permissions, budgets, approval rules                   | Security · 2           |
| Agent design guide                   | Adapter contracts, spawning limits, memory rules              | AI lead · 4            |
| Eval and red-team plan               | Golden sets, thresholds, release gates                        | AI/QA · 4              |
| Runbooks and DR plan                 | Incident response, rollback, backup/restore, RTO/RPO          | SRE · 8                |
| Node Fabric consent and privacy pack | Consent copy, privacy notice, data map, DPIA                  | Legal · 7              |
| Compliance evidence binder           | Controls mapped to SOC 2 / ISO 27001 / DPDP                   | Compliance · 8         |
| Developer and customer docs          | Quickstarts, SDKs, examples, pricing and SLAs                 | DevRel · 6–8           |


## 11. First 30 days

1.  Freeze the layer model above and write the first 5 ADRs (language, transport, policy engine, orchestration adapter, model gateway).
2.  Stand up the monorepo, CI, and a 3-node Om Sanchar prototype with mTLS.
3.  Write the adapter interfaces and connect one framework plus one local model through the gateway.
4.  Expose one internal product as an MCP server and complete one real workflow with tracing and cost logging.
5.  Commission the threat model and the Node Fabric legal review in parallel.

## 12. Success metrics

Task success rate on golden sets, cost per completed task, p95 end-to-end latency, time to swap a model (target under a day), time to onboard a new tool via MCP (target under a week), zero critical security findings, and paying pilot tenants before Phase 7.
