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

If GNU Make is installed, `make dev-native` runs the same server command in WSL. On Windows, use `make PYTHON=python dev-native` when Make is installed, or run the Python command directly. The server uses port 8080 by default; set `OM_GATEWAY_PORT` before launching to choose another port:

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

In the Ubuntu shell, install the native build, Rust, formatter, linter, and Python tools, then enter the working tree and run the checks:

```bash
sudo apt-get update
sudo apt-get install -y build-essential git python3 python3-venv cargo rustc rustfmt rust-clippy
cd "/mnt/c/Users/Shashank patel/Desktop/Evolucentsphere_DB/Evolucentsphere Pvt Ltd/omsanchar"
python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install --disable-pip-version-check -r requirements-dev.txt
make test
make lint
make dev-native
```

The commands work from this Windows-mounted workspace. For sustained Rust builds, keep a checkout under `~/src` on the WSL Linux filesystem to avoid Windows filesystem I/O overhead. The Rust core currently pins toolchain 1.75.0 in CI; Ubuntu's packaged compiler should match that release line.

## Optional Docker Compose stack

Docker Compose builds the same Python gateway in a local development image. It is not required for native development:

```powershell
docker compose -f deploy/dev.yml up --build
```

The service listens on host port 8080 by default. Set `OM_GATEWAY_PORT` before Compose to change both the host and container port. Compose binds the gateway to all container interfaces so Docker can publish the port; native runs stay on loopback by default. Stop it with `Ctrl+C`; run `docker compose -f deploy/dev.yml down` after a detached launch.

The separate `deploy/Dockerfile.verify` image runs reference checks in CI. `deploy/Dockerfile.dev` is for local Compose use; neither image is a production deployment image.

## Podman in WSL2 when Docker Desktop is unavailable

Install Podman and use it to build and exercise both local images:

```bash
sudo apt-get install -y podman
podman info
podman build -f deploy/Dockerfile.verify -t om-sanchar-verify:local .
podman run --rm om-sanchar-verify:local
podman build -f deploy/Dockerfile.dev -t om-sanchar-dev:local .
podman run --rm -d --name om-sanchar-dev -p 127.0.0.1:8080:8080 om-sanchar-dev:local
curl http://localhost:8080/healthz
podman stop om-sanchar-dev
```

The development image binds to the container interface; native `make dev-native` stays on loopback. CI continues to build the Compose file with Docker Compose.

## Checks and security reports

From an environment with GNU Make and the named tools on `PATH`:

```bash
make test
make lint
make proto       # requires Buf CLI 1.73.0
make dev-native
make sbom        # requires Syft; writes source and dependency SBOMs
make vuln-scan   # requires Syft and Grype; fails on high severity or above
```

The CI workflow generates a source inventory and a dependency SBOM, audits the SBOM for known vulnerabilities, checks exact Python pins plus the locked Rust dependency versions and licenses, validates protobuf compatibility against `v0.1.0`, and builds both the verification image and the Compose development image. The Python reference gateway has no runtime package dependencies. The Rust conformance tests use the reviewed Cargo dependency tree. Third-party dependencies must be added to `docs/security/dependency-inventory.json` and pass `scripts/check_dependencies.py --check-installed --check-rust`.

## Environment check recorded for this workspace

The Windows host has Python 3.12.8 and Docker CLI 29.6.2, but its Docker engine is unavailable. WSL2 Ubuntu 24.04 is installed and was verified. Rust/Cargo 1.75.0, rustfmt, Clippy, GNU Make 4.3, Python venv support, and Podman were installed there. The Python/Rust test and lint targets passed in WSL; both Podman images built, and the verification image tests and gateway health route passed. No hosted CI run is available because this checkout has no Git remote.
