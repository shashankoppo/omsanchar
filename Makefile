.PHONY: dev-native test test-spec test-sim test-gateway test-token test-rust lint proto sbom source-sbom dependency-sbom vuln-scan container compose-build deps

PYTHON ?= python3
BUF ?= buf
DOCKER ?= docker
SYFT ?= syft
GRYPE ?= grype

dev-native:
	$(PYTHON) -m gateway.server

test: test-spec test-sim test-gateway test-token test-rust

test-spec:
	$(PYTHON) -m unittest discover -s spec/tests -v

test-sim:
	$(PYTHON) -m unittest discover -s sim/tests -v

test-gateway:
	$(PYTHON) -m unittest discover -s gateway/tests -v

test-token:
	$(PYTHON) -m unittest discover -s spikes/capability-token/tests -v

test-rust:
	cargo test --locked --manifest-path dataplane/sanchar-core/Cargo.toml

lint:
	$(PYTHON) scripts/check_style.py
	$(PYTHON) scripts/check_dependencies.py --check-installed --check-rust
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	cargo fmt --manifest-path dataplane/sanchar-core/Cargo.toml -- --check
	cargo clippy --locked --manifest-path dataplane/sanchar-core/Cargo.toml -- -D warnings

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
