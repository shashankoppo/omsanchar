"""Generate a source-file inventory in SPDX JSON format."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".venv", ".tools", ".tools-npm", ".bufcache", "venv", "artifacts", "target", "dist"}


def generate(output: Path) -> None:
    file_entries = []
    relationships = []
    for index, path in enumerate(sorted(ROOT.rglob("*")), start=1):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        relative = path.relative_to(ROOT).as_posix()
        file_id = f"SPDXRef-File-{index}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_entries.append(
            {
                "SPDXID": file_id,
                "fileName": f"./{relative}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {"spdxElementId": "SPDXRef-OmSancharSource", "relationshipType": "CONTAINS", "relatedSpdxElement": file_id}
        )

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Om Sanchar source inventory",
        "documentNamespace": f"https://spdx.org/spdxdocs/om-sanchar-source-{uuid.uuid4()}",
        "creationInfo": {
            "creators": ["Tool: om-sanchar-source-sbom/0.1.0"],
            "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
        "packages": [
            {
                "name": "om-sanchar-source",
                "SPDXID": "SPDXRef-OmSancharSource",
                "versionInfo": "0.1.0-dev",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        ],
        "files": file_entries,
        "relationships": relationships,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    generate(output)
    print(f"Wrote source inventory SBOM: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
