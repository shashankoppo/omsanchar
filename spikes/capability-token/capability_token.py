"""Bounded HMAC capability-token spike; standard-library-only prototype."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

FORMAT_VERSION = 1
MAX_DEPTH = 8
MAX_TOKEN_BYTES = 4096
MAX_I64 = (1 << 63) - 1
TOKEN_PREFIX = "omct1."
ROOT_DOMAIN = b"om-sanchar/capability-token/v1/root\x00"
CAVEAT_DOMAIN = b"\x00om-sanchar/capability-token/v1/caveat\x00"
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_ROOT_FIELDS = {
    "tenant",
    "subject",
    "resources",
    "actions",
    "budget_micros",
    "expires_unix_ms",
    "token_id",
}
_CAVEAT_FIELDS = {"resources", "actions", "budget_micros", "expires_unix_ms"}
_TOKEN_FIELDS = {"v", "root", "caveats", "mac"}


class TokenError(ValueError):
    """Raised when a token is malformed, invalid, expired, or over-scoped."""


@dataclass(frozen=True)
class Grant:
    tenant: str
    subject: str
    resources: frozenset[str]
    actions: frozenset[str]
    budget_micros: int
    expires_unix_ms: int
    token_id: str
    depth: int


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not _B64URL.fullmatch(value):
        raise TokenError("invalid base64url encoding")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise TokenError("invalid base64url encoding") from exc


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise TokenError(f"{field} must be a non-empty string of at most 512 characters")
    if any(ord(char) < 0x20 for char in value):
        raise TokenError(f"{field} must not contain control characters")
    return value


def _i64(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_I64:
        raise TokenError(f"{field} must be an integer in [{minimum}, {MAX_I64}]")
    return value


def _string_set(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 128:
        raise TokenError(f"{field} must be a list of at most 128 strings")
    values = [_string(item, field) for item in value]
    if len(set(values)) != len(values):
        raise TokenError(f"{field} must not contain duplicates")
    return sorted(values)


def _validate_root(root: Any) -> dict[str, Any]:
    if not isinstance(root, dict) or set(root) != _ROOT_FIELDS:
        raise TokenError("root grant has an unexpected shape")
    return {
        "tenant": _string(root["tenant"], "tenant"),
        "subject": _string(root["subject"], "subject"),
        "resources": _string_set(root["resources"], "resources"),
        "actions": _string_set(root["actions"], "actions"),
        "budget_micros": _i64(root["budget_micros"], "budget_micros"),
        "expires_unix_ms": _i64(root["expires_unix_ms"], "expires_unix_ms", minimum=1),
        "token_id": _string(root["token_id"], "token_id"),
    }


def _validate_caveat_shape(caveat: Any) -> dict[str, Any]:
    if not isinstance(caveat, dict) or not caveat or not set(caveat) <= _CAVEAT_FIELDS:
        raise TokenError("caveat has an unexpected shape")
    out: dict[str, Any] = {}
    for field in ("resources", "actions"):
        if field in caveat:
            out[field] = _string_set(caveat[field], field)
    if "budget_micros" in caveat:
        out["budget_micros"] = _i64(caveat["budget_micros"], "budget_micros")
    if "expires_unix_ms" in caveat:
        out["expires_unix_ms"] = _i64(caveat["expires_unix_ms"], "expires_unix_ms", minimum=1)
    return out


def _apply_caveat(grant: dict[str, Any], caveat: dict[str, Any]) -> None:
    for field in ("resources", "actions"):
        if field in caveat:
            narrowed = set(caveat[field])
            if not narrowed <= set(grant[field]):
                raise TokenError(f"caveat widens {field}")
            grant[field] = sorted(narrowed)
    for field in ("budget_micros", "expires_unix_ms"):
        if field in caveat:
            if caveat[field] > grant[field]:
                raise TokenError(f"caveat widens {field}")
            grant[field] = caveat[field]


def _parse(token: str) -> tuple[dict[str, Any], bytes, bytes]:
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
        raise TokenError("unsupported token prefix")
    if len(token) > MAX_TOKEN_BYTES:
        raise TokenError("token exceeds the 4096-byte limit")
    raw = _b64url_decode(token[len(TOKEN_PREFIX) :])
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenError("token payload is not canonical JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _TOKEN_FIELDS:
        raise TokenError("token has an unexpected shape")
    if _canonical_json(payload) != raw:
        raise TokenError("token JSON must be canonical")
    if not isinstance(payload["v"], int) or isinstance(payload["v"], bool) or payload["v"] != FORMAT_VERSION:
        raise TokenError("unsupported token version")
    if not isinstance(payload["caveats"], list) or len(payload["caveats"]) > MAX_DEPTH:
        raise TokenError("token exceeds maximum attenuation depth of 8")
    mac = _b64url_decode(payload["mac"])
    if len(mac) != hashlib.sha256().digest_size:
        raise TokenError("invalid MAC length")
    return payload, raw, mac


def _encode(payload: dict[str, Any]) -> str:
    raw = _canonical_json(payload)
    token = TOKEN_PREFIX + _b64url_encode(raw)
    if len(token) > MAX_TOKEN_BYTES:
        raise TokenError("token exceeds the 4096-byte limit")
    return token


def mint(
    issuer_key: bytes,
    *,
    tenant: str,
    subject: str,
    resources: list[str] | tuple[str, ...] | set[str],
    actions: list[str] | tuple[str, ...] | set[str],
    budget_micros: int,
    expires_unix_ms: int,
    token_id: str | None = None,
) -> str:
    """Mint an issuer-authenticated root grant. Keys must contain at least 32 bytes."""
    if not isinstance(issuer_key, bytes) or len(issuer_key) < 32:
        raise TokenError("issuer key must contain at least 32 bytes")
    root = _validate_root(
        {
            "tenant": tenant,
            "subject": subject,
            "resources": list(resources),
            "actions": list(actions),
            "budget_micros": budget_micros,
            "expires_unix_ms": expires_unix_ms,
            "token_id": token_id or secrets.token_urlsafe(16),
        }
    )
    root_mac = hmac.new(issuer_key, ROOT_DOMAIN + _canonical_json(root), hashlib.sha256).digest()
    return _encode({"v": FORMAT_VERSION, "root": root, "caveats": [], "mac": _b64url_encode(root_mac)})


def _effective_unverified(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    effective = _validate_root(payload["root"])
    caveats = [_validate_caveat_shape(item) for item in payload["caveats"]]
    for caveat in caveats:
        _apply_caveat(effective, caveat)
    return effective, caveats


def attenuate(
    token: str,
    *,
    resources: list[str] | tuple[str, ...] | set[str] | None = None,
    actions: list[str] | tuple[str, ...] | set[str] | None = None,
    budget_micros: int | None = None,
    expires_unix_ms: int | None = None,
) -> str:
    """Append a caveat using the bearer-held MAC; no issuer round trip is needed.

    The returned token still needs full verification at the gateway. This function
    deliberately cannot expand any root claim, even before that verification.
    """
    payload, _, previous_mac = _parse(token)
    if len(payload["caveats"]) >= MAX_DEPTH:
        raise TokenError("maximum attenuation depth of 8 reached")
    effective, caveats = _effective_unverified(payload)
    caveat: dict[str, Any] = {}
    if resources is not None:
        caveat["resources"] = _string_set(list(resources), "resources")
    if actions is not None:
        caveat["actions"] = _string_set(list(actions), "actions")
    if budget_micros is not None:
        caveat["budget_micros"] = _i64(budget_micros, "budget_micros")
    if expires_unix_ms is not None:
        caveat["expires_unix_ms"] = _i64(expires_unix_ms, "expires_unix_ms", minimum=1)
    if not caveat:
        raise TokenError("attenuation must add at least one restriction")
    normalized = _validate_caveat_shape(caveat)
    _apply_caveat(effective, normalized)
    caveats.append(normalized)
    new_mac = hmac.new(previous_mac, CAVEAT_DOMAIN + _canonical_json(normalized), hashlib.sha256).digest()
    return _encode(
        {
            "v": FORMAT_VERSION,
            "root": payload["root"],
            "caveats": caveats,
            "mac": _b64url_encode(new_mac),
        }
    )


def verify(
    token: str,
    issuer_key: bytes,
    *,
    now_unix_ms: int,
    expected_tenant: str | None = None,
    expected_subject: str | None = None,
) -> Grant:
    """Verify issuer MAC, entire caveat chain, context, and absolute expiry."""
    if not isinstance(issuer_key, bytes) or len(issuer_key) < 32:
        raise TokenError("issuer key must contain at least 32 bytes")
    now = _i64(now_unix_ms, "now_unix_ms")
    payload, _, supplied_mac = _parse(token)
    root = _validate_root(payload["root"])
    if root != payload["root"]:
        raise TokenError("root set claims must be sorted and unique")
    expected_mac = hmac.new(issuer_key, ROOT_DOMAIN + _canonical_json(root), hashlib.sha256).digest()
    effective = dict(root)
    for raw_caveat in payload["caveats"]:
        caveat = _validate_caveat_shape(raw_caveat)
        if caveat != raw_caveat:
            raise TokenError("caveat set claims must be sorted and unique")
        _apply_caveat(effective, caveat)
        expected_mac = hmac.new(expected_mac, CAVEAT_DOMAIN + _canonical_json(caveat), hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, supplied_mac):
        raise TokenError("invalid token MAC")
    if expected_tenant is not None and root["tenant"] != expected_tenant:
        raise TokenError("tenant mismatch")
    if expected_subject is not None and root["subject"] != expected_subject:
        raise TokenError("subject mismatch")
    if now >= effective["expires_unix_ms"]:
        raise TokenError("token expired")
    return Grant(
        tenant=root["tenant"],
        subject=root["subject"],
        resources=frozenset(effective["resources"]),
        actions=frozenset(effective["actions"]),
        budget_micros=effective["budget_micros"],
        expires_unix_ms=effective["expires_unix_ms"],
        token_id=root["token_id"],
        depth=len(payload["caveats"]),
    )
