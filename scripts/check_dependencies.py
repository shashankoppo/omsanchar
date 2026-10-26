"""Check exact Python development pins against the reviewed license inventory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-dev.txt"
INVENTORY = ROOT / "docs" / "security" / "dependency-inventory.json"
CARGO_MANIFEST = ROOT / "dataplane" / "sanchar-core" / "Cargo.toml"
CARGO_LOCK = ROOT / "dataplane" / "sanchar-core" / "Cargo.lock"
PIN = re.compile(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\Z")
LICENSE_ALIASES = {
    "apache license 2.0": "apache-2.0",
    "apache license, version 2.0": "apache-2.0",
    "apache-2.0": "apache-2.0",
    "bsd 3-clause license": "bsd-3-clause",
    "bsd-3-clause": "bsd-3-clause",
    "mit license": "mit",
    "mit": "mit",
}
ALLOWED_CARGO_LICENSE_IDS = {
    "0bsd",
    "apache-2.0",
    "bsd-1-clause",
    "bsd-2-clause",
    "bsd-3-clause",
    "bsl-1.0",
    "mit",
    "unicode-3.0",
    "unlicense",
    "zlib",
}
ALLOWED_CARGO_LICENSE_EXCEPTIONS = {"llvm-exception"}


def normalized_license(value: str) -> str:
    return LICENSE_ALIASES.get(value.strip().lower(), value.strip().lower())


def cargo_metadata() -> dict:
    if shutil.which("cargo") is None:
        raise RuntimeError("cargo is required for Rust dependency/license checks")
    result = subprocess.run(
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(CARGO_MANIFEST),
            "--format-version",
            "1",
            "--all-features",
            "--locked",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"cargo metadata failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def rust_packages(metadata_json: dict) -> list[dict]:
    return [package for package in metadata_json.get("packages", []) if package.get("source")]


def normalized_cargo_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.lower())


def check_cargo_license_expression(name: str, version: str, expression: str) -> str | None:
    atoms = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", expression)
    license_ids = []
    index = 0
    while index < len(atoms):
        atom = atoms[index]
        normalized = atom.lower()
        if normalized == "with":
            exception = atoms[index + 1].lower() if index + 1 < len(atoms) else ""
            if exception not in ALLOWED_CARGO_LICENSE_EXCEPTIONS:
                return f"Unreviewed Rust license exception for {name}=={version}: {exception or expression!r}"
            index += 2
            continue
        if normalized not in {"and", "or"}:
            license_ids.append(atom)
        index += 1
    if not license_ids:
        return f"Rust dependency has no parseable license expression: {name}=={version}"
    disallowed = sorted({normalized_license(atom) for atom in license_ids} - ALLOWED_CARGO_LICENSE_IDS)
    if disallowed:
        return f"Disallowed Rust license for {name}=={version}: {expression!r} ({', '.join(disallowed)})"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-installed",
        action="store_true",
        help="also compare installed package versions and license metadata with the reviewed inventory",
    )
    parser.add_argument(
        "--check-rust",
        action="store_true",
        help="compare Cargo.lock and cargo metadata versions, sources, and licenses with the reviewed inventory",
    )
    parser.add_argument(
        "--print-rust-packages",
        action="store_true",
        help="print resolved Cargo package name, version, source, and license metadata for inventory review",
    )
    args = parser.parse_args()

    requirements: dict[str, str] = {}
    for line_no, raw in enumerate(REQUIREMENTS.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match is None:
            print(f"requirements-dev.txt:{line_no}: dependency must use an exact == version pin", file=sys.stderr)
            return 1
        name = re.sub(r"[-_.]+", "-", match.group(1).lower())
        version = match.group(2)
        if name in requirements:
            print(f"requirements-dev.txt:{line_no}: duplicate dependency {name}", file=sys.stderr)
            return 1
        # Keep this small first-pass gate scoped to the reviewed Python tools.
        requirements[name] = version

    inventory_data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if inventory_data.get("schema_version") != 1:
        print("Unsupported dependency inventory schema", file=sys.stderr)
        return 1
    inventory_entries: dict[str, dict[tuple[str, str], dict[str, str]]] = {"python": {}, "cargo": {}}
    for entry in inventory_data.get("dependencies", []):
        ecosystem = str(entry.get("ecosystem", "python")).lower()
        key = normalized_cargo_name(str(entry.get("name", "")))
        version = str(entry.get("version", ""))
        if (
            ecosystem not in inventory_entries
            or not key
            or not version
            or not entry.get("license")
            or not entry.get("source")
            or not entry.get("purpose")
        ):
            print(f"Incomplete dependency license record: {entry!r}", file=sys.stderr)
            return 1
        record_key = (key, version)
        if record_key in inventory_entries[ecosystem]:
            print(f"Duplicate dependency inventory record: {ecosystem} {key}=={version}", file=sys.stderr)
            return 1
        inventory_entries[ecosystem][record_key] = entry

    if args.print_rust_packages:
        try:
            print(
                json.dumps(
                    [
                        {
                            "name": package["name"],
                            "version": package["version"],
                            "license": package.get("license"),
                            "source": package.get("source"),
                        }
                        for package in rust_packages(cargo_metadata())
                    ],
                    indent=2,
                )
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    python_reviewed = {name: version for (name, version) in inventory_entries["python"]}

    if requirements != python_reviewed:
        print(
            f"Pinned Python dependencies differ from reviewed license inventory: pins={requirements}, inventory={python_reviewed}",
            file=sys.stderr,
        )
        return 1

    if args.check_installed:
        entries = {name: entry for (name, _), entry in inventory_entries["python"].items()}
        for name, expected_version in sorted(requirements.items()):
            try:
                distribution = metadata.distribution(name)
            except metadata.PackageNotFoundError:
                print(f"Installed dependency is missing: {name}=={expected_version}", file=sys.stderr)
                return 1
            if distribution.version != expected_version:
                print(
                    f"Installed version mismatch for {name}: expected {expected_version}, found {distribution.version}",
                    file=sys.stderr,
                )
                return 1
            actual_license = distribution.metadata.get("License-Expression") or distribution.metadata.get("License")
            expected_license = str(entries[name]["license"])
            if not actual_license:
                print(f"Installed dependency has no license metadata: {name}=={expected_version}", file=sys.stderr)
                return 1
            if normalized_license(actual_license) != normalized_license(expected_license):
                print(
                    f"Installed license mismatch for {name}: inventory={expected_license!r}, "
                    f"metadata={actual_license!r}",
                    file=sys.stderr,
                )
                return 1

    if args.check_rust:
        try:
            lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
            locked = {
                (normalized_cargo_name(package["name"]), package["version"]): package
                for package in lock.get("package", [])
                if package.get("source")
            }
            reviewed = inventory_entries["cargo"]
            if set(locked) != set(reviewed):
                print(
                    f"Cargo.lock differs from reviewed dependency inventory: "
                    f"missing={sorted(set(locked) - set(reviewed))}, "
                    f"extra={sorted(set(reviewed) - set(locked))}",
                    file=sys.stderr,
                )
                return 1
            for package_key, package in locked.items():
                if package.get("source") != reviewed[package_key]["source"]:
                    print(f"Cargo source mismatch for {package_key}: {package.get('source')}", file=sys.stderr)
                    return 1

            actual_packages = {
                (normalized_cargo_name(package["name"]), package["version"]): package
                for package in rust_packages(cargo_metadata())
            }
            if set(actual_packages) != set(locked):
                print("cargo metadata resolved package set differs from Cargo.lock", file=sys.stderr)
                return 1
            for package_key, package in actual_packages.items():
                record = reviewed[package_key]
                actual_license = package.get("license")
                if not actual_license:
                    print(f"Rust dependency has no license metadata: {package_key}", file=sys.stderr)
                    return 1
                if actual_license != record["license"]:
                    print(
                        f"Rust license metadata mismatch for {package_key}: "
                        f"inventory={record['license']!r}, cargo={actual_license!r}",
                        file=sys.stderr,
                    )
                    return 1
                disallowed = check_cargo_license_expression(package["name"], package["version"], actual_license)
                if disallowed:
                    print(disallowed, file=sys.stderr)
                    return 1
        except (OSError, KeyError, RuntimeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            print(f"Rust dependency/license check failed: {exc}", file=sys.stderr)
            return 1

    if requirements or inventory_entries["cargo"]:
        suffix = " including installed Python license metadata" if args.check_installed else ""
        if args.check_rust:
            suffix += f" and Rust lock/metadata/license policy ({len(inventory_entries['cargo'])} packages)"
        print(f"Dependency pin and license inventory checks passed{suffix}.")
    else:
        print("Dependency pin and license inventory checks passed (no packages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
