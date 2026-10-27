"""Execute the shell commands shown in the public gateway quickstart."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "docs" / "quickstart.md"
EXAMPLE_MARKER = re.compile(r"^<!-- docs-example: ([a-z0-9-]+) -->\s*$")
FENCE_OPEN = re.compile(r"^```(\w+)\s*$")


def examples_by_id(markdown: str) -> dict[str, tuple[str, str]]:
    lines = markdown.splitlines()
    examples: dict[str, tuple[str, str]] = {}
    index = 0
    while index < len(lines):
        marker = EXAMPLE_MARKER.match(lines[index])
        if not marker:
            index += 1
            continue
        example_id = marker.group(1)
        index += 1
        if index >= len(lines):
            raise ValueError(f"{example_id}: missing fenced example")
        opening = FENCE_OPEN.match(lines[index])
        if not opening:
            raise ValueError(f"{example_id}: marker must immediately precede a fenced example")
        language = opening.group(1)
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index] != "```":
            body.append(lines[index])
            index += 1
        if index == len(lines):
            raise ValueError(f"{example_id}: unclosed fenced example")
        if example_id in examples:
            raise ValueError(f"duplicate quickstart example id: {example_id}")
        examples[example_id] = (language, "\n".join(body))
        index += 1
    return examples


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    examples = examples_by_id(QUICKSTART.read_text(encoding="utf-8"))
    if set(examples) != {"start-gateway", "call-gateway"}:
        raise SystemExit(f"quickstart must define start-gateway and call-gateway, got {sorted(examples)}")

    language, start_command = examples["start-gateway"]
    if language != "bash" or shlex.split(start_command) != ["python3", "-m", "gateway.server"]:
        raise SystemExit("the documented start-gateway command changed; update this runner with it")
    language, call_commands = examples["call-gateway"]
    if language != "bash":
        raise SystemExit("call-gateway example must remain a Bash block")

    port = available_port()
    token = "docs-example-token"
    env = os.environ.copy()
    env.update({"OM_GATEWAY_PORT": str(port), "OM_GATEWAY_TOKEN": token})
    server = subprocess.Popen([sys.executable, "-m", "gateway.server"], cwd=ROOT, env=env)
    try:
        health_url = f"http://127.0.0.1:{port}/healthz"
        deadline = time.monotonic() + 10
        while True:
            try:
                with urllib.request.urlopen(health_url, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, TimeoutError):
                if server.poll() is not None:
                    raise RuntimeError("gateway process exited before becoming healthy")
                if time.monotonic() >= deadline:
                    raise RuntimeError("gateway did not become healthy within 10 seconds")
                time.sleep(0.05)

        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", call_commands],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"quickstart commands failed ({result.returncode}):\n{result.stderr}\n{result.stdout}")
        for expected in ('"status":"ok"', '"delta":"token-1"', '"delta":"token-2"', "event: done"):
            if expected not in result.stdout:
                raise RuntimeError(f"quickstart response did not contain {expected!r}:\n{result.stdout}")
        print("Documentation quickstart passed: health, authenticated SSE request, two tokens, terminal event.")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
