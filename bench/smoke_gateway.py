"""Measure the native mock-stream gateway over loopback; not a proxy comparison."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import random
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gateway.server import GatewayService, make_server  # noqa: E402


def _sse_event(response: http.client.HTTPResponse) -> dict[str, Any]:
    fields: dict[str, str] = {}
    while True:
        line = response.readline().decode("utf-8").rstrip("\r\n")
        if not line:
            if fields:
                return {
                    "id": fields.get("id"),
                    "event": fields.get("event", "message"),
                    "data": json.loads(fields.get("data", "{}")),
                }
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        fields[name] = value.lstrip()


def _run_one(host: str, port: int, index: int) -> dict[str, int]:
    connection = http.client.HTTPConnection(host, port, timeout=10)
    body = json.dumps(
        {
            "model": "om://demo/model/default",
            "messages": [{"role": "user", "content": "hello there"}],
            "stream": True,
            "idempotency_key": f"bench-{index}",
            "max_tokens": 1,
        },
        separators=(",", ":"),
    )
    started = time.perf_counter_ns()
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Authorization": "Bearer benchmark-token", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        headers_ns = time.perf_counter_ns()
        if response.status != 200:
            raise RuntimeError(f"gateway returned HTTP {response.status}: {response.read().decode('utf-8')}")
        first = _sse_event(response)
        first_token_ns = time.perf_counter_ns()
        if first["event"] != "delta":
            raise RuntimeError(f"expected first event delta, got {first['event']}")
        while True:
            event = _sse_event(response)
            if event["event"] == "done":
                break
            if event["event"] != "delta":
                raise RuntimeError(f"unexpected event during benchmark: {event['event']}")
        completed_ns = time.perf_counter_ns()
        return {
            "headers_ns": headers_ns - started,
            "first_token_ns": first_token_ns - started,
            "complete_ns": completed_ns - started,
        }
    finally:
        connection.close()


def _quantiles_ms(samples_ns: list[int]) -> dict[str, Any]:
    ordered = sorted(samples_ns)

    def percentile(percent: float) -> float:
        index = max(0, min(len(ordered) - 1, int((percent / 100) * len(ordered) + 0.999999) - 1))
        return ordered[index] / 1_000_000

    rng = random.Random(0)
    bootstrap_medians = sorted(statistics.median(rng.choices(ordered, k=len(ordered))) for _ in range(2_000))
    low = bootstrap_medians[int(0.025 * len(bootstrap_medians))] / 1_000_000
    high = bootstrap_medians[int(0.975 * len(bootstrap_medians)) - 1] / 1_000_000
    return {
        "min": ordered[0] / 1_000_000,
        "median": statistics.median(ordered) / 1_000_000,
        "mean": statistics.fmean(ordered) / 1_000_000,
        "p95": percentile(95),
        "p99": percentile(99),
        "max": ordered[-1] / 1_000_000,
        "median_ci95_percentile_bootstrap": {"low": low, "high": high, "resamples": 2_000, "seed": 0},
    }


def _ram_bytes() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("avail_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_phys)
    except (AttributeError, OSError):
        return None
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("bench/results/gateway-smoke-windows-python312-100x10.json"),
    )
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0:
        parser.error("iterations must be positive and warmup cannot be negative")

    service = GatewayService(bearer_token="benchmark-token", allowance_microcredits=10_000_000, model_delay_seconds=0)
    server = make_server("127.0.0.1", 0, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        for index in range(args.warmup):
            _run_one(host, port, index)
        raw = [_run_one(host, port, args.warmup + index) for index in range(args.iterations)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    script_path = Path(__file__).resolve()
    service_path = ROOT / "gateway" / "server.py"
    result = {
        "schema_version": 1,
        "benchmark": "native_gateway_loopback_stream_smoke",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": None,
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "processor_identifier": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unavailable"),
            "logical_processors": os.cpu_count(),
            "total_ram_bytes": _ram_bytes(),
        },
        "workload": {
            "transport": "HTTP/1.1 over IPv4 loopback",
            "requests": args.iterations,
            "warmup_requests": args.warmup,
            "concurrency": 1,
            "input_tokens": 2,
            "output_tokens_per_request": 1,
            "model": "deterministic in-process mock",
            "mock_delay_ms": 0,
            "auth": "static local bearer credential",
            "price_table": {"input_microcredits_per_token": 1, "output_microcredits_per_token": 2},
        },
        "confidence_interval_method": "95% percentile bootstrap interval for the median, 2,000 resamples, seed 0",
        "metrics_ms": {
            name.removesuffix("_ns"): _quantiles_ms([sample[name] for sample in raw])
            for name in ("headers_ns", "first_token_ns", "complete_ns")
        },
        "raw_samples_ns": raw,
        "source_sha256": {
            str(script_path.relative_to(ROOT)): _sha256(script_path),
            str(service_path.relative_to(ROOT)): _sha256(service_path),
        },
        "limitations": [
            "This is an end-to-end smoke measurement of the Python reference gateway, not proxy overhead.",
            "It is not an Envoy-versus-Rust comparison and does not cover MCP tool-call or fan-out workloads.",
            "Loopback, one client, one in-process mock model, one output token, and no TLS are used.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "metrics_ms": result["metrics_ms"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
