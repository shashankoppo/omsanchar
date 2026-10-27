#!/usr/bin/env python3
"""Post-process Rust d5_loadgen reports; this script is outside the measured path."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

PERCENTILES = {"p50_ns": 0.50, "p99_ns": 0.99, "p999_ns": 0.999}
IMPLEMENTATIONS = ("baseline", "envoy", "rust")
TRANSPORTS = ("http", "https")
WORKLOADS = ("sse500", "mcp", "fanout")
CONCURRENCY = (1, 100, 1000, 10000)
RUNS = range(1, 11)


def bootstrap_ci(values: list[int], *, seed: int, replicates: int = 20_000) -> list[float]:
    rng = random.Random(seed)
    estimates = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(replicates))
    return [float(estimates[int(replicates * 0.025)]), float(estimates[int(replicates * 0.975)])]


def load_cell(
    root: Path, implementation: str, transport: str, workload: str, concurrency: int
) -> dict[int, dict[str, Any]]:
    reports: dict[int, dict[str, Any]] = {}
    for run in RUNS:
        path = root / implementation / transport / workload / f"c{concurrency}" / f"run-{run}.json"
        if not path.is_file():
            raise FileNotFoundError(f"missing registered run: {path}")
        reports[run] = json.loads(path.read_text(encoding="utf-8"))
    return reports


def histogram_value(report: dict[str, Any], quantile: float) -> int:
    for value in report["hdrhistogram_percentiles"]:
        if abs(value["percentile"] - quantile) < 1e-9:
            return int(value["value_ns"])
    raise ValueError(f"missing HdrHistogram quantile {quantile}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="run-matrix.sh output directory")
    parser.add_argument("--output", type=Path, default=Path("bench/results/d5-summary.json"))
    parser.add_argument("--feature-parity-verified", action="store_true")
    args = parser.parse_args()

    results = []
    platform_keys: set[tuple[str, str, str]] = set()
    frequency_snapshots: set[str] = set()
    all_wsl = True
    for transport in TRANSPORTS:
        for workload in WORKLOADS:
            for concurrency in CONCURRENCY:
                cells = {
                    implementation: load_cell(args.root, implementation, transport, workload, concurrency)
                    for implementation in IMPLEMENTATIONS
                }
                baseline = cells["baseline"]
                for implementation, reports in cells.items():
                    for run, report in reports.items():
                        if report["offered_rate_rps"] != baseline[run]["offered_rate_rps"]:
                            raise ValueError("offered rates differ within a paired run")
                        if report["planned_duration_seconds"] != baseline[run]["planned_duration_seconds"]:
                            raise ValueError("durations differ within a paired run")
                        platform_keys.add(
                            (
                                report["kernel"],
                                report["cpu_model"],
                                report["allowed_cpu_list"],
                            )
                        )
                        frequency_snapshots.add(report["cpu_frequency_mhz_snapshot"])
                        all_wsl &= "WSL2" in report["platform_scope"]
                if len(platform_keys) > 1:
                    raise ValueError("reports include mixed kernel/CPU/frequency/affinity metadata")

                for implementation in ("envoy", "rust"):
                    proxy = cells[implementation]
                    metric_deltas = {}
                    for metric_index, (metric, quantile) in enumerate(PERCENTILES.items()):
                        paired_deltas = [
                            histogram_value(proxy[run], quantile) - histogram_value(baseline[run], quantile)
                            for run in RUNS
                        ]
                        metric_deltas[metric] = {
                            "median_proxy_minus_baseline_ns": statistics.median(paired_deltas),
                            "bootstrap_95_ci_ns": bootstrap_ci(
                                paired_deltas,
                                seed=20261027
                                + metric_index
                                + concurrency
                                + (0 if implementation == "envoy" else 100_000),
                            ),
                            "paired_run_deltas_ns": paired_deltas,
                        }
                    invalid_runs = [
                        run
                        for run in RUNS
                        if cells[implementation][run]["http_or_transport_errors"]
                        or baseline[run]["http_or_transport_errors"]
                        or cells[implementation][run]["dropped_at_concurrency_cap"]
                        or baseline[run]["dropped_at_concurrency_cap"]
                        or cells[implementation][run]["late_dispatches_over_1ms"]
                        or baseline[run]["late_dispatches_over_1ms"]
                    ]
                    results.append(
                        {
                            "classification": "measured; WSL2 development-only"
                            if all_wsl
                            else "measured; host qualification required",
                            "implementation": implementation,
                            "transport": transport,
                            "workload": workload,
                            "concurrency_cap": concurrency,
                            "run_count": len(RUNS),
                            "overhead_deltas": metric_deltas,
                            "invalid_runs_with_errors_or_drops": invalid_runs,
                            "feature_parity_verified": args.feature_parity_verified,
                            "target_cpu_seconds_per_completed_request": None,
                            "target_resident_memory_bytes": None,
                            "decision_status": "inconclusive",
                            "decision_reason": "target CPU/RSS collectors and native-host qualification are required; equal-feature pipeline must be independently verified",
                        }
                    )

    summary = {
        "classification": "estimated confidence intervals over measured per-run HdrHistogram quantiles",
        "platform_scope": "WSL2 development-only" if all_wsl else "qualify native Linux host before making a decision",
        "run_root": str(args.root),
        "paired_bootstrap_replicates": 20_000,
        "confidence_level": 0.95,
        "same_host_metadata": next(iter(platform_keys), None),
        "observed_cpu_frequency_snapshots": sorted(frequency_snapshots),
        "feature_parity_verified": args.feature_parity_verified,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}; {len(results)} paired proxy cells; decision remains inconclusive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
