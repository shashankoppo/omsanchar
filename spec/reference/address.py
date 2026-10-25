"""Dependency-free reference parser for om:// addresses."""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = frozenset({"model", "tool", "agent", "topic", "node", "channel"})
_SEGMENT = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_ADDRESS = re.compile(
    r"om://(?P<tenant>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/"
    r"(?P<kind>model|tool|agent|topic|node|channel)/"
    r"(?P<name>[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)"
    r"(?:@(?P<version>[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?))?\Z"
)


class AddressError(ValueError):
    """Raised when an address is outside the v0.1 grammar."""


@dataclass(frozen=True, slots=True)
class OMAddress:
    tenant: str
    kind: str
    name: str
    version: str | None = None

    def __str__(self) -> str:
        suffix = f"@{self.version}" if self.version is not None else ""
        return f"om://{self.tenant}/{self.kind}/{self.name}{suffix}"


def validate_tenant(value: str) -> str:
    """Validate and return a canonical v0.1 tenant identifier."""
    if not isinstance(value, str) or len(value) > 63 or not _TENANT.fullmatch(value):
        raise AddressError("tenant must be 1 to 63 lowercase ASCII letters, digits, or internal hyphens")
    return value


def parse_address(value: str) -> OMAddress:
    """Parse a canonical v0.1 address or raise :class:`AddressError`."""
    if not isinstance(value, str):
        raise AddressError("address must be a string")
    match = _ADDRESS.fullmatch(value)
    if match is None:
        raise AddressError("address does not match the om:// v0.1 grammar")

    tenant = match.group("tenant")
    name = match.group("name")
    version = match.group("version")
    if len(tenant) > 63 or len(name) > 127 or (version is not None and len(version) > 63):
        raise AddressError("address segment exceeds its maximum length")
    validate_tenant(tenant)
    if not _SEGMENT.fullmatch(name) or (version is not None and not _SEGMENT.fullmatch(version)):
        raise AddressError("name or version segment is not canonical")
    return OMAddress(tenant, match.group("kind"), name, version)
