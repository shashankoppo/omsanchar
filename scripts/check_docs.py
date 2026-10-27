"""Validate first-party Markdown links and executable fence syntax."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})([^`]*)$")
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)]*)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_ID = re.compile(r"\bid=[\"']([^\"']+)[\"']", re.IGNORECASE)

SKIP_PARTS = {
    "docs/upstream",
    "docs/security/reports",
    "bench/quarantine",
}
ROOT_MARKDOWN = {
    "README.md",
    "CHANGELOG.md",
    "CLAUDE.md",
    "PROGRESS.md",
}
EXTRA_MARKDOWN = {
    "bench/README.md",
    "bench/d5/README.md",
    "spikes/capability-token/README.md",
}


def authored_markdown() -> list[Path]:
    paths = {ROOT / value for value in ROOT_MARKDOWN | EXTRA_MARKDOWN}
    for folder in (ROOT / "docs", ROOT / "adr", ROOT / "spec"):
        paths.update(folder.rglob("*.md"))
    return sorted(
        path
        for path in paths
        if path.is_file() and not any(part in path.relative_to(ROOT).as_posix() for part in SKIP_PARTS)
    )


def remove_fenced_code(text: str, path: Path) -> tuple[str, list[tuple[int, str, str]]]:
    lines = text.splitlines()
    visible: list[str] = []
    blocks: list[tuple[int, str, str]] = []
    opening: tuple[int, str, int, str] | None = None
    content: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        match = FENCE.match(line)
        if opening is None:
            if match:
                marker = match.group(1)
                opening = (line_number, marker[0], len(marker), match.group(2).strip())
                content = []
                visible.append("")
            else:
                visible.append(line)
            continue

        _, fence_char, fence_length, language = opening
        if match and match.group(1)[0] == fence_char and len(match.group(1)) >= fence_length:
            blocks.append((opening[0], language, "\n".join(content)))
            opening = None
            content = []
        else:
            content.append(line)
        visible.append("")

    if opening is not None:
        raise ValueError(f"{path.relative_to(ROOT)}:{opening[0]}: unclosed fenced code block")
    return "\n".join(visible), blocks


def slug_heading(value: str) -> str:
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = value.lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value.strip())


def page_anchors(path: Path) -> set[str]:
    text, _ = remove_fenced_code(path.read_text(encoding="utf-8"), path)
    anchors = set(HTML_ID.findall(text))
    counts: dict[str, int] = {}
    for line in text.splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        base = slug_heading(match.group(2))
        count = counts.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        counts[base] = count + 1
    return anchors


def link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def resolve_link(source: Path, raw_target: str) -> tuple[Path | None, str]:
    parts = urlsplit(raw_target)
    target_path = unquote(parts.path)
    if parts.scheme or parts.netloc or target_path.startswith("//"):
        return None, ""
    if not target_path:
        return source, unquote(parts.fragment)

    target = (ROOT / target_path.lstrip("/")) if target_path.startswith("/") else (source.parent / target_path)
    target = target.resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return target, unquote(parts.fragment)
    if target.is_dir():
        for name in ("index.md", "README.md"):
            candidate = target / name
            if candidate.is_file():
                return candidate, unquote(parts.fragment)
    return target, unquote(parts.fragment)


def check_links(path: Path, visible_markdown: str) -> list[str]:
    errors: list[str] = []
    links = [match.group(1) for match in INLINE_LINK.finditer(visible_markdown)]
    links.extend(match.group(1) for match in REFERENCE_LINK.finditer(visible_markdown))
    for raw in links:
        target_string = link_target(raw)
        if not target_string or target_string.startswith(("#", "mailto:", "tel:", "data:")):
            continue
        target, fragment = resolve_link(path, target_string)
        if target is None:
            continue
        if not target.is_file():
            errors.append(f"{path.relative_to(ROOT)}: broken local link {target_string!r}")
            continue
        if fragment and target.suffix.lower() == ".md":
            anchors = page_anchors(target)
            if fragment not in anchors:
                errors.append(f"{path.relative_to(ROOT)}: missing anchor {fragment!r} in {target.relative_to(ROOT)}")
    return errors


def check_fences(path: Path, blocks: list[tuple[int, str, str]], strict_tools: bool) -> list[str]:
    errors: list[str] = []
    for line_number, language_info, content in blocks:
        language = language_info.split(maxsplit=1)[0].lower() if language_info else ""
        where = f"{path.relative_to(ROOT)}:{line_number}"
        if not language:
            errors.append(f"{where}: fenced block must declare a language")
            continue
        if not content.strip():
            errors.append(f"{where}: fenced block must contain an example")
            continue
        if language in {"sh", "bash", "shell"}:
            if shutil.which("bash"):
                result = subprocess.run(["bash", "-n"], input=content, text=True, capture_output=True, check=False)
                if result.returncode:
                    errors.append(f"{where}: shell syntax error: {result.stderr.strip()}")
            elif strict_tools:
                errors.append(f"{where}: bash is required to validate shell examples")
        elif language == "json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                errors.append(f"{where}: invalid JSON example: {exc}")
        elif language in {"regex", "regexp"}:
            import re

            try:
                re.compile(content.strip())
            except re.error as exc:
                errors.append(f"{where}: invalid regular expression: {exc}")
        elif language in {"python", "python3"}:
            try:
                compile(content, f"{path}:{line_number}", "exec")
            except SyntaxError as exc:
                errors.append(f"{where}: invalid Python example: {exc}")
        elif language == "mermaid" and not content.lstrip().startswith(
            ("stateDiagram", "flowchart", "sequenceDiagram", "erDiagram")
        ):
            errors.append(f"{where}: Mermaid example must declare a supported diagram type")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-tools", action="store_true", help="fail if bash is unavailable for shell checks")
    args = parser.parse_args()

    errors: list[str] = []
    count = 0
    for path in authored_markdown():
        count += 1
        try:
            visible, blocks = remove_fenced_code(path.read_text(encoding="utf-8"), path)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        errors.extend(check_links(path, visible))
        errors.extend(check_fences(path, blocks, args.strict_tools))

    if errors:
        print("Documentation checks failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Documentation links and fenced examples validated across {count} first-party Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
