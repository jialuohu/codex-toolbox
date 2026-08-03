"""Stable operation result and error contracts for future MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorCode(StrEnum):
    """Wire-stable machine-readable error categories."""

    CONFIGURATION_INVALID = "configuration_invalid"
    AUTH_REQUIRED = "auth_required"
    PROFILE_BUSY = "profile_busy"
    WRITE_COMPATIBILITY_BLOCKED = "write_compatibility_blocked"
    PAGE_UNAVAILABLE = "page_unavailable"
    CONFLICT = "conflict"
    OUTCOME_UNKNOWN = "outcome_unknown"
    PARTIAL_SUCCESS = "partial_success"
    INVALID_MARKDOWN = "invalid_markdown"
    UPSTREAM_ERROR = "upstream_error"
    INTERNAL_ERROR = "internal_error"


class OperationError(BaseModel):
    """A structured, serializable error that does not expose sensitive values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, str] = Field(default_factory=dict)


class OperationResult[ResultData](BaseModel):
    """An exclusive success-or-error envelope for future tool responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    data: ResultData | None = None
    error: OperationError | None = None

    @model_validator(mode="after")
    def validate_exclusive_state(self) -> Self:
        if self.ok and self.error is not None:
            msg = "successful result cannot include an error"
            raise ValueError(msg)
        if not self.ok and self.data is not None:
            msg = "failed result cannot include data"
            raise ValueError(msg)
        if not self.ok and self.error is None:
            msg = "failed result must include an error"
            raise ValueError(msg)
        return self

    @classmethod
    def success(cls, data: ResultData | None = None) -> Self:
        return cls(ok=True, data=data)

    @classmethod
    def failure(
        cls,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, str] | None = None,
    ) -> Self:
        return cls(
            ok=False,
            error=OperationError(
                code=code,
                message=message,
                retryable=retryable,
                details={} if details is None else details,
            ),
        )
