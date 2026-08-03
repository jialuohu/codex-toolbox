"""Stable operation result and error contracts for future MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


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


class _DocmostModel(BaseModel):
    """Tolerant read model for additive upstream response fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, frozen=True)


class User(_DocmostModel):
    """A minimally stable Docmost user projection."""

    id: str
    name: str | None = None
    email: str | None = None


class Workspace(_DocmostModel):
    """A minimally stable Docmost workspace projection."""

    id: str
    name: str | None = None
    slug: str | None = None


class CurrentUser(_DocmostModel):
    """Authenticated user and workspace returned by ``/api/users/me``."""

    user: User
    workspace: Workspace


class Space(_DocmostModel):
    """A Docmost space returned by the read API."""

    id: str
    name: str | None = None
    slug: str | None = None


class Page(_DocmostModel):
    """Canonical read projection of a Docmost page."""

    id: str
    title: str | None = None
    slug_id: str | None = Field(default=None, alias="slugId")
    space_id: str | None = None
    space_name: str | None = None
    space_slug: str | None = None
    parent: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    url: str | None = None
    markdown: str | None = None
    truncated: bool = False
    next_offset: int | None = None


class Comment(_DocmostModel):
    """A Docmost page-comment projection."""

    id: str
    content: JsonValue | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    edited_at: str | None = Field(default=None, alias="editedAt")


class CursorPage[Item](_DocmostModel):
    """A cursor-paginated upstream response normalized for read tools."""

    items: list[Item]
    next_cursor: str | None = None


class PageList(CursorPage[Page]):
    """A page listing; ``root_only`` marks ``list_pages`` semantics."""

    root_only: bool = False


class SearchResults(CursorPage[Page]):
    """Offset-paginated search results with an opaque, versioned next cursor."""

    next_cursor: str | None = None


class VersionInfo(_DocmostModel):
    """The version signal used solely for read-profile selection."""

    current_version: str | None = Field(default=None, alias="currentVersion")
