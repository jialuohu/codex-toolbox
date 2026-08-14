"""Versioned, scoped HMAC handles for Mail objects."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from .models import AppleMailError, ErrorCode

_PREFIX = "amh1"


class HandleSigner:
    def __init__(self, key_path: Path) -> None:
        self._key = key_path.read_bytes()
        if len(self._key) != 32:
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Signing key is invalid")

    def sign(self, kind: str, payload: dict[str, Any]) -> str:
        body = json.dumps(
            {"v": 1, "kind": kind, **payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        encoded = _encode(body)
        signature = _encode(hmac.digest(self._key, encoded.encode(), "sha256"))
        return f"{_PREFIX}.{encoded}.{signature}"

    def verify(self, token: str, kind: str) -> dict[str, Any]:
        try:
            prefix, encoded, supplied = token.split(".")
            expected = _encode(hmac.digest(self._key, encoded.encode(), "sha256"))
            if prefix != _PREFIX or not hmac.compare_digest(supplied, expected):
                raise ValueError
            value = json.loads(_decode(encoded))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AppleMailError(ErrorCode.INVALID_HANDLE, "Handle is invalid") from error
        if not isinstance(value, dict) or value.get("v") != 1 or value.get("kind") != kind:
            raise AppleMailError(ErrorCode.INVALID_HANDLE, "Handle kind is invalid")
        return value


def message_fingerprint(message: dict[str, Any]) -> str:
    fields = (
        message.get("rfc_message_id") or "",
        message.get("subject") or "",
        message.get("sender") or "",
        message.get("date_received") or "",
        str(message.get("message_size") or 0),
    )
    return hashlib.sha256("\0".join(fields).encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode()
