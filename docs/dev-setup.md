# Development setup

The reference gateway is designed to run directly on the host. Python 3.12 or newer is the only runtime needed for `make dev-native`; Docker is optional.

## Native Windows

Open PowerShell in the repository root:

```powershell
Set-Location 'C:\Users\Shashank patel\Desktop\Evolucentsphere_DB\Evolucentsphere Pvt Ltd\omsanchar'
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --disable-pip-version-check -r requirements-dev.txt
python -m gateway.server
```

The server uses port 8080 by default; set `OM_GATEWAY_PORT` before launching to choose another port:

```powershell
$env:OM_GATEWAY_PORT = '8081'
python -m gateway.server
```

The server runs in the foreground. Press `Ctrl+C` to stop it.

## WSL2 with Ubuntu

WSL2 Ubuntu is the primary development environment for Rust and Linux integration work. On a machine without WSL2, install it from an elevated PowerShell window and restart Windows if requested:

```powershell
wsl --install -d Ubuntu
```

In the Ubuntu shell, install native build tools and Python, then use rustup to install the repository's Rust toolchain. Replace the example path with the checkout's actual Windows path:

```bash
sudo apt-get update
sudo apt-get install -y build-essential git curl python3 python3-venv
cd "$(wslpath 'C:\\path\\to\\omsanchar')"
rustup toolchain install 1.88.0 --component rustfmt --component clippy
rustup default 1.88.0
python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install --disable-pip-version-check -r requirements-dev.txt
python -m pip install --disable-pip-version-check --no-deps -r requirements-docs.txt
make test
make lint
make docs
make dev-native
```

Install rustup before the `rustup toolchain` commands if it is not already available. These commands work from a Windows-mounted workspace. For sustained Rust builds, keep a checkout under `~/src` on the WSL Linux filesystem to avoid Windows filesystem I/O overhead. CI pins Rust 1.88.0, the minimum supported by the security-patched `time` 0.3.47 dependency.

## Integrated development stack

The D3 stack starts the Python reference gateway, Envoy, the Rust mock model, NATS with JetStream enabled, and an OpenTelemetry Collector. Envoy forwards HTTP traffic to the mock model and exports sampled traces to the collector. NATS JetStream is available for integration work; the gateway does not yet use it for durable stream storage.

With Docker Engine and the Compose plugin installed, one command starts the native-engine stack:

```bash
make dev-stack
```

With Podman and a Compose provider installed, one command starts the Podman stack:

```bash
make dev-stack-podman
```

These are container-engine modes. `make dev-native` still runs only the Python gateway directly on the host. The default published ports are gateway 8080, Rust mock 8081, Envoy 10000, Envoy admin 9901, NATS client 4222, NATS monitor 8222, and OTLP gRPC/HTTP 4317/4318. Override them with `OM_GATEWAY_PORT`, `OM_MOCK_PORT`, `OM_ENVOY_PORT`, `OM_ENVOY_ADMIN_PORT`, `OM_NATS_CLIENT_PORT`, `OM_NATS_MONITOR_PORT`, `OM_OTEL_GRPC_PORT`, and `OM_OTEL_HTTP_PORT`.

Stop the foreground stack with `Ctrl+C`, or stop a detached stack with `make dev-stack-down` for Docker Compose and `make dev-stack-down-podman` for Podman Compose. `deploy/Dockerfile.verify` is used for reference checks; `deploy/Dockerfile.dev` and `deploy/Dockerfile.mock-model` are development images. None is a production deployment image.

## Checks and security reports

From an environment with GNU Make and the named tools on `PATH`:

```bash
make test
make lint
make docs       # requires the pinned requirements-docs.txt toolchain
make proto       # requires Buf CLI 1.73.0
make dev-native
make sbom        # requires Syft; writes source and dependency SBOMs
make vuln-scan   # requires Syft and Grype; fails on high severity or above
```

The CI workflow generates a source inventory and a dependency SBOM, audits the SBOM for known vulnerabilities, checks exact Python pins plus the locked Rust dependency versions and licenses, validates protobuf compatibility against `v0.1.0`, builds the strict documentation site, and builds both the verification image and the Compose development image. A Windows job parses PowerShell examples. The Python reference gateway has no runtime package dependencies. The Rust conformance tests use the reviewed Cargo dependency tree. Third-party dependencies must be added to `docs/security/dependency-inventory.json` and pass `scripts/check_dependencies.py --check-installed --check-rust`.

## Environment check recorded for this workspace

The Windows host has Python 3.12.8 and Docker CLI 29.6.2, but its Docker engine is unavailable. WSL2 Ubuntu is installed with Rust/Cargo, rustfmt, Clippy, GNU Make 4.3, Python venv support, and Podman. Use the pinned Rust 1.88.0 toolchain for Rust checks and research binaries. Results in WSL2 are development-only. The `v0.1.0` tag workflow has passed on GitHub; hosted CI for a pushed working branch must be checked per commit.
