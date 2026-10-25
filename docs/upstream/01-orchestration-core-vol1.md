

Evolucentsphere · Om Sanchar · Orchestration Core


# Orchestration Core Technical Specification

A model-agnostic, protocol-native, policy-governed agent runtime designed to stay current through roughly 2038.


**Honest scope note.** No one can guarantee "best on the planet" or predict 12 years of AI. What can be engineered is **durability**: stable internal contracts, replaceable engines, protocol adapters at the edge, and evals that tell you when to swap a component. Protocol names and versions below reflect the landscape as of mid-2026; verify each spec's current status before pinning.


## 1. Design thesis

- **Ports and adapters.** Your own contracts (Agent, Tool, Skill, Memory, Model, Policy, Trace) sit in the middle. Frameworks, models and protocols are adapters on the outside, so any can be replaced without touching the core.
- **Deterministic shell, probabilistic core.** LLM calls are non-deterministic; everything around them (state, retries, budgets, permissions, replay) must be deterministic.
- **Capabilities, not credentials.** Agents hold narrow, expiring, auditable grants, never raw secrets or ambient authority.
- **Everything is measurable.** Each step emits a trace, a cost, and an eval signal; improvement is driven by data, not opinion.
- **Federation-ready.** Cores can run on a server, on-device, or at a client site and still cooperate over open agent protocols.

## 2. Planes and subsystems


| Plane          | Subsystem                        | What it does                                                                                                                 |
|----------------|----------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| **Intent**     | Intake and Intent Parser         | Normalises text, voice, screen, event and API triggers into a typed Task with goal, constraints, budget, deadline, risk tier |
|                | Planner                          | Chooses strategy per task: direct answer, ReAct loop, plan-and-execute, graph search, or multi-agent; re-plans on failure    |
|                | Task Contract Store              | Versioned acceptance criteria so success is machine-checkable                                                                |
| **Execution**  | Durable Runtime                  | Checkpointed workflows (Temporal-class); resume after crash, deterministic replay, timers, signals                           |
|                | Agent Runtime                    | Runs agent loops with step, token, cost and time budgets; spawns sub-agents with inherited-but-reduced authority             |
|                | Scheduler and Queues             | Priority, fairness per tenant, back-pressure, cron/event triggers, preemption for urgent tasks                               |
|                | Sandbox Manager                  | Firecracker/gVisor microVMs for code execution and computer-use; recorded sessions; no host access                           |
| **Cognition**  | Model Router                     | Picks model by task type, risk, latency, cost, data class; fallback chains, hedged requests, semantic cache                  |
|                | Context Engine                   | Assembles the prompt: retrieval, compaction, summarisation, prompt-cache layout, tool-result trimming                        |
|                | Memory System                    | Working, episodic, semantic, procedural and shared stores with consolidation, decay and per-tenant isolation                 |
|                | Reasoning Modes                  | Self-consistency, reflection, verifier models, debate, best-of-N, test-time compute scaling by risk tier                     |
| **Capability** | Tool Registry (MCP)              | Typed, versioned, permissioned tools with schemas, rate limits, cost, side-effect class and compensation actions             |
|                | Skill Library                    | Reusable procedures (see section 6) loaded on demand                                                                         |
|                | Agent Directory (A2A)            | Discovery of internal and partner agents via capability cards                                                                |
| **Governance** | Policy Decision Point            | OPA/Cedar decisions on every tool call, data access, spend and spawn                                                         |
|                | Guardrails and Injection Defence | Input/output screening, taint tracking, quarantined parsing of untrusted content, egress allow-lists                         |
|                | Human-in-the-Loop                | Approval gates by risk tier, escalation, reviewer UI, timeout behaviour                                                      |
| **Learning**   | Observability and Trace Store    | OpenTelemetry GenAI traces, cost ledger, tamper-evident audit log                                                            |
|                | Eval Engine                      | Golden sets, simulators, LLM-as-judge with calibration, regression gates, canary and shadow runs                             |
|                | Optimiser                        | Programmatic prompt/skill optimisation (DSPy-style), router tuning from outcomes; changes ship only through eval gates       |


## 3. Protocol matrix


| Need               | Protocol / standard                                                   | Role in the core                                                                      |
|--------------------|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| Agent to tool      | **MCP** (Model Context Protocol)                                      | All tools exposed and consumed as MCP servers; gateway adds auth, quotas, audit       |
| Agent to agent     | **A2A** (Agent2Agent)                                                 | Capability cards, task delegation, streaming results across vendors and organisations |
| Agent to UI        | **AG-UI** style event streams, SSE/WebSocket                          | Streams tokens, tool calls, state diffs and approval requests to any frontend         |
| Skills packaging   | Folder-based skill format (SKILL.md plus scripts/resources)           | Portable, versioned procedures with progressive disclosure                            |
| Model access       | OpenAI-compatible API plus native provider SDKs                       | Single Model Port; provider quirks stay in adapters                                   |
| Service calls      | gRPC / Connect, Protobuf, JSON Schema, OpenAPI                        | Internal contracts; schema registry with compatibility checks                         |
| Events             | CloudEvents over NATS/Kafka                                           | Triggers, state changes, audit streams                                                |
| Identity           | SPIFFE/SPIRE, OIDC, OAuth 2.1, token exchange (RFC 8693), DPoP        | Workload and agent identity; delegated, down-scoped tokens per task                   |
| Policy             | OPA (Rego) or Cedar                                                   | Central, testable, versioned authorisation                                            |
| Telemetry          | OpenTelemetry + GenAI semantic conventions, W3C Trace Context         | One trace across agents, tools, models and Om Sanchar hops                            |
| Real-time media    | WebRTC, gRPC streams                                                  | Voice, screen share and video to multimodal models                                    |
| Transport security | mTLS, hybrid post-quantum key exchange (ML-KEM), WireGuard            | Quantum-resilient links ahead of the 2030s                                            |
| Verifiability      | W3C Verifiable Credentials / DIDs, signed provenance (C2PA for media) | Prove which agent did what; trusted partner-agent identity                            |


## 4. Methodology library

- **Reasoning loops:** ReAct, plan-and-execute, ReWOO (plan without observation), reflection/self-critique, CodeAct (act through code), tree and graph search, Monte-Carlo-style rollout for high-stakes decisions.
- **Multi-agent patterns:** supervisor-worker, handoff chains, blackboard, parallel fan-out/fan-in, debate with judge, market/auction for resource allocation, role-based crews. Each is a template with budgets and exit rules.
- **Reliability patterns:** idempotency keys, saga with compensating actions, outbox, circuit breakers, bulkheads, hedged requests, deadlines and cancellation propagation.
- **Context patterns:** hierarchical summarisation, retrieval with reranking, query decomposition, graph-RAG for relational data, tool-result compaction, cache-friendly prompt layout.
- **Quality patterns:** verifier models, self-consistency voting, structured outputs with schema validation and repair, rubric-based judging with human calibration samples.
- **Operating methods:** contract-first design, trunk-based CI with eval gates, canary and shadow deployments, SRE error budgets, blameless post-incident reviews, chaos testing of tools and models.

## 5. Core contracts (stable for 12 years)

    class Model(Protocol):
        def generate(self, req: ModelRequest) -> Stream[ModelEvent]: ...
        capabilities: ModelCaps          # modalities, context, tools, cost, data_class

    class Tool(Protocol):
        spec: ToolSpec                   # JSON Schema in/out, side_effect, cost, idempotent
        def call(self, args, grant: Grant, ctx: TraceCtx) -> ToolResult: ...
        def compensate(self, call_id: str) -> None: ...

    class Skill(Protocol):
        manifest: SkillManifest          # name, version, triggers, tools_needed, evals
        def load(self, level: int) -> Context: ...   # progressive disclosure

    class Agent(Protocol):
        def step(self, state: State, budget: Budget) -> Decision: ...  # pure given state

    class Memory(Protocol):
        def recall(self, q: Query, scope: Scope) -> list[Item]: ...
        def write(self, item: Item, scope: Scope) -> None: ...
        def consolidate(self) -> None: ...

    class Policy(Protocol):
        def decide(self, principal, action, resource, context) -> Decision: ...

Every adapter (LangGraph, CrewAI, LlamaIndex, Haystack, Semantic Kernel, future frameworks) implements these. A framework is admitted only if it passes the conformance test suite.

## 6. Skills system

- A skill is a versioned package: instructions, optional scripts, reference files, required tools, test cases, and an owner. Only its short description is always in context; full instructions load when triggered.
- Lifecycle: draft → eval on golden tasks → security scan → sign → publish to registry → canary → default. Skills carry a permission manifest and cannot exceed it.
- Agents can propose new skills from successful traces; a human or a verifier agent must approve before publication.
- Starter skills: document and spreadsheet generation, code review, SQL analysis, browser/computer-use tasks, CRM and ERP actions, Hindi/Indic-language support, compliance checks, report building.

## 7. Memory architecture


| Type       | Holds                                     | Store                          | Rules                                                                   |
|------------|-------------------------------------------|--------------------------------|-------------------------------------------------------------------------|
| Working    | Current task state and scratchpad         | Durable runtime state          | Discarded or summarised at task end                                     |
| Episodic   | What happened: runs, outcomes, feedback   | Trace store + vector index     | Time decay; sampled for learning                                        |
| Semantic   | Facts, documents, entities, relationships | Vector DB + graph + relational | Source citation and freshness tags                                      |
| Procedural | How-to: skills, playbooks, tuned prompts  | Skill registry                 | Versioned, eval-gated                                                   |
| Shared     | Team and cross-agent knowledge            | Namespaced stores              | Per-tenant isolation, explicit sharing grants, right-to-erasure support |


Memory is exportable in an open format so customers are never locked in, and swappable stores sit behind the Memory contract.

## 8. Security model

- **Agent identity:** every agent instance gets a workload identity and a per-task token derived from the user's authority, always narrower than the user's.
- **Prompt-injection defence in depth:** treat all retrieved or tool-returned content as untrusted data; taint tracking so tainted text cannot trigger privileged tools; quarantined low-privilege model parses untrusted input; privileged planner never sees raw untrusted content; strict output schemas.
- **Blast-radius control:** side-effect classes (read, reversible write, irreversible, financial, external-communication) map to approval rules; irreversible and financial actions need human or dual-agent approval.
- **Sandboxing:** code and computer-use run in disposable microVMs with deny-by-default network and filesystem; recorded and replayable.
- **Audit:** append-only, hash-chained logs of every decision, tool call and approval; exportable for SOC 2, ISO 27001, DPDP and EU AI Act evidence.
- **Supply chain:** signed skills and MCP servers, SBOM, licence scanning, pinned versions, provenance checks.

## 9. Evaluation and continuous improvement

- **Tiers:** unit (tools), scenario (workflows), golden set (answer quality), simulation (synthetic users and adversaries), production shadow comparison.
- **Metrics:** task success rate, cost per task, p95 latency, tool error rate, human-escalation rate, safety violations, regression delta per release.
- **Model swap protocol:** any new model must beat or match the incumbent on your golden sets at equal or lower cost before routing shifts; shift gradually by traffic percentage.
- **Learning loop:** failed traces are clustered, turned into new eval cases, and used to tune prompts, skills and routing, never to silently change production behaviour.

## 10. Twelve-year horizon plan


| Horizon       | Expected shift                                                                                                                                   | Core response                                                                                                                                                                                          |
|---------------|--------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **2026–2028** | Agents become routine; MCP and A2A mature; cheaper strong models; computer-use reliable                                                          | Ship full core with adapters; eval-gated routing; Indic-language skills; MCP servers for all products                                                                                                  |
| **2029–2032** | Long-horizon autonomous work (days); on-device and edge models; agent-to-agent commerce; stricter AI regulation; post-quantum migration          | Durable runtime tuned for multi-day tasks; federation to edge nodes; agent identity with verifiable credentials and spend limits; hybrid PQ crypto default; compliance-as-code                         |
| **2033–2038** | New architectures beyond today's transformers; agent ecosystems across organisations; embodied and robotic tools; heavy automation of operations | Model Port abstracts architecture changes; tool contracts extend to physical actuators with stronger safety classes; cross-org trust frameworks; continuous automated re-evaluation of every component |


Re-run an architecture review every 6 months: for each protocol, framework and model, ask "is it still the best option, and how cheaply can we replace it?"

## 11. Maturity ladder and build order


| Level | Capability                                                                              | Gate                                                  |
|-------|-----------------------------------------------------------------------------------------|-------------------------------------------------------|
| M1    | Contracts, Model Router, MCP tool calls, one framework adapter, tracing                 | One real workflow, fully traced                       |
| M2    | Durable runtime, policy engine, memory, guardrails, eval CI                             | Crash-resume and unauthorised-action tests pass       |
| M3    | Multi-agent patterns, A2A, skills registry, sandboxed computer-use, HITL UI             | Cross-agent task with audit trail; skill canary works |
| M4    | Optimiser loop, federation to edge/client sites, multi-tenant billing, compliance packs | Paying tenants; external audit readiness              |
| M5    | Autonomous long-horizon operations, verifiable agent identity, post-quantum default     | Multi-day tasks at agreed safety and cost targets     |


## 12. Where this can genuinely beat incumbents

- **Vendor-neutral by design:** big providers optimise for their own models; you route across all of them, including self-hosted.
- **Sovereign deployment:** runs inside a client's infrastructure with full audit, which regulated and Indian enterprises need.
- **Governed autonomy:** policy, approvals and replayable audit built in, not bolted on.
- **Domain depth:** skills and MCP servers for BPO/KPO, ERP, marketing and cybersecurity workflows, in Indic languages, that generic platforms lack.

**Biggest execution risk:** trying to build every subsystem at once. Reach M1 and M2 with one vertical workflow before expanding.
