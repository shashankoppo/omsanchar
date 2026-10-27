"""Bounded process-local retention for resumable streams and gateway records."""

from __future__ import annotations

import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Hashable

STATE_MEMORY_BUDGET_BYTES = 128 * 1024 * 1024
MAX_STREAM_EVENTS = 16
MAX_STREAM_EVENT_BYTES = 2048
MAX_STREAM_WINDOW_BYTES = 4096
STREAM_EVENT_ACCOUNTED_RESERVE_BYTES = 4096
MAX_ACTIVE_STREAMS = 10_000

STORE_LIMITS = {
    "streams": 10_000,
    "requests": 8192,
    "audit": 8192,
    "trace": 8192,
    "evicted": 4096,
}
STORE_TTLS_SECONDS = {
    "streams": 300.0,
    "requests": 60.0,
    "audit": 900.0,
    "trace": 300.0,
    "evicted": 300.0,
}

_LOCK_TYPES = (type(threading.Lock()), type(threading.RLock()), type(threading.Condition()))


class StateCapacityError(RuntimeError):
    """Raised when retaining an entry would exceed a configured state bound."""


@dataclass(slots=True)
class _Entry:
    value: Any
    inserted_at: float
    expires_at: float
    sequence: int
    charge: int


def deep_size(value: Any, seen: set[int] | None = None) -> int:
    """Estimate retained Python object bytes, avoiding double-counted references."""
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value, 0)
    if isinstance(value, _LOCK_TYPES):
        return size
    if isinstance(value, dict):
        return size + sum(deep_size(key, seen) + deep_size(item, seen) for key, item in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return size + sum(deep_size(item, seen) for item in value)
    if hasattr(value, "__dict__"):
        return size + deep_size(vars(value), seen)
    slots = getattr(type(value), "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    return size + sum(deep_size(getattr(value, slot), seen) for slot in slots if hasattr(value, slot))


class BoundedState:
    """FIFO stores sharing a hard accounting budget, TTLs, and entry limits.

    TTLs begin at insertion and are not refreshed on reads. Active streams are
    protected from capacity eviction, but their fixed stream TTL fails and removes
    an open stream; if no other eligible entry can make room, admission fails with
    ``StateCapacityError``.
    """

    def __init__(
        self,
        *,
        memory_budget_bytes: int = STATE_MEMORY_BUDGET_BYTES,
        store_limits: dict[str, int] | None = None,
        store_ttls: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if memory_budget_bytes < 1:
            raise ValueError("memory budget must be positive")
        self.memory_budget_bytes = memory_budget_bytes
        self.store_limits = dict(STORE_LIMITS if store_limits is None else store_limits)
        self.store_ttls = dict(STORE_TTLS_SECONDS if store_ttls is None else store_ttls)
        self.clock = clock
        self._stores: dict[str, OrderedDict[Hashable, _Entry]] = {name: OrderedDict() for name in self.store_limits}
        self._lock = threading.RLock()
        self._sequence = 0
        self._append_sequence = {"audit": 0, "trace": 0}
        self._used_bytes = 0
        self._entry_count = 0
        self._evictions = {name: 0 for name in self.store_limits}

    @property
    def used_bytes(self) -> int:
        with self._lock:
            return self._used_bytes

    @property
    def entry_count(self) -> int:
        with self._lock:
            return self._entry_count

    def eviction_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._evictions)

    def store_bytes(self, store: str) -> int:
        with self._lock:
            self._sweep(self.clock())
            return sum(entry.charge for entry in self._store(store).values())

    def reserve_growth(self, store: str, key: Hashable, additional_bytes: int) -> None:
        """Reserve an upper bound before mutating a retained value."""
        if additional_bytes < 0:
            raise ValueError("additional_bytes must be non-negative")
        with self._lock:
            now = self.clock()
            self._sweep(now)
            entries = self._store(store)
            entry = entries.get(key)
            if entry is None:
                raise StateCapacityError("retained entry no longer exists")
            if additional_bytes:
                self._make_room(
                    store,
                    additional_bytes,
                    now,
                    protected=(store, key),
                    count_delta=0,
                )
                entry.charge += additional_bytes
                self._used_bytes += additional_bytes

    def reaccount(self, store: str, key: Hashable) -> None:
        """Replace a temporary growth reserve with measured retained object size."""
        with self._lock:
            now = self.clock()
            self._sweep(now)
            entries = self._store(store)
            entry = entries.get(key)
            if entry is None:
                raise StateCapacityError("retained entry no longer exists")
            charge = deep_size(entry.value) + 256
            delta = charge - entry.charge
            if delta > 0:
                self._make_room(
                    store,
                    delta,
                    now,
                    protected=(store, key),
                    count_delta=0,
                )
            entry.charge = charge
            self._used_bytes += delta

    def active_stream_count(self) -> int:
        with self._lock:
            return sum(1 for entry in self._store("streams").values() if self._is_active_stream(entry))

    def was_stream_evicted(self, stream_id: str) -> bool:
        return self.get("evicted", stream_id, False) is True

    def put(
        self,
        store: str,
        key: Hashable,
        value: Any,
        *,
        reserved_bytes: int = 0,
    ) -> None:
        with self._lock:
            now = self.clock()
            self._sweep(now)
            entries = self._store(store)
            old = entries.get(key)
            charge = max(deep_size(value) + 256, reserved_bytes)
            if old is not None:
                delta = charge - old.charge
                if delta > 0:
                    self._make_room(store, delta, now, protected=(store, key), count_delta=0)
                old.value = value
                old.charge = charge
                self._used_bytes += delta
                return
            self._make_room(store, charge, now)
            self._sequence += 1
            ttl = self.store_ttls[store]
            entries[key] = _Entry(value, now, now + ttl, self._sequence, charge)
            self._used_bytes += charge
            self._entry_count += 1

    def append(self, store: str, value: Any, *, max_value_bytes: int = 8192) -> None:
        if store not in {"audit", "trace"}:
            raise ValueError("append is supported only for audit and trace stores")
        charge = deep_size(value) + 256
        if charge > max_value_bytes:
            raise StateCapacityError(f"{store} record exceeds its per-entry byte limit")
        with self._lock:
            self._append_sequence[store] += 1
            key = self._append_sequence[store]
        self.put(store, key, value)

    def get(self, store: str, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entries = self._store(store)
            entry = entries.get(key)
            if entry is None:
                return default
            if entry.expires_at <= self.clock():
                self._drop(store, key, entry, expired=True)
                return default
            return entry.value

    def delete(self, store: str, key: Hashable) -> None:
        with self._lock:
            entry = self._store(store).get(key)
            if entry is not None:
                self._drop(store, key, entry, count_eviction=False, remember_eviction=False)

    def values(self, store: str) -> tuple[Any, ...]:
        with self._lock:
            self._sweep(self.clock())
            return tuple(entry.value for entry in self._store(store).values())

    def contains(self, store: str, key: Hashable) -> bool:
        marker = object()
        return self.get(store, key, marker) is not marker

    def _store(self, name: str) -> OrderedDict[Hashable, _Entry]:
        try:
            return self._stores[name]
        except KeyError as exc:
            raise ValueError(f"unknown state store: {name}") from exc

    @staticmethod
    def _is_active_stream(entry: _Entry) -> bool:
        return getattr(entry.value, "state", None) == "OPEN"

    def _sweep(self, now: float) -> None:
        for store, entries in self._stores.items():
            expired = []
            for key, entry in entries.items():
                if entry.expires_at > now:
                    break
                expired.append((key, entry))
            for key, entry in expired:
                if entries.get(key) is entry:
                    self._drop(store, key, entry, expired=True)

    def _make_room(
        self,
        requested_store: str,
        additional_bytes: int,
        now: float,
        *,
        protected: tuple[str, Hashable] | None = None,
        count_delta: int = 1,
    ) -> None:
        entries = self._store(requested_store)
        while (
            len(entries) + (count_delta if protected is None else 0) > self.store_limits[requested_store]
            or self._entry_count + count_delta > sum(self.store_limits.values())
            or self._used_bytes + additional_bytes > self.memory_budget_bytes
        ):
            candidate = self._oldest_candidate(
                now,
                required_store=requested_store
                if len(entries) + count_delta > self.store_limits[requested_store]
                else None,
                protected=protected,
            )
            if candidate is None:
                raise StateCapacityError("global retained-state budget is full")
            self._drop(*candidate)

    def _oldest_candidate(
        self,
        now: float,
        *,
        required_store: str | None = None,
        protected: tuple[str, Hashable] | None = None,
    ) -> tuple[str, Hashable, _Entry] | None:
        choices: list[tuple[str, Hashable, _Entry]] = []
        stores = [required_store] if required_store else list(self._stores)
        for store in stores:
            entries = self._store(store)
            for key, entry in entries.items():
                if protected == (store, key):
                    continue
                if store == "streams" and self._is_active_stream(entry):
                    continue
                choices.append((store, key, entry))
                break
        return min(choices, key=lambda item: item[2].sequence) if choices else None

    def _drop(
        self,
        store: str,
        key: Hashable,
        entry: _Entry,
        *,
        expired: bool = False,
        count_eviction: bool = True,
        remember_eviction: bool = True,
    ) -> None:
        entries = self._store(store)
        if entries.get(key) is not entry:
            return
        if expired and store == "streams" and self._is_active_stream(entry):
            finish = getattr(entry.value, "finish", None)
            if callable(finish):
                finish("FAILED")
        del entries[key]
        self._used_bytes -= entry.charge
        self._entry_count -= 1
        if store in self._evictions and count_eviction:
            self._evictions[store] += 1
        if store == "streams" and remember_eviction:
            self._add_tombstone(str(key), entry.charge)

    def _add_tombstone(self, stream_id: str, freed_bytes: int) -> None:
        entries = self._store("evicted")
        now = self.clock()
        old = entries.pop(stream_id, None)
        if old is not None:
            self._used_bytes -= old.charge
            self._entry_count -= 1
        charge = min(max(sys.getsizeof(stream_id) + 128, 160), freed_bytes)
        if charge <= 0:
            return
        while len(entries) >= self.store_limits["evicted"]:
            key, item = next(iter(entries.items()))
            self._drop("evicted", key, item)
        while self._used_bytes + charge > self.memory_budget_bytes and entries:
            key, item = next(iter(entries.items()))
            self._drop("evicted", key, item)
        if self._used_bytes + charge > self.memory_budget_bytes:
            return
        self._sequence += 1
        entries[stream_id] = _Entry(True, now, now + self.store_ttls["evicted"], self._sequence, charge)
        self._used_bytes += charge
        self._entry_count += 1


class StoreView:
    """Small mapping facade retained for the gateway's inspection API."""

    def __init__(self, state: BoundedState, store: str):
        self.state = state
        self.store = store

    def get(self, key: Hashable, default: Any = None) -> Any:
        return self.state.get(self.store, key, default)

    def __getitem__(self, key: Hashable) -> Any:
        marker = object()
        value = self.get(key, marker)
        if value is marker:
            raise KeyError(key)
        return value

    def __setitem__(self, key: Hashable, value: Any) -> None:
        self.state.put(self.store, key, value)

    def __contains__(self, key: Hashable) -> bool:
        return self.state.contains(self.store, key)

    def __len__(self) -> int:
        return len(self.state.values(self.store))
