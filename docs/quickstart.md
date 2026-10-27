# Quickstart

This quickstart exercises the P0 Python reference gateway and deterministic mock model. It is a development example; it does not configure a production identity provider or external model.

## Start the gateway

From the repository root, start the server in one terminal. Python 3.12 or newer is required.

<!-- docs-example: start-gateway -->
```bash
python3 -m gateway.server
```

The default listen address is `127.0.0.1:8080` and the development bearer credential is `dev-demo-token`. Set `OM_GATEWAY_TOKEN` before starting the server to use a different local credential.

## Check health and request a streamed completion

In a second terminal, run the following commands. The endpoint requires a bearer credential and an idempotency key. `curl --no-buffer` prints each server-sent event as it arrives.

<!-- docs-example: call-gateway -->
```bash
curl --fail --silent --show-error \
  "http://127.0.0.1:${OM_GATEWAY_PORT:-8080}/healthz"

curl --fail --silent --show-error --no-buffer \
  --header "Authorization: Bearer ${OM_GATEWAY_TOKEN:-dev-demo-token}" \
  --header "Content-Type: application/json" \
  --data '{"model":"om://demo/model/default","messages":[{"role":"user","content":"hello there"}],"stream":true,"idempotency_key":"quickstart-1","max_tokens":2}' \
  "http://127.0.0.1:${OM_GATEWAY_PORT:-8080}/v1/chat/completions"
```

The response includes an `X-Om-Stream-ID` header, a `traceparent`, two `delta` events, and a terminal `done` event. The quickstart API example is executed by CI through `make docs`.

## Run the complete local checks

```bash
make test
make lint
make docs
```

See [stream retention](stream-retention.md) for the resume cursor API and its expiry behavior. The development endpoint does not survive a process restart; [ADR-008](https://github.com/shashankoppo/omsanchar/blob/main/adr/008-durable-stream-log.md) records the JetStream-backed P1 design.
