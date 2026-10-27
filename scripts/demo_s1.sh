#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

cargo build --locked --manifest-path crates/Cargo.toml --workspace

target_root="${CARGO_TARGET_DIR:-crates/target}"
mock_log="$(mktemp)"
gateway_log="$(mktemp)"
mock_pid=""
gateway_pid=""
response_file=""

cleanup() {
  if [[ -n "$gateway_pid" ]]; then
    kill "$gateway_pid" 2>/dev/null || true
    wait "$gateway_pid" 2>/dev/null || true
  fi
  if [[ -n "$mock_pid" ]]; then
    kill "$mock_pid" 2>/dev/null || true
    wait "$mock_pid" 2>/dev/null || true
  fi
  rm -f "$mock_log" "$gateway_log"
  if [[ -n "$response_file" ]]; then
    rm -f "$response_file"
  fi
}
trap cleanup EXIT INT TERM

OM_MOCK_LISTEN="${OM_MOCK_LISTEN:-127.0.0.1:8081}" "$target_root/debug/om-mock-model" >"$mock_log" 2>&1 &
mock_pid=$!
OM_GATEWAY_CONFIG="${OM_GATEWAY_CONFIG:-crates/om-gateway/config/routes.local.json}" \
  OM_GATEWAY_LISTEN="${OM_GATEWAY_LISTEN:-127.0.0.1:8080}" \
  "$target_root/debug/om-gateway" >"$gateway_log" 2>&1 &
gateway_pid=$!

wait_for_health() {
  local url="$1"
  for _ in $(seq 1 60); do
    if curl --fail --silent "$url" >/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  cat "$mock_log" "$gateway_log" >&2
  echo "timed out waiting for $url" >&2
  return 1
}

wait_for_health "http://${OM_MOCK_LISTEN:-127.0.0.1:8081}/healthz"
wait_for_health "http://${OM_GATEWAY_LISTEN:-127.0.0.1:8080}/readyz"

echo "Gateway health:"
curl --fail --silent --show-error "http://${OM_GATEWAY_LISTEN:-127.0.0.1:8080}/healthz"
echo
echo "Streaming completion through om-gateway:"
response_file="$(mktemp)"
curl --include --fail --silent --show-error --no-buffer \
  --header 'content-type: application/json' \
  --data '{"model":"om://demo/model/default","messages":[{"role":"user","content":"Say hello"}],"stream":true,"max_tokens":3}' \
  "http://${OM_GATEWAY_LISTEN:-127.0.0.1:8080}/v1/chat/completions" | tee "$response_file"
echo
grep --quiet '"content":"Rust"' "$response_file"
grep --quiet '"content":"gateway"' "$response_file"
grep --quiet '"content":"stream"' "$response_file"
grep --quiet 'data: \[DONE\]' "$response_file"
echo "Structured gateway and mock logs:"
cat "$gateway_log" "$mock_log"
echo "S1 demo passed: Rust gateway streamed three upstream chunks and the terminal event."
