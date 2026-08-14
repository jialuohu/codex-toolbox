"""Stable operation result and error contracts for future MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ErrorCode(StrEnum):
    """Wire-stable machine-readable error categories."""

    CONFIGURATION_INVALID = "configuration_invalid"
    AUTH_REQUIRED = "auth_required"
    PROFILE_BUSY = "profile_busy"
    WRITE_COMPATIBILITY_BLOCKED = "write_compatibility_blocked"
    FORBIDDEN = "forbidden"
    PAGE_UNAVAILABLE = "page_unavailable"
    CONFLICT = "conflict"
    OUTCOME_UNKNOWN = "outcome_unknown"
    PARTIAL_SUCCESS = "partial_success"
    INVALID_MARKDOWN = "invalid_markdown"
    ATTACHMENT_UNAVAILABLE = "attachment_unavailable"
    UNSUPPORTED_ATTACHMENT = "unsupported_attachment"
    ATTACHMENT_TOO_LARGE = "attachment_too_large"
    SNAPSHOT_INCOMPLETE = "snapshot_incomplete"
    SNAPSHOT_CONFLICT = "snapshot_conflict"
    SNAPSHOT_SAFETY_CAP = "snapshot_safety_cap"
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

    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


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
    position: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    url: str | None = None
    markdown: str | None = None
    truncated: bool = False
    next_offset: int | None = None


class CreatePageResult(BaseModel):
    """A created page plus an explicit warning when optional nesting failed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: Page
    placement_status: Literal["root", "nested", "unknown"] = "root"
    partial_success: bool = False
    warning: OperationError | None = None

    @model_validator(mode="after")
    def validate_warning_state(self) -> Self:
        if self.partial_success != (self.warning is not None):
            raise ValueError("partial_success and warning must be present together")
        if self.warning is not None and self.warning.code is not ErrorCode.PARTIAL_SUCCESS:
            raise ValueError("partial-success warning must use the partial_success code")
        if self.placement_status == "root" and self.page.parent is not None:
            raise ValueError("root placement cannot include a parent")
        if self.placement_status == "nested" and self.page.parent is None:
            raise ValueError("nested placement must include a parent")
        if self.placement_status == "unknown" and not self.partial_success:
            raise ValueError("unknown placement must include a partial-success warning")
        return self


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


class AttachmentInfo(_DocmostModel):
    """Private attachment metadata used to validate a requested download."""

    id: str
    file_name: str = Field(alias="fileName")
    file_size: int = Field(alias="fileSize", ge=0)
    file_ext: str = Field(alias="fileExt")
    mime_type: str = Field(alias="mimeType")
    type: str
    page_id: str = Field(alias="pageId")


class AttachmentDownload(BaseModel):
    """A private temporary attachment snapshot plus its integrity receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    download_token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    local_path: str = Field(min_length=1)
    filename: str = Field(min_length=1, max_length=512)
    media_type: Literal["application/pdf", "text/plain"]
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttachmentRelease(BaseModel):
    """Idempotent cleanup result for one temporary download token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    released: bool


class WorkspaceSnapshotReceipt(BaseModel):
    """Receipt for a complete private workspace snapshot.

    Page bodies are deliberately absent from this model and remain only in the
    referenced mode-``0600`` JSONL file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_token: str = Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    local_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["docmost.workspace-snapshot.v1"]
    workspace_id: str = Field(min_length=1, max_length=512)
    space_count: int = Field(ge=1)
    page_count: int = Field(ge=0)
    markdown_chars: int = Field(ge=0)
    size_bytes: int = Field(ge=1)


class WorkspaceSnapshotRelease(BaseModel):
    """Idempotent cleanup result for one private workspace snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    released: bool
