from __future__ import annotations

import http.client
import json
import threading
import time
import unittest

from gateway.server import GatewayService, make_server


def read_sse_event(response: http.client.HTTPResponse) -> dict[str, object]:
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


class GatewayIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = GatewayService(
            bearer_token="test-token", allowance_microcredits=100_000, model_delay_seconds=0.01
        )
        self.server = make_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _post(
        self, body: dict[str, object], *, token: str = "test-token"
    ) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        connection = http.client.HTTPConnection(*self.base, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(body),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        return connection, connection.getresponse()

    @staticmethod
    def _body(*, key: str = "request-1", limit: int = 6, cost_limit: int | None = None) -> dict[str, object]:
        body: dict[str, object] = {
            "model": "om://demo/model/default",
            "messages": [{"role": "user", "content": "hello there"}],
            "stream": True,
            "idempotency_key": key,
            "max_tokens": limit,
        }
        if cost_limit is not None:
            body["cost_limit_microcredits"] = cost_limit
        return body

    def test_disconnect_and_resume_delivers_every_token_once(self) -> None:
        connection, response = self._post(self._body())
        self.assertEqual(response.status, 200)
        stream_id = response.getheader("X-Om-Stream-ID")
        self.assertTrue(stream_id)
        traceparent = response.getheader("traceparent")

        initial = [read_sse_event(response), read_sse_event(response)]
        self.assertEqual([item["event"] for item in initial], ["delta", "delta"])
        self.assertTrue(all(item["data"]["traceparent"] == traceparent for item in initial))
        connection.close()  # Simulate the client process losing its TCP connection.
        response.close()

        stream = self.service.streams[stream_id]
        deadline = time.monotonic() + 3
        while stream.state == "OPEN" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(stream.state, "COMPLETED")

        resumed = http.client.HTTPConnection(*self.base, timeout=5)
        resumed.request(
            "GET",
            f"/v1/streams/{stream_id}?cursor=2",
            headers={"Authorization": "Bearer test-token"},
        )
        replay = resumed.getresponse()
        self.assertEqual(replay.status, 200)
        later: list[dict[str, object]] = []
        while True:
            item = read_sse_event(replay)
            if item["event"] == "done":
                break
            later.append(item)
        resumed.close()

        received = initial + later
        self.assertEqual([item["data"]["seq"] for item in received], list(range(1, 7)))
        self.assertEqual([item["data"]["delta"] for item in received], [f"token-{i}" for i in range(1, 7)])
        self.assertEqual(len({item["data"]["seq"] for item in received}), 6)
        self.assertEqual(self.service.meter.output_tokens, 6)
        self.assertEqual(self.service.meter.used_microcredits, 2 + 6 * 2)
        self.assertTrue(any(event["action"] == "stream_resumed" for event in self.service.audit_events))
        trace_names = {event["name"] for event in self.service.trace_events}
        self.assertIn("gateway.request.authorized", trace_names)
        self.assertIn("gateway.output_token", trace_names)
        self.assertIn("gateway.stream.resumed", trace_names)
        self.assertTrue(
            all(event["traceparent"].split("-")[1] == traceparent.split("-")[1] for event in self.service.trace_events)
        )

    def test_signed_microcredit_budget_cuts_before_unaffordable_token(self) -> None:
        # Two input tokens cost 2; one output token costs 2. The fourth credit
        # cannot cover another complete output token, so exactly one is emitted.
        connection, response = self._post(self._body(key="budget", limit=5, cost_limit=4))
        self.assertEqual(response.status, 200)
        emitted: list[dict[str, object]] = []
        while True:
            item = read_sse_event(response)
            if item["event"] == "done":
                break
            emitted.append(item)
        connection.close()
        self.assertEqual([item["event"] for item in emitted], ["delta", "error"])
        self.assertEqual(emitted[0]["data"]["delta"], "token-1")
        self.assertEqual(emitted[0]["data"]["budget_remaining_microcredits"], 0)
        self.assertEqual(emitted[1]["data"]["code"], "OS-3029")
        self.assertEqual(emitted[1]["data"]["cause"], "OS-0201")
        self.assertEqual(self.service.meter.used_microcredits, 4)
        self.assertEqual(self.service.meter.output_tokens, 1)

    def test_initial_tenant_quota_error_preserves_core_cause(self) -> None:
        self.service.meter.allowance_microcredits = 1
        connection, response = self._post(self._body(key="tenant-quota"))
        self.assertEqual(response.status, 429)
        error = json.loads(response.read())
        connection.close()
        self.assertEqual(error["code"], "OS-3029")
        self.assertEqual(error["cause"], "OS-0200")

    def test_zero_budget_is_rejected_before_upstream_work(self) -> None:
        connection, response = self._post(self._body(key="zero-budget", cost_limit=0))
        self.assertEqual(response.status, 429)
        error = json.loads(response.read())
        connection.close()
        self.assertEqual(error["code"], "OS-3029")
        self.assertEqual(error["cause"], "OS-0201")
        self.assertEqual(self.service.meter.used_microcredits, 0)
        self.assertEqual(self.service.meter.input_tokens, 0)

    def test_authentication_and_integer_budget_validation(self) -> None:
        connection, response = self._post(self._body(key="unauthorized"), token="wrong")
        self.assertEqual(response.status, 401)
        response.read()
        response.close()
        connection.close()

        body = self._body(key="float-budget")
        body["cost_limit_microcredits"] = 1.5
        connection, response = self._post(body)
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read())["code"], "OS-0001")
        connection.close()

    def test_metrics_and_trace_context_are_exposed(self) -> None:
        connection, response = self._post(
            self._body(key="trace"),
        )
        self.assertEqual(response.status, 200)
        self.assertRegex(response.getheader("traceparent", ""), r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")
        stream_id = response.getheader("X-Om-Stream-ID")
        response.close()
        connection.close()
        stream = self.service.streams[stream_id]
        deadline = time.monotonic() + 3
        while stream.state == "OPEN" and time.monotonic() < deadline:
            time.sleep(0.01)
        metric_text = self.service.metrics_text()
        self.assertIn("om_gateway_output_tokens_total 6", metric_text)
        self.assertIn("om_gateway_cost_microcredits_total 14", metric_text)


if __name__ == "__main__":
    unittest.main()
