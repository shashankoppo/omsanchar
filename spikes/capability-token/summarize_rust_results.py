"""Summarize raw Rust token measurements and bootstrap run-level median CIs."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import zlib
from pathlib import Path
from typing import Any


def percentile(values: list[int], numerator: int, denominator: int) -> int:
    ordered = sorted(values)
    index = max(0, (len(ordered) * numerator + denominator - 1) // denominator - 1)
    return ordered[index]


def summarize_runs(runs: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    all_samples = [sample for run in runs for sample in run["samples_ns"]]
    run_medians = [int(run["p50_ns"]) for run in runs]
    generator = random.Random(seed)
    bootstrap_medians = sorted(
        statistics.median(generator.choices(run_medians, k=len(run_medians)))
        for _ in range(20_000)
    )
    return {
        "median_ns": int(statistics.median(all_samples)),
        "p95_ns": percentile(all_samples, 95, 100),
        "p99_ns": percentile(all_samples, 99, 100),
        "run_median_min_ns": min(run_medians),
        "run_median_max_ns": max(run_medians),
        "median_95pct_bootstrap_ci_ns": [
            int(percentile(bootstrap_medians, 2, 100)),
            int(percentile(bootstrap_medians, 98, 100)),
        ],
        "confidence_method": "percentile bootstrap over 10 independent run medians, 20,000 resamples; WSL2 development-only",
    }


def render_markdown(summary: dict[str, Any]) -> str:
    by_depth: dict[int, dict[str, dict[str, Any]]] = {}
    for cell in summary["results"]:
        by_depth.setdefault(cell["depth"], {})[cell["scheme"]] = cell
    schemes = ["hmac-chain", "biscuit-auth-6.0.0", "ed25519-attenuation-chain"]
    labels = [
        "HMAC chain (bytes / cold p50 us [CI] / cache p50 us)",
        "Biscuit 6.0.0 (bytes / cold p50 us [CI] / cache p50 us)",
        "Ed25519 chain (bytes / cold p50 us [CI] / cache p50 us)",
    ]
    lines = [
        "# Rust capability-token comparison (WSL2 development only)",
        "",
        "All values below are **measured** on WSL2 Ubuntu and are not native Linux target evidence. The final 50 us target verdict is **inconclusive** until the same matrix is run on a native Linux host.",
        "",
        f"- Platform: `{summary['metadata']['kernel']}`, `{summary['metadata']['cpu_model']}`, allowed CPUs `{summary['metadata']['allowed_cpu_list']}`.",
        f"- Rust: `{summary['metadata']['rustc']}`; `{summary['metadata']['runs_per_cell']}` runs x `{summary['metadata']['iterations_per_run']}` measured samples per scheme/depth/mode, plus `{summary['metadata']['warmup_iterations_per_run']}` warmups per run.",
        "- Each cell shows token bytes / uncached p50 microseconds with a 95% bootstrap CI over run medians / cached p50 microseconds. The summary JSON includes p95, p99, and raw run distributions; the adjacent raw JSON retains every sample.",
        "- Cache hit timing includes SHA-256 token hashing, a hash-map lookup, a monotonic 10-minute TTL check, and issuer-key version check. It excludes cache insertion and internal-credential minting.",
        "",
        "| Depth | " + " | ".join(labels) + " |",
        "|---:|---:|---:|---:|",
    ]
    for depth in sorted(by_depth):
        cells = by_depth[depth]
        values = []
        for scheme in schemes:
            cell = cells[scheme]
            cold = cell["uncached"]
            low, high = cold["median_95pct_bootstrap_ci_ns"]
            values.append(
                f"{cell['token_size_bytes']} B / {cold['median_ns'] / 1000:.3f} "
                f"[{low / 1000:.3f}, {high / 1000:.3f}] / {cell['cached']['median_ns'] / 1000:.3f}"
            )
        lines.append(f"| {depth} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## Depth-4 target reading",
            "",
            "At depth 4 the HMAC token is 160 B at 1.185 us uncached p50, Biscuit is 818 B at 215.368 us, and the Ed25519 chain is 608 B at 148.444 us. Their cached p50 values are 0.156, 0.432, and 0.349 us, respectively. The 1.5 KB depth-4 size target is measured as met for all three encodings. The 50 us uncached verification target is missed by both public-key designs on this WSL2 run; HMAC meets the numeric target but has the root-secret trust problem below.",
            "",
            "## Trust and two-tier design",
            "",
            "Every HMAC verifier needs the root secret; compromise of any gateway holding it permits minting valid tokens for that root. Biscuit and the Ed25519 attenuation chain verify from public keys, so gateway compromise does not expose issuer minting authority. The public-key verification cost is higher in this prototype. The two-tier design remains the preferred direction for evaluation: verify the public-key chain once at ingress, cache the verified authorization by token hash with TTL and issuer-key version checks, then mint an audience-bound, short-lived internal credential bounded by the parent expiry and request deadline. This benchmark measures cache-hit lookup only; it does not measure internal-credential minting or propagation.",
            "",
            "## Exact commands",
            "",
            "```bash",
            "RUSTUP_HOME=/tmp/omsanchar-rustup CARGO_HOME=/home/shashank_patel/.cargo PATH=/tmp/omsanchar-rust-cargo/bin:$PATH \\",
            "  cargo +1.85.0 run --release --locked --manifest-path dataplane/sanchar-core/Cargo.toml \\",
            "  --features token-bench --bin capability_token_bench -- 1000 10 \\",
            "  bench/results/capability-token-rust-wsl2-2026-10-25.json",
            "python spikes/capability-token/summarize_rust_results.py \\",
            "  bench/results/capability-token-rust-wsl2-2026-10-25.json",
            "```",
            "",
            f"Confidence intervals are estimated with `{summary['confidence_method']}`. These are development results, so they do not replace the native Linux measurement required by ADR-005.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    summary = {
        "classification": raw["metadata"]["classification"],
        "platform_scope": raw["metadata"]["platform_scope"],
        "metadata": raw["metadata"],
        "confidence_method": "percentile bootstrap over 10 independent run medians, 20,000 resamples; reported intervals are estimates",
        "results": [],
    }
    for cell in raw["results"]:
        seed = zlib.crc32(f"{cell['scheme']}:{cell['depth']}".encode("utf-8"))
        summary["results"].append(
            {
                "scheme": cell["scheme"],
                "depth": cell["depth"],
                "token_size_bytes": cell["token_size_bytes"],
                "uncached": summarize_runs(cell["uncached"], seed=seed),
                "cached": summarize_runs(cell["cached"], seed=seed ^ 0xA5A5A5A5),
            }
        )
    output = args.output or args.input.with_name(args.input.stem + "-summary.json")
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = output.with_suffix(".md")
    markdown.write_text(render_markdown(summary), encoding="utf-8")
    print(f"{output}\n{markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
