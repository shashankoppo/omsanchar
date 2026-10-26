#!/usr/bin/env bash
set -euo pipefail

: "${D5_BASELINE_HTTP:?set D5_BASELINE_HTTP}"
: "${D5_BASELINE_HTTPS:?set D5_BASELINE_HTTPS}"
: "${D5_ENVOY_HTTP:?set D5_ENVOY_HTTP}"
: "${D5_ENVOY_HTTPS:?set D5_ENVOY_HTTPS}"
: "${D5_RUST_HTTP:?set D5_RUST_HTTP}"
: "${D5_RUST_HTTPS:?set D5_RUST_HTTPS}"

rate_rps="${D5_RATE_RPS:-100}"
duration_secs="${D5_DURATION_SECS:-10}"
output_root="${D5_OUTPUT_ROOT:-bench/results/d5}"
ca_cert="${D5_CA_CERT:-}"
root="$(git rev-parse --show-toplevel)"

for implementation in baseline envoy rust; do
  case "$implementation" in
    baseline)
      http_endpoint="$D5_BASELINE_HTTP"
      https_endpoint="$D5_BASELINE_HTTPS"
      ;;
    envoy)
      http_endpoint="$D5_ENVOY_HTTP"
      https_endpoint="$D5_ENVOY_HTTPS"
      ;;
    rust)
      http_endpoint="$D5_RUST_HTTP"
      https_endpoint="$D5_RUST_HTTPS"
      ;;
  esac
  for tls in http https; do
    if [[ "$tls" == "http" ]]; then
      endpoint="$http_endpoint"
    else
      endpoint="$https_endpoint"
    fi
    for workload in sse500 mcp fanout; do
      for concurrency in 1 100 1000 10000; do
        for run in $(seq 1 10); do
          output="$output_root/$implementation/$tls/$workload/c$((concurrency))/run-${run}.json"
          mkdir -p "$(dirname "$output")"
          command=(cargo +1.85.0 run --release --locked --manifest-path "$root/dataplane/sanchar-core/Cargo.toml" --features d5-bench --bin d5_loadgen -- "$endpoint" "$workload" "$rate_rps" "$duration_secs" "$concurrency" "$output")
          if [[ "$tls" == "https" && -n "$ca_cert" ]]; then
            command+=("$ca_cert")
          fi
          printf 'D5_CELL implementation=%s tls=%s workload=%s concurrency=%s run=%s\n' \
            "$implementation" "$tls" "$workload" "$concurrency" "$run"
          "${command[@]}"
        done
      done
    done
  done
done
