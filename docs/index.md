# Om Sanchar documentation

Om Sanchar is a self-hostable communication layer and API gateway for the Evolucentsphere platform. This documentation describes the implemented reference gateway, protocol contracts, development workflow, and measured limits. Planned behavior is labeled as planned; it is not presented as available functionality.

## Start here

- [Quickstart](quickstart.md) runs the gateway's documented health and streaming requests against the local mock model.
- [Development setup](dev-setup.md) covers Windows, WSL2, and the integrated development stack.
- [Stream retention](stream-retention.md) describes memory bounds, eviction, resume errors, and measured soak evidence.
- [Dependency policy](security/dependency-policy.md) explains pinned tools, package review, SBOMs, and vulnerability scans.
- [P0 execution plan](plan/p0-execution-plan.md) records the foundation phase and its evidence requirements.
- [Phase 1 execution plan](plan/phase1-execution-plan.md) tracks the ordered gateway MVP work packages.

The protocol source of truth lives in [`/spec`](https://github.com/shashankoppo/omsanchar/tree/main/spec); architecture decisions live in [`/adr`](https://github.com/shashankoppo/omsanchar/tree/main/adr). The [project status](https://github.com/shashankoppo/omsanchar/blob/main/PROGRESS.md) distinguishes measured results from estimates and open work.

## Documentation workflow

Markdown pages are versioned with the code they describe. `make docs` checks local Markdown links, validates fenced examples, executes the quickstart HTTP/SSE example, and builds this site in strict mode. The same command runs in pull-request and push CI. See [documentation authoring](authoring.md) for source-of-truth, example, and review rules.

The copied source material in `docs/upstream/`, generated security reports, and the session handoff are retained in Git but excluded from the public documentation site. The upstream README defines the authority order for those source documents.
