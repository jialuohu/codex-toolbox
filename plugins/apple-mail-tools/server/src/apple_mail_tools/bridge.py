"""Fixed AppleScriptObjC transport for Mail.app."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .config import RuntimePaths
from .models import AppleMailError, ErrorCode

_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_ACTIONS = {
    "health",
    "list_accounts",
    "list_mailboxes",
    "list_messages",
    "get_message",
    "find_message",
    "list_attachments",
    "fetch_attachment",
    "create_draft",
    "mutate_message",
}
_MAIL_LOCK = threading.RLock()


class AppleScriptRunner:
    """Serialize calls and pass data only through private JSON files."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        script_path: Path | None = None,
        osascript_path: Path = Path("/usr/bin/osascript"),
        command_runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self.paths = paths
        self.script_path = script_path or Path(__file__).with_name("mail_bridge.applescript")
        self.osascript_path = osascript_path
        self._run = command_runner

    def invoke(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60,
    ) -> dict[str, Any]:
        if platform.system() != "Darwin":
            raise AppleMailError(ErrorCode.UNSUPPORTED_PLATFORM, "Apple Mail tools require macOS")
        if action not in _ACTIONS:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Bridge action is not allowed")
        if (
            not self.osascript_path.is_file()
            or self.osascript_path.is_symlink()
            or not self.script_path.is_file()
            or self.script_path.is_symlink()
        ):
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "AppleScript bridge is missing")
        self.paths.ensure()
        request = {"version": 1, "action": action, "params": params or {}}
        descriptor, raw_path = tempfile.mkstemp(
            prefix="request-", suffix=".json", dir=self.paths.requests_root
        )
        request_path = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(json.dumps(request, ensure_ascii=False).encode())
                stream.flush()
                os.fsync(stream.fileno())
            with _MAIL_LOCK:
                try:
                    result = self._run(
                        [str(self.osascript_path), str(self.script_path), str(request_path)],
                        check=False,
                        capture_output=True,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired as error:
                    raise AppleMailError(
                        ErrorCode.TIMEOUT,
                        "Mail did not finish the bounded operation",
                        retryable=True,
                    ) from error
        finally:
            try:
                request_path.unlink()
            except FileNotFoundError:
                pass
        if result.returncode != 0:
            raise _process_failure(result.stderr)
        if len(result.stdout) > _MAX_RESPONSE_BYTES:
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned too much data")
        try:
            raw_response: Any = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data") from error
        if not isinstance(raw_response, dict):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
        response = cast(dict[str, Any], raw_response)
        if not isinstance(response.get("ok"), bool):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
        if response["ok"] is not True:
            raw_error = response.get("error")
            error_data = cast(dict[str, Any], raw_error) if isinstance(raw_error, dict) else {}
            code = error_data.get("code")
            message = error_data.get("message")
            mapping = {
                "permission_required": ErrorCode.PERMISSION_REQUIRED,
                "not_found": ErrorCode.NOT_FOUND,
                "ambiguous": ErrorCode.AMBIGUOUS,
                "validation_error": ErrorCode.VALIDATION_ERROR,
            }
            mapped_code = mapping.get(code) if isinstance(code, str) else None
            raise AppleMailError(
                mapped_code or ErrorCode.BRIDGE_ERROR,
                message if isinstance(message, str) else "Mail operation failed",
                retryable=code == "permission_required",
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
        return cast(dict[str, Any], data)


def _process_failure(stderr: bytes) -> AppleMailError:
    lowered = stderr.decode(errors="ignore").casefold()
    if "not authorized" in lowered or "-1743" in lowered or "automation" in lowered:
        return AppleMailError(
            ErrorCode.PERMISSION_REQUIRED,
            "Allow Codex or osascript to control Mail in System Settings > "
            "Privacy & Security > Automation",
            retryable=True,
        )
    if "application isn't running" in lowered or "connection is invalid" in lowered:
        return AppleMailError(ErrorCode.MAIL_UNAVAILABLE, "Mail is unavailable", retryable=True)
    return AppleMailError(ErrorCode.BRIDGE_ERROR, "AppleScript bridge failed")
