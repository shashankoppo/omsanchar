"""Dependency-free checks for whitespace and final newlines in text files."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    ".venv-wsl",
    ".tools",
    ".tools-npm",
    ".bufcache",
    "venv",
    "artifacts",
    "target",
    "dist",
}
TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".json", ".toml", ".proto", ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".sh"}


def main() -> int:
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        relative_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in relative_parts) or not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Makefile", ".gitignore", ".editorconfig"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if content and not content.endswith("\n"):
            problems.append(f"{relative}: missing final newline")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if line.endswith((" ", "\t")):
                problems.append(f"{relative}:{line_no}: trailing whitespace")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Text formatting checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
