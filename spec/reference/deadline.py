"""Reference arithmetic for relative deadline propagation."""

from __future__ import annotations

_UINT64_MAX = (1 << 64) - 1
_NANOS_PER_MILLISECOND = 1_000_000


class DeadlineError(ValueError):
    """A deadline is invalid or has expired."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def effective_deadline_ms(requested_ms: int, policy_max_ms: int) -> int:
    """Resolve inheritance and clamp the caller duration to tenant policy."""
    if (
        isinstance(requested_ms, bool)
        or not isinstance(requested_ms, int)
        or not 0 <= requested_ms <= _UINT64_MAX
        or isinstance(policy_max_ms, bool)
        or not isinstance(policy_max_ms, int)
        or not 1 <= policy_max_ms <= _UINT64_MAX
    ):
        raise DeadlineError("OS-0001", "deadline values must fit the unsigned 64-bit wire range")
    return min(requested_ms or policy_max_ms, policy_max_ms)


def remaining_deadline_ms(deadline_ms: int, elapsed_monotonic_ns: int) -> int:
    """Return whole milliseconds remaining, expiring before encoding zero."""
    if (
        isinstance(deadline_ms, bool)
        or not isinstance(deadline_ms, int)
        or not 1 <= deadline_ms <= _UINT64_MAX
        or isinstance(elapsed_monotonic_ns, bool)
        or not isinstance(elapsed_monotonic_ns, int)
        or elapsed_monotonic_ns < 0
    ):
        raise DeadlineError("OS-0001", "deadline duration and monotonic elapsed time must be valid")
    remaining_ns = deadline_ms * _NANOS_PER_MILLISECOND - elapsed_monotonic_ns
    remaining_ms = remaining_ns // _NANOS_PER_MILLISECOND
    if remaining_ms < 1:
        raise DeadlineError("OS-0500", "deadline expired before another hop")
    return remaining_ms


def forwarded_deadline_ms(
    received_ms: int,
    elapsed_monotonic_ns: int,
    *,
    safety_margin_ms: int,
    minimum_useful_ms: int,
) -> int:
    """Subtract hop-local elapsed time and the configured transit safety margin.

    Elapsed time is rounded up to a whole millisecond so encoding cannot extend
    the caller's budget. If the result is below the route's minimum useful budget,
    fail before starting downstream work.
    """
    if (
        isinstance(received_ms, bool)
        or not isinstance(received_ms, int)
        or not 1 <= received_ms <= _UINT64_MAX
        or isinstance(elapsed_monotonic_ns, bool)
        or not isinstance(elapsed_monotonic_ns, int)
        or elapsed_monotonic_ns < 0
        or isinstance(safety_margin_ms, bool)
        or not isinstance(safety_margin_ms, int)
        or safety_margin_ms < 0
        or isinstance(minimum_useful_ms, bool)
        or not isinstance(minimum_useful_ms, int)
        or minimum_useful_ms < 1
    ):
        raise DeadlineError("OS-0001", "hop deadline policy values are invalid")
    elapsed_ms = (elapsed_monotonic_ns + _NANOS_PER_MILLISECOND - 1) // _NANOS_PER_MILLISECOND
    forwarded_ms = received_ms - elapsed_ms - safety_margin_ms
    if forwarded_ms < minimum_useful_ms:
        raise DeadlineError("OS-0500", "deadline is below the minimum useful downstream budget")
    return forwarded_ms
