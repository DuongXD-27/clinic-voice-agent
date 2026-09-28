"""Irreversible call correlation identifiers."""

from __future__ import annotations

import base64
import hashlib
import hmac


class CallKeyFactory:
    def __init__(self, key: str | bytes, *, version: str, environment: str) -> None:
        key_bytes = key.encode("utf-8") if isinstance(key, str) else key
        if len(key_bytes) < 32:
            raise ValueError("pseudonymization key must contain at least 32 bytes")
        if not version or not version.replace("_", "").replace("-", "").isalnum():
            raise ValueError("trace key version is invalid")
        if not environment:
            raise ValueError("trace environment is required")
        self._key = key_bytes
        self._version = version
        self._environment = environment

    def create(self, call_id: str) -> str:
        digest = hmac.new(
            self._key,
            f"{self._environment}\0{call_id}".encode(),
            hashlib.sha256,
        ).digest()
        token = base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")
        return f"ck_{self._version}_{token}"

    def __repr__(self) -> str:
        return (
            f"CallKeyFactory(version={self._version!r}, "
            f"environment={self._environment!r}, key=<redacted>)"
        )
