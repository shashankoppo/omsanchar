"""Run cargo-audit for every committed Rust lockfile and validate dated exceptions."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS = ROOT / "docs" / "security" / "security-exceptions.json"
LOCKFILES = (
    ROOT / "dataplane" / "sanchar-core" / "Cargo.lock",
    ROOT / "crates" / "Cargo.lock",
)


def exception_identities(lockfile: Path, today: date) -> set[tuple[str, str, str]]:
    data = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported security exception schema")
    identities: set[tuple[str, str, str]] = set()
    for exception in data.get("exceptions", []):
        expiry = date.fromisoformat(exception["expires"])
        if expiry < today:
            raise ValueError(
                f"security exception {exception.get('advisory')} expired on {expiry.isoformat()}"
            )
        if exception.get("scanner_suppression") is not False:
            raise ValueError(f"security exception {exception.get('advisory')} suppresses scanner output")
        if not all(exception.get(field) for field in ("advisory", "package", "version", "reason", "scope")):
            raise ValueError(f"security exception is missing its identity or rationale: {exception!r}")
        if lockfile.relative_to(ROOT).as_posix() in exception.get("lockfiles", []):
            identities.add((exception["advisory"], exception["package"], exception["version"]))
    return identities


def audit(lockfile: Path, exceptions: set[tuple[str, str, str]]) -> bool:
    result = subprocess.run(
        ["cargo", "audit", "--json", "--file", str(lockfile)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout, file=sys.stderr, end="")
        print(result.stderr, file=sys.stderr, end="")
        print(f"cargo audit returned non-JSON output for {lockfile.relative_to(ROOT)}", file=sys.stderr)
        return False

    findings = {
        (
            item["advisory"]["id"],
            item["package"]["name"],
            item["package"]["version"],
        )
        for item in report.get("vulnerabilities", {}).get("list", [])
    }
    print(
        f"cargo audit: {lockfile.relative_to(ROOT)} — "
        f"{len(findings)} vulnerability finding(s), exit {result.returncode}"
    )
    if findings:
        # Preserve the scanner's full output in CI logs; an exception never hides a finding.
        print(result.stdout)
    unexpected = findings - exceptions
    if unexpected:
        print(f"unexpected RustSec findings in {lockfile.relative_to(ROOT)}: {sorted(unexpected)}", file=sys.stderr)
        return False
    if result.returncode not in (0, 1) or (result.returncode == 1 and not findings):
        print(result.stderr, file=sys.stderr, end="")
        print(f"cargo audit failed outside the reviewed advisory exception for {lockfile}", file=sys.stderr)
        return False
    for advisory, package, version in sorted(findings):
        print(f"active dated exception: {advisory} {package}=={version}; finding remains visible above")
    return True


def main() -> int:
    if shutil.which("cargo") is None:
        print("cargo is required for RustSec audits", file=sys.stderr)
        return 1
    today = datetime.now(timezone.utc).date()
    success = True
    for lockfile in LOCKFILES:
        try:
            exceptions = exception_identities(lockfile, today)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"security exception validation failed: {exc}", file=sys.stderr)
            return 1
        success = audit(lockfile, exceptions) and success
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
