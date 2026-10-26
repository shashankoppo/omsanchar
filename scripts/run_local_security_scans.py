#!/usr/bin/env python3
"""Run checksum-verified local WSL2 supply-chain tools and retain raw reports."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import subprocess
import sys
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools" / "bin"
REPORTS = ROOT / "docs" / "security" / "reports"
SNAPSHOTS = Path("/tmp/omsanchar-security-snapshots")


def run(argv: list[str], *, output_file: Path | None = None) -> dict[str, Any]:
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    if output_file is not None:
        output_file.write_text(result.stdout, encoding="utf-8")
    return {
        "command": [str(Path(argv[0]).relative_to(ROOT)) if Path(argv[0]).is_absolute() else argv[0], *argv[1:]],
        "exit_code": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout if output_file is None else None,
        "output_file": str(output_file.relative_to(ROOT)) if output_file else None,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as report:
        for chunk in iter(lambda: report.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_advisory_snapshot(date: str) -> tuple[Path, dict[str, str]]:
    """Use the official GitHub source archive when the Git upload-pack endpoint is unavailable."""
    request = urllib.request.Request(
        "https://api.github.com/repos/RustSec/advisory-db/commits/HEAD",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "om-sanchar-local-audit"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        commit = json.load(response)["sha"]
    archive_url = f"https://codeload.github.com/RustSec/advisory-db/tar.gz/{commit}"
    with urllib.request.urlopen(archive_url, timeout=180) as response:
        archive_bytes = response.read()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    snapshot = SNAPSHOTS / f"advisory-db-{date}-{commit[:12]}"
    db_path = snapshot / "db"
    if not (db_path / ".git").is_dir():
        source = snapshot / f"source-{archive_hash[:12]}"
        source.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = archive.getmembers()
            if any(Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members):
                raise RuntimeError("RustSec advisory archive contains an unsafe path")
            archive.extractall(source, filter="data")
        roots = list(source.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise RuntimeError("unexpected RustSec advisory archive layout")
        roots[0].rename(db_path)
        for command in (
            ["git", "init", "--quiet"],
            ["git", "add", "."],
            [
                "git",
                "-c",
                "user.name=Om Sanchar audit runner",
                "-c",
                "user.email=audit@localhost",
                "commit",
                "--quiet",
                "-m",
                f"RustSec advisory snapshot {commit}",
            ],
        ):
            subprocess.run(command, cwd=db_path, check=True, capture_output=True, text=True)
    snapshot_subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=db_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    expected_subject = f"RustSec advisory snapshot {commit}"
    if snapshot_subject != expected_subject:
        raise RuntimeError(f"cached RustSec snapshot mismatch: expected {expected_subject!r}, found {snapshot_subject!r}")
    snapshot_changes = subprocess.run(
        ["git", "status", "--porcelain"], cwd=db_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    if snapshot_changes:
        raise RuntimeError("cached RustSec snapshot has local changes")
    metadata = {
        "source_repository": "https://github.com/RustSec/advisory-db",
        "source_commit": commit,
        "archive_url": archive_url,
        "archive_sha256": archive_hash,
        "local_snapshot_path": str(db_path),
        "local_snapshot_reason": "cargo-audit could not reach the Git upload-pack endpoint; the official archive was committed locally and audited with --no-fetch",
    }
    (REPORTS / f"rustsec-advisory-db-snapshot-{date}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return db_path, metadata


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = datetime.now(UTC).date().isoformat()
    syft_path = TOOLS / "syft"
    grype_path = TOOLS / "grype"
    audit_path = TOOLS / "cargo-audit"
    syft_report = REPORTS / f"syft-{date}.spdx.json"
    grype_report = REPORTS / f"grype-{date}.json"
    audit_report = REPORTS / f"cargo-audit-{date}.json"

    versions = {
        "syft": subprocess.run([str(syft_path), "version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "grype": subprocess.run([str(grype_path), "version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "cargo_audit": subprocess.run([str(audit_path), "-V"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "cargo": subprocess.run(["cargo", "--version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "rustc": subprocess.run(["rustc", "--version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
    }
    syft_cmd = [
        str(syft_path),
        "dir:.",
        "--exclude",
        "**/.git/**",
        "--exclude",
        "**/.venv/**",
        "--exclude",
        "**/.venv-wsl/**",
        "--exclude",
        "**/.tools/**",
        "--exclude",
        "**/.tools-npm/**",
        "--exclude",
        "**/.bufcache/**",
        "--exclude",
        "**/target/**",
        "-o",
        f"spdx-json={syft_report.relative_to(ROOT)}",
    ]
    syft = run(syft_cmd)
    grype = run([str(grype_path), f"sbom:{syft_report.relative_to(ROOT)}", "-o", "json"], output_file=grype_report)
    db_path, advisory_snapshot = materialize_advisory_snapshot(date)
    audit = run(
        [
            str(audit_path),
            "audit",
            "--json",
            "--db",
            str(db_path),
            "--no-fetch",
            "--file",
            "dataplane/sanchar-core/Cargo.lock",
        ],
        output_file=audit_report,
    )

    reports = []
    for item, path in ((syft, syft_report), (grype, grype_report), (audit, audit_report)):
        if path.exists():
            item["sha256"] = sha256(path)
            item["size_bytes"] = path.stat().st_size
            if item["stderr"]:
                stderr_path = path.with_suffix(path.suffix + ".stderr.txt")
                stderr_path.write_text(item["stderr"], encoding="utf-8")
                item["stderr_file"] = str(stderr_path.relative_to(ROOT))
                item["stderr"] = None
        reports.append(item)

    manifest = {
        "classification": "measured",
        "platform_scope": "WSL2 development-only; these scans are supply-chain inventory results, not Linux-host performance evidence",
        "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": platform.node(),
        "platform": platform.platform(),
        "versions": versions,
        "reports": reports,
        "advisory_database": advisory_snapshot,
        "note": "Scanner exit codes are preserved. Grype reports findings without a severity threshold. cargo-audit uses the official RustSec advisory-db source commit recorded above; the Git upload-pack endpoint was unavailable, so the source archive was initialized as a local Git database and audited with --no-fetch.",
    }
    manifest_path = REPORTS / f"manifest-{date}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    print(json.dumps({"versions": versions, "reports": reports}, indent=2))
    return int(any(item["exit_code"] != 0 for item in reports))


if __name__ == "__main__":
    sys.exit(main())
