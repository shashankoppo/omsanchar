# Om Sanchar

Om Sanchar is the proposed sovereign communication layer and API gateway for the Evolucentsphere platform. It is intended to unify model and agent traffic, workload identity and policy, peer connectivity, durable events, and channel adapters behind stable protocols.

The repository is in **P0: foundations and spikes**. `/docs/upstream/04-om-sanchar-rnd-and-developer-handbook.md` is the Om Sanchar authority; `/spec` contains the current executable protocol draft. Implementation and performance claims remain provisional until measured and recorded in `PROGRESS.md`.

## Repository map

- `/gateway` — native D4 reference gateway and local mock streaming model.
- `/dataplane` — Rust stream protocol core (`sanchar-core`).
- `/spikes/capability-token` — D6 prototype, attenuation tests, and measurements.
- `/docs/upstream` — supplied platform and Om Sanchar source documents.

- `/spec` — protocol schemas, rules, executable reference validators, and conformance vectors.
- `/dataplane`, `/controlplane`, `/overlay`, `/policy`, `/sdk`, `/adapters` — implementation areas reserved for P0/P1 work.
- `/sim` — deterministic reference state machines and fault scenarios.
- `/bench` — benchmark workloads, harnesses, and reports.
- `/deploy` — local and production deployment definitions.
- `/docs` — plans, security, operations, and developer documentation.
- `/adr` — architecture decision records.

The [documentation portal](docs/index.md) is built and link-checked by `make docs`. Protocol and ADR contracts remain canonical under `/spec` and `/adr`.

## Current local checks

Use WSL2 Ubuntu for Rust development and Linux integration work. Python 3.12 or newer runs the native gateway and reference checks:

```powershell
python -m unittest discover -s spec/tests -v
python -m unittest discover -s sim/tests -v
python -m unittest discover -s gateway/tests -v
python scripts/check_style.py
```

Install the pinned Python linter before running `make lint`:

```powershell
python -m pip install -r requirements-dev.txt
```

`make dev-native` runs the D4 gateway without Docker. `make test` also runs the Rust conformance crate; `make lint` checks Python and Rust. CI uses Buf CLI 1.73.0 for schema validation and checks breaking changes against the `v0.1.0` tag. CI also builds the verification and Compose images and generates/scans a dependency SBOM. See [developer setup](docs/dev-setup.md) for WSL2 and local commands.

Read [CLAUDE.md](CLAUDE.md), [PROGRESS.md](PROGRESS.md), and `/adr` before making changes.
