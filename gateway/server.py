"""Dependency-free local gateway for the first Om Sanchar vertical slice.

This is a native development implementation, not a hardened production server.
It demonstrates bearer authentication, per-tenant pricing and quota, metering,
trace propagation, and resumable SSE delivery against a deterministic mock model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from gateway.state import (
    MAX_ACTIVE_STREAMS,
    MAX_STREAM_EVENT_BYTES,
    MAX_STREAM_EVENTS,
    MAX_STREAM_WINDOW_BYTES,
    STREAM_EVENT_ACCOUNTED_RESERVE_BYTES,
    BoundedState,
    StateCapacityError,
    StoreView,
    deep_size,
)

I64_MAX = (1 << 63) - 1
TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-0[0-9a-f]$")


@dataclass(frozen=True, slots=True)
class Price:
    input_microcredits_per_token: int
    output_microcredits_per_token: int


DEFAULT_PRICES: dict[str, dict[str, Price]] = {
    "demo": {"om://demo/model/default": Price(1, 2)},
}


@dataclass(frozen=True, slots=True)
class StreamEvent:
    seq: int
    event: str
    data: dict[str, Any]


class StreamCursorExpiredError(ValueError):
    """The requested cursor is older than the in-memory resume window."""


class Authenticator(Protocol):
    """Replaceable ingress authentication boundary for the request pipeline."""

    def authenticate(self, authorization: str | None) -> bool: ...


class StaticBearerAuthenticator:
    """P0 local credential adapter; replaceable by SPIFFE/OAuth plus DPoP later."""

    def __init__(self, bearer_token: str):
        if not bearer_token:
            raise ValueError("bearer_token must be non-empty")
        self._expected = f"Bearer {bearer_token}"

    def authenticate(self, authorization: str | None) -> bool:
        return authorization == self._expected


class EventStream:
    """Thread-safe stream with a bounded rolling in-memory resume window."""

    def __init__(
        self,
        stream_id: str,
        request_id: str,
        traceparent: str,
        budget_remaining: int,
        *,
        max_events: int = MAX_STREAM_EVENTS,
        max_window_bytes: int = MAX_STREAM_WINDOW_BYTES,
    ):
        if max_events < 1 or max_window_bytes < 1:
            raise ValueError("stream resume-window limits must be positive")
        self.stream_id = stream_id
        self.request_id = request_id
        self.traceparent = traceparent
        self._budget_remaining = budget_remaining
        self._max_events = max_events
        self._max_window_bytes = max_window_bytes
        self._events: list[StreamEvent] = []
        self._event_sizes: list[int] = []
        self._idempotency: dict[str, StreamEvent] = {}
        self._retained_window_bytes = 0
        self._base_seq = 0
        self._last_seq = 0
        self._state = "OPEN"
        self._condition = threading.Condition()

    def publish(self, event: str, data: dict[str, Any], key: str) -> StreamEvent:
        with self._condition:
            previous = self._idempotency.get(key)
            if previous is not None:
                if previous.event != event or previous.data != data:
                    raise ValueError("event idempotency key was reused with different data")
                return previous
            if self._state != "OPEN":
                raise RuntimeError("cannot publish to a terminal stream")
            if len(key.encode("utf-8")) > 128 or len(event.encode("utf-8")) > 32:
                raise RuntimeError("stream event metadata exceeds its byte limit")
            serialized_data = json.dumps(data, separators=(",", ":")).encode("utf-8")
            if len(serialized_data) > MAX_STREAM_EVENT_BYTES or deep_size(data) > MAX_STREAM_EVENT_BYTES:
                raise RuntimeError("stream event exceeds its byte limit")
            sequence = self._last_seq + 1
            frame = json.dumps({"seq": sequence, **data}, separators=(",", ":")).encode("utf-8")
            retained_bytes = len(event.encode("utf-8")) + len(frame) + 16
            if retained_bytes > self._max_window_bytes:
                raise RuntimeError("stream event exceeds its resume-window byte limit")
            while self._events and (
                len(self._events) >= self._max_events
                or self._retained_window_bytes + retained_bytes > self._max_window_bytes
            ):
                expired = self._events.pop(0)
                self._retained_window_bytes -= self._event_sizes.pop(0)
                self._base_seq = expired.seq
                for idempotency_key, previous_event in tuple(self._idempotency.items()):
                    if previous_event.seq == expired.seq:
                        del self._idempotency[idempotency_key]
            item = StreamEvent(sequence, event, data)
            self._events.append(item)
            self._event_sizes.append(retained_bytes)
            self._retained_window_bytes += retained_bytes
            self._last_seq = sequence
            self._idempotency[key] = item
            self._condition.notify_all()
            return item

    def finish(self, state: str = "COMPLETED") -> None:
        if state not in {"COMPLETED", "FAILED"}:
            raise ValueError("invalid terminal stream state")
        with self._condition:
            if self._state == "OPEN":
                self._state = state
                self._condition.notify_all()

    def after(self, cursor: int, timeout: float) -> tuple[tuple[StreamEvent, ...], bool, str]:
        with self._condition:
            if cursor < 0:
                raise ValueError("cursor is malformed or ahead of the stream")
            if cursor < self._base_seq:
                raise StreamCursorExpiredError("cursor is older than the retained resume window")
            if cursor > self._last_seq:
                raise ValueError("cursor is malformed or ahead of the stream")
            if cursor == self._last_seq and self._state == "OPEN":
                self._condition.wait(timeout)
                if cursor < self._base_seq:
                    raise StreamCursorExpiredError("cursor is older than the retained resume window")
            events = tuple(event for event in self._events if event.seq > cursor)
            return events, self._state != "OPEN", self._state

    @property
    def last_seq(self) -> int:
        with self._condition:
            return self._last_seq

    @property
    def retained_window_bytes(self) -> int:
        with self._condition:
            return self._retained_window_bytes

    @property
    def retained_event_count(self) -> int:
        with self._condition:
            return len(self._events)

    @property
    def state(self) -> str:
        with self._condition:
            return self._state

    @property
    def budget_remaining(self) -> int:
        with self._condition:
            return self._budget_remaining

    def update_budget_remaining(self, amount: int) -> None:
        with self._condition:
            self._budget_remaining = amount


@dataclass(slots=True)
class TenantMeter:
    allowance_microcredits: int
    used_microcredits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def debit(self, amount: int) -> bool:
        if amount < 0 or amount > I64_MAX:
            return False
        with self._lock:
            if self.allowance_microcredits - self.used_microcredits < amount:
                return False
            self.used_microcredits += amount
            return True

    def remaining(self) -> int:
        with self._lock:
            return self.allowance_microcredits - self.used_microcredits

    def record_tokens(self, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens


class GatewayService:
    def __init__(
        self,
        *,
        bearer_token: str = "dev-demo-token",
        tenant: str = "demo",
        allowance_microcredits: int = 1_000_000,
        prices: dict[str, dict[str, Price]] | None = None,
        model_delay_seconds: float = 0.01,
        authenticator: Authenticator | None = None,
        bounded_state: BoundedState | None = None,
        stream_resume_events: int = MAX_STREAM_EVENTS,
        stream_resume_window_bytes: int = MAX_STREAM_WINDOW_BYTES,
    ):
        if not bearer_token:
            raise ValueError("bearer_token must be non-empty")
        if not 0 <= allowance_microcredits <= I64_MAX:
            raise ValueError("tenant allowance must be a signed 64-bit non-negative integer")
        self.authenticator = authenticator or StaticBearerAuthenticator(bearer_token)
        self.tenant = tenant
        self.prices = prices or DEFAULT_PRICES
        self.model_delay_seconds = max(0.0, model_delay_seconds)
        if stream_resume_events < 1 or stream_resume_window_bytes < 1:
            raise ValueError("stream resume-window limits must be positive")
        self.stream_resume_events = stream_resume_events
        self.stream_resume_window_bytes = stream_resume_window_bytes
        self.meter = TenantMeter(allowance_microcredits)
        self.state = bounded_state or BoundedState()
        self.streams = StoreView(self.state, "streams")
        self.requests = StoreView(self.state, "requests")
        self._lock = threading.RLock()
        self._metrics = {
            "requests": 0,
            "streams": 0,
            "resumes": 0,
            "output_tokens": 0,
            "cost_microcredits": 0,
        }

    def authenticate(self, authorization: str | None) -> bool:
        return self.authenticator.authenticate(authorization)

    @property
    def audit_events(self) -> tuple[dict[str, Any], ...]:
        return self.state.values("audit")

    @property
    def trace_events(self) -> tuple[dict[str, Any], ...]:
        return self.state.values("trace")

    def price_for(self, tenant: str, model: str) -> Price | None:
        return self.prices.get(tenant, {}).get(model)

    def audit(self, action: str, **details: Any) -> None:
        with self._lock:
            self.state.append("audit", {"time_unix_ms": time.time_ns() // 1_000_000, "action": action, **details})

    def trace(self, name: str, traceparent: str, **attributes: Any) -> None:
        with self._lock:
            self.state.append(
                "trace",
                {"time_unix_ns": time.time_ns(), "name": name, "traceparent": traceparent, **attributes},
            )

    def publish_event(self, stream: EventStream, event: str, data: dict[str, Any], key: str) -> StreamEvent:
        self.state.reserve_growth("streams", stream.stream_id, STREAM_EVENT_ACCOUNTED_RESERVE_BYTES)
        try:
            item = stream.publish(event, data, key)
        except Exception:
            self.state.reaccount("streams", stream.stream_id)
            raise
        self.state.reaccount("streams", stream.stream_id)
        return item

    def increment(self, metric: str, amount: int = 1) -> None:
        with self._lock:
            self._metrics[metric] += amount

    def metrics_text(self) -> str:
        with self._lock:
            values = dict(self._metrics)
        values["tenant_used_microcredits"] = self.meter.used_microcredits
        values["tenant_remaining_microcredits"] = self.meter.remaining()
        output = [f"om_gateway_{name}_total {value}\n" for name, value in values.items()]
        output.append(f"om_gateway_state_memory_bytes {self.state.used_bytes}\n")
        output.append(f"om_gateway_state_entries {self.state.entry_count}\n")
        output.append(f"om_gateway_state_memory_budget_bytes {self.state.memory_budget_bytes}\n")
        output.extend(
            f'om_gateway_state_evictions_total{{store="{store}"}} {count}\n'
            for store, count in self.state.eviction_counts().items()
        )
        return "".join(output)

    def new_traceparent(self, incoming: str | None) -> str | None:
        if incoming:
            if not TRACEPARENT_RE.fullmatch(incoming):
                return None
            trace_id = incoming.split("-")[1]
        else:
            trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        return f"00-{trace_id}-{span_id}-01"

    def create_stream(
        self,
        *,
        body: dict[str, Any],
        raw_body: bytes,
        request_idempotency_key: str,
        traceparent: str,
    ) -> tuple[EventStream, int, bool]:
        cache_key = (self.tenant, request_idempotency_key)
        body_digest = hashlib.sha256(raw_body).digest()
        with self._lock:
            previous = self.requests.get(cache_key)
            if previous is not None:
                if previous[0] != body_digest or previous[1] != len(raw_body):
                    raise GatewayError(409, "OS-2009", "idempotency key was reused with a different request body")
                cached = self.state.get("streams", previous[2])
                if cached is not None:
                    return cached, 0, True
                if self.state.was_stream_evicted(previous[2]):
                    raise GatewayError(410, "OS-0400", "stream state expired or was evicted")
                self.state.delete("requests", cache_key)

        model = body.get("model")
        if not isinstance(model, str):
            raise GatewayError(400, "OS-0001", "model must be a string")
        price = self.price_for(self.tenant, model)
        if price is None:
            raise GatewayError(404, "OS-2004", "model address is not configured")

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise GatewayError(400, "OS-0001", "messages must be a non-empty array")
        input_tokens = 0
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise GatewayError(400, "OS-0001", "each message must have string content")
            input_tokens += len(message["content"].split())
        max_tokens = body.get("max_tokens", 8)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 128:
            raise GatewayError(400, "OS-0001", "max_tokens must be an integer from 1 through 128")
        budget = body.get("cost_limit_microcredits")
        if budget is not None and (
            isinstance(budget, bool) or not isinstance(budget, int) or not 0 <= budget <= I64_MAX
        ):
            raise GatewayError(400, "OS-0001", "cost_limit_microcredits must be a non-negative signed 64-bit integer")

        input_cost = input_tokens * price.input_microcredits_per_token
        if input_cost > I64_MAX:
            raise GatewayError(400, "OS-0001", "input cost overflows signed 64-bit microcredits")
        if budget == 0:
            raise GatewayError(429, "OS-3029", "zero request cost budget forbids upstream work", cause="OS-0201")
        if budget is not None and budget < input_cost:
            raise GatewayError(
                429,
                "OS-3029",
                "request cost budget cannot cover input tokens",
                cause="OS-0201",
            )
        remaining_request_budget = I64_MAX if budget is None else budget - input_cost

        stream_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        stream = EventStream(
            stream_id,
            request_id,
            traceparent,
            remaining_request_budget,
            max_events=self.stream_resume_events,
            max_window_bytes=self.stream_resume_window_bytes,
        )
        with self._lock:
            previous = self.requests.get(cache_key)
            if previous is not None:
                if previous[0] != body_digest or previous[1] != len(raw_body):
                    raise GatewayError(409, "OS-2009", "idempotency key was reused with a different request body")
                cached = self.state.get("streams", previous[2])
                if cached is not None:
                    return cached, 0, True
                if self.state.was_stream_evicted(previous[2]):
                    raise GatewayError(410, "OS-0400", "stream state expired or was evicted")
                self.state.delete("requests", cache_key)
            if self.state.active_stream_count() >= MAX_ACTIVE_STREAMS:
                raise GatewayError(503, "OS-0503", "active stream capacity is full")
            try:
                self.state.put("streams", stream_id, stream)
                self.state.put("requests", cache_key, (body_digest, len(raw_body), stream_id))
            except StateCapacityError as exc:
                self.state.delete("streams", stream_id)
                self.state.delete("requests", cache_key)
                raise GatewayError(503, "OS-0503", "gateway retained-state capacity is full") from exc
            if not self.meter.debit(input_cost):
                self.state.delete("streams", stream_id)
                self.state.delete("requests", cache_key)
                raise GatewayError(429, "OS-3029", "tenant microcredit quota is exhausted", cause="OS-0200")
            self.meter.record_tokens(input_tokens=input_tokens)
            self._metrics["streams"] += 1
            self._metrics["requests"] += 1
            self._metrics["cost_microcredits"] += input_cost
        self.audit(
            "request_authorized",
            tenant=self.tenant,
            request_id=request_id,
            stream_id=stream_id,
            model=model,
            input_tokens=input_tokens,
            input_cost_microcredits=input_cost,
        )
        self.trace("gateway.request.authorized", traceparent, request_id=request_id, stream_id=stream_id)
        worker = threading.Thread(
            target=self._run_model,
            args=(stream, model, max_tokens, price, remaining_request_budget),
            name=f"mock-model-{stream_id[:8]}",
            daemon=True,
        )
        worker.start()
        return stream, remaining_request_budget, False

    def _run_model(
        self,
        stream: EventStream,
        model: str,
        max_tokens: int,
        price: Price,
        remaining_request_budget: int,
    ) -> None:
        emitted = 0
        try:
            if remaining_request_budget < price.output_microcredits_per_token:
                self.publish_event(
                    stream,
                    "error",
                    {
                        "code": "OS-3029",
                        "cause": "OS-0201",
                        "message": "request cost budget reached before the next output token",
                    },
                    "terminal:quota",
                )
                self.audit("budget_cutoff", tenant=self.tenant, stream_id=stream.stream_id, output_tokens=0)
                return
            if self.meter.remaining() < price.output_microcredits_per_token:
                self.publish_event(
                    stream,
                    "error",
                    {
                        "code": "OS-3029",
                        "cause": "OS-0200",
                        "message": "tenant microcredit quota is exhausted",
                    },
                    "terminal:quota",
                )
                self.audit("quota_cutoff", tenant=self.tenant, stream_id=stream.stream_id, output_tokens=0)
                return
            for token in mock_model_stream(model, max_tokens):
                if remaining_request_budget < price.output_microcredits_per_token:
                    self.publish_event(
                        stream,
                        "error",
                        {
                            "code": "OS-3029",
                            "cause": "OS-0201",
                            "message": "request cost budget reached before the next output token",
                        },
                        "terminal:quota",
                    )
                    self.audit("quota_cutoff", tenant=self.tenant, stream_id=stream.stream_id, output_tokens=emitted)
                    return
                if not self.meter.debit(price.output_microcredits_per_token):
                    self.publish_event(
                        stream,
                        "error",
                        {
                            "code": "OS-3029",
                            "cause": "OS-0200",
                            "message": "tenant microcredit quota reached before the next output token",
                        },
                        "terminal:quota",
                    )
                    self.audit("quota_cutoff", tenant=self.tenant, stream_id=stream.stream_id, output_tokens=emitted)
                    return
                remaining_request_budget -= price.output_microcredits_per_token
                stream.update_budget_remaining(remaining_request_budget)
                emitted += 1
                self.publish_event(
                    stream,
                    "delta",
                    {
                        "delta": token,
                        "traceparent": stream.traceparent,
                        "cost_microcredits": price.output_microcredits_per_token,
                        "budget_remaining_microcredits": remaining_request_budget,
                    },
                    f"output:{emitted}",
                )
                self.meter.record_tokens(output_tokens=1)
                self.increment("output_tokens")
                self.increment("cost_microcredits", price.output_microcredits_per_token)
                self.audit(
                    "output_token_metered",
                    tenant=self.tenant,
                    request_id=stream.request_id,
                    stream_id=stream.stream_id,
                    seq=emitted,
                    cost_microcredits=price.output_microcredits_per_token,
                )
                self.trace(
                    "gateway.output_token",
                    stream.traceparent,
                    request_id=stream.request_id,
                    stream_id=stream.stream_id,
                    seq=emitted,
                )
                if self.model_delay_seconds:
                    time.sleep(self.model_delay_seconds)
        except Exception as exc:  # The mock worker must always terminate the stream.
            try:
                self.publish_event(
                    stream,
                    "error",
                    {"code": "OS-4000", "message": type(exc).__name__},
                    "terminal:failed",
                )
            except Exception:
                pass
            stream.finish("FAILED")
            try:
                self.audit("stream_failed", stream_id=stream.stream_id, error=type(exc).__name__)
            except StateCapacityError:
                pass
        finally:
            if stream.state == "OPEN":
                stream.finish("COMPLETED")
                self.audit("stream_completed", tenant=self.tenant, stream_id=stream.stream_id, output_tokens=emitted)


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str, *, cause: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.cause = cause


def mock_model_stream(model: str, max_tokens: int):
    """Yield deterministic mock output; each item represents one billable token."""
    del model
    for index in range(1, max_tokens + 1):
        yield f"token-{index}"


class GatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16_384

    def __init__(self, address: tuple[str, int], service: GatewayService):
        self.service = service
        super().__init__(address, GatewayRequestHandler)


class GatewayRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: GatewayHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        # Avoid leaking bearer credentials or user prompt text in default logs.
        return

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in {"/healthz", "/readyz"}:
            self._json(200, {"status": "ok"})
            return
        if parsed.path == "/metrics":
            body = self.server.service.metrics_text().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._authorized():
            return
        prefix = "/v1/streams/"
        if parsed.path.startswith(prefix):
            self._resume(parsed.path[len(prefix) :], parse_qs(parsed.query))
            return
        self._json(404, {"code": "OS-2004", "message": "route not found"})

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/v1/chat/completions":
            self._json(404, {"code": "OS-2004", "message": "route not found"})
            return
        if not self._authorized():
            return
        try:
            raw_body = self._read_body()
            body = json.loads(raw_body)
            if not isinstance(body, dict):
                raise GatewayError(400, "OS-0001", "request body must be a JSON object")
            if body.get("stream") is not True:
                raise GatewayError(400, "OS-0001", "stream must be true for this endpoint")
            key = body.get("idempotency_key")
            if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 128:
                raise GatewayError(400, "OS-0001", "idempotency_key must contain 1 to 128 UTF-8 bytes")
            traceparent = self.server.service.new_traceparent(self.headers.get("traceparent"))
            if traceparent is None:
                raise GatewayError(400, "OS-0001", "traceparent is malformed")
            stream, _, duplicate = self.server.service.create_stream(
                body=body,
                raw_body=raw_body,
                request_idempotency_key=key,
                traceparent=traceparent,
            )
            cursor = _parse_cursor(parse_qs(parsed.query).get("cursor", ["0"])[0])
            if duplicate:
                self.server.service.audit(
                    "idempotent_request_reused", tenant=self.server.service.tenant, stream_id=stream.stream_id
                )
            self.server.service.audit("stream_connected", stream_id=stream.stream_id, resumed=cursor > 0)
            self.server.service.trace(
                "gateway.stream.connected",
                stream.traceparent,
                request_id=stream.request_id,
                stream_id=stream.stream_id,
                cursor=cursor,
            )
            self._stream(stream, cursor)
        except GatewayError as exc:
            value = {"code": exc.code, "message": str(exc)}
            if exc.cause is not None:
                value["cause"] = exc.cause
            self._json(exc.status, value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(400, {"code": "OS-0001", "message": str(exc)})

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise GatewayError(400, "OS-0001", "invalid Content-Length") from exc
        if length < 0 or length > 1_048_576:
            raise GatewayError(413, "OS-0001", "request body exceeds 1 MiB")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise GatewayError(400, "OS-0001", "request body ended early")
        return raw

    def _authorized(self) -> bool:
        if self.server.service.authenticate(self.headers.get("Authorization")):
            return True
        self._json(401, {"code": "OS-1001", "message": "missing or invalid bearer credential"})
        return False

    def _resume(self, stream_id: str, query: dict[str, list[str]]) -> None:
        service = self.server.service
        stream = service.streams.get(stream_id)
        if stream is None:
            if service.state.was_stream_evicted(stream_id):
                self._json(410, {"code": "OS-0400", "message": "stream state expired or was evicted"})
            else:
                self._json(404, {"code": "OS-2004", "message": "stream not found"})
            return
        try:
            cursor = _parse_cursor(query.get("cursor", ["0"])[0])
            stream.after(cursor, 0)
        except StreamCursorExpiredError as exc:
            self._json(410, {"code": "OS-0400", "message": str(exc)})
            return
        except ValueError as exc:
            self._json(400, {"code": "OS-0402", "message": str(exc)})
            return
        self.server.service.increment("resumes")
        self.server.service.audit("stream_resumed", stream_id=stream.stream_id, cursor=cursor)
        self.server.service.trace(
            "gateway.stream.resumed",
            stream.traceparent,
            request_id=stream.request_id,
            stream_id=stream.stream_id,
            cursor=cursor,
        )
        self._stream(stream, cursor)

    def _stream(self, stream: EventStream, cursor: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Om-Stream-ID", stream.stream_id)
        self.send_header("X-Om-Request-ID", stream.request_id)
        self.send_header("traceparent", stream.traceparent)
        self.send_header("X-Om-Budget-Remaining", str(stream.budget_remaining))
        self.end_headers()
        try:
            while True:
                events, done, state = stream.after(cursor, 0.5)
                for item in events:
                    data = json.dumps({"seq": item.seq, **item.data}, separators=(",", ":"))
                    payload = f"id: {item.seq}\nevent: {item.event}\ndata: {data}\n\n".encode("utf-8")
                    self.wfile.write(payload)
                    self.wfile.flush()
                    cursor = item.seq
                if done and cursor >= stream.last_seq:
                    final = json.dumps({"state": state, "last_seq": stream.last_seq}, separators=(",", ":"))
                    self.wfile.write(f"event: done\ndata: {final}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    return
        except StreamCursorExpiredError as exc:
            error = json.dumps({"code": "OS-0400", "message": str(exc)}, separators=(",", ":"))
            try:
                self.wfile.write(f"event: error\ndata: {error}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (OSError, TimeoutError):
                pass
        except (OSError, TimeoutError):
            # The producer remains independent; the client can resume by ID/cursor.
            self.server.service.audit("client_disconnected", stream_id=stream.stream_id, cursor=cursor)

    def _json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def _parse_cursor(value: str) -> int:
    try:
        cursor = int(value, 10)
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor must be a non-negative integer") from exc
    if cursor < 0:
        raise ValueError("cursor must be a non-negative integer")
    return cursor


def make_server(host: str = "127.0.0.1", port: int = 8080, service: GatewayService | None = None) -> GatewayHTTPServer:
    return GatewayHTTPServer((host, port), service or GatewayService())


def main() -> None:
    host = os.environ.get("OM_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("OM_GATEWAY_PORT", "8080"))
    token = os.environ.get("OM_GATEWAY_TOKEN", "dev-demo-token")
    service = GatewayService(bearer_token=token)
    server = make_server(host, port, service)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    print(f"Om Sanchar native gateway listening at http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handle_sigterm(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
