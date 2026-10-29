#!/usr/bin/env bash
set -euo pipefail

curl_request=(curl --connect-timeout 2 --max-time 20)

export OM_TOKEN_ROOT_SECRET="${OM_TOKEN_ROOT_SECRET:-om-sanchar-demo-root-secret-change-before-deployment}"
export OM_ADMIN_TOKEN="${OM_ADMIN_TOKEN:-om-sanchar-demo-admin-secret-change-before-deployment}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
cargo build --locked --manifest-path crates/Cargo.toml --workspace

target_root="${CARGO_TARGET_DIR:-crates/target}"
mock_log="$(mktemp)"
gateway_log="$(mktemp)"
response_file="$(mktemp)"
mock_pid=""
gateway_pid=""
cleanup() {
  if [[ -n "$gateway_pid" ]]; then
    kill "$gateway_pid" 2>/dev/null || true
    wait "$gateway_pid" 2>/dev/null || true
  fi
  if [[ -n "$mock_pid" ]]; then
    kill "$mock_pid" 2>/dev/null || true
    wait "$mock_pid" 2>/dev/null || true
  fi
  rm -f "$mock_log" "$gateway_log" "$response_file"
}
trap cleanup EXIT INT TERM

OM_MOCK_LISTEN="${OM_MOCK_LISTEN:-127.0.0.1:8081}" "$target_root/debug/om-mock-model" >"$mock_log" 2>&1 &
mock_pid=$!
OM_GATEWAY_CONFIG="${OM_GATEWAY_CONFIG:-crates/om-gateway/config/routes.local.json}" \
  OM_GATEWAY_LISTEN="${OM_GATEWAY_LISTEN:-127.0.0.1:8080}" \
  OM_TOKEN_ROOT_SECRET="$OM_TOKEN_ROOT_SECRET" \
  OM_ADMIN_TOKEN="$OM_ADMIN_TOKEN" \
  "$target_root/debug/om-gateway" >"$gateway_log" 2>&1 &
gateway_pid=$!

gateway_url="http://${OM_GATEWAY_LISTEN:-127.0.0.1:8080}"
for _ in $(seq 1 80); do
  if "${curl_request[@]}" --fail --silent "$gateway_url/readyz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! "${curl_request[@]}" --fail --silent "$gateway_url/readyz" >/dev/null; then
  cat "$mock_log" "$gateway_log" >&2
  echo "timed out waiting for gateway readiness" >&2
  exit 1
fi

admin_status="$("${curl_request[@]}" --silent --output /dev/null --write-out '%{http_code}' \
  --header 'content-type: application/json' \
  --data '{"tenant":"tenant-a","model":"om://demo/model/default","budget_microcredits":500000,"max_output_tokens":64,"expires_in_seconds":3600}' \
  "$gateway_url/v1/control/tokens")"
test "$admin_status" = 401

parent="$("${curl_request[@]}" --fail --silent --show-error \
  --header "x-om-admin-token: ${OM_ADMIN_TOKEN}" \
  --header 'content-type: application/json' \
  --data '{"tenant":"tenant-a","model":"om://demo/model/default","budget_microcredits":500000,"max_output_tokens":64,"expires_in_seconds":3600}' \
  "$gateway_url/v1/control/tokens")"
parent_token="$(sed -n 's/.*"token":"\([^"]*\)".*/\1/p' <<<"$parent")"
expires_at="$(sed -n 's/.*"expires_at_unix_seconds":\([0-9]*\).*/\1/p' <<<"$parent")"

attenuation_body="{\"token\":\"${parent_token}\",\"tenant\":\"tenant-a\",\"model\":\"om://demo/model/default\",\"budget_microcredits\":10000,\"max_output_tokens\":16,\"expires_at_unix_seconds\":${expires_at}}"
child="$("${curl_request[@]}" --fail --silent --show-error \
  --header "x-om-admin-token: ${OM_ADMIN_TOKEN}" \
  --header 'content-type: application/json' \
  --data "$attenuation_body" \
  "$gateway_url/v1/control/tokens/attenuate")"
child_token="$(sed -n 's/.*"token":"\([^"]*\)".*/\1/p' <<<"$child")"
test -n "$parent_token"
test -n "$child_token"

echo "Narrow token: allowed request (budget 9,000 / output 8)"
"${curl_request[@]}" --fail --silent --show-error --no-buffer \
  --header 'content-type: application/json' \
  --header "authorization: Bearer ${child_token}" \
  --header 'x-om-tenant: tenant-a' \
  --header 'x-om-budget-microcredits: 9000' \
  --data '{"model":"om://demo/model/default","stream":true,"max_tokens":8}' \
  "$gateway_url/v1/chat/completions" | tee "$response_file"
grep --fixed-strings --quiet 'data: [DONE]' "$response_file"

echo "Narrow token: over-limit request is denied"
denied_status="$("${curl_request[@]}" --silent --show-error --output "$response_file" --write-out '%{http_code}' \
  --header 'content-type: application/json' \
  --header "authorization: Bearer ${child_token}" \
  --header 'x-om-tenant: tenant-a' \
  --header 'x-om-budget-microcredits: 9000' \
  --data '{"model":"om://demo/model/default","stream":true,"max_tokens":17}' \
  "$gateway_url/v1/chat/completions")"
test "$denied_status" = 403
grep --quiet 'OS-0101' "$response_file"

"${curl_request[@]}" --fail --silent --show-error \
  --header "x-om-admin-token: ${OM_ADMIN_TOKEN}" \
  --header 'content-type: application/json' \
  --data "{\"token\":\"${child_token}\"}" \
  "$gateway_url/v1/control/tokens/revoke" >/dev/null
revoked_status="$("${curl_request[@]}" --silent --show-error --output "$response_file" --write-out '%{http_code}' \
  --header 'content-type: application/json' \
  --header "authorization: Bearer ${child_token}" \
  --header 'x-om-tenant: tenant-a' \
  --header 'x-om-budget-microcredits: 9000' \
  --data '{"model":"om://demo/model/default","stream":true,"max_tokens":8}' \
  "$gateway_url/v1/chat/completions")"
test "$revoked_status" = 401
grep --quiet 'OS-0100' "$response_file"

echo "Bounded token metrics:"
"${curl_request[@]}" --fail --silent --show-error "$gateway_url/metrics" | grep '^om_token_'
echo "S2 demo passed: admin minting, attenuation, scoped allow/deny, revocation, and bounded cache metrics."
