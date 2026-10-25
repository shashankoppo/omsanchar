"""Deterministic bounded reference model for stream resume semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

_NANOS_PER_MILLISECOND = 1_000_000
_UINT64_MAX = (1 << 64) - 1


class StreamState(str, Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StreamError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DeadlineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class SimulatedClock:
    """Independent wall and monotonic clocks for deterministic skew injection."""

    monotonic_ns: int = 0
    wall_clock_ns: int = 0

    def advance(self, elapsed_monotonic_ns: int, *, wall_clock_jump_ns: int = 0) -> None:
        if (
            isinstance(elapsed_monotonic_ns, bool)
            or not isinstance(elapsed_monotonic_ns, int)
            or elapsed_monotonic_ns < 0
            or isinstance(wall_clock_jump_ns, bool)
            or not isinstance(wall_clock_jump_ns, int)
        ):
            raise ValueError("clock advances require non-negative monotonic elapsed time and integer wall skew")
        self.monotonic_ns += elapsed_monotonic_ns
        self.wall_clock_ns += elapsed_monotonic_ns + wall_clock_jump_ns


class MonotonicDeadline:
    """Hop-local absolute deadline driven only by the simulated monotonic clock."""

    def __init__(self, clock: SimulatedClock, remaining_ms: int):
        if isinstance(remaining_ms, bool) or not isinstance(remaining_ms, int) or not 1 <= remaining_ms <= _UINT64_MAX:
            raise DeadlineError("OS-0001", "wire deadline must be a positive unsigned 64-bit duration")
        self.deadline_at_ns = clock.monotonic_ns + remaining_ms * _NANOS_PER_MILLISECOND

    def remaining_ms(self, clock: SimulatedClock) -> int:
        remaining_ms = (self.deadline_at_ns - clock.monotonic_ns) // _NANOS_PER_MILLISECOND
        if remaining_ms < 1:
            raise DeadlineError("OS-0500", "deadline expired before another hop")
        return remaining_ms


@dataclass(frozen=True, slots=True)
class StreamEvent:
    seq: int
    idempotency_key: str
    payload: bytes


class StreamRecord:
    """Single-process reference model; production durability is out of scope."""

    def __init__(
        self,
        stream_id: str,
        *,
        buffer_limit: int = 8,
        max_events: int = 1024,
        max_payload_bytes: int = 64 * 1024,
        max_total_payload_bytes: int = 16 * 1024 * 1024,
    ):
        if not stream_id:
            raise ValueError("stream_id must be non-empty")
        if (
            buffer_limit < 1
            or max_events < buffer_limit
            or max_payload_bytes < 1
            or max_total_payload_bytes < max_payload_bytes
        ):
            raise ValueError("limits must be positive and max_events >= buffer_limit")
        self.stream_id = stream_id
        self.buffer_limit = buffer_limit
        self.max_events = max_events
        self.max_payload_bytes = max_payload_bytes
        self.max_total_payload_bytes = max_total_payload_bytes
        self.state = StreamState.NEW
        self.ack_cursor = 0
        self.last_seq = 0
        self._retained: list[StreamEvent] = []
        self._idempotency: dict[str, StreamEvent] = {}
        self._total_payload_bytes = 0

    def open(self) -> None:
        self._require_state(StreamState.NEW)
        self.state = StreamState.OPEN

    def publish(self, idempotency_key: str, payload: bytes) -> StreamEvent:
        self._require_state(StreamState.OPEN)
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise StreamError("OS-0001", "idempotency key must contain 1 to 128 UTF-8 bytes")
        try:
            key_length = len(idempotency_key.encode("utf-8"))
        except UnicodeError as exc:
            raise StreamError("OS-0001", "idempotency key must be valid UTF-8") from exc
        if key_length > 128:
            raise StreamError("OS-0001", "idempotency key must contain 1 to 128 UTF-8 bytes")
        if not isinstance(payload, bytes):
            raise StreamError("OS-0001", "payload must be bytes")
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            if existing.payload != payload:
                raise StreamError("OS-0401", "idempotency key was reused with different payload bytes")
            return existing
        if len(self._idempotency) >= self.max_events:
            raise StreamError("OS-0404", "stream reached its configured event limit")
        if len(payload) > self.max_payload_bytes:
            raise StreamError("OS-0404", "payload exceeds the configured per-event limit")
        if self._total_payload_bytes + len(payload) > self.max_total_payload_bytes:
            raise StreamError("OS-0404", "stream reached its configured payload byte limit")
        if len(self._retained) >= self.buffer_limit:
            raise StreamError("OS-0403", "retained event buffer is full")
        self.last_seq += 1
        event = StreamEvent(self.last_seq, idempotency_key, payload)
        self._retained.append(event)
        self._idempotency[idempotency_key] = event
        self._total_payload_bytes += len(payload)
        return event

    def acknowledge(self, cursor: int) -> None:
        self._require_state(StreamState.OPEN)
        if (
            isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < self.ack_cursor
            or cursor > self.last_seq
        ):
            raise StreamError("OS-0402", "cursor is malformed, regresses, or is ahead of the stream")
        self.ack_cursor = cursor
        self._retained = [event for event in self._retained if event.seq > cursor]

    def disconnect(self) -> None:
        self._require_state(StreamState.OPEN)
        self.state = StreamState.SUSPENDED

    def resume(self, cursor: int) -> tuple[StreamEvent, ...]:
        self._require_state(StreamState.SUSPENDED)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0 or cursor > self.last_seq:
            raise StreamError("OS-0402", "resume cursor is malformed or ahead of the stream")
        if cursor < self.ack_cursor:
            raise StreamError("OS-0400", "requested cursor predates retained data")
        self.state = StreamState.OPEN
        return tuple(event for event in self._retained if event.seq > cursor)

    def complete(self) -> None:
        self._finish(StreamState.COMPLETED)

    def fail(self) -> None:
        self._finish(StreamState.FAILED)

    def cancel(self) -> None:
        self._finish(StreamState.CANCELLED)

    def _finish(self, final_state: StreamState) -> None:
        if self.state not in (StreamState.OPEN, StreamState.SUSPENDED):
            raise StreamError("OS-0001", f"cannot transition {self.state.value} to {final_state.value}")
        self.state = final_state

    def _require_state(self, expected: StreamState) -> None:
        if self.state is not expected:
            raise StreamError("OS-0001", f"operation requires {expected.value}, current state is {self.state.value}")
