"""Wire-stable results and internal errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue


class ErrorCode(StrEnum):
    CONFIGURATION_INVALID = "configuration_invalid"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    PERMISSION_REQUIRED = "permission_required"
    MAIL_UNAVAILABLE = "mail_unavailable"
    BRIDGE_ERROR = "bridge_error"
    TIMEOUT = "timeout"
    INVALID_HANDLE = "invalid_handle"
    STALE_HANDLE = "stale_handle"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    VALIDATION_ERROR = "validation_error"
    INDEX_DISABLED = "index_disabled"
    INDEX_INCOMPLETE = "index_incomplete"
    INTENT_EXPIRED = "intent_expired"
    INTENT_USED = "intent_used"
    FORBIDDEN_PATH = "forbidden_path"
    ATTACHMENT_TOO_LARGE = "attachment_too_large"
    OUTCOME_UNKNOWN = "outcome_unknown"
    PARTIAL_SUCCESS = "partial_success"
    INTERNAL_ERROR = "internal_error"


class OperationError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] | None = None


class ToolResult(BaseModel):
    """Common `{ok, data, error, coverage}` response envelope."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: JsonValue | None = None
    error: OperationError | None = None
    coverage: JsonValue | None = None


class AppleMailError(RuntimeError):
    """Expected failure safe to translate into the public envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


def success(data: JsonValue | None = None, *, coverage: JsonValue | None = None) -> ToolResult:
    return ToolResult(ok=True, data=data, coverage=coverage)


def failure(error: AppleMailError, *, data: JsonValue | None = None) -> ToolResult:
    return ToolResult(
        ok=False,
        data=data,
        error=OperationError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        ),
    )
