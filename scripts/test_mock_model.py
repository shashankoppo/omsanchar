"""Smoke-test the Rust mock model without placing Python on its request path."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(port: int, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/test_mock_model.py PATH_TO_MOCK_MODEL_BINARY")
    binary = Path(sys.argv[1]).resolve()
    port = free_port()
    environment = os.environ.copy()
    environment["OM_MOCK_PORT"] = str(port)
    process = subprocess.Popen([str(binary)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                status, payload = request(port, "GET", "/healthz")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("Rust mock model did not become healthy")
        assert json.loads(payload) == {"status": "ok"}

        status, payload = request(
            port,
            "POST",
            "/mcp",
            json.dumps({"jsonrpc": "2.0", "id": "tool-1", "method": "tools/call"}).encode(),
        )
        assert status == 200
        tool_result = json.loads(payload)
        assert tool_result["id"] == "tool-1"
        assert tool_result["result"]["content"][0]["text"] == "mock-tool-ok"

        status, payload = request(port, "GET", "/fanout?n=16")
        assert status == 200
        assert len(json.loads(payload)["results"]) == 16

        status, payload = request(
            port,
            "POST",
            "/v1/chat/completions",
            b'{"stream":true}',
        )
        assert status == 200
        assert len([line for line in payload.splitlines() if line.startswith(b"event: delta")]) == 500
        print("Rust mock smoke passed: health, MCP JSON-RPC, 16-way fan-out, and 500-token SSE")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
