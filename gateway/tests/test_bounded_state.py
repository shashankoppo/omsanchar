from __future__ import annotations

import gc
import http.client
import json
import platform
import sys
import threading
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

        state.put("streams", first.stream_id, first)
        state.put("streams", second.stream_id, second)

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
        state.put("streams", stream.stream_id, stream)

        now[0] += 301
        self.assertIsNone(state.get("streams", stream.stream_id))
        self.assertTrue(state.was_stream_evicted(stream.stream_id))
        now[0] += 301
        self.assertFalse(state.was_stream_evicted(stream.stream_id))
        self.assertEqual(state.eviction_counts()["evicted"], 1)

    def test_ttl_fails_and_evicts_an_open_stream(self):
        now = [100.0]
        state = BoundedState(clock=lambda: now[0])
        stream = EventStream("c" * 32, "request-open", TRACEPARENT, 0)
        state.put("streams", stream.stream_id, stream)

        now[0] += 301
        self.assertIsNone(state.get("streams", stream.stream_id))
        self.assertEqual(stream.state, "FAILED")
        self.assertTrue(state.was_stream_evicted(stream.stream_id))
        self.assertEqual(state.active_stream_count(), 0)

    def test_event_log_has_fixed_per_stream_count_and_byte_limits(self):
        stream = EventStream("d" * 32, "request", TRACEPARENT, 0)
        for index in range(MAX_STREAM_EVENTS + 2):
            stream.publish("delta", {"delta": str(index)}, f"key-{index}")
        self.assertEqual(stream.last_seq, MAX_STREAM_EVENTS + 2)
        self.assertEqual(stream.retained_event_count, MAX_STREAM_EVENTS)
        with self.assertRaisesRegex(ValueError, "older than the retained"):
            stream.after(0, 0)
        retained, done, _ = stream.after(2, 0)
        self.assertFalse(done)
        self.assertEqual([event.seq for event in retained], list(range(3, MAX_STREAM_EVENTS + 3)))

        other = EventStream("e" * 32, "request", TRACEPARENT, 0)
        with self.assertRaisesRegex(RuntimeError, "byte limit"):
            other.publish("delta", {"payload": "x" * 5000}, "large")

    def test_resume_window_enforces_configurable_serialized_byte_ceiling(self):
        stream = EventStream("e" * 32, "request", TRACEPARENT, 0, max_events=16, max_window_bytes=4096)
        for index in range(8):
            stream.publish("delta", {"delta": "x" * 700}, f"key-{index}")
        self.assertLessEqual(stream.retained_window_bytes, 4096)
        self.assertLess(stream.retained_event_count, 8)
        with self.assertRaisesRegex(ValueError, "older than the retained"):
            stream.after(0, 0)

    def test_cursor_that_expires_while_waiting_is_rejected(self):
        stream = EventStream("6" * 32, "request", TRACEPARENT, 0, max_events=2)
        waiting = threading.Event()
        original_wait = stream._condition.wait

        def publish_after_wake(timeout=None):
            waiting.set()
            result = original_wait(timeout)
            for index in range(3):
                stream.publish("delta", {"delta": str(index)}, f"key-{index}")
            return result

        stream._condition.wait = publish_after_wake

        def wake_waiter():
            if waiting.wait(1):
                with stream._condition:
                    stream._condition.notify()

        wake_thread = threading.Thread(target=wake_waiter)
        wake_thread.start()
        try:
            with self.assertRaisesRegex(ValueError, "older than the retained"):
                stream.after(0, 0.5)
        finally:
            wake_thread.join(timeout=1)

    def test_state_reaccounts_event_growth_from_retained_object_bytes(self):
        state = BoundedState()
        stream = EventStream("7" * 32, "request", TRACEPARENT, 0)
        state.put("streams", stream.stream_id, stream)
        initial_bytes = state.store_bytes("streams")
        service = GatewayService(bounded_state=state)
        service.publish_event(stream, "delta", {"delta": "x" * 500}, "output:1")
        after_one_event = state.store_bytes("streams")
        self.assertGreater(after_one_event, initial_bytes)
        for index in range(2, 40):
            service.publish_event(stream, "delta", {"delta": f"token-{index}"}, f"output:{index}")
        self.assertLessEqual(stream.retained_event_count, MAX_STREAM_EVENTS)
        self.assertLessEqual(state.used_bytes, state.memory_budget_bytes)
        self.assertLess(state.store_bytes("streams"), after_one_event + 8192 * 39)

    def test_active_streams_are_not_evicted_and_new_admission_fails_before_debit(self):
        limits = dict(STORE_LIMITS)
        limits["streams"] = 1
        state = BoundedState(store_limits=limits)
        active = EventStream("1" * 32, "active", TRACEPARENT, 0)
        state.put("streams", active.stream_id, active)
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
            state.put("streams", stream_id, stream)
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
        retained_stream_count = len(state.values("streams"))
        retained_stream_bytes = state.store_bytes("streams")
        average_stream_entry_bytes = retained_stream_bytes / retained_stream_count if retained_stream_count else 0
        print(
            "BOUNDED_STATE_SOAK="
            + json.dumps(
                {
                    "streams_opened_and_abandoned": stream_count,
                    "accounted_budget_bytes": STATE_MEMORY_BUDGET_BYTES,
                    "accounted_retained_bytes_after_soak": state.used_bytes,
                    "retained_entries_after_soak": state.entry_count,
                    "retained_streams_after_soak": len(state.values("streams")),
                    "retained_stream_entry_bytes": retained_stream_bytes,
                    "average_accounted_bytes_per_retained_stream": average_stream_entry_bytes,
                    "estimated_stream_entries_per_gib": (
                        int((1024**3) / average_stream_entry_bytes) if average_stream_entry_bytes else None
                    ),
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
        state.put("streams", old.stream_id, old)
        state.put("streams", newest.stream_id, newest)

        server = make_server("127.0.0.1", 0, service)
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

    def test_resume_cursor_before_retained_window_returns_410_os_0400(self):
        state = BoundedState()
        service = GatewayService(bearer_token="window-test", bounded_state=state)
        stream = EventStream("9" * 32, "request-window", TRACEPARENT, 0, max_events=2)
        state.put("streams", stream.stream_id, stream)
        for index in range(3):
            service.publish_event(stream, "delta", {"delta": str(index)}, f"output:{index}")
        stream.finish()

        server = make_server("127.0.0.1", 0, service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            connection.request(
                "GET",
                f"/v1/streams/{stream.stream_id}?cursor=0",
                headers={"Authorization": "Bearer window-test"},
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
