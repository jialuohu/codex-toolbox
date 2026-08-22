"""Guarded HTTP compatibility client for Docmost browser sessions."""

from __future__ import annotations

import base64
import json
import re
import time
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from docmost_tools.attachment_download import AttachmentDownloadStore, AttachmentStageError
from docmost_tools.attachment_upload import (
    PdfUploadValidator,
    PdfValidationError,
    ValidatedPdf,
)
from docmost_tools.comment_markdown import MarkdownValidationError, markdown_to_tiptap
from docmost_tools.config import DocmostSettings, WriteProfile
from docmost_tools.models import (
    AttachmentDownload,
    AttachmentInfo,
    AttachmentRelease,
    Comment,
    CreatePageResult,
    CurrentUser,
    CursorPage,
    ErrorCode,
    JsonPatchOperation,
    OperationError,
    OperationResult,
    Page,
    PageContentPatchResult,
    PageContentResult,
    PageList,
    PageTextEditResult,
    PdfAttachmentResult,
    SearchResults,
    Space,
    UploadedPdf,
    VersionInfo,
    WorkspaceSnapshotReceipt,
    WorkspaceSnapshotRelease,
)
from docmost_tools.page_content import (
    InspectedPageContent,
    InvalidPageContent,
    InvalidPagePatch,
    PagePatchConflict,
    apply_page_patch,
    inspect_page_content,
    validate_patch_operations,
)
from docmost_tools.recovery import AUTH_REQUIRED_SENTENCE
from docmost_tools.workspace_snapshot import WorkspaceSnapshotBuilder, WorkspaceSnapshotStore

AUTH_REQUIRED_MESSAGE = AUTH_REQUIRED_SENTENCE
PAGE_UNAVAILABLE_MESSAGE = "PAGE_UNAVAILABLE"
FORBIDDEN_MESSAGE = "FORBIDDEN"
WRITE_COMPATIBILITY_BLOCKED_MESSAGE = "WRITE_COMPATIBILITY_BLOCKED"
_MAX_PAGE_SIZE = 100
_MAX_SEARCH_SIZE = 50
_DEFAULT_PAGE_SIZE = 50
_DEFAULT_SEARCH_SIZE = 20
_MAX_PAGE_CHARS = 100_000
_CURSOR_PATTERN = re.compile(r"[A-Za-z0-9._~=-]{1,1024}\Z")
_IDENTIFIER_PATTERN = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_SEARCH_CURSOR_PREFIX = "docmost-search.v1."
_SEARCH_CURSOR_PAYLOAD = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TITLE_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_MARKDOWN_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TITLE_CHARS = 250
_MAX_PAGE_MARKDOWN_CHARS = 1_000_000
_MAX_PAGE_EDIT_TEXT_CHARS = 100_000
_MAX_PROSEMIRROR_DEPTH = 100
_MAX_PROSEMIRROR_NODES = 100_000
_MAX_PROSEMIRROR_TEXT_CHARS = 1_000_000
_MAX_COMMENT_MARKDOWN_CHARS = 20_000
_MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_DOWNLOAD_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_FILENAME_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_EDIT_TEXT_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_CONTENT_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_OUTCOME_UNKNOWN_MESSAGE = "OUTCOME_UNKNOWN: search or read Docmost before retrying this write."
_PARTIAL_CREATE_MESSAGE = (
    "Page was created at the space root, but nesting failed. "
    "Do not retry create_page; read the returned page before any manual move."
)
_PARTIAL_CREATE_UNKNOWN_MESSAGE = (
    "Page was created, but the nesting outcome is unknown. "
    "Do not retry create_page; read the returned page before any manual move."
)
_PARTIAL_PDF_UNLINKED_MESSAGE = (
    "The PDF exists in Docmost but is not linked in the page body. "
    "Do not upload it again; use docmost_link_uploaded_pdf with a fresh page read."
)
_PARTIAL_PDF_UNKNOWN_MESSAGE = (
    "The PDF exists in Docmost but its page-link outcome is unknown. "
    "Do not retry the write; read the page and reconcile the returned attachment ID."
)
_PDF_UPLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)
ModelItem = TypeVar("ModelItem", bound=BaseModel)


class _ClientFailure(RuntimeError):
    """Internal error marker whose message deliberately contains no request data."""

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable


class DocmostReadClient:
    """Use fixed Docmost API paths with an in-memory browser session cookie."""

    def __init__(
        self,
        settings: DocmostSettings,
        session_cookie: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
        snapshot_store: WorkspaceSnapshotStore | None = None,
        pdf_validator: PdfUploadValidator | None = None,
    ) -> None:
        if not session_cookie:
            raise ValueError("A non-empty Docmost session cookie is required")
        if max_retries < 0 or max_retries > 3:
            raise ValueError("max_retries must be between 0 and 3")
        self._settings = settings
        self._session_cookie = SecretStr(session_cookie)
        self._sleeper = sleeper
        self._max_retries = max_retries
        verify: bool | str = True if settings.ca_bundle is None else str(settings.ca_bundle)
        self._http = httpx.Client(
            transport=transport,
            verify=verify,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
        )
        self._downloads = AttachmentDownloadStore(max_bytes=_MAX_ATTACHMENT_BYTES)
        self._pdf_validator = pdf_validator or PdfUploadValidator(max_bytes=_MAX_ATTACHMENT_BYTES)
        self._workspace_snapshot_store = snapshot_store or WorkspaceSnapshotStore()
        self._workspace_snapshots = WorkspaceSnapshotBuilder(
            self,
            self._workspace_snapshot_store,
        )
        self._version_result: OperationResult[VersionInfo] | None = None

    def __repr__(self) -> str:
        return (
            f"DocmostReadClient(base_url={self._origin()!r}, read_profile={self.read_profile!r}, "
            "session_cookie=SecretStr('**********'))"
        )

    def __enter__(self) -> DocmostReadClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Deterministically release the underlying pooled HTTP resources."""

        try:
            self._workspace_snapshot_store.close()
        finally:
            try:
                self._downloads.close()
            finally:
                self._http.close()

    @property
    def read_profile(self) -> Literal["v0_95", "generic"]:
        """Return the pinned profile only for a positively identified v0.95 server."""

        version = self._version_result
        if version is not None and version.ok and version.data is not None:
            current = version.data.current_version
            if current is not None and current.startswith("0.95."):
                return "v0_95"
        return "generic"

    @property
    def writes_permitted(self) -> bool:
        """Writes remain disabled unless the operator explicitly pins their profile."""

        return self._settings.write_profile is WriteProfile.V0_95

    @property
    def write_compatibility_error(self) -> OperationError | None:
        """Expose a stable guard for future write tools without inferring compatibility."""

        if self.writes_permitted:
            return None
        return OperationError(
            code=ErrorCode.WRITE_COMPATIBILITY_BLOCKED,
            message=WRITE_COMPATIBILITY_BLOCKED_MESSAGE,
        )

    def version(self) -> OperationResult[VersionInfo]:
        """Probe and cache ``/api/version``; failure never blocks generic read calls."""

        if self._version_result is None:
            self._version_result = self._run(
                lambda: VersionInfo.model_validate(self._post("/api/version", {}))
            )
        return self._version_result

    def current_user(self) -> OperationResult[CurrentUser]:
        """Return the authenticated user and workspace."""

        return self._run(lambda: CurrentUser.model_validate(self._post("/api/users/me", {})))

    def list_spaces(
        self, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[CursorPage[Space]]:
        """List spaces through Docmost's cursor-paginated read route."""

        try:
            validated_limit = self._page_limit(limit)
            body: dict[str, object] = {"limit": validated_limit}
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._invalid(error)
        return self._run(
            lambda: self._cursor_page(self._post("/api/spaces", body), Space, limit=validated_limit)
        )

    def get_space(self, space_id: str) -> OperationResult[Space]:
        """Return a single space by its opaque Docmost identifier."""

        return self._run(
            lambda: Space.model_validate(
                self._post("/api/spaces/info", {"spaceId": self._identifier(space_id)})
            )
        )

    def search(
        self,
        query: str,
        *,
        space_id: str | None = None,
        limit: int = _DEFAULT_SEARCH_SIZE,
        cursor: str | None = None,
    ) -> OperationResult[SearchResults]:
        """Search pages, returning an opaque next cursor only after a full page."""

        try:
            if not query.strip() or len(query) > 1024:
                raise ValueError("query must be non-empty and at most 1024 characters")
            if limit < 1 or limit > _MAX_SEARCH_SIZE:
                raise ValueError(f"limit must be between 1 and {_MAX_SEARCH_SIZE}")
            offset = self._search_offset(cursor)
        except ValueError as error:
            return self._invalid(error)
        fetch_limit = limit + 1
        body: dict[str, object] = {"query": query, "limit": fetch_limit, "offset": offset}
        if space_id is not None:
            try:
                body["spaceId"] = self._identifier(space_id)
            except ValueError as error:
                return self._invalid(error)

        def operation() -> SearchResults:
            result = self._cursor_page(self._post("/api/search", body), Page, limit=fetch_limit)
            next_cursor = (
                self._encode_search_cursor(offset + limit)
                if len(result.items) == fetch_limit
                else None
            )
            return SearchResults(items=result.items[:limit], next_cursor=next_cursor)

        return self._run(operation)

    def get_page(
        self, page_id: str, *, offset: int = 0, max_chars: int = _MAX_PAGE_CHARS
    ) -> OperationResult[Page]:
        """Fetch canonical Markdown and return an optional bounded content window."""

        try:
            identifier = self._identifier(page_id)
            if offset < 0:
                raise ValueError("offset must be zero or greater")
            if max_chars < 1 or max_chars > _MAX_PAGE_CHARS:
                raise ValueError(f"max_chars must be between 1 and {_MAX_PAGE_CHARS}")
        except ValueError as error:
            return self._page_invalid(error)
        return self._run(
            lambda: self._page_from_data(
                self._post(
                    "/api/pages/info", {"pageId": identifier, "format": "markdown"}, page_scope=True
                ),
                offset=offset,
                max_chars=max_chars,
            ),
            page_scope=True,
        )

    def get_page_content(self, page_id: str) -> OperationResult[PageContentResult]:
        """Fetch one complete bounded ProseMirror document and its canonical hash."""

        try:
            identifier = self._identifier(page_id)
        except ValueError as error:
            return cast(OperationResult[PageContentResult], self._page_invalid(error))

        def operation() -> PageContentResult:
            data = self._post(
                "/api/pages/info",
                {"pageId": identifier, "format": "json"},
                page_scope=True,
            )
            page, document = self._page_json_document_from_data(data)
            inspected = inspect_page_content(document)
            return PageContentResult(
                page=page,
                content=inspected.document,
                content_sha256=inspected.content_sha256,
            )

        return self._run(operation, page_scope=True)

    def list_pages(
        self, space_id: str, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[PageList]:
        """List only root-level pages in a space (not all descendants)."""

        try:
            validated_limit = self._page_limit(limit)
            body: dict[str, object] = {
                "spaceId": self._identifier(space_id),
                "limit": validated_limit,
            }
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._invalid(error)
        return self._run(
            lambda: PageList(
                **self._cursor_page(
                    self._post("/api/pages/sidebar-pages", body, page_scope=True),
                    Page,
                    limit=validated_limit,
                ).model_dump(),
                root_only=True,
            ),
            page_scope=True,
        )

    def list_child_pages(
        self, page_id: str, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[PageList]:
        """List direct children after resolving a slug/page input to its canonical UUID."""

        try:
            identifier = self._identifier(page_id)
            validated_limit = self._page_limit(limit)
            validated_cursor = self._cursor(cursor) if cursor is not None else None
        except ValueError as error:
            return self._page_invalid(error)

        def operation() -> PageList:
            canonical_id = self._page_id_from_data(
                self._post("/api/pages/info", {"pageId": identifier}, page_scope=True)
            )
            body: dict[str, object] = {"pageId": canonical_id, "limit": validated_limit}
            if validated_cursor is not None:
                body["cursor"] = validated_cursor
            parsed = self._cursor_page(
                self._post("/api/pages/sidebar-pages", body, page_scope=True),
                Page,
                limit=validated_limit,
            )
            return PageList(**parsed.model_dump(), root_only=False)

        return self._run(operation, page_scope=True)

    def list_comments(
        self, page_id: str, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[CursorPage[Comment]]:
        """List comments for a page through the fixed cursor-paginated endpoint."""

        try:
            validated_limit = self._page_limit(limit)
            body: dict[str, object] = {
                "pageId": self._identifier(page_id),
                "limit": validated_limit,
            }
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._page_invalid(error)
        return self._run(
            lambda: self._cursor_page(
                self._post("/api/comments", body, page_scope=True),
                Comment,
                limit=validated_limit,
            ),
            page_scope=True,
        )

    def download_attachment(
        self, page_id: str, attachment_id: str
    ) -> OperationResult[AttachmentDownload]:
        """Stage one authorized PDF or UTF-8 text attachment in private local storage."""

        try:
            validated_page_id = self._identifier(page_id)
            validated_attachment_id = self._identifier(attachment_id)
        except ValueError as error:
            return cast(OperationResult[AttachmentDownload], self._page_invalid(error))

        def operation() -> AttachmentDownload:
            canonical_page_id = self._page_id_from_data(
                self._post(
                    "/api/pages/info",
                    {"pageId": validated_page_id},
                    page_scope=True,
                )
            )
            try:
                metadata = AttachmentInfo.model_validate(
                    self._post(
                        "/api/files/info",
                        {"attachmentId": validated_attachment_id},
                        page_scope=True,
                    )
                )
            except _ClientFailure as error:
                if error.code in {ErrorCode.PAGE_UNAVAILABLE, ErrorCode.FORBIDDEN}:
                    raise _ClientFailure(
                        ErrorCode.ATTACHMENT_UNAVAILABLE,
                        "ATTACHMENT_UNAVAILABLE",
                    ) from error
                raise
            if (
                metadata.id != validated_attachment_id
                or metadata.page_id != canonical_page_id
                or metadata.type != "file"
            ):
                raise _ClientFailure(
                    ErrorCode.ATTACHMENT_UNAVAILABLE,
                    "ATTACHMENT_UNAVAILABLE",
                )
            filename, media_type = self._validated_attachment_metadata(metadata)
            if metadata.file_size > _MAX_ATTACHMENT_BYTES:
                raise _ClientFailure(
                    ErrorCode.ATTACHMENT_TOO_LARGE,
                    "ATTACHMENT_TOO_LARGE",
                )
            return self._download_and_stage(metadata, filename=filename, media_type=media_type)

        return self._run(operation, page_scope=False)

    def release_attachment_download(
        self, download_token: str
    ) -> OperationResult[AttachmentRelease]:
        """Release one managed temporary download; repeated release is safe."""

        if _DOWNLOAD_TOKEN_PATTERN.fullmatch(download_token) is None:
            return OperationResult[AttachmentRelease].failure(
                ErrorCode.CONFIGURATION_INVALID,
                "download_token is invalid",
            )
        return OperationResult[AttachmentRelease].success(
            AttachmentRelease(released=self._downloads.release(download_token))
        )

    def prepare_workspace_snapshot(
        self,
        *,
        all_spaces: bool,
        space_ids: list[str] | None,
        max_pages: int,
        max_page_chars: int,
    ) -> OperationResult[WorkspaceSnapshotReceipt]:
        """Build one complete snapshot using only the crawler's read protocol."""

        return self._workspace_snapshots.prepare(
            all_spaces=all_spaces,
            space_ids=space_ids,
            max_pages=max_pages,
            max_page_chars=max_page_chars,
        )

    def release_workspace_snapshot(
        self,
        snapshot_token: str,
    ) -> OperationResult[WorkspaceSnapshotRelease]:
        """Release one private snapshot; repeated cleanup is safe."""

        return self._workspace_snapshots.release(snapshot_token)

    def create_page(
        self,
        space_id: str,
        title: str,
        markdown: str,
        *,
        parent_page_id: str | None = None,
    ) -> OperationResult[CreatePageResult]:
        """Create a root page through Markdown import, then optionally nest it once."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[CreatePageResult](ok=False, error=blocked)
        try:
            validated_space_id = self._identifier(space_id)
            validated_title = self._title(title)
            validated_markdown = self._page_markdown(markdown)
            validated_parent = (
                self._identifier(parent_page_id) if parent_page_id is not None else None
            )
        except ValueError as error:
            return cast(OperationResult[CreatePageResult], self._invalid(error))

        def operation() -> CreatePageResult:
            canonical_parent: str | None = None
            if validated_parent is not None:
                parent_data = self._post(
                    "/api/pages/info",
                    {"pageId": validated_parent},
                    page_scope=True,
                )
                canonical_parent = self._page_id_from_data(parent_data)
                if self._page_space_id_from_data(parent_data) != validated_space_id:
                    raise _ClientFailure(
                        ErrorCode.PAGE_UNAVAILABLE,
                        PAGE_UNAVAILABLE_MESSAGE,
                    )

            imported = self._post_write_multipart(
                "/api/pages/import",
                data={"spaceId": validated_space_id},
                files={
                    "file": (
                        "docmost-page.md",
                        self._import_markdown(validated_title, validated_markdown).encode("utf-8"),
                        "text/markdown",
                    )
                },
            )
            created = self._parse_write_result(lambda: self._page_summary_from_data(imported))
            if canonical_parent is None:
                return CreatePageResult(page=created)

            raw_position = imported.get("position")
            if not isinstance(raw_position, str) or not 5 <= len(raw_position) <= 12:
                return self._partial_create(created, ErrorCode.UPSTREAM_ERROR)
            try:
                self._post_write_json(
                    "/api/pages/move",
                    {
                        "pageId": created.id,
                        "position": raw_position,
                        "parentPageId": canonical_parent,
                    },
                    page_scope=True,
                    allow_null_data=True,
                )
            except _ClientFailure as error:
                return self._partial_create(created, error.code)
            return CreatePageResult(
                page=created.model_copy(update={"parent": canonical_parent}),
                placement_status="nested",
            )

        return self._run_write(operation)

    def update_page_title(
        self, page_id: str, title: str, expected_updated_at: str
    ) -> OperationResult[Page]:
        """Optimistically update a title after a non-atomic timestamp reread."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[Page](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            validated_title = self._title(title)
            validated_timestamp = self._timestamp(expected_updated_at)
        except ValueError as error:
            return cast(OperationResult[Page], self._page_invalid(error))

        def operation() -> Page:
            current = self._page_summary_from_data(
                self._post(
                    "/api/pages/info",
                    {"pageId": validated_page_id},
                    page_scope=True,
                )
            )
            if current.updated_at != validated_timestamp:
                raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
            updated = self._post_write_json(
                "/api/pages/update",
                {"pageId": current.id, "title": validated_title},
                page_scope=True,
            )
            return self._parse_write_result(lambda: self._page_summary_from_data(updated))

        return self._run_write(operation)

    def edit_page_text(
        self,
        page_id: str,
        old_text: str,
        new_text: str,
        expected_updated_at: str,
    ) -> OperationResult[PageTextEditResult]:
        """Replace one exact text-node occurrence after a non-atomic revision check."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[PageTextEditResult](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            validated_old_text = self._edit_text(old_text, allow_empty=False)
            validated_new_text = self._edit_text(new_text, allow_empty=True)
            validated_timestamp = self._timestamp(expected_updated_at)
            if validated_old_text == validated_new_text:
                raise ValueError("old_text and new_text must differ")
        except ValueError as error:
            return cast(OperationResult[PageTextEditResult], self._invalid(error))

        def operation() -> PageTextEditResult:
            current_data = self._post(
                "/api/pages/info",
                {"pageId": validated_page_id, "format": "json"},
                page_scope=True,
            )
            try:
                raw_page = current_data.get("page", current_data)
                current = self._page_summary_from_data(raw_page)
            except ValueError as error:
                raise _ClientFailure(
                    ErrorCode.PAGE_UNAVAILABLE,
                    PAGE_UNAVAILABLE_MESSAGE,
                ) from error
            if current.updated_at != validated_timestamp:
                raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
            try:
                _, document = self._page_json_document_from_data(current_data)
                self._replace_unique_text_node(
                    document,
                    validated_old_text,
                    validated_new_text,
                )
            except ValueError as error:
                raise _ClientFailure(
                    ErrorCode.PAGE_UNAVAILABLE,
                    PAGE_UNAVAILABLE_MESSAGE,
                ) from error

            updated = self._post_write_json(
                "/api/pages/update",
                {
                    "pageId": current.id,
                    "content": document,
                    "format": "json",
                    "operation": "replace",
                },
                page_scope=True,
            )

            def parse_result() -> PageTextEditResult:
                page, _ = self._page_json_document_from_data(updated)
                return PageTextEditResult(page=page)

            return self._parse_write_result(parse_result)

        return self._run_write(operation)

    def patch_page_content(
        self,
        page_id: str,
        patch: list[JsonPatchOperation],
        expected_updated_at: str,
        expected_content_sha256: str,
    ) -> OperationResult[PageContentPatchResult]:
        """Apply one bounded body-scoped RFC 6902 patch after dual preconditions."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[PageContentPatchResult](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            validated_patch = validate_patch_operations(patch)
            validated_timestamp = self._timestamp(expected_updated_at)
            validated_sha256 = self._content_sha256(expected_content_sha256)
        except InvalidPagePatch as error:
            return OperationResult[PageContentPatchResult].failure(
                ErrorCode.INVALID_PATCH,
                str(error),
            )
        except ValueError as error:
            return cast(OperationResult[PageContentPatchResult], self._invalid(error))

        def operation() -> PageContentPatchResult:
            current_data = self._post(
                "/api/pages/info",
                {"pageId": validated_page_id, "format": "json"},
                page_scope=True,
            )
            try:
                current_page, current_document = self._page_json_document_from_data(current_data)
                current = inspect_page_content(current_document)
            except (InvalidPageContent, ValueError) as error:
                raise _ClientFailure(
                    ErrorCode.PAGE_UNAVAILABLE,
                    PAGE_UNAVAILABLE_MESSAGE,
                ) from error
            if (
                current_page.updated_at != validated_timestamp
                or current.content_sha256 != validated_sha256
            ):
                raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
            try:
                patched = apply_page_patch(current, validated_patch)
            except PagePatchConflict as error:
                raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT") from error
            except InvalidPagePatch as error:
                raise _ClientFailure(ErrorCode.INVALID_PATCH, str(error)) from error

            updated = self._post_write_json(
                "/api/pages/update",
                {
                    "pageId": current_page.id,
                    "content": patched.document,
                    "format": "json",
                    "operation": "replace",
                },
                page_scope=True,
            )

            def parse_result() -> PageContentPatchResult:
                page, response_document = self._page_json_document_from_data(updated)
                response_content = inspect_page_content(response_document)
                if (
                    page.id != current_page.id
                    or response_content.canonical_bytes != patched.canonical_bytes
                ):
                    raise ValueError("Docmost returned different page content")
                return PageContentPatchResult(
                    page=page,
                    content_sha256=response_content.content_sha256,
                    operations_applied=len(validated_patch),
                )

            return self._parse_write_result(parse_result)

        return self._run_write(operation)

    def attach_pdf_to_page(
        self,
        page_id: str,
        local_path: str,
        expected_file_sha256: str,
        expected_updated_at: str,
        expected_content_sha256: str,
    ) -> OperationResult[PdfAttachmentResult]:
        """Upload and append one guarded PDF attachment node to a page."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[PdfAttachmentResult](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            validated_file_sha256 = self._file_sha256(expected_file_sha256)
            validated_timestamp = self._timestamp(expected_updated_at)
            validated_content_sha256 = self._content_sha256(expected_content_sha256)
        except ValueError as error:
            return cast(OperationResult[PdfAttachmentResult], self._invalid(error))

        def operation() -> PdfAttachmentResult:
            page, document, current = self._guarded_page_content(
                validated_page_id,
                validated_timestamp,
                validated_content_sha256,
            )
            try:
                with self._pdf_validator.open(local_path, validated_file_sha256) as pdf:
                    matching_nodes = self._attachment_nodes(document, filename=pdf.filename)
                    if len(matching_nodes) > 1:
                        raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
                    if matching_nodes:
                        attrs = matching_nodes[0].get("attrs")
                        typed_attrs = (
                            cast(dict[str, object], attrs)
                            if isinstance(attrs, dict)
                            else {}
                        )
                        attachment_id = typed_attrs.get("attachmentId")
                        if not isinstance(attachment_id, str) or not attachment_id:
                            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
                        existing = self._verify_pdf_attachment(
                            page.id,
                            attachment_id,
                            validated_file_sha256,
                        )
                        pdf.assert_stable()
                        if (
                            existing.filename != pdf.filename
                            or existing.size_bytes != pdf.size_bytes
                            or len(
                                self._root_attachment_nodes(
                                    document,
                                    attachment_id=existing.id,
                                )
                            )
                            != 1
                            or not self._pdf_node_matches(matching_nodes[0], existing)
                        ):
                            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
                        return PdfAttachmentResult(
                            page=page,
                            attachment=existing,
                            link_status="already_linked",
                            content_sha256=current.content_sha256,
                        )

                    pdf.assert_stable()
                    uploaded_info = self._post_pdf_upload(page.id, pdf)
                    uploaded = self._uploaded_pdf_from_info(
                        uploaded_info,
                        validated_file_sha256,
                        checksum_verified=False,
                    )
                    try:
                        pdf.assert_stable()
                    except PdfValidationError:
                        return self._partial_pdf_result(
                            page,
                            current,
                            uploaded,
                            link_status="uploaded_unlinked",
                            cause=ErrorCode.CONFLICT,
                        )
                    if not self._upload_metadata_matches(uploaded_info, page.id, pdf):
                        return self._partial_pdf_result(
                            page,
                            current,
                            uploaded,
                            link_status="uploaded_unlinked",
                            cause=ErrorCode.UPSTREAM_ERROR,
                        )
                    try:
                        verified = self._verify_pdf_attachment(
                            page.id,
                            uploaded.id,
                            validated_file_sha256,
                        )
                    except _ClientFailure as error:
                        return self._partial_pdf_result(
                            page,
                            current,
                            uploaded,
                            link_status="uploaded_unlinked",
                            cause=error.code,
                        )

                    try:
                        latest_page, latest_document, latest = self._page_content_snapshot(page.id)
                    except _ClientFailure as error:
                        return self._partial_pdf_result(
                            page,
                            current,
                            verified,
                            link_status="uploaded_unlinked",
                            cause=error.code,
                        )
                    if (
                        latest_page.updated_at != validated_timestamp
                        or latest.content_sha256 != validated_content_sha256
                    ):
                        return self._partial_pdf_result(
                            latest_page,
                            latest,
                            verified,
                            link_status="uploaded_unlinked",
                            cause=ErrorCode.CONFLICT,
                        )
                    return self._link_verified_pdf(
                        latest_page,
                        latest_document,
                        latest,
                        verified,
                    )
            except PdfValidationError as error:
                raise self._pdf_validation_failure(error) from error

        return self._run_write(operation)

    def link_uploaded_pdf(
        self,
        page_id: str,
        attachment_id: str,
        expected_file_sha256: str,
        expected_updated_at: str,
        expected_content_sha256: str,
    ) -> OperationResult[PdfAttachmentResult]:
        """Verify and link an existing uploaded PDF without uploading it again."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[PdfAttachmentResult](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            validated_attachment_id = self._identifier(attachment_id)
            validated_file_sha256 = self._file_sha256(expected_file_sha256)
            validated_timestamp = self._timestamp(expected_updated_at)
            validated_content_sha256 = self._content_sha256(expected_content_sha256)
        except ValueError as error:
            return cast(OperationResult[PdfAttachmentResult], self._invalid(error))

        def operation() -> PdfAttachmentResult:
            page, document, current = self._guarded_page_content(
                validated_page_id,
                validated_timestamp,
                validated_content_sha256,
            )
            verified = self._verify_pdf_attachment(
                page.id,
                validated_attachment_id,
                validated_file_sha256,
            )
            return self._link_verified_pdf(page, document, current, verified)

        return self._run_write(operation)

    def create_comment(self, page_id: str, markdown: str) -> OperationResult[Comment]:
        """Create a page comment from the conservative Markdown subset."""

        blocked = self.write_compatibility_error
        if blocked is not None:
            return OperationResult[Comment](ok=False, error=blocked)
        try:
            validated_page_id = self._identifier(page_id)
            if len(markdown) > _MAX_COMMENT_MARKDOWN_CHARS:
                raise MarkdownValidationError(
                    f"comment Markdown must be at most {_MAX_COMMENT_MARKDOWN_CHARS} characters"
                )
            tiptap = markdown_to_tiptap(markdown)
        except MarkdownValidationError as error:
            return OperationResult[Comment].failure(ErrorCode.INVALID_MARKDOWN, str(error))
        except ValueError as error:
            return cast(OperationResult[Comment], self._page_invalid(error))

        def operation() -> Comment:
            canonical_page_id = self._page_id_from_data(
                self._post(
                    "/api/pages/info",
                    {"pageId": validated_page_id},
                    page_scope=True,
                )
            )
            created = self._post_write_json(
                "/api/comments/create",
                {
                    "pageId": canonical_page_id,
                    "content": json.dumps(tiptap, ensure_ascii=False, separators=(",", ":")),
                    "type": "page",
                },
                page_scope=True,
            )
            return self._parse_write_result(lambda: Comment.model_validate(created))

        return self._run_write(operation)

    def _page_content_snapshot(
        self, page_id: str
    ) -> tuple[Page, dict[str, object], InspectedPageContent]:
        data = self._post(
            "/api/pages/info",
            {"pageId": page_id, "format": "json"},
            page_scope=True,
        )
        try:
            page, document = self._page_json_document_from_data(data)
            inspected = inspect_page_content(document)
        except (InvalidPageContent, ValueError) as error:
            raise _ClientFailure(
                ErrorCode.PAGE_UNAVAILABLE,
                PAGE_UNAVAILABLE_MESSAGE,
            ) from error
        return page, document, inspected

    def _guarded_page_content(
        self,
        page_id: str,
        expected_updated_at: str,
        expected_content_sha256: str,
    ) -> tuple[Page, dict[str, object], InspectedPageContent]:
        page, document, inspected = self._page_content_snapshot(page_id)
        if (
            page.updated_at != expected_updated_at
            or inspected.content_sha256 != expected_content_sha256
        ):
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
        return page, document, inspected

    def _verify_pdf_attachment(
        self,
        page_id: str,
        attachment_id: str,
        expected_sha256: str,
    ) -> UploadedPdf:
        try:
            metadata = AttachmentInfo.model_validate(
                self._post(
                    "/api/files/info",
                    {"attachmentId": attachment_id},
                    page_scope=True,
                )
            )
        except _ClientFailure as error:
            if error.code in {ErrorCode.PAGE_UNAVAILABLE, ErrorCode.FORBIDDEN}:
                raise _ClientFailure(
                    ErrorCode.ATTACHMENT_UNAVAILABLE,
                    "ATTACHMENT_UNAVAILABLE",
                ) from error
            raise
        if (
            metadata.id != attachment_id
            or metadata.page_id != page_id
            or metadata.type != "file"
            or metadata.file_size > _MAX_ATTACHMENT_BYTES
        ):
            raise _ClientFailure(
                ErrorCode.ATTACHMENT_UNAVAILABLE,
                "ATTACHMENT_UNAVAILABLE",
            )
        filename, media_type = self._validated_attachment_metadata(metadata)
        if media_type != "application/pdf":
            raise _ClientFailure(
                ErrorCode.UNSUPPORTED_ATTACHMENT,
                "UNSUPPORTED_ATTACHMENT",
            )
        staged = self._download_and_stage(
            metadata,
            filename=filename,
            media_type="application/pdf",
        )
        try:
            if staged.sha256 != expected_sha256:
                raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
            return UploadedPdf(
                id=metadata.id,
                page_id=metadata.page_id,
                filename=filename,
                size_bytes=metadata.file_size,
                sha256=staged.sha256,
                checksum_verified=True,
                url=self._attachment_relative_url(metadata.id, filename),
            )
        finally:
            self._downloads.release(staged.download_token)

    def _link_verified_pdf(
        self,
        page: Page,
        document: dict[str, object],
        current: InspectedPageContent,
        attachment: UploadedPdf,
    ) -> PdfAttachmentResult:
        id_nodes = self._attachment_nodes(document, attachment_id=attachment.id)
        if id_nodes:
            root_nodes = self._root_attachment_nodes(
                document,
                attachment_id=attachment.id,
            )
            if (
                len(id_nodes) == 1
                and len(root_nodes) == 1
                and self._pdf_node_matches(id_nodes[0], attachment)
            ):
                return PdfAttachmentResult(
                    page=page,
                    attachment=attachment,
                    link_status="already_linked",
                    content_sha256=current.content_sha256,
                )
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
        if self._attachment_nodes(document, filename=attachment.filename):
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")

        patched_document = deepcopy(document)
        raw_children = patched_document.get("content")
        if raw_children is None:
            children: list[object] = []
            patched_document["content"] = children
        elif isinstance(raw_children, list):
            children = cast(list[object], raw_children)
        else:
            raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
        children.append(self._pdf_attachment_node(attachment))
        try:
            patched = inspect_page_content(patched_document)
        except InvalidPageContent as error:
            raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE) from error

        try:
            updated = self._post_write_json(
                "/api/pages/update",
                {
                    "pageId": page.id,
                    "content": patched.document,
                    "format": "json",
                    "operation": "replace",
                },
                page_scope=True,
            )
        except _ClientFailure as error:
            if error.code is ErrorCode.OUTCOME_UNKNOWN:
                return self._reconcile_pdf_link(page, current, attachment)
            return self._partial_pdf_result(
                page,
                current,
                attachment,
                link_status="uploaded_unlinked",
                cause=error.code,
            )

        try:
            updated_page, updated_document = self._page_json_document_from_data(updated)
            updated_content = inspect_page_content(updated_document)
            if (
                updated_page.id != page.id
                or updated_content.canonical_bytes != patched.canonical_bytes
                or len(self._attachment_nodes(updated_document, attachment_id=attachment.id)) != 1
                or len(
                    self._root_attachment_nodes(
                        updated_document,
                        attachment_id=attachment.id,
                    )
                )
                != 1
            ):
                return self._reconcile_pdf_link(page, current, attachment)
        except (InvalidPageContent, ValueError):
            return self._reconcile_pdf_link(page, current, attachment)
        return PdfAttachmentResult(
            page=updated_page,
            attachment=attachment,
            link_status="linked",
            content_sha256=updated_content.content_sha256,
        )

    def _reconcile_pdf_link(
        self,
        fallback_page: Page,
        fallback_content: InspectedPageContent,
        attachment: UploadedPdf,
    ) -> PdfAttachmentResult:
        try:
            page, document, content = self._page_content_snapshot(fallback_page.id)
        except _ClientFailure:
            return self._partial_pdf_result(
                fallback_page,
                fallback_content,
                attachment,
                link_status="link_unknown",
                cause=ErrorCode.OUTCOME_UNKNOWN,
            )
        nodes = self._attachment_nodes(document, attachment_id=attachment.id)
        root_nodes = self._root_attachment_nodes(
            document,
            attachment_id=attachment.id,
        )
        if (
            len(nodes) == 1
            and len(root_nodes) == 1
            and self._pdf_node_matches(nodes[0], attachment)
        ):
            return PdfAttachmentResult(
                page=page,
                attachment=attachment,
                link_status="linked",
                content_sha256=content.content_sha256,
            )
        return self._partial_pdf_result(
            page,
            content,
            attachment,
            link_status="link_unknown",
            cause=ErrorCode.OUTCOME_UNKNOWN,
        )

    @staticmethod
    def _attachment_nodes(
        document: dict[str, object],
        *,
        attachment_id: str | None = None,
        filename: str | None = None,
    ) -> list[dict[str, object]]:
        matches: list[dict[str, object]] = []
        stack: list[dict[str, object]] = [document]
        while stack:
            node = stack.pop()
            if node.get("type") == "attachment":
                attrs = node.get("attrs")
                if isinstance(attrs, dict):
                    typed_attrs = cast(dict[str, object], attrs)
                    id_matches = (
                        attachment_id is None
                        or typed_attrs.get("attachmentId") == attachment_id
                    )
                    name_matches = filename is None or typed_attrs.get("name") == filename
                    if id_matches and name_matches:
                        matches.append(node)
            raw_children = node.get("content")
            if isinstance(raw_children, list):
                for child in reversed(cast(list[object], raw_children)):
                    if isinstance(child, dict):
                        stack.append(cast(dict[str, object], child))
        return matches

    @staticmethod
    def _root_attachment_nodes(
        document: dict[str, object],
        *,
        attachment_id: str | None = None,
    ) -> list[dict[str, object]]:
        raw_children = document.get("content")
        if not isinstance(raw_children, list):
            return []
        matches: list[dict[str, object]] = []
        for raw_node in cast(list[object], raw_children):
            if not isinstance(raw_node, dict):
                continue
            node = cast(dict[str, object], raw_node)
            if node.get("type") != "attachment":
                continue
            attrs = node.get("attrs")
            typed_attrs = cast(dict[str, object], attrs) if isinstance(attrs, dict) else {}
            if attachment_id is None or typed_attrs.get("attachmentId") == attachment_id:
                matches.append(node)
        return matches

    @classmethod
    def _pdf_node_matches(cls, node: dict[str, object], attachment: UploadedPdf) -> bool:
        attrs = node.get("attrs")
        if not isinstance(attrs, dict):
            return False
        typed_attrs = cast(dict[str, object], attrs)
        raw_expected = cls._pdf_attachment_node(attachment)["attrs"]
        assert isinstance(raw_expected, dict)
        expected = cast(dict[str, object], raw_expected)
        return all(typed_attrs.get(key) == value for key, value in expected.items())

    @staticmethod
    def _pdf_attachment_node(attachment: UploadedPdf) -> dict[str, object]:
        return {
            "type": "attachment",
            "attrs": {
                "url": attachment.url,
                "name": attachment.filename,
                "mime": attachment.media_type,
                "size": attachment.size_bytes,
                "attachmentId": attachment.id,
            },
        }

    def _uploaded_pdf_from_info(
        self,
        metadata: AttachmentInfo,
        expected_sha256: str,
        *,
        checksum_verified: bool,
    ) -> UploadedPdf:
        filename = self._safe_filename(metadata.file_name)
        return UploadedPdf(
            id=self._identifier(metadata.id),
            page_id=self._identifier(metadata.page_id),
            filename=filename,
            size_bytes=metadata.file_size,
            sha256=expected_sha256,
            checksum_verified=checksum_verified,
            url=self._attachment_relative_url(metadata.id, filename),
        )

    @classmethod
    def _upload_metadata_matches(
        cls,
        metadata: AttachmentInfo,
        page_id: str,
        pdf: ValidatedPdf,
    ) -> bool:
        return (
            metadata.page_id == page_id
            and metadata.file_name == pdf.filename
            and metadata.file_size == pdf.size_bytes
            and metadata.type == "file"
            and metadata.file_ext.lower() == ".pdf"
            and cls._normalized_media_type(metadata.mime_type) == "application/pdf"
        )

    @staticmethod
    def _partial_pdf_result(
        page: Page,
        content: InspectedPageContent,
        attachment: UploadedPdf,
        *,
        link_status: Literal["uploaded_unlinked", "link_unknown"],
        cause: ErrorCode,
    ) -> PdfAttachmentResult:
        message = (
            _PARTIAL_PDF_UNKNOWN_MESSAGE
            if link_status == "link_unknown"
            else _PARTIAL_PDF_UNLINKED_MESSAGE
        )
        return PdfAttachmentResult(
            page=page,
            attachment=attachment,
            link_status=link_status,
            content_sha256=content.content_sha256,
            partial_success=True,
            warning=OperationError(
                code=ErrorCode.PARTIAL_SUCCESS,
                message=message,
                retryable=False,
                details={"cause": cause.value, "link_status": link_status},
            ),
        )

    @staticmethod
    def _pdf_validation_failure(error: PdfValidationError) -> _ClientFailure:
        mapping: dict[str, tuple[ErrorCode, str]] = {
            "forbidden_path": (ErrorCode.FORBIDDEN_PATH, "FORBIDDEN_PATH"),
            "unsupported_attachment": (
                ErrorCode.UNSUPPORTED_ATTACHMENT,
                "UNSUPPORTED_ATTACHMENT",
            ),
            "attachment_too_large": (
                ErrorCode.ATTACHMENT_TOO_LARGE,
                "ATTACHMENT_TOO_LARGE",
            ),
            "conflict": (ErrorCode.CONFLICT, "CONFLICT"),
        }
        code, message = mapping[error.kind]
        return _ClientFailure(code, message)

    @staticmethod
    def _attachment_relative_url(attachment_id: str, filename: str) -> str:
        return f"/api/files/{quote(attachment_id, safe='')}/{quote(filename, safe='')}"

    def _post(
        self, path: str, body: dict[str, object], *, page_scope: bool = False
    ) -> dict[str, object]:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(
                    self._endpoint(path),
                    json=body,
                    headers={
                        "Cookie": f"{self._settings.session_cookie}="
                        f"{self._session_cookie.get_secret_value()}"
                    },
                )
            except httpx.TransportError as error:
                if attempt < self._max_retries:
                    self._sleeper(0.25 * (2**attempt))
                    continue
                raise _ClientFailure(
                    ErrorCode.UPSTREAM_ERROR, "Docmost read request failed", retryable=True
                ) from error
            if response.status_code in _TRANSIENT_STATUS_CODES and attempt < self._max_retries:
                self._sleeper(0.25 * (2**attempt))
                continue
            return self._validate_response(response, page_scope=page_scope)
        raise AssertionError("unreachable retry loop")

    def _download_and_stage(
        self,
        metadata: AttachmentInfo,
        *,
        filename: str,
        media_type: Literal["application/pdf", "text/plain"],
    ) -> AttachmentDownload:
        try:
            with self._http.stream(
                "GET",
                self._attachment_endpoint(metadata.id, filename),
                headers=self._cookie_headers(),
            ) as response:
                if response.status_code == 401:
                    raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
                if response.status_code in {403, 404}:
                    raise _ClientFailure(
                        ErrorCode.ATTACHMENT_UNAVAILABLE,
                        "ATTACHMENT_UNAVAILABLE",
                    )
                if 300 <= response.status_code < 400:
                    raise _ClientFailure(
                        ErrorCode.ATTACHMENT_UNAVAILABLE,
                        "ATTACHMENT_UNAVAILABLE",
                    )
                if response.status_code != 200:
                    raise _ClientFailure(
                        ErrorCode.UPSTREAM_ERROR,
                        "Docmost attachment download failed",
                        retryable=response.status_code in _TRANSIENT_STATUS_CODES,
                    )

                response_type = self._normalized_media_type(response.headers.get("content-type"))
                if response_type != media_type:
                    raise _ClientFailure(
                        ErrorCode.UNSUPPORTED_ATTACHMENT,
                        "UNSUPPORTED_ATTACHMENT",
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    if not content_length.isdecimal():
                        raise _ClientFailure(
                            ErrorCode.ATTACHMENT_UNAVAILABLE,
                            "ATTACHMENT_UNAVAILABLE",
                        )
                    declared_size = int(content_length)
                    if declared_size > _MAX_ATTACHMENT_BYTES:
                        raise _ClientFailure(
                            ErrorCode.ATTACHMENT_TOO_LARGE,
                            "ATTACHMENT_TOO_LARGE",
                        )
                    if declared_size != metadata.file_size:
                        raise _ClientFailure(
                            ErrorCode.ATTACHMENT_UNAVAILABLE,
                            "ATTACHMENT_UNAVAILABLE",
                        )
                try:
                    return self._downloads.stage(
                        filename=filename,
                        media_type=media_type,
                        chunks=response.iter_bytes(),
                        expected_size=metadata.file_size,
                    )
                except AttachmentStageError as error:
                    if error.kind == "too_large":
                        raise _ClientFailure(
                            ErrorCode.ATTACHMENT_TOO_LARGE,
                            "ATTACHMENT_TOO_LARGE",
                        ) from error
                    raise _ClientFailure(
                        ErrorCode.UNSUPPORTED_ATTACHMENT,
                        "UNSUPPORTED_ATTACHMENT",
                    ) from error
        except httpx.TransportError as error:
            raise _ClientFailure(
                ErrorCode.UPSTREAM_ERROR,
                "Docmost attachment download failed",
                retryable=True,
            ) from error

    def _post_write_json(
        self,
        path: str,
        body: dict[str, object],
        *,
        page_scope: bool,
        allow_null_data: bool = False,
    ) -> dict[str, object]:
        try:
            response = self._http.post(
                self._endpoint(path),
                json=body,
                headers=self._cookie_headers(),
            )
        except httpx.TimeoutException as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error
        except httpx.TransportError as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error
        return self._validate_write_response(
            response,
            page_scope=page_scope,
            allow_null_data=allow_null_data,
        )

    def _post_write_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
    ) -> dict[str, object]:
        try:
            response = self._http.post(
                self._endpoint(path),
                data=data,
                files=files,
                headers=self._cookie_headers(),
            )
        except httpx.TimeoutException as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error
        except httpx.TransportError as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error
        return self._validate_write_response(response, page_scope=False)

    def _post_pdf_upload(self, page_id: str, pdf: ValidatedPdf) -> AttachmentInfo:
        """Upload one validated PDF through Docmost's raw v0.95 response contract."""

        try:
            pdf.stream.seek(0)
            response = self._http.post(
                self._endpoint("/api/files/upload"),
                data={"pageId": page_id},
                files={"file": (pdf.filename, pdf.stream, "application/pdf")},
                headers=self._cookie_headers(),
                timeout=_PDF_UPLOAD_TIMEOUT,
            )
        except (httpx.TimeoutException, httpx.TransportError, OSError) as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error

        if response.status_code == 401:
            raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
        if response.status_code in {403, 404}:
            raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
        if response.status_code == 409:
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
        if response.status_code in _TRANSIENT_STATUS_CODES:
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        if 300 <= response.status_code < 400:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            )
        if 200 <= response.status_code < 300 and response.status_code not in {200, 201}:
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        if response.status_code not in {200, 201}:
            raise _ClientFailure(ErrorCode.UPSTREAM_ERROR, "Docmost PDF upload failed")

        try:
            payload = cast(object, response.json())
            if not isinstance(payload, dict):
                raise ValueError("attachment upload response must be an object")
            metadata = AttachmentInfo.model_validate(cast(dict[str, object], payload))
            self._identifier(metadata.id)
            self._identifier(metadata.page_id)
            self._safe_filename(metadata.file_name)
            return metadata
        except (ValidationError, TypeError, ValueError) as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error

    def _validate_response(
        self, response: httpx.Response, *, page_scope: bool
    ) -> dict[str, object]:
        if response.status_code == 401:
            raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
        if response.status_code in {403, 404}:
            if page_scope:
                raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
            if response.status_code == 403:
                raise _ClientFailure(ErrorCode.FORBIDDEN, FORBIDDEN_MESSAGE)
        if 300 <= response.status_code < 400:
            raise self._unavailable(page_scope, "Docmost read request was redirected")
        if response.status_code != 200:
            raise self._unavailable(
                page_scope,
                "Docmost read request failed",
                retryable=response.status_code in _TRANSIENT_STATUS_CODES,
            )
        try:
            payload = cast(object, response.json())
        except ValueError as error:
            raise self._unavailable(
                page_scope, "Docmost read response was not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise self._unavailable(page_scope, "Docmost read response had an invalid envelope")
        envelope = cast(dict[str, object], payload)
        data = envelope.get("data")
        if (
            envelope.get("success") is not True
            or envelope.get("status") != 200
            or not isinstance(data, dict)
        ):
            raise self._unavailable(page_scope, "Docmost read response had an invalid envelope")
        return cast(dict[str, object], data)

    def _validate_write_response(
        self,
        response: httpx.Response,
        *,
        page_scope: bool,
        allow_null_data: bool = False,
    ) -> dict[str, object]:
        if response.status_code == 401:
            raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
        if response.status_code in {403, 404} and page_scope:
            raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
        if response.status_code == 403:
            raise _ClientFailure(ErrorCode.FORBIDDEN, FORBIDDEN_MESSAGE)
        if response.status_code == 409:
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
        if response.status_code in _TRANSIENT_STATUS_CODES:
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        if 300 <= response.status_code < 400:
            raise _ClientFailure(ErrorCode.UPSTREAM_ERROR, "Docmost write request was redirected")
        if response.status_code != 200:
            raise _ClientFailure(ErrorCode.UPSTREAM_ERROR, "Docmost write request failed")
        try:
            payload = cast(object, response.json())
        except ValueError as error:
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE) from error
        if not isinstance(payload, dict):
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        envelope = cast(dict[str, object], payload)
        data = envelope.get("data")
        if envelope.get("success") is not True or envelope.get("status") != 200:
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        if data is None and allow_null_data:
            return {}
        if not isinstance(data, dict):
            raise _ClientFailure(ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE)
        return cast(dict[str, object], data)

    def _run[ResultData](
        self, operation: Callable[[], ResultData], *, page_scope: bool = False
    ) -> OperationResult[ResultData]:
        try:
            return OperationResult[ResultData].success(operation())
        except _ClientFailure as error:
            return OperationResult[ResultData].failure(
                error.code, error.public_message, retryable=error.retryable
            )
        except (ValidationError, TypeError, ValueError):
            return OperationResult[ResultData].failure(
                ErrorCode.PAGE_UNAVAILABLE if page_scope else ErrorCode.UPSTREAM_ERROR,
                PAGE_UNAVAILABLE_MESSAGE if page_scope else "Docmost read response was invalid",
            )

    def _run_write[ResultData](
        self, operation: Callable[[], ResultData]
    ) -> OperationResult[ResultData]:
        try:
            return OperationResult[ResultData].success(operation())
        except _ClientFailure as error:
            return OperationResult[ResultData].failure(
                error.code,
                error.public_message,
                retryable=False,
            )
        except (ValidationError, TypeError, ValueError):
            return OperationResult[ResultData].failure(
                ErrorCode.UPSTREAM_ERROR,
                "Docmost write response was invalid",
            )

    @staticmethod
    def _parse_write_result[ResultData](
        parser: Callable[[], ResultData],
    ) -> ResultData:
        """Treat post-dispatch model failures as an ambiguous committed outcome."""

        try:
            return parser()
        except (ValidationError, TypeError, ValueError) as error:
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN,
                _OUTCOME_UNKNOWN_MESSAGE,
            ) from error

    def _cursor_page(
        self,
        data: dict[str, object],
        item_type: type[ModelItem],
        *,
        limit: int,
    ) -> CursorPage[ModelItem]:
        raw_items: object = data["items"] if "items" in data else None
        raw_meta: object = data["meta"] if "meta" in data else {}
        if not isinstance(raw_items, list) or not isinstance(raw_meta, dict):
            raise ValueError("cursor response must contain items and meta")
        items = cast(list[object], raw_items)
        if len(items) > limit:
            raise ValueError("cursor response exceeded the requested limit")
        meta = cast(dict[str, object], raw_meta)
        next_cursor = meta.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("nextCursor must be a string")
        if isinstance(next_cursor, str):
            next_cursor = self._cursor(next_cursor)
        if item_type is Page:
            parsed_items = cast(
                list[ModelItem],
                [self._page_summary_from_data(item) for item in items],
            )
        else:
            parsed_items = [item_type.model_validate(item) for item in items]
        return CursorPage[ModelItem](items=parsed_items, next_cursor=next_cursor)

    def _page_from_data(
        self, data: dict[str, object], *, offset: int = 0, max_chars: int = _MAX_PAGE_CHARS
    ) -> Page:
        raw_page = data.get("page", data)
        if not isinstance(raw_page, dict):
            raise ValueError("page response must contain a page object")
        page_data = cast(dict[str, object], raw_page)
        raw_space = page_data.get("space", data.get("space", {}))
        space = cast(dict[str, object], raw_space) if isinstance(raw_space, dict) else {}
        if "content" in data:
            content = data["content"]
        elif "content" in page_data:
            content = page_data["content"]
        else:
            raise ValueError("page response must include Markdown content")
        if content is None:
            content = ""
        elif not isinstance(content, str):
            raise ValueError("page content must be Markdown text")
        page_id = page_data.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("page response must contain an id")
        slug_id = page_data.get("slugId")
        space_slug = space.get("slug")
        title = page_data.get("title")
        url = self._page_url(space_slug, title, slug_id)
        window = content[offset : offset + max_chars]
        next_offset = offset + len(window) if offset + len(window) < len(content) else None
        return Page(
            id=page_id,
            title=self._string(title),
            slugId=self._string(slug_id),
            space_id=self._string(space.get("id")),
            space_name=self._string(space.get("name")),
            space_slug=self._string(space_slug),
            parent=self._string(page_data.get("parentPageId", page_data.get("parentId"))),
            position=self._string(page_data.get("position")),
            created_at=self._string(page_data.get("createdAt")),
            updated_at=self._string(page_data.get("updatedAt")),
            url=url,
            markdown=window,
            truncated=next_offset is not None,
            next_offset=next_offset,
        )

    def _page_summary_from_data(self, value: object) -> Page:
        if not isinstance(value, dict):
            raise ValueError("page list item must be an object")
        page_data = cast(dict[str, object], value)
        page_id = page_data.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("page list item must contain an id")
        raw_space = page_data.get("space", {})
        space = cast(dict[str, object], raw_space) if isinstance(raw_space, dict) else {}
        slug_id = page_data.get("slugId")
        space_slug = space.get("slug")
        title = page_data.get("title")
        return Page(
            id=page_id,
            title=self._string(title),
            slugId=self._string(slug_id),
            space_id=self._string(space.get("id", page_data.get("spaceId"))),
            space_name=self._string(space.get("name")),
            space_slug=self._string(space_slug),
            parent=self._string(page_data.get("parentPageId", page_data.get("parentId"))),
            position=self._string(page_data.get("position")),
            created_at=self._string(page_data.get("createdAt")),
            updated_at=self._string(page_data.get("updatedAt")),
            url=self._page_url(space_slug, title, slug_id),
        )

    def _page_json_document_from_data(
        self, data: dict[str, object]
    ) -> tuple[Page, dict[str, object]]:
        raw_page = data.get("page", data)
        if not isinstance(raw_page, dict):
            raise ValueError("page response must contain a page object")
        page_data = cast(dict[str, object], raw_page)
        page = self._page_summary_from_data(page_data)
        content = data.get("content", page_data.get("content"))
        if not isinstance(content, dict):
            raise ValueError("page response must contain a ProseMirror document")
        document = cast(dict[str, object], content)
        if document.get("type") != "doc":
            raise ValueError("page response must contain a ProseMirror document")
        raw_children = document.get("content")
        if raw_children is not None and not isinstance(raw_children, list):
            raise ValueError("ProseMirror document content must be a list")
        return page, document

    @classmethod
    def _replace_unique_text_node(
        cls,
        document: dict[str, object],
        old_text: str,
        new_text: str,
    ) -> None:
        """Mutate only one matching text node after bounded structural validation."""

        match: tuple[list[object], int, dict[str, object], int] | None = None
        node_count = 0
        total_text_chars = 0
        stack: list[tuple[dict[str, object], int, list[object] | None, int | None]] = [
            (document, 0, None, None)
        ]

        while stack:
            node, depth, parent, parent_index = stack.pop()
            node_count += 1
            if node_count > _MAX_PROSEMIRROR_NODES or depth > _MAX_PROSEMIRROR_DEPTH:
                raise ValueError("page content exceeded edit safety bounds")

            node_type = node.get("type")
            if not isinstance(node_type, str) or not node_type:
                raise ValueError("ProseMirror node type is invalid")
            raw_children = node.get("content")
            if raw_children is None:
                children: list[object] | None = None
            elif isinstance(raw_children, list):
                children = cast(list[object], raw_children)
            else:
                raise ValueError("ProseMirror node content is invalid")

            raw_text = node.get("text")
            if node_type == "text":
                if not isinstance(raw_text, str) or not raw_text or children is not None:
                    raise ValueError("ProseMirror text node is invalid")
                if parent is None or parent_index is None:
                    raise ValueError("ProseMirror text node has no parent")
                total_text_chars += len(raw_text)
                if total_text_chars > _MAX_PROSEMIRROR_TEXT_CHARS:
                    raise ValueError("page text exceeded edit safety bounds")
                position = raw_text.find(old_text)
                while position >= 0:
                    if match is not None:
                        raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
                    match = (parent, parent_index, node, position)
                    position = raw_text.find(old_text, position + 1)
            elif raw_text is not None:
                raise ValueError("non-text ProseMirror node contained text")

            if children is not None:
                if len(children) > _MAX_PROSEMIRROR_NODES:
                    raise ValueError("page content exceeded edit safety bounds")
                if cls._contains_cross_node_match(children, old_text):
                    raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
                for child_index in range(len(children) - 1, -1, -1):
                    child = children[child_index]
                    if not isinstance(child, dict):
                        raise ValueError("ProseMirror child node is invalid")
                    stack.append(
                        (cast(dict[str, object], child), depth + 1, children, child_index)
                    )

        if match is None:
            raise _ClientFailure(ErrorCode.CONFLICT, "CONFLICT")
        if total_text_chars - len(old_text) + len(new_text) > _MAX_PROSEMIRROR_TEXT_CHARS:
            raise ValueError("edited page text exceeded edit safety bounds")

        parent, index, node, position = match
        current_text = cast(str, node["text"])
        replacement = (
            current_text[:position]
            + new_text
            + current_text[position + len(old_text) :]
        )
        if replacement:
            node["text"] = replacement
        else:
            del parent[index]

    @staticmethod
    def _contains_cross_node_match(children: list[object], old_text: str) -> bool:
        if len(old_text) < 2:
            return False

        run: list[str] = []
        run_chars = 0

        def run_has_cross_match(parts: list[str]) -> bool:
            if len(parts) < 2:
                return False
            joined = "".join(parts)
            boundaries: list[tuple[int, int]] = []
            offset = 0
            for part in parts:
                boundaries.append((offset, offset + len(part)))
                offset += len(part)
            position = joined.find(old_text)
            while position >= 0:
                end = position + len(old_text)
                if not any(start <= position and end <= stop for start, stop in boundaries):
                    return True
                position = joined.find(old_text, position + 1)
            return False

        for child in [*children, None]:
            if isinstance(child, dict):
                child_node = cast(dict[str, object], child)
            else:
                child_node = None
            if child_node is not None and child_node.get("type") == "text":
                text = child_node.get("text")
                if not isinstance(text, str) or not text:
                    raise ValueError("ProseMirror text node is invalid")
                run_chars += len(text)
                if run_chars > _MAX_PROSEMIRROR_TEXT_CHARS:
                    raise ValueError("page text exceeded edit safety bounds")
                run.append(text)
                continue
            if run_has_cross_match(run):
                return True
            run = []
            run_chars = 0
        return False

    @staticmethod
    def _page_id_from_data(data: dict[str, object]) -> str:
        raw_page = data.get("page", data)
        if not isinstance(raw_page, dict):
            raise ValueError("page response must contain a page object")
        page_data = cast(dict[str, object], raw_page)
        page_id = page_data.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("page response must contain an id")
        return page_id

    @staticmethod
    def _page_space_id_from_data(data: dict[str, object]) -> str:
        raw_page = data.get("page", data)
        if not isinstance(raw_page, dict):
            raise ValueError("page response must contain a page object")
        page_data = cast(dict[str, object], raw_page)
        space_id = page_data.get("spaceId")
        if not isinstance(space_id, str):
            raw_space = page_data.get("space", data.get("space", {}))
            if isinstance(raw_space, dict):
                space_id = cast(dict[str, object], raw_space).get("id")
        if not isinstance(space_id, str) or not space_id:
            raise ValueError("page response must contain a space id")
        return space_id

    def _page_url(self, space_slug: object, title: object, slug_id: object) -> str | None:
        if not isinstance(space_slug, str) or not isinstance(slug_id, str):
            return None
        page_slug = f"{self._title_slug(title)}-{slug_id}"
        return f"{self._origin()}/s/{quote(space_slug, safe='')}/p/{quote(page_slug, safe='')}"

    @staticmethod
    def _title_slug(title: object) -> str:
        source = title[:70] if isinstance(title, str) and title else "untitled"
        source = source.replace("♥", "").replace("🦄", "")
        ascii_source = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode()
        normalized = re.sub(r"[^a-z0-9]+", "-", ascii_source.lower()).strip("-")
        return normalized or "untitled"

    @staticmethod
    def _encode_search_cursor(offset: int) -> str:
        if offset < 0:
            raise ValueError("search offset must be non-negative")
        encoded = base64.urlsafe_b64encode(str(offset).encode("ascii")).rstrip(b"=").decode("ascii")
        return f"{_SEARCH_CURSOR_PREFIX}{encoded}"

    @staticmethod
    def _search_offset(cursor: str | None) -> int:
        if cursor is None:
            return 0
        if not cursor.startswith(_SEARCH_CURSOR_PREFIX):
            raise ValueError("search cursor is invalid")
        payload = cursor.removeprefix(_SEARCH_CURSOR_PREFIX)
        if not _SEARCH_CURSOR_PAYLOAD.fullmatch(payload):
            raise ValueError("search cursor is invalid")
        try:
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("search cursor is invalid") from error
        if not decoded.isdecimal():
            raise ValueError("search cursor is invalid")
        offset = int(decoded)
        if offset > 2**63 - 1 or DocmostReadClient._encode_search_cursor(offset) != cursor:
            raise ValueError("search cursor is invalid")
        return offset

    @staticmethod
    def _string(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _origin(self) -> str:
        return str(self._settings.base_url).rstrip("/")

    def _endpoint(self, path: str) -> str:
        if path not in {
            "/api/version",
            "/api/users/me",
            "/api/spaces",
            "/api/spaces/info",
            "/api/search",
            "/api/pages/info",
            "/api/pages/sidebar-pages",
            "/api/comments",
            "/api/files/info",
            "/api/files/upload",
            "/api/pages/import",
            "/api/pages/move",
            "/api/pages/update",
            "/api/comments/create",
        }:
            raise ValueError("Docmost endpoint is not allowlisted")
        return f"{self._origin()}{path}"

    def _attachment_endpoint(self, attachment_id: str, filename: str) -> str:
        identifier = self._identifier(attachment_id)
        if self._safe_filename(filename) != filename:
            raise ValueError("attachment filename is invalid")
        return (
            f"{self._origin()}/api/files/{quote(identifier, safe='')}/"
            f"{quote(filename, safe='')}"
        )

    def _cookie_headers(self) -> dict[str, str]:
        return {
            "Cookie": (f"{self._settings.session_cookie}={self._session_cookie.get_secret_value()}")
        }

    @staticmethod
    def _title(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > _MAX_TITLE_CHARS:
            raise ValueError(f"title must be between 1 and {_MAX_TITLE_CHARS} characters")
        if _TITLE_CONTROL_PATTERN.search(normalized):
            raise ValueError("title contains unsupported control characters")
        return normalized

    @staticmethod
    def _timestamp(value: str) -> str:
        if not value or len(value) > 128 or _TITLE_CONTROL_PATTERN.search(value):
            raise ValueError("expected_updated_at is invalid")
        return value

    @staticmethod
    def _content_sha256(value: str) -> str:
        if _CONTENT_SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("expected_content_sha256 is invalid")
        return value

    @staticmethod
    def _file_sha256(value: str) -> str:
        if _CONTENT_SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("expected_file_sha256 is invalid")
        return value

    @staticmethod
    def _page_markdown(value: str) -> str:
        if len(value) > _MAX_PAGE_MARKDOWN_CHARS:
            raise ValueError(f"page Markdown must be at most {_MAX_PAGE_MARKDOWN_CHARS} characters")
        if _MARKDOWN_CONTROL_PATTERN.search(value):
            raise ValueError("page Markdown contains unsupported control characters")
        return value.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _edit_text(value: str, *, allow_empty: bool) -> str:
        if (not allow_empty and not value) or len(value) > _MAX_PAGE_EDIT_TEXT_CHARS:
            minimum = 0 if allow_empty else 1
            raise ValueError(
                f"page edit text must be between {minimum} and "
                f"{_MAX_PAGE_EDIT_TEXT_CHARS} characters"
            )
        if _EDIT_TEXT_CONTROL_PATTERN.search(value):
            raise ValueError("page edit text contains unsupported control characters")
        return value

    @staticmethod
    def _import_markdown(title: str, markdown: str) -> str:
        escaped_title = re.sub(r"([\\*_[\]`<>])", r"\\\1", title)
        return f"# {escaped_title}\n\n{markdown}"

    @staticmethod
    def _partial_create(page: Page, cause: ErrorCode) -> CreatePageResult:
        placement_unknown = cause is ErrorCode.OUTCOME_UNKNOWN
        return CreatePageResult(
            page=page if placement_unknown else page.model_copy(update={"parent": None}),
            placement_status="unknown" if placement_unknown else "root",
            partial_success=True,
            warning=OperationError(
                code=ErrorCode.PARTIAL_SUCCESS,
                message=(
                    _PARTIAL_CREATE_UNKNOWN_MESSAGE
                    if placement_unknown
                    else _PARTIAL_CREATE_MESSAGE
                ),
                retryable=False,
                details={
                    "move_error": cause.value,
                    "placement_status": "unknown" if placement_unknown else "root",
                },
            ),
        )

    @staticmethod
    def _identifier(value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("identifier is invalid")
        return value

    @staticmethod
    def _cursor(value: str) -> str:
        if not _CURSOR_PATTERN.fullmatch(value):
            raise ValueError("cursor is invalid")
        return value

    @staticmethod
    def _page_limit(value: int) -> int:
        if value < 1 or value > _MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}")
        return value

    @staticmethod
    def _safe_filename(value: str) -> str:
        if (
            not value
            or len(value) > 512
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or _FILENAME_CONTROL_PATTERN.search(value)
        ):
            raise ValueError("attachment filename is invalid")
        return value

    @staticmethod
    def _normalized_media_type(value: str | None) -> str | None:
        if value is None:
            return None
        return value.split(";", 1)[0].strip().lower()

    @classmethod
    def _validated_attachment_metadata(
        cls, metadata: AttachmentInfo
    ) -> tuple[str, Literal["application/pdf", "text/plain"]]:
        try:
            filename = cls._safe_filename(metadata.file_name)
        except ValueError as error:
            raise _ClientFailure(
                ErrorCode.UNSUPPORTED_ATTACHMENT,
                "UNSUPPORTED_ATTACHMENT",
            ) from error
        extension = metadata.file_ext.lower()
        mime_type = cls._normalized_media_type(metadata.mime_type)
        if (
            filename.lower().endswith(".pdf")
            and extension == ".pdf"
            and mime_type == "application/pdf"
        ):
            return filename, "application/pdf"
        if filename.lower().endswith(".txt") and extension == ".txt" and mime_type == "text/plain":
            return filename, "text/plain"
        raise _ClientFailure(
            ErrorCode.UNSUPPORTED_ATTACHMENT,
            "UNSUPPORTED_ATTACHMENT",
        )

    @staticmethod
    def _unavailable(page_scope: bool, message: str, *, retryable: bool = False) -> _ClientFailure:
        if page_scope:
            return _ClientFailure(
                ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE, retryable=retryable
            )
        return _ClientFailure(ErrorCode.UPSTREAM_ERROR, message, retryable=retryable)

    @staticmethod
    def _invalid(error: ValueError) -> OperationResult[Any]:
        return OperationResult[Any].failure(ErrorCode.CONFIGURATION_INVALID, str(error))

    @staticmethod
    def _page_invalid(error: ValueError) -> OperationResult[Any]:
        del error
        return OperationResult[Any].failure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
