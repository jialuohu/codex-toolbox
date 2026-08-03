"""Guarded HTTP compatibility client for Docmost browser sessions."""

from __future__ import annotations

import base64
import json
import re
import time
import unicodedata
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from docmost_tools.comment_markdown import MarkdownValidationError, markdown_to_tiptap
from docmost_tools.config import DocmostSettings, WriteProfile
from docmost_tools.models import (
    Comment,
    CreatePageResult,
    CurrentUser,
    CursorPage,
    ErrorCode,
    OperationError,
    OperationResult,
    Page,
    PageList,
    SearchResults,
    Space,
    VersionInfo,
)

AUTH_REQUIRED_MESSAGE = "docmost-auth login"
PAGE_UNAVAILABLE_MESSAGE = "PAGE_UNAVAILABLE"
WRITE_COMPATIBILITY_BLOCKED_MESSAGE = "WRITE_COMPATIBILITY_BLOCKED"
_MAX_PAGE_SIZE = 100
_MAX_SEARCH_SIZE = 50
_DEFAULT_PAGE_SIZE = 50
_DEFAULT_SEARCH_SIZE = 20
_MAX_PAGE_CHARS = 100_000
_CURSOR_PATTERN = re.compile(r"[A-Za-z0-9._~=-]{1,1024}\Z")
_IDENTIFIER_PATTERN = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_SEARCH_CURSOR_PREFIX = "docmost-search.v1."
_SEARCH_CURSOR_PAYLOAD = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TITLE_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_MARKDOWN_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TITLE_CHARS = 250
_MAX_PAGE_MARKDOWN_CHARS = 1_000_000
_MAX_COMMENT_MARKDOWN_CHARS = 20_000
_OUTCOME_UNKNOWN_MESSAGE = (
    "OUTCOME_UNKNOWN: search or read Docmost before retrying this write."
)
_PARTIAL_CREATE_MESSAGE = (
    "Page was created at the space root, but nesting failed. "
    "Do not retry create_page; read the returned page before any manual move."
)
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
            body: dict[str, object] = {"limit": self._page_limit(limit)}
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._invalid(error)
        return self._run(lambda: self._cursor_page(self._post("/api/spaces", body), Space))

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
        body: dict[str, object] = {"query": query, "limit": limit, "offset": offset}
        if space_id is not None:
            try:
                body["spaceId"] = self._identifier(space_id)
            except ValueError as error:
                return self._invalid(error)

        def operation() -> SearchResults:
            result = self._cursor_page(self._post("/api/search", body), Page)
            next_cursor = (
                self._encode_search_cursor(offset + limit) if len(result.items) == limit else None
            )
            return SearchResults(items=result.items, next_cursor=next_cursor)

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

    def list_pages(
        self, space_id: str, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[PageList]:
        """List only root-level pages in a space (not all descendants)."""

        try:
            body: dict[str, object] = {
                "spaceId": self._identifier(space_id),
                "limit": self._page_limit(limit),
            }
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._invalid(error)
        return self._run(
            lambda: PageList(
                **self._cursor_page(
                    self._post("/api/pages/sidebar-pages", body), Page
                ).model_dump(),
                root_only=True,
            )
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
                self._post(
                    "/api/pages/info", {"pageId": identifier, "format": "markdown"}, page_scope=True
                )
            )
            body: dict[str, object] = {"pageId": canonical_id, "limit": validated_limit}
            if validated_cursor is not None:
                body["cursor"] = validated_cursor
            parsed = self._cursor_page(
                self._post("/api/pages/sidebar-pages", body, page_scope=True), Page
            )
            return PageList(**parsed.model_dump(), root_only=False)

        return self._run(operation, page_scope=True)

    def list_comments(
        self, page_id: str, *, limit: int = _DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> OperationResult[CursorPage[Comment]]:
        """List comments for a page through the fixed cursor-paginated endpoint."""

        try:
            body: dict[str, object] = {
                "pageId": self._identifier(page_id),
                "limit": self._page_limit(limit),
            }
            if cursor is not None:
                body["cursor"] = self._cursor(cursor)
        except ValueError as error:
            return self._page_invalid(error)
        return self._run(
            lambda: self._cursor_page(self._post("/api/comments", body, page_scope=True), Comment),
            page_scope=True,
        )

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
                    {"pageId": validated_parent, "format": "markdown"},
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
            created = self._parse_write_result(
                lambda: self._page_summary_from_data(imported)
            )
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
                page=created.model_copy(update={"parent": canonical_parent})
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
            current = self._page_from_data(
                self._post(
                    "/api/pages/info",
                    {"pageId": validated_page_id, "format": "markdown"},
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
            return self._parse_write_result(
                lambda: self._page_summary_from_data(updated)
            )

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
                    {"pageId": validated_page_id, "format": "markdown"},
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

    def _validate_response(
        self, response: httpx.Response, *, page_scope: bool
    ) -> dict[str, object]:
        if response.status_code == 401:
            raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
        if response.status_code == 403:
            if page_scope:
                raise _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
            raise _ClientFailure(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
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
            raise _ClientFailure(ErrorCode.UPSTREAM_ERROR, "Docmost write was forbidden")
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
            raise _ClientFailure(
                ErrorCode.OUTCOME_UNKNOWN, _OUTCOME_UNKNOWN_MESSAGE
            ) from error
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
        self, data: dict[str, object], item_type: type[ModelItem]
    ) -> CursorPage[ModelItem]:
        raw_items: object = data["items"] if "items" in data else None
        raw_meta: object = data["meta"] if "meta" in data else {}
        if not isinstance(raw_items, list) or not isinstance(raw_meta, dict):
            raise ValueError("cursor response must contain items and meta")
        items = cast(list[object], raw_items)
        meta = cast(dict[str, object], raw_meta)
        next_cursor = meta.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("nextCursor must be a string")
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
        if not isinstance(content, str):
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
            "/api/pages/import",
            "/api/pages/move",
            "/api/pages/update",
            "/api/comments/create",
        }:
            raise ValueError("Docmost endpoint is not allowlisted")
        return f"{self._origin()}{path}"

    def _cookie_headers(self) -> dict[str, str]:
        return {
            "Cookie": (
                f"{self._settings.session_cookie}="
                f"{self._session_cookie.get_secret_value()}"
            )
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
    def _page_markdown(value: str) -> str:
        if len(value) > _MAX_PAGE_MARKDOWN_CHARS:
            raise ValueError(
                f"page Markdown must be at most {_MAX_PAGE_MARKDOWN_CHARS} characters"
            )
        if _MARKDOWN_CONTROL_PATTERN.search(value):
            raise ValueError("page Markdown contains unsupported control characters")
        return value.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _import_markdown(title: str, markdown: str) -> str:
        escaped_title = re.sub(r"([\\*_[\]`<>])", r"\\\1", title)
        return f"# {escaped_title}\n\n{markdown}"

    @staticmethod
    def _partial_create(page: Page, cause: ErrorCode) -> CreatePageResult:
        return CreatePageResult(
            page=page.model_copy(update={"parent": None}),
            partial_success=True,
            warning=OperationError(
                code=ErrorCode.PARTIAL_SUCCESS,
                message=_PARTIAL_CREATE_MESSAGE,
                retryable=False,
                details={"move_error": cause.value},
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
    def _unavailable(page_scope: bool, message: str, *, retryable: bool = False) -> _ClientFailure:
        if page_scope:
            return _ClientFailure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
        return _ClientFailure(ErrorCode.UPSTREAM_ERROR, message, retryable=retryable)

    @staticmethod
    def _invalid(error: ValueError) -> OperationResult[Any]:
        return OperationResult[Any].failure(ErrorCode.CONFIGURATION_INVALID, str(error))

    @staticmethod
    def _page_invalid(error: ValueError) -> OperationResult[Any]:
        del error
        return OperationResult[Any].failure(ErrorCode.PAGE_UNAVAILABLE, PAGE_UNAVAILABLE_MESSAGE)
