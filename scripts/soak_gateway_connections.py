#!/usr/bin/env python3
"""Open real partial HTTP requests to measure live gateway socket/thread RSS."""

from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gateway.server import GatewayHTTPServer, GatewayService  # noqa: E402

GIB = 1024**3


class QuietSoakServer(GatewayHTTPServer):
    def handle_error(self, request, client_address):  # noqa: ANN001
        # Closed soak clients are expected; keep per-thread tracebacks out of the report.
        return


def current_rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def task_count() -> int:
    try:
        return len(list(Path("/proc/self/task").iterdir()))
    except OSError:
        return threading.active_count()


def first_cpu_line(prefix: str) -> str:
    try:
        return next(line.strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith(prefix))
    except (OSError, StopIteration):
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--thread-stack-bytes", type=int, default=128 * 1024)
    parser.add_argument("--output", type=Path, default=Path("bench/results/bounded-state-socket-soak-wsl2.json"))
    args = parser.parse_args()
    if args.connections < 1 or args.batch_size < 1 or args.thread_stack_bytes < 32 * 1024:
        parser.error("connections and batch-size must be positive; thread stack must be at least 32 KiB")

    threading.stack_size(args.thread_stack_bytes)
    service = GatewayService(model_delay_seconds=0)
    server = QuietSoakServer(("127.0.0.1", 0), service)
    serving_thread = threading.Thread(target=server.serve_forever, name="gateway-soak-listener", daemon=True)
    serving_thread.start()
    time.sleep(0.05)

    baseline_threads = task_count()
    baseline_rss = current_rss_bytes()
    peak_rss = baseline_rss or 0
    clients: list[socket.socket] = []
    failures: list[str] = []
    highest_live_threads = baseline_threads
    highest_accepted_connections = 0
    shutdown_started = False
    try:
        for batch_start in range(0, args.connections, args.batch_size):
            batch_end = min(args.connections, batch_start + args.batch_size)
            for index in range(batch_start, batch_end):
                if not serving_thread.is_alive():
                    failures.append("gateway listener thread stopped while accepting sockets")
                    break
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(30)
                try:
                    client.connect(server.server_address)
                    clients.append(client)
                except OSError as exc:
                    failures.append(f"connection {index} failed: {type(exc).__name__}: {exc}")
                    client.close()
                    break
            expected = baseline_threads + len(clients)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current_threads = task_count()
                highest_live_threads = max(highest_live_threads, current_threads)
                highest_accepted_connections = max(
                    highest_accepted_connections, max(0, current_threads - baseline_threads)
                )
                peak_rss = max(peak_rss, current_rss_bytes() or 0)
                if current_threads >= expected or not serving_thread.is_alive():
                    break
                time.sleep(0.01)
            if len(clients) < batch_end or not serving_thread.is_alive():
                break
    finally:
        for client in clients:
            client.close()
        if serving_thread.is_alive():
            server.shutdown()
            shutdown_started = True
        server.server_close()
        if shutdown_started:
            serving_thread.join(timeout=5)
        cleanup_deadline = time.monotonic() + 10
        while time.monotonic() < cleanup_deadline and task_count() > baseline_threads:
            time.sleep(0.05)
        time.sleep(0.1)

    actual_connections = len(clients)
    rss_delta = max(0, peak_rss - (baseline_rss or peak_rss))
    bytes_per_connection = rss_delta / highest_accepted_connections if highest_accepted_connections else None
    kernel = platform.release()
    platform_scope = (
        "WSL2 development-only; not native Linux capacity evidence"
        if "microsoft" in kernel.lower()
        else "Linux; host qualification required"
    )
    report = {
        "classification": "measured",
        "platform_scope": platform_scope,
        "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": platform.node(),
        "platform": platform.platform(),
        "kernel": kernel,
        "python": sys.version.split()[0],
        "cpu_model": first_cpu_line("model name"),
        "cpu_frequency_mhz_snapshot": first_cpu_line("cpu MHz"),
        "allowed_cpu_list": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/self/status").read_text().splitlines()
                if line.startswith("Cpus_allowed_list:")
            ),
            "unavailable",
        ),
        "requested_connections": args.connections,
        "opened_real_sockets": actual_connections,
        "highest_accepted_handler_threads": highest_accepted_connections,
        "completed_accepted_target": highest_accepted_connections == args.connections,
        "highest_live_threads": highest_live_threads,
        "baseline_threads": baseline_threads,
        "thread_stack_bytes": args.thread_stack_bytes,
        "baseline_process_rss_bytes": baseline_rss,
        "peak_sampled_process_rss_bytes": peak_rss,
        "incremental_rss_bytes": rss_delta,
        "estimated_rss_bytes_per_live_handler_thread": bytes_per_connection,
        "estimated_connections_per_gib_from_incremental_rss": int(GIB / bytes_per_connection)
        if bytes_per_connection
        else None,
        "retained_state_bytes": service.state.used_bytes,
        "active_streams": service.state.active_stream_count(),
        "connection_protocol": "TCP connected with no request bytes sent; each accepted socket remains blocked on the HTTP request line",
        "failures": failures,
        "handler_threads_cleaned_up": task_count() <= baseline_threads,
        "shell_setup": "ulimit -n 30000; previous soft limit 10240, hard limit 1048576",
        "exact_command": "python scripts/soak_gateway_connections.py " + " ".join(sys.argv[1:]),
        "known_limit": "This measures idle live HTTP socket and Python handler-thread overhead, not an active model stream or native Linux capacity.",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "platform_scope",
                    "requested_connections",
                    "opened_real_sockets",
                    "highest_live_threads",
                    "highest_accepted_handler_threads",
                    "incremental_rss_bytes",
                    "estimated_rss_bytes_per_live_handler_thread",
                    "estimated_connections_per_gib_from_incremental_rss",
                    "failures",
                )
            },
            sort_keys=True,
        )
    )
    return 0 if actual_connections == args.connections and highest_accepted_connections == args.connections else 1


if __name__ == "__main__":
    raise SystemExit(main())
