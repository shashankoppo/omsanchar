

Evolucentsphere · Om Sanchar · Orchestration Core · Volume 2 (v1.1)


# Merged Deep Specification

What the leading labs and platforms do, distilled into one vendor-neutral core, plus the subsystems Volume 1 left out.


**Read this first.** Internal orchestration code at OpenAI, Google, Microsoft, xAI, DeepSeek and others is proprietary. This volume merges what they have **publicly** shipped or documented (SDKs, protocols, model cards, papers) through mid-2026, and checked against current sources where possible. Claims about Grok and Oracle rest on general public knowledge; verify before relying on them. "Most powerful ever built" cannot be proven on paper; the measurable target is in section 13.


## 1. What each leader contributes (public patterns)


| Source              | Public pattern                                                                                                                                                                         | What the merged core adopts                                                                                                                                              |
|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **OpenAI**          | Agents SDK: thin primitives (agents, handoffs, guardrails, sessions, built-in tracing); Responses and Realtime APIs; MCP support                                                       | Handoff as a first-class primitive; guardrails running in parallel with the agent; tracing on by default; speech-to-speech path                                          |
| **Anthropic**       | Agent SDK with hooks, subagents, MCP and skills on the same harness as its coding agent; hosted managed runtime; computer use; context compaction and prompt caching                   | Lifecycle hooks (pre/post tool, on-stop) as policy insertion points; subagents with isolated context; skills with progressive disclosure; sandboxed hosted-runtime model |
| **Google**          | ADK: hierarchical agent trees, A2A Agent Cards, Vertex Agent Engine, native multimodal and live audio/video                                                                            | A2A for federation; root-to-sub-agent delegation; multimodal as native input, not an add-on                                                                              |
| **Microsoft**       | Agent Framework merging AutoGen (conversational teams) and Semantic Kernel (enterprise SDK); enterprise identity and Azure integration                                                 | Conversation-style team patterns plus enterprise plugins; agent identity tied to directory/IAM; .NET and Python parity                                                   |
| **Moonshot Kimi**   | K2.5 Agent Swarm: self-directed swarm of up to 100 sub-agents and about 1,500 coordinated steps, trained with parallel-agent reinforcement learning rather than hand-written workflows | Dynamic swarm planner (section 3); parallelism measured by wall-clock gain; context-discard strategies for long tasks                                                    |
| **DeepSeek**        | Open-weight, cost-efficient reasoning models with tool use in thinking mode                                                                                                            | A cheap self-hosted reasoning tier in the router; open-weight fallback to avoid API dependence                                                                           |
| **xAI Grok**        | Live-data search tools; parallel multi-agent "heavy" reasoning for hard problems; very large compute                                                                                   | Real-time data tool class; parallel test-time compute reserved for high-risk or hard tasks                                                                               |
| **SpaceX**          | Not a public AI-orchestration vendor. Known for engineering doctrine: redundancy, test-as-you-fly, telemetry on everything, fast iterate-and-learn loops, simulation first             | Reliability doctrine in section 11 (redundant paths, chaos and flight-sim style testing, telemetry-driven fixes)                                                         |
| **Oracle**          | Managed agents and RAG close to the database; in-database vector search; sovereign and dedicated cloud regions                                                                         | Compute-to-data retrieval with database-enforced permissions; sovereign deployment option                                                                                |
| **Open frameworks** | LangGraph (typed-state graphs), CrewAI (roles and Flows), LlamaIndex (data), Pydantic AI (typed outputs), Smolagents (code actions)                                                    | Behind adapters only; graph state for control flow, roles for team design                                                                                                |


Industry comparisons note that several vendor SDKs are provider-specific and hard to migrate away from, which is exactly why this core keeps its own contracts and treats every SDK as a replaceable adapter.

## 2. Merged request lifecycle (the spine)

1.  **Ingress:** channel adapter (web, WhatsApp, voice, email, API, event) authenticates and creates a Task with tenant, user, risk tier, budget, deadline.
2.  **Policy pre-check:** identity, data class, spend, allowed tools; reject or require approval early.
3.  **Intent and plan:** planner picks strategy (direct, ReAct, plan-and-execute, graph, swarm) using task features and past outcomes.
4.  **Context build:** memory recall, RAG retrieval with permission filters, skill descriptions, cache-friendly layout.
5.  **Route:** model router selects tier (local small, local reasoning, premium API) by risk, latency, data class and cost.
6.  **Execute loop:** agent steps inside the durable runtime; hooks fire before and after every tool call.
7.  **Parallel guardrails:** input/output screening and injection checks run alongside, able to halt.
8.  **Tool call:** through MCP gateway with scoped grant, rate limit, sandbox if code or UI.
9.  **Delegation:** handoff, subagent spawn, swarm fan-out, or A2A call with reduced authority and child budgets.
10. **Verify:** acceptance criteria check, verifier model or tests, groundedness check for RAG answers.
11. **Approval gate:** human or dual-agent sign-off for irreversible, financial or external-communication actions.
12. **Deliver:** streamed to the channel; artifacts stored with provenance.
13. **Record:** trace, cost ledger, audit chain, memory consolidation.
14. **Learn:** outcome signals feed evals, router tuning and skill proposals (gated).

## 3. Swarm Engine


| Element          | Specification                                                                                                                                                                                    |
|------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Triggers         | Wide parallelisable work (research across many sources, bulk document processing, large code or data audits, multi-site checks). Not used for small or sequential tasks.                         |
| Decomposition    | Planner emits a task DAG with independent shards, expected cost and merge rule; supports dynamic re-sharding. Later: learned decomposition from outcome data.                                    |
| Worker model     | Lightweight workers with narrow skills and tool allow-lists; cheap models by default; isolated context per worker.                                                                               |
| Coordination     | Blackboard shared state plus event bus on Om Sanchar; optional peer mesh for decentralised workers; leader election and heartbeat for coordinators.                                              |
| Consensus        | Merge strategies: union, vote, weighted vote by verifier score, judge agent, human arbitration for conflicts.                                                                                    |
| Budget control   | Global and per-worker caps on cost, steps, depth and time; fan-out limit (default 25, ceiling configurable); automatic kill on runaway or duplicate work.                                        |
| Failure handling | Straggler timeout and hedge, retry with a different model, partial-result return with coverage report.                                                                                           |
| Metrics          | Speed-up versus single agent, cost multiplier, coverage, duplicate rate, merge conflict rate. A swarm must beat the single-agent baseline on speed and quality or the planner stops choosing it. |


## 4. RAG and knowledge pipeline


| Stage           | Specification                                                                                                                                                                   |
|-----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Ingest          | Connectors: Drive, SharePoint, email, CRM/ERP, web, databases, uploads; change-data-capture for freshness; dedupe and versioning.                                               |
| Parse           | Layout-aware parsing for PDFs, tables, forms, slides; OCR including Indic scripts; image and diagram captions; audio and video transcripts.                                     |
| Chunk           | Hierarchical (document, section, passage) with semantic boundaries; table-aware; metadata: owner, ACL, date, source, language, sensitivity.                                     |
| Embed and index | Multilingual embeddings (Hindi, English, code-mixed); hybrid index: dense vectors + BM25 + knowledge graph for entities; per-tenant namespaces.                                 |
| Retrieve        | Query rewriting and decomposition, hybrid search, reranker, ACL filter applied inside the store, recency boost, multi-hop via graph, agentic retrieval when first pass is weak. |
| Generate        | Answers cite sources with passage links; abstain when evidence is weak; structured outputs for downstream tools.                                                                |
| Verify          | Groundedness check (every claim traceable to a passage), contradiction detection, freshness warning.                                                                            |
| Evaluate        | Recall@k, MRR, faithfulness, answer relevance, citation precision, latency, cost; golden Q&A sets per tenant; drift alerts when sources change.                                 |
| Compute-to-data | For sensitive or sovereign clients, run retrieval inside their database or network and send only minimal context to the model.                                                  |


## 5. Voice and real-time stack

- **Paths:** (a) cascaded: streaming speech-to-text → LLM → streaming text-to-speech, for control and Indic quality; (b) native speech-to-speech models for lowest latency; the router picks per use case.
- **Latency budget:** target under 800 ms from end of user speech to first audio; stream everything; speculative response start; prompt-cache the system context.
- **Conversation control:** voice activity detection, barge-in (user interrupts), backchannel handling, turn-taking, silence and noise handling, DTMF fallback.
- **Languages:** Hindi, English, Hinglish code-switching, and major Indian languages; accent robustness; domain vocabulary biasing (product names, places).
- **Telephony and apps:** SIP/PSTN trunks, WhatsApp calling where available, WebRTC for web and mobile, call transfer to humans with context hand-off.
- **Safety and compliance:** spoken consent and recording notices, PII redaction in transcripts, telecom-regulation checks (verify current TRAI rules), voice-cloning misuse controls and caller disclosure that it is an AI.
- **Screen and video:** screen-share frames sampled and streamed to multimodal models; live co-browsing agent in a sandbox with visible action log.

## 6. Autonomy levels and kill switch


| Level | Behaviour                                                                    | Typical use                                     |
|-------|------------------------------------------------------------------------------|-------------------------------------------------|
| A0    | Answer only, no tools                                                        | FAQ, public chat                                |
| A1    | Read-only tools                                                              | Search, reports, analysis                       |
| A2    | Drafts actions; human executes                                               | Emails, invoices, code PRs                      |
| A3    | Executes reversible actions; asks before irreversible                        | CRM updates, scheduling, deployments to staging |
| A4    | Executes within policy and budget; samples reviewed after the fact           | Routine back-office automation                  |
| A5    | Long-horizon goals with periodic check-ins and strict spend and scope fences | Multi-day research or operations projects       |


Autonomy is set per tenant, agent, tool and risk class, and earned by evidence: an agent moves up a level only after meeting eval and incident thresholds. Global, tenant and per-agent **kill switches** revoke grants within seconds, halt workflows safely (checkpoint, then compensate), and are drill-tested monthly.

## 7. Channels layer

Adapters for WhatsApp Business, email, SMS, voice/telephony, Telegram, Slack/Teams, web chat widget, mobile SDK, REST/webhooks, and event triggers. Each adapter handles identity linking, message formatting, rate limits, opt-in and opt-out rules, delivery receipts, templates and media, and maps every inbound message to the same Task contract. Conversation continuity follows the person across channels via a tenant-scoped identity graph.

## 8. Training and data flywheel

- **Data capture:** consented, de-identified traces, tool outcomes, human corrections and approvals, thumbs and edits.
- **Curation:** automatic quality scoring, deduplication, PII scrub, licence and consent tags, per-tenant data boundaries (no cross-tenant training without explicit contract).
- **Improvement ladder, cheapest first:** prompt and skill optimisation → retrieval tuning → router tuning → preference-data collection → LoRA/adapter fine-tuning of open-weight models → distillation of premium behaviour into small local models → reinforcement learning on verifiable tasks.
- **Gates:** every new model, adapter or prompt passes golden sets, safety suites and shadow runs, then canary; instant rollback.
- **Synthetic data:** simulators and scenario generators for rare cases and red-team coverage, always validated against real traces.

## 9. Developer platform


| Component               | Contents                                                                                                                 |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------|
| SDKs                    | Python and TypeScript first, then Go and Java/.NET; typed clients generated from contracts                               |
| CLI and local runtime   | Scaffold agents, run offline with local models, replay traces, run evals, publish skills                                 |
| Visual builder          | No-code workflow and agent canvas that compiles to the same typed definitions (never a separate runtime)                 |
| Registry                | Skills, tools (MCP servers), agents, prompts, eval sets; semantic versions, signatures, ratings, permission manifests    |
| Playground and debugger | Step-through traces, time-travel to any checkpoint, what-if reruns with a different model or prompt                      |
| Templates               | Support agent, sales assistant, research swarm, document processor, voice receptionist, DevOps agent, compliance checker |
| Docs and academy        | Quickstarts, reference, cookbooks, architecture guides, certification for partners and resellers                         |


## 10. Governance, privacy and cost

- **Data governance:** classification at ingest, PII detection and redaction before model calls, data lineage from answer back to source, residency per tenant, retention and erasure workflows (DPDP, GDPR).
- **Model governance:** model cards and approved-model lists, per-data-class routing rules, licence tracking for open-weight models, exit plan for each provider.
- **AI risk management:** maintain a risk register mapped to NIST AI RMF, ISO/IEC 42001 and EU AI Act obligations; human oversight evidence recorded automatically.
- **FinOps:** cost ledger per tenant, agent, tool and model; budgets with soft and hard limits; anomaly alerts; unit economics (cost per resolved task); prompt-cache and semantic-cache hit-rate targets; scale-to-zero for idle GPUs.
- **Inference serving:** vLLM or SGLang with continuous batching, quantisation, speculative decoding, prefix caching; autoscaling and multi-region failover.

## 11. Reliability doctrine (SpaceX-style engineering applied to software)

- **Redundancy:** at least two independent model providers and two inference paths per critical function; automatic failover tested weekly.
- **Test as you fly:** staging uses production-identical policies and data shapes; simulation environments replay real traces against new versions.
- **Telemetry on everything:** every step traced; incidents trigger new eval cases, so each failure becomes a permanent test.
- **Fault isolation:** bulkheads per tenant and per tool; one failing tool or runaway agent cannot take down the platform.
- **Chaos and game days:** inject model outages, slow tools, poisoned documents and malicious prompts on a schedule.
- **Fast iteration with guardrails:** small frequent releases, error budgets, automatic rollback on SLO breach.

## 12. Requirement coverage (your checklist)


| Requirement                                    | Where specified                                                           |
|------------------------------------------------|---------------------------------------------------------------------------|
| Swarm                                          | Section 3 (this volume); Vol. 1 sections 4 and 6 for multi-agent patterns |
| RAG                                            | Section 4; memory in Vol. 1 section 7                                     |
| Voice and real-time                            | Section 5                                                                 |
| Autonomous                                     | Section 6; durable runtime in Vol. 1                                      |
| API-first and modular                          | Vol. 1 sections 1 and 5; developer platform here, section 9               |
| Protocols (MCP, A2A, AG-UI, OTel, SPIFFE, OPA) | Vol. 1 section 3                                                          |
| Channels (WhatsApp, telephony, email)          | Section 7                                                                 |
| Training and fine-tuning                       | Section 8                                                                 |
| Security, governance, compliance               | Vol. 1 section 8; section 10 here                                         |
| Reliability and cost control                   | Sections 10 and 11                                                        |
| Distributed user-device compute                | Platform blueprint section 4 (opt-in only)                                |


## 13. How "best" gets proven, and what to build first

- **Benchmarks to publish internally:** task success on your own golden sets, agentic benchmarks for browsing and coding, RAG faithfulness, voice latency, cost per resolved task, swarm speed-up, recovery time after failure injection.
- **Beat incumbents where it is real:** vendor neutrality, sovereign deployment, governed autonomy, Indic and Hinglish depth, and Indian business workflows.
- **Build order:** M1 core and one workflow → M2 durability, policy, RAG → channels (WhatsApp and email) → voice → swarm → training flywheel → developer platform. Do not start swarm or training before evals and tracing are solid; they amplify mistakes.
- **Review cadence:** every 6 months re-score each protocol, framework and model against alternatives, and replace anything that is no longer the best at acceptable switching cost.
