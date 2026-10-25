"""Small reference validator for JSON conformance vectors."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from spec.reference.address import AddressError, parse_address, validate_tenant

_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_KINDS = {"MESSAGE_KIND_REQUEST", "MESSAGE_KIND_RESPONSE", "MESSAGE_KIND_EVENT", "MESSAGE_KIND_CONTROL"}
_CLASSES = {"PRIORITY_CLASS_VOICE", "PRIORITY_CLASS_INTERACTIVE", "PRIORITY_CLASS_BATCH"}
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1
_INT64_MAX = (1 << 63) - 1
_UNSIGNED_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_SIGNED_DECIMAL = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")


def _int64_json(value: Any, field: str, *, signed: bool) -> int:
    """Read a ProtoJSON integer without accepting booleans or lossy coercions."""
    pattern = _SIGNED_DECIMAL if signed else _UNSIGNED_DECIMAL
    if isinstance(value, bool):
        raise EnvelopeError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and pattern.fullmatch(value):
        return int(value)
    raise EnvelopeError(f"{field} must be a decimal integer or JSON integer")


class EnvelopeError(ValueError):
    """Raised when a public JSON envelope is invalid."""


def _base64_field(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise EnvelopeError(f"{field} must be a base64 string")
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeError(f"{field} must be valid base64") from exc


def validate_envelope(value: Any) -> None:
    """Validate the structural v1 JSON subset used in conformance vectors."""
    if not isinstance(value, dict):
        raise EnvelopeError("envelope must be an object")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise EnvelopeError("version must be 1")
    if not isinstance(value.get("id"), str) or not _ULID.fullmatch(value["id"]):
        raise EnvelopeError("id must be a canonical 26-character ULID")
    key = value.get("idempotencyKey")
    if not isinstance(key, str) or not key:
        raise EnvelopeError("idempotencyKey must contain 1 to 128 UTF-8 bytes")
    try:
        key_length = len(key.encode("utf-8"))
    except UnicodeError as exc:
        raise EnvelopeError("idempotencyKey must be valid UTF-8") from exc
    if key_length > 128:
        raise EnvelopeError("idempotencyKey must contain 1 to 128 UTF-8 bytes")
    for field in ("from", "to"):
        try:
            parse_address(value.get(field))
        except AddressError as exc:
            raise EnvelopeError(f"{field} is not a canonical address") from exc
    if value.get("kind") not in _KINDS:
        raise EnvelopeError("kind is unsupported")
    _base64_field(value.get("payload"), "payload")
    if "grant" in value:
        _base64_field(value["grant"], "grant")
    if "signature" in value:
        _base64_field(value["signature"], "signature")
    seq = _int64_json(value.get("seq", 0), "seq", signed=False)
    if not 0 <= seq <= _UINT64_MAX:
        raise EnvelopeError("seq must be an unsigned 64-bit integer")

    meta = value.get("meta")
    if not isinstance(meta, dict):
        raise EnvelopeError("meta must be an object")
    try:
        validate_tenant(meta.get("tenant"))
    except AddressError as exc:
        raise EnvelopeError("meta.tenant is not a canonical tenant identifier") from exc
    if meta.get("class") not in _CLASSES:
        raise EnvelopeError("meta.class is unsupported")
    deadline = _int64_json(meta.get("deadlineMs", 0), "meta.deadlineMs", signed=False)
    if not 0 <= deadline <= _UINT64_MAX:
        raise EnvelopeError("meta.deadlineMs must be an unsigned 64-bit duration in milliseconds")
    budget = meta.get("budget", {})
    if not isinstance(budget, dict):
        raise EnvelopeError("meta.budget must be an object")
    token_limit = budget.get("tokenLimit")
    if token_limit is not None:
        token_limit = _int64_json(token_limit, "meta.budget.tokenLimit", signed=False)
        if not 0 <= token_limit <= _UINT64_MAX:
            raise EnvelopeError("meta.budget.tokenLimit must be an unsigned 64-bit integer")
    cost_limit = budget.get("costLimitMicrocredits")
    if cost_limit is not None:
        cost_limit = _int64_json(cost_limit, "meta.budget.costLimitMicrocredits", signed=True)
        if not 0 <= cost_limit <= _INT64_MAX:
            raise EnvelopeError("meta.budget.costLimitMicrocredits must be a non-negative signed 64-bit integer")
    max_hops = budget.get("maxHops")
    if max_hops is not None and (
        isinstance(max_hops, bool) or not isinstance(max_hops, int) or not 0 <= max_hops <= _UINT32_MAX
    ):
        raise EnvelopeError("meta.budget.maxHops must be an unsigned 32-bit integer")
