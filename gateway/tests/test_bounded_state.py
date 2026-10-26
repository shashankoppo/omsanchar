from __future__ import annotations

import gc
import http.client
import json
import platform
import sys
import tracemalloc
import unittest

try:
    import resource
except ImportError:  # Windows test runners do not expose getrusage.
    resource = None

from gateway.server import EventStream, GatewayError, GatewayService, make_server
from gateway.state import (
    MAX_STREAM_EVENTS,
    STATE_MEMORY_BUDGET_BYTES,
    STORE_LIMITS,
    STREAM_EVENT_RESERVATION_BYTES,
    BoundedState,
)

TRACEPARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


def completed_stream(stream_id: str) -> EventStream:
    stream = EventStream(stream_id, f"request-{stream_id}", TRACEPARENT, 0)
    stream.finish()
    return stream


class BoundedStateTests(unittest.TestCase):
    def test_fifo_eviction_adds_bounded_tombstone_and_metric(self):
        limits = dict(STORE_LIMITS)
        limits["streams"] = 1
        state = BoundedState(store_limits=limits)
        first = completed_stream("a" * 32)
        second = completed_stream("b" * 32)

        state.put("streams", first.stream_id, first, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)
        state.put("streams", second.stream_id, second, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)

        self.assertIsNone(state.get("streams", first.stream_id))
        self.assertTrue(state.was_stream_evicted(first.stream_id))
        self.assertIs(state.get("streams", second.stream_id), second)
        self.assertEqual(state.eviction_counts()["streams"], 1)
        self.assertLessEqual(state.used_bytes, state.memory_budget_bytes)
        metrics = GatewayService(bounded_state=state).metrics_text()
        self.assertIn('om_gateway_state_evictions_total{store="streams"} 1', metrics)

    def test_ttl_expires_completed_stream_and_then_tombstone(self):
        now = [100.0]
        state = BoundedState(clock=lambda: now[0])
        stream = completed_stream("c" * 32)
        state.put("streams", stream.stream_id, stream, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)

        now[0] += 301
        self.assertIsNone(state.get("streams", stream.stream_id))
        self.assertTrue(state.was_stream_evicted(stream.stream_id))
        now[0] += 301
        self.assertFalse(state.was_stream_evicted(stream.stream_id))

    def test_event_log_has_fixed_per_stream_count_and_byte_limits(self):
        stream = EventStream("d" * 32, "request", TRACEPARENT, 0)
        for index in range(MAX_STREAM_EVENTS):
            stream.publish("delta", {"delta": str(index)}, f"key-{index}")
        with self.assertRaisesRegex(RuntimeError, "event limit"):
            stream.publish("delta", {"delta": "overflow"}, "overflow")

        other = EventStream("e" * 32, "request", TRACEPARENT, 0)
        with self.assertRaisesRegex(RuntimeError, "byte limit"):
            other.publish("delta", {"payload": "x" * 5000}, "large")

    def test_active_streams_are_not_evicted_and_new_admission_fails_before_debit(self):
        limits = dict(STORE_LIMITS)
        limits["streams"] = 1
        state = BoundedState(store_limits=limits)
        active = EventStream("1" * 32, "active", TRACEPARENT, 0)
        state.put("streams", active.stream_id, active, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)
        service = GatewayService(bearer_token="capacity-test", bounded_state=state)
        body = {
            "model": "om://demo/model/default",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 1,
        }

        with self.assertRaises(GatewayError) as caught:
            service.create_stream(
                body=body,
                raw_body=b"{}",
                request_idempotency_key="capacity",
                traceparent=TRACEPARENT,
            )

        self.assertEqual(caught.exception.code, "OS-0503")
        self.assertEqual(service.meter.used_microcredits, 0)
        self.assertIs(state.get("streams", active.stream_id), active)

    def test_million_open_then_abandoned_streams_stay_under_memory_ceiling(self):
        stream_count = 1_000_000
        state = BoundedState()
        gc.collect()
        tracemalloc.start()
        initial_current, _ = tracemalloc.get_traced_memory()
        max_retained = 0

        for index in range(stream_count):
            stream_id = f"{index:032x}"
            stream = EventStream(stream_id, f"request-{index}", TRACEPARENT, 0)
            state.put("streams", stream_id, stream, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)
            # The client has abandoned the stream; its producer finishes without a reader.
            stream.finish()
            if index % 10_000 == 0:
                max_retained = max(max_retained, len(state.values("streams")))

        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_rss_bytes = None
        if resource is not None:
            peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        print(
            "BOUNDED_STATE_SOAK="
            + json.dumps(
                {
                    "streams_opened_and_abandoned": stream_count,
                    "accounted_budget_bytes": STATE_MEMORY_BUDGET_BYTES,
                    "accounted_retained_bytes_after_soak": state.used_bytes,
                    "retained_entries_after_soak": state.entry_count,
                    "retained_streams_after_soak": len(state.values("streams")),
                    "max_sampled_retained_streams": max_retained,
                    "tracemalloc_peak_bytes_above_start": peak - initial_current,
                    "process_peak_rss_bytes": peak_rss_bytes,
                    "python": sys.version.split()[0],
                    "platform": platform.platform(),
                },
                sort_keys=True,
            )
        )
        self.assertEqual(stream_count, 1_000_000)
        self.assertLessEqual(state.used_bytes, STATE_MEMORY_BUDGET_BYTES)
        self.assertLessEqual(state.entry_count, sum(state.store_limits.values()))
        self.assertLessEqual(max_retained, state.store_limits["streams"])
        self.assertLessEqual(peak - initial_current, STATE_MEMORY_BUDGET_BYTES)
        self.assertGreater(state.eviction_counts()["streams"], 0)

        if resource is not None:
            # Linux reports ru_maxrss in KiB. This also checks interpreter and
            # test-process overhead in the WSL2 execution requested for the soak.
            self.assertLessEqual(peak_rss_bytes, STATE_MEMORY_BUDGET_BYTES)


class EvictedResumeTests(unittest.TestCase):
    def test_resume_of_evicted_stream_returns_410_os_0400(self):
        limits = dict(STORE_LIMITS)
        limits["streams"] = 1
        state = BoundedState(store_limits=limits)
        service = GatewayService(bearer_token="resume-test", bounded_state=state)
        old = completed_stream("f" * 32)
        newest = completed_stream("0" * 32)
        state.put("streams", old.stream_id, old, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)
        state.put("streams", newest.stream_id, newest, reserved_bytes=STREAM_EVENT_RESERVATION_BYTES)

        server = make_server("127.0.0.1", 0, service)
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            connection.request(
                "GET",
                f"/v1/streams/{old.stream_id}?cursor=0",
                headers={"Authorization": "Bearer resume-test"},
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 410)
            self.assertEqual(body["code"], "OS-0400")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_authenticator_is_injected_behind_a_replaceable_interface(self):
        class TestAuthenticator:
            def __init__(self):
                self.seen = []

            def authenticate(self, authorization):
                self.seen.append(authorization)
                return authorization == "Bearer federated-test"

        adapter = TestAuthenticator()
        service = GatewayService(authenticator=adapter)
        self.assertTrue(service.authenticate("Bearer federated-test"))
        self.assertFalse(service.authenticate("Bearer dev-demo-token"))
        self.assertEqual(adapter.seen, ["Bearer federated-test", "Bearer dev-demo-token"])


if __name__ == "__main__":
    unittest.main()
