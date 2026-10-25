"""Reproducible, raw-sample verifier microbenchmark for token depths 1..8."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from capability_token import attenuate, mint, verify

SPIKE_VERSION = "0.1.0"
TOKEN_FORMAT_VERSION = 1
NOW_UNIX_MS = 1_800_000_000_000


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    rank = max(1, int((len(ordered) * fraction) + 0.999999999))
    return ordered[rank - 1]


def run(iterations: int, warmup: int) -> dict[str, object]:
    issuer_key = b"benchmark-key-32-bytes-0123456789"
    root = mint(
        issuer_key,
        tenant="bench-tenant",
        subject="bench-agent",
        resources=[f"om://bench-tenant/tool/tool-{index:02d}" for index in range(8)],
        actions=["invoke", "read", "write", "stream"],
        budget_micros=5_000_000,
        expires_unix_ms=NOW_UNIX_MS + 3_600_000,
        token_id="bench-token-v1",
    )
    cases: list[dict[str, object]] = []
    for depth in range(1, 9):
        token = root
        for hop in range(depth):
            token = attenuate(
                token,
                budget_micros=5_000_000 - hop - 1,
                expires_unix_ms=NOW_UNIX_MS + 3_600_000 - hop - 1,
            )
        for _ in range(warmup):
            verify(token, issuer_key, now_unix_ms=NOW_UNIX_MS)
        measurements_ns: list[int] = []
        for _ in range(iterations):
            started = time.perf_counter_ns()
            verify(token, issuer_key, now_unix_ms=NOW_UNIX_MS)
            measurements_ns.append(time.perf_counter_ns() - started)
        cases.append(
            {
                "depth_hops": depth,
                "token_bytes_ascii": len(token.encode("ascii")),
                "verified_operations": iterations,
                "warmup_operations": warmup,
                "verification_ns": measurements_ns,
                "summary_ns": {
                    "min": min(measurements_ns),
                    "median": int(statistics.median(measurements_ns)),
                    "p95_nearest_rank": percentile(measurements_ns, 0.95),
                    "p99_nearest_rank": percentile(measurements_ns, 0.99),
                    "max": max(measurements_ns),
                    "mean": round(statistics.fmean(measurements_ns), 2),
                },
            }
        )
    return {
        "schema": "om-sanchar-capability-token-benchmark/v1",
        "spike_version": SPIKE_VERSION,
        "token_format_version": TOKEN_FORMAT_VERSION,
        "algorithm": "HMAC-SHA256 root authentication and chained caveat MACs",
        "benchmark": "single-threaded full-chain verify; perf_counter_ns around verify only",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_revision": os.environ.get("GIT_COMMIT"),
        "source_files_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("capability_token.py", "benchmark.py")
        },
        "environment": {
            "os": platform.platform(),
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER") or "unavailable",
            "logical_cpu_count": os.cpu_count(),
        },
        "workload": {
            "iterations_per_depth": iterations,
            "warmup_per_depth": warmup,
            "depth_hops": list(range(1, 9)),
            "issuer_key_bytes": len(issuer_key),
            "root_resource_count": 8,
            "root_action_count": 4,
            "budget_micros": 5_000_000,
            "clock_value_unix_ms": NOW_UNIX_MS,
            "measurement_unit": "nanoseconds per successful verification",
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 100 or args.warmup < 0:
        parser.error("--iterations must be at least 100 and --warmup must be non-negative")
    result = run(args.iterations, args.warmup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for case in result["cases"]:
        summary = case["summary_ns"]
        print(
            f"depth={case['depth_hops']} bytes={case['token_bytes_ascii']} "
            f"median_us={summary['median'] / 1000:.2f} "
            f"p95_us={summary['p95_nearest_rank'] / 1000:.2f} "
            f"p99_us={summary['p99_nearest_rank'] / 1000:.2f}"
        )
    print(f"raw results: {args.output}")


if __name__ == "__main__":
    main()
