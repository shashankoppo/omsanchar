

Evolucentsphere · Om Sanchar · Volume 3


# Bare-Metal Stack and Open-Source Catalog

From a single GPU workstation to rack-scale clusters, owned hardware end to end, with every layer's best open-source default.


**Scope.** Engineering only; compliance is owned by your team. Hardware facts reflect public reports through mid-2026 and change fast: Blackwell (B200, B300, GB300 NVL72) is shippable now, Vera Rubin began shipping in Q3 2026 with volume ramping in Q4 and long allocation queues into 2027, AMD MI350X is available and MI400 is arriving. Cost and power figures below are order-of-magnitude estimates; get vendor quotes. "Most powerful on the planet" means the frontier labs' billion-dollar clusters; this plan gives you the same architecture at a scale your budget can grow into, tier by tier.


## 1. Capacity tiers


| Tier              | Hardware                                                                                          | What it runs (estimates)                                                                                                  | Role                                   |
|-------------------|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| **T0** Dev        | 1–4 workstation GPUs (e.g. 96 GB Blackwell workstation cards or L40S-class), 256–512 GB RAM, NVMe | 7B–70B quantised models, embeddings, voice, rerankers, all development and CI evals                                       | Build and test the whole stack offline |
| **T1** Node       | One 8-GPU server (H200, B200, B300 or AMD MI355X class), 2 TB RAM, 30+ TB NVMe, 400G NICs         | Up to ~700B-parameter FP8 or ~1T-parameter MoE in 4-bit, with KV-cache headroom; high-throughput 70B serving              | First production inference             |
| **T2** Cluster    | 4–16 nodes (32–128 GPUs), 400/800G InfiniBand or RoCE fabric, parallel file system                | Several frontier-class open models concurrently, fine-tuning and RL, 100s of concurrent agents or swarms                  | Production plus training               |
| **T3** Rack-scale | GB300 NVL72 or Vera Rubin NVL72 (72 GPUs on one NVLink domain)                                    | Largest MoE models with expert parallelism, long-context reasoning at scale, serious pretraining or continued pretraining | Frontier-class capacity                |
| **T4** Federation | Multiple pods in several sites plus edge nodes and cloud burst, all joined by Om Sanchar          | Geo-redundant serving, data-local inference, burst for peaks                                                              | Resilience and reach                   |


- **Sizing rule:** weight memory ≈ parameters × bytes per weight (FP16 2, FP8 1, FP4/int4 0.5); add 20–40% for KV cache, activations and batching. Long context and high concurrency raise KV cost sharply.
- **Buying advice:** buy Blackwell-class now (reported 8–12 week lead time for 8-GPU systems; custom NVL72 racks 40+ weeks), keep software hardware-agnostic (ROCm and CUDA paths) so Rubin or MI400 drop in later. H100/H200 remain easier to source.
- **Cost order of magnitude:** an 8-GPU Blackwell-class server is typically several hundred thousand USD; an NVL72 rack runs into millions; networking, storage, power and cooling add roughly 20–40%. Owning beats renting when utilisation stays above roughly 50–60% for 2–3 years; below that, rent or burst.

## 2. Facility, power and cooling

- **Power per unit (approx.):** 8-GPU Hopper node ~10 kW, Blackwell node ~14 kW, NVL72 rack ~120–140 kW. Plan 2N or N+1 feeds, UPS plus battery backup units, generators, and per-rack metering.
- **Cooling:** air cooling is fine to roughly 20–30 kW per rack; above that use direct-to-chip liquid cooling with CDUs (mandatory for NVL72), rear-door heat exchangers as a bridge. Target PUE under 1.3.
- **Siting:** a Tier III+ colocation hall with high-density racks in a major Indian hub (low latency, strong power) is faster than building your own; keep your own cage, cages locks and remote hands. Add a second site 500+ km away for DR.
- **Physical:** structured cabling plan, hot/cold aisle, leak detection, fire suppression suitable for electronics, environmental sensors feeding the same observability stack.

## 3. Network


| Fabric                 | Design                                                                                                                                                                                                        |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Compute (GPU to GPU)   | Rail-optimised leaf-spine, 400G (later 800G) InfiniBand NDR/XDR or lossless RoCEv2 Ethernet; one NIC per GPU; adaptive routing, in-network reduction where supported; NCCL/RCCL tuned and continuously tested |
| Storage                | Separate 200–400G Ethernet or IB; GPUDirect Storage; dedicated to checkpoints, datasets and vector stores                                                                                                     |
| Front-end and services | 25–100G Ethernet; BGP with ECMP; anycast ingress; DDoS scrubbing; WAF; CDN for static and edge caching                                                                                                        |
| Management (OOB)       | Isolated 1G/10G network for BMC/Redfish, PDUs, switches, console servers; reachable only via hardened jump hosts                                                                                              |
| Overlay                | Om Sanchar (LibP2P, WireGuard tunnels, mTLS) between pods, sites, edge and partner networks; zero-trust segmentation with microsegmentation at the host                                                       |


## 4. Storage

- **Hot tier:** local NVMe on nodes for model weights, KV-cache spill and scratch.
- **Shared parallel file system:** WEKA, Lustre, BeeGFS or GPFS-class for datasets and checkpoints (async checkpointing, sharded and resumable).
- **Object store:** Ceph (RGW) or MinIO-class for artifacts, models, logs, backups, with erasure coding and versioning.
- **Databases:** Postgres (Patroni HA) with pgvector, Qdrant/Milvus/Weaviate for large vector sets, OpenSearch for text, Neo4j or similar for graphs, ClickHouse for traces and analytics, Redis/Valkey for cache, NATS JetStream or Kafka for events.
- **Protection:** 3-2-1 backups with an offline or immutable copy, tested restores monthly, snapshots before every schema or model change.

## 5. Provisioning, OS and fleet management

- **Bare-metal lifecycle:** MAAS, Tinkerbell, Metal3/Ironic or Foreman for PXE and imaging; NetBox as source of truth for racks, cables, IPs and assets; Redfish/IPMI for power and firmware.
- **OS:** minimal immutable Linux (Talos, Flatcar or hardened Ubuntu/RHEL) with pinned kernel, GPU driver and CUDA/ROCm versions; image-based upgrades with canary racks.
- **Everything as code:** OpenTofu/Terraform, Ansible, Argo CD or Flux for GitOps; no manual node changes; drift detection.
- **Hardware trust:** secure boot, TPM attestation of nodes before they join the cluster, firmware inventory and signed updates, HSM for root keys, disk encryption with remote key release.
- **Burn-in:** every new GPU node passes stress, memory, NCCL all-reduce and thermal tests before entering the pool; lemon nodes are cordoned automatically.

## 6. Cluster scheduling and GPU operations

- **Kubernetes** with NVIDIA GPU Operator (or AMD GPU Operator), device plugins/Dynamic Resource Allocation, DCGM exporter, MIG or MPS slicing for small workloads, topology-aware placement (NVLink domains, rails).
- **Batch and queueing:** Kueue, Volcano or NVIDIA KAI/Run:ai-style schedulers for gang scheduling, fair share, quotas per tenant, preemption and backfill; Slurm (or SUNK-style Slurm-on-Kubernetes) for large training jobs; Ray for distributed Python and agent workloads.
- **Priority classes:** interactive and voice inference highest, batch inference, then fine-tuning, then evals and experiments; automatic preemption with checkpoint-and-resume.
- **Autoscaling:** by queue depth, tokens per second and time-to-first-token SLO; scale-to-zero for idle small models; cloud burst when the on-prem pool saturates.
- **Health:** XID/ECC error handling, automatic drain and reschedule, thermal and power capping policies, spare nodes (N+1 per 16).

## 7. Inference platform


| Capability            | Default                                                                                  | Notes                                                                |
|-----------------------|------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| Serving engines       | vLLM, SGLang; TensorRT-LLM on NVIDIA for peak throughput; llama.cpp for CPU/edge         | Run more than one; pick per model by benchmark                       |
| Disaggregated serving | Separate prefill and decode pools (NVIDIA Dynamo, llm-d or vLLM disaggregation)          | Improves latency and utilisation at scale                            |
| KV cache              | Prefix caching, LMCache-style tiering to CPU RAM and NVMe                                | Large win for agents that reuse long system prompts and tool schemas |
| Parallelism           | Tensor, pipeline, data and expert parallelism for MoE                                    | Match to NVLink domain size                                          |
| Speed tricks          | FP8/FP4 quantisation, speculative decoding, continuous batching, chunked prefill         | Validate quality on your golden sets after each change               |
| Adapters              | Multi-LoRA serving: thousands of tenant adapters on one base model                       | Cheap per-tenant customisation                                       |
| Gateway               | OpenAI-compatible API plus router (cost, latency, data class, fallback to external APIs) | Single entry for the Orchestration Core's Model Port                 |
| Specialist models     | Embeddings, rerankers, ASR (Whisper-class), TTS, vision, OCR, guard models               | Smaller dedicated GPUs or MIG slices                                 |


## 8. Training and improvement stack

- **Frameworks:** PyTorch with FSDP2, DeepSpeed, Megatron-LM or NVIDIA NeMo for large runs; Axolotl, Unsloth, TRL and LLaMA-Factory for fine-tuning; verl or OpenRLHF for reinforcement learning on verifiable tasks.
- **Data:** Ray Data/Spark for pipelines, dedupe and quality scoring, versioned datasets (DVC, lakeFS), synthetic data generators validated against real traces.
- **Experiment control:** MLflow or Aim (self-hosted), reproducible configs, seed and data lineage, automated eval after every run.
- **Resilience:** frequent sharded checkpoints, elastic restarts, straggler detection, loss-spike alarms.
- **Path:** start with LoRA on open-weight models, distil premium-model behaviour into small local models, add RL on tasks with checkable outcomes, consider continued pretraining only when you own proprietary data at scale.

## 9. Observability and SRE for hardware and models

- **Stack:** OpenTelemetry, Prometheus/Mimir, Grafana, Loki, Tempo, ClickHouse; DCGM and node exporters; switch and fabric telemetry (counters, congestion, link flaps); power and temperature per rack.
- **Golden signals per layer:** GPU utilisation and memory, tokens/s, time-to-first-token, queue depth, cache hit rate, NCCL bandwidth, storage latency, error budgets, cost per million tokens.
- **Operations:** on-call rotation, runbooks, game days (pull a node, cut a link, fail a site), blameless reviews feeding new automated checks.
- **Targets:** serving availability 99.9%+ (99.95% for voice), RPO under 5 minutes for databases, RTO under 30 minutes for the control plane, under 4 hours for full-site failover.

## 10. Hardware-level security and isolation

- Confidential computing where supported (NVIDIA Hopper/Blackwell confidential mode, AMD SEV-SNP, Intel TDX) for tenants who need hardware-isolated inference.
- Per-tenant network namespaces, separate GPU partitions (MIG) or dedicated nodes for high-sensitivity clients; no shared KV caches across tenants.
- Sandboxed agent execution in microVMs (Firecracker, Kata, gVisor) on a separate untrusted pool with deny-by-default egress.
- Supply-chain integrity: signed images and models, reproducible builds, SBOMs, internal mirrors of every dependency so builds never fetch from the open internet.

## 11. Hybrid burst and exit options

Keep every workload packaged as the same container images and Helm/GitOps definitions so the stack runs on rented GPUs (hyperscaler or specialist GPU clouds) with no code change. Use rented capacity for training spikes, new-hardware trials and overflow; keep sensitive and steady-state serving on owned metal. Also keep a documented path to move between NVIDIA and AMD.

## 12. Open-source catalog by layer


| Layer                          | Primary choice                                         | Alternatives                                                                                                                                          |
|--------------------------------|--------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Orchestration and agents       | LangGraph, CrewAI (behind own adapters)                | LlamaIndex, Haystack, Semantic Kernel/Microsoft Agent Framework, AutoGen/AG2, Pydantic AI, Smolagents, OpenAI Agents SDK (model-agnostic), Google ADK |
| Durable execution              | Temporal                                               | Restate, Inngest, Argo Workflows, Prefect, Dagster                                                                                                    |
| Visual builders                | Dify, n8n                                              | Langflow, Flowise                                                                                                                                     |
| Memory                         | Mem0, Letta                                            | Zep, custom on Postgres + vector DB                                                                                                                   |
| RAG and parsing                | LlamaIndex + Docling                                   | Unstructured, Haystack, RAGFlow, Marker                                                                                                               |
| Vector and search              | pgvector, Qdrant                                       | Milvus, Weaviate, OpenSearch, Vespa, Neo4j (graph)                                                                                                    |
| Model families (open weights)  | Llama, Qwen, DeepSeek, Kimi, Mistral                   | GLM, Gemma, gpt-oss and newer releases; check each licence for commercial use                                                                         |
| Serving                        | vLLM, SGLang                                           | TensorRT-LLM, NVIDIA Dynamo, llm-d, llama.cpp, KServe, Ollama (dev only)                                                                              |
| Voice and realtime             | LiveKit, Pipecat, Whisper-class ASR                    | AI4Bharat/Bhashini Indic models, Piper/XTTS-class TTS, FreeSWITCH/Asterisk for SIP                                                                    |
| Computer-use and coding agents | Playwright, browser-use, OpenHands                     | Aider, SWE-agent, Open Interpreter                                                                                                                    |
| Guardrails and safety          | NeMo Guardrails, Llama Guard                           | Guardrails AI, Presidio (PII), garak and promptfoo (red-team)                                                                                         |
| Evals and tracing              | Langfuse, Ragas, OpenTelemetry                         | Phoenix, DeepEval, lm-eval-harness, Inspect                                                                                                           |
| Fine-tuning and RL             | Axolotl, Unsloth, TRL                                  | LLaMA-Factory, torchtune, verl, OpenRLHF, DeepSpeed, Megatron-LM, NeMo                                                                                |
| Compute orchestration          | Kubernetes, Kueue, Ray                                 | Slurm, Volcano, SkyPilot, Nomad                                                                                                                       |
| Networking and mesh            | LibP2P, WireGuard, Cilium                              | Istio/Linkerd, Envoy, NATS, Tailscale/Headscale                                                                                                       |
| Policy, identity, secrets      | OPA, SPIFFE/SPIRE, Keycloak, Vault/OpenBao             | Cedar, Zitadel, Authentik, Teleport                                                                                                                   |
| Storage                        | Ceph, MinIO-class, Postgres (Patroni)                  | Lustre, BeeGFS, JuiceFS, ClickHouse, Valkey                                                                                                           |
| Provisioning and GitOps        | MAAS or Tinkerbell, NetBox, Argo CD, OpenTofu, Ansible | Metal3, Foreman, Flux, Crossplane                                                                                                                     |
| Observability                  | Prometheus, Grafana, Loki, Tempo, DCGM                 | Mimir, VictoriaMetrics, SigNoz, Jaeger                                                                                                                |


Rule for every entry: pin versions, mirror internally, keep one maintained fallback, and re-score each choice every six months. Licences vary (permissive, modified MIT, AGPL, community terms); your compliance team gates each one before it enters the merged codebase.

## 13. Phased bare-metal build


| Phase | Months | Build                                                                                                                                             | Gate to proceed                                                              |
|-------|--------|---------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| A     | 0–3    | T0 workstations, rented GPUs for load tests, full software stack on Kubernetes (kind/k3s), CI with evals, procurement quotes, colo site selection | One real workflow end to end on rented GPUs; signed colo and hardware quotes |
| B     | 3–9    | First T1 node(s) in colo, OOB network, storage, observability, GitOps, backup; migrate steady inference from rented to owned                      | Node pool at 50%+ sustained utilisation; failover drill passed               |
| C     | 9–18   | T2 cluster with high-speed fabric and parallel file system; Slurm and Kueue; training pipelines; second site for DR                               | Fine-tuned model beating base on golden sets; site failover under RTO        |
| D     | 18–36  | T3 rack-scale (Blackwell Ultra or Rubin) as demand and revenue justify; federation to edge and partner sites; confidential-computing tenants      | Revenue and utilisation justify the capex; power and cooling ready           |
| E     | 36+    | Multi-site T4 federation, continued pretraining on proprietary data, next-gen hardware refreshes on a 3–4 year cycle                              | Ongoing 6-month architecture reviews                                         |


**The one decision that matters most:** do not buy ahead of demand. Rent while workloads are unproven, buy when utilisation is steady, and let the software abstractions (Volumes 1 and 2) keep every hardware choice reversible.
