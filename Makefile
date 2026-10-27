.PHONY: dev-native dev-stack dev-stack-podman dev-stack-down dev-stack-down-podman test test-spec test-sim test-gateway test-token test-rust test-token-rust test-d5-loadgen test-mock bench-token-rust bench-d5 lint proto sbom source-sbom dependency-sbom vuln-scan container compose-build deps s1-check demo-s1

PYTHON ?= python3
CARGO ?= cargo
BUF ?= buf
DOCKER ?= docker
SYFT ?= syft
GRYPE ?= grype
TOKEN_BENCH_ITERATIONS ?= 1000
TOKEN_BENCH_RUNS ?= 10
TOKEN_BENCH_OUTPUT ?= bench/results/capability-token-rust.json
D5_ENDPOINT ?= http://127.0.0.1:8081
D5_WORKLOAD ?= sse500
D5_RATE_RPS ?= 10
D5_DURATION_SECS ?= 1
D5_MAX_IN_FLIGHT ?= 100
D5_OUTPUT ?= bench/results/d5-development-run.json
CRATES_MANIFEST ?= crates/Cargo.toml

dev-native:
	$(PYTHON) -m gateway.server

dev-stack:
	$(DOCKER) compose -f deploy/dev.yml up --build

dev-stack-podman:
	podman compose -f deploy/dev.yml up --build

dev-stack-down:
	$(DOCKER) compose -f deploy/dev.yml down

dev-stack-down-podman:
	podman compose -f deploy/dev.yml down

test: test-spec test-sim test-gateway test-token test-rust test-token-rust test-d5-loadgen test-mock

s1-check:
	$(CARGO) fmt --manifest-path $(CRATES_MANIFEST) --all -- --check
	$(CARGO) clippy --locked --manifest-path $(CRATES_MANIFEST) --workspace --all-targets -- -D warnings
	$(CARGO) test --locked --manifest-path $(CRATES_MANIFEST) --workspace
	$(MAKE) demo-s1

demo-s1:
	bash scripts/demo_s1.sh

test-spec:
	$(PYTHON) -m unittest discover -s spec/tests -v

test-sim:
	$(PYTHON) -m unittest discover -s sim/tests -v

test-gateway:
	$(PYTHON) -m unittest discover -s gateway/tests -v

test-token:
	$(PYTHON) -m unittest discover -s spikes/capability-token/tests -v

test-rust:
	$(CARGO) test --locked --manifest-path dataplane/sanchar-core/Cargo.toml

test-token-rust:
	$(CARGO) test --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features token-bench --bin capability_token_bench

test-d5-loadgen:
	$(CARGO) test --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features d5-bench --bin d5_loadgen

test-mock:
	$(CARGO) build --locked --manifest-path dataplane/sanchar-core/Cargo.toml --bin mock_model
	$(PYTHON) scripts/test_mock_model.py dataplane/sanchar-core/target/debug/mock_model

bench-token-rust:
	$(CARGO) run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features token-bench --bin capability_token_bench -- $(TOKEN_BENCH_ITERATIONS) $(TOKEN_BENCH_RUNS) $(TOKEN_BENCH_OUTPUT)

bench-d5:
	$(CARGO) run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml --features d5-bench --bin d5_loadgen -- $(D5_ENDPOINT) $(D5_WORKLOAD) $(D5_RATE_RPS) $(D5_DURATION_SECS) $(D5_MAX_IN_FLIGHT) $(D5_OUTPUT) $(D5_CA_CERT)

lint:
	$(PYTHON) scripts/check_style.py
	$(PYTHON) scripts/check_dependencies.py --check-installed --check-rust
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(CARGO) fmt --manifest-path dataplane/sanchar-core/Cargo.toml -- --check
	$(CARGO) clippy --locked --manifest-path dataplane/sanchar-core/Cargo.toml -- -D warnings

deps:
	$(PYTHON) scripts/check_dependencies.py --check-installed --check-rust

proto:
	$(BUF) lint spec
	$(BUF) build spec

sbom:
	$(MAKE) source-sbom dependency-sbom

source-sbom:
	$(PYTHON) scripts/generate_source_sbom.py --output artifacts/source-sbom.spdx.json

dependency-sbom:
	$(SYFT) dir:. -o spdx-json=artifacts/dependency-sbom.spdx.json

vuln-scan: dependency-sbom
	$(GRYPE) sbom:artifacts/dependency-sbom.spdx.json --fail-on high

container:
	$(DOCKER) build -f deploy/Dockerfile.verify -t om-sanchar-verify:local .

compose-build:
	$(DOCKER) compose -f deploy/dev.yml build
