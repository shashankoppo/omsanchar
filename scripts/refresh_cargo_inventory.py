"""Print or explicitly refresh the reviewed Cargo dependency inventory."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from check_dependencies import check_cargo_license_expression, normalized_cargo_name

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataplane" / "sanchar-core" / "Cargo.toml"
INVENTORY = ROOT / "docs" / "security" / "dependency-inventory.json"

DIRECT_PURPOSES = {
    "biscuit-auth": "Biscuit capability-token verification comparison in the optional research binary",
    "bytes": "HTTP body buffers for the Rust mock model",
    "ed25519-dalek": "Ed25519 attenuation-chain capability-token comparison",
    "futures-util": "Asynchronous HTTP response stream composition",
    "hdrhistogram": "HdrHistogram distributions for the D5 open-loop load generator",
    "hmac": "HMAC attenuation-chain capability-token comparison",
    "http-body-util": "HTTP full and streaming body adapters for the mock model",
    "hyper": "HTTP/1 server for the Rust mock model",
    "hyper-util": "Tokio transport integration for Hyper",
    "rand": "Deterministic random number generation for token benchmark reproducibility",
    "reqwest": "Asynchronous HTTP and TLS client for the D5 open-loop load generator",
    "serde": "Serialization of Rust benchmark reports",
    "serde_json": "MCP JSON-RPC fixture responses and Rust conformance vectors",
    "sha2": "SHA-256 token hashing and HMAC capability-token comparison",
    "tokio": "Asynchronous runtime and TCP listener for the Rust mock model",
    "webpki-roots": "Mozilla root-certificate data for Reqwest Rustls TLS in the D5 harness",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace Cargo inventory records after license checks")
    args = parser.parse_args()
    result = subprocess.run(
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(MANIFEST),
            "--format-version",
            "1",
            "--all-features",
            "--locked",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.stderr)
    metadata = json.loads(result.stdout)
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    existing = {
        (normalized_cargo_name(entry["name"]), entry["version"]): entry
        for entry in inventory["dependencies"]
        if entry.get("ecosystem") == "cargo"
    }
    packages = [package for package in metadata["packages"] if package.get("source")]
    candidate = []
    for package in sorted(packages, key=lambda entry: (normalized_cargo_name(entry["name"]), entry["version"])):
        key = (normalized_cargo_name(package["name"]), package["version"])
        license_expression = package.get("license")
        if not license_expression:
            raise SystemExit(f"missing license metadata: {package['name']}=={package['version']}")
        violation = check_cargo_license_expression(package["name"], package["version"], license_expression)
        if violation:
            raise SystemExit(violation)
        previous = existing.get(key)
        purpose = (
            previous["purpose"]
            if previous
            else DIRECT_PURPOSES.get(
                normalized_cargo_name(package["name"]),
                "Transitive dependency of the pinned Rust async mock and protocol test stack",
            )
        )
        candidate.append(
            {
                "ecosystem": "cargo",
                "name": package["name"],
                "version": package["version"],
                "license": license_expression,
                "purpose": purpose,
                "source": package["source"],
            }
        )
    non_cargo = [entry for entry in inventory["dependencies"] if entry.get("ecosystem", "python") != "cargo"]
    updated = {"schema_version": inventory["schema_version"], "dependencies": non_cargo + candidate}
    if args.write:
        INVENTORY.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "write": args.write,
                "cargo_package_count": len(candidate),
                "added_packages": [
                    {"name": entry["name"], "version": entry["version"], "license": entry["license"]}
                    for entry in candidate
                    if (normalized_cargo_name(entry["name"]), entry["version"]) not in existing
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
