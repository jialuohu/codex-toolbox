"""Contract tests for guarded, non-retrying Docmost write operations."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from docmost_tools.client import DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode


def settings(*, writes: bool = True) -> DocmostSettings:
    values: dict[str, object] = {"base_url": "https://docs.example.test"}
    if writes:
        values["write_profile"] = "v0_95"
    return DocmostSettings.model_validate(values)


def envelope(data: object, *, status: int = 200) -> dict[str, object]:
    return {"data": data, "success": True, "status": status}


def client_for(
    handler: Callable[[httpx.Request], httpx.Response], *, writes: bool = True
) -> DocmostReadClient:
    return DocmostReadClient(
        settings(writes=writes),
        "session-secret",
        transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
        max_retries=3,
    )


def request_json(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)


@pytest.mark.parametrize(
    "operation_name",
    ["create_page", "update_page_title", "create_comment"],
)
def test_writes_require_an_explicit_v095_profile_without_a_request(
    operation_name: str,
) -> None:
    client = client_for(lambda _: pytest.fail("request must not be sent"), writes=False)
    if operation_name == "create_page":
        result = client.create_page("space-1", "Title", "Body")
    elif operation_name == "update_page_title":
        result = client.update_page_title("page-1", "Title", "2026-01-01T00:00:00Z")
    else:
        result = client.create_comment("page-1", "Comment")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.WRITE_COMPATIBILITY_BLOCKED
    assert result.error.retryable is False


def test_create_page_imports_markdown_once_and_returns_the_created_root() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "page-1",
                    "slugId": "page-slug",
                    "title": "A *literal* title",
                    "spaceId": "space-1",
                    "position": "a0V1b",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-01T00:00:00Z",
                }
            ),
        )

    result = client_for(handler).create_page("space-1", "A *literal* title", "Paragraph body")

    assert result.ok is True and result.data is not None
    assert result.data.page.id == "page-1"
    assert result.data.page.space_id == "space-1"
    assert result.data.page.parent is None
    assert result.data.placement_status == "root"
    assert result.data.partial_success is False
    assert result.data.warning is None
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/pages/import"
    assert request.headers["cookie"] == "authToken=session-secret"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="spaceId"' in request.content
    assert b"space-1" in request.content
    assert b'name="file"; filename="docmost-page.md"' in request.content
    assert b"# A \\*literal\\* title\n\nParagraph body" in request.content


def test_non_page_write_forbidden_is_stably_forbidden() -> None:
    result = client_for(lambda _: httpx.Response(403, json={"message": "forbidden"})).create_page(
        "space-1", "Title", "Body"
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.FORBIDDEN
    assert result.error.message == "FORBIDDEN"
    assert result.error.retryable is False


def test_create_page_validates_parent_then_moves_with_the_imported_position() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "parent-canonical",
                        "slugId": "parent-slug",
                        "spaceId": "space-1",
                    }
                ),
            )
        if request.url.path == "/api/pages/import":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "page-1",
                        "slugId": "page-slug",
                        "title": "Child",
                        "spaceId": "space-1",
                        "position": "a0V1b",
                    }
                ),
            )
        return httpx.Response(200, json=envelope(None))

    result = client_for(handler).create_page(
        "space-1", "Child", "Body", parent_page_id="parent-input"
    )

    assert result.ok is True and result.data is not None
    assert result.data.page.parent == "parent-canonical"
    assert result.data.placement_status == "nested"
    assert result.data.partial_success is False
    assert [request.url.path for request in seen] == [
        "/api/pages/info",
        "/api/pages/import",
        "/api/pages/move",
    ]
    assert request_json(seen[0]) == {"pageId": "parent-input"}
    assert request_json(seen[2]) == {
        "pageId": "page-1",
        "position": "a0V1b",
        "parentPageId": "parent-canonical",
    }


def test_create_page_rejects_a_parent_from_another_space_before_import() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json=envelope({"id": "parent", "slugId": "parent-slug", "spaceId": "other"}),
        )

    result = client_for(handler).create_page("space-1", "Child", "Body", parent_page_id="parent")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.PAGE_UNAVAILABLE
    assert requests == 1


def test_create_page_preserves_root_and_warns_when_parent_move_fails_without_retry() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope({"id": "parent", "slugId": "parent-slug", "spaceId": "space-1"}),
            )
        if request.url.path == "/api/pages/import":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "created-root",
                        "slugId": "created-slug",
                        "spaceId": "space-1",
                        "position": "a0V1b",
                    }
                ),
            )
        return httpx.Response(503, json={"message": "move failed"})

    result = client_for(handler).create_page("space-1", "Child", "Body", parent_page_id="parent")

    assert result.ok is True and result.data is not None
    assert result.data.page.id == "created-root"
    assert result.data.page.parent is None
    assert result.data.placement_status == "unknown"
    assert result.data.partial_success is True
    assert result.data.warning is not None
    assert result.data.warning.code is ErrorCode.PARTIAL_SUCCESS
    assert result.data.warning.retryable is False
    assert result.data.warning.details == {
        "move_error": "outcome_unknown",
        "placement_status": "unknown",
    }
    assert "nesting outcome is unknown" in result.data.warning.message
    assert "read the returned page" in result.data.warning.message
    assert paths == ["/api/pages/info", "/api/pages/import", "/api/pages/move"]


def test_create_page_import_timeout_is_outcome_unknown_and_never_retried() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("ambiguous")

    result = client_for(handler).create_page("space-1", "Title", "Body")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.error.retryable is False
    assert "search or read" in result.error.message
    assert attempts == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(408, json={"message": "request timed out after dispatch"}),
        httpx.Response(503, json={"message": "proxy failed after dispatch"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": {}, "success": False, "status": 200}),
    ],
)
def test_create_page_ambiguous_write_response_requires_readback_without_retry(
    response: httpx.Response,
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response

    result = client_for(handler).create_page("space-1", "Title", "Body")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.error.retryable is False
    assert "search or read" in result.error.message
    assert attempts == 1


def test_create_page_success_envelope_with_invalid_page_is_outcome_unknown() -> None:
    result = client_for(lambda _: httpx.Response(200, json=envelope({}))).create_page(
        "space-1", "Title", "Body"
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.error.retryable is False
    assert "search or read" in result.error.message


def test_update_page_title_checks_expected_timestamp_then_posts_once() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "page-canonical",
                        "slugId": "old-slug",
                        "title": "Old",
                        "spaceId": "space-1",
                        "updatedAt": "2026-01-02T03:04:05Z",
                    }
                ),
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "page-canonical",
                    "slugId": "old-slug",
                    "title": "New",
                    "spaceId": "space-1",
                    "updatedAt": "2026-01-02T03:04:06Z",
                }
            ),
        )

    result = client_for(handler).update_page_title("page-input", "New", "2026-01-02T03:04:05Z")

    assert result.ok is True and result.data is not None
    assert result.data.id == "page-canonical"
    assert result.data.title == "New"
    assert [request.url.path for request in seen] == ["/api/pages/info", "/api/pages/update"]
    assert request_json(seen[0]) == {"pageId": "page-input"}
    assert request_json(seen[1]) == {"pageId": "page-canonical", "title": "New"}


def test_update_page_title_conflict_stops_before_the_write() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "page-1",
                    "slugId": "page-slug",
                    "updatedAt": "newer",
                }
            ),
        )

    result = client_for(handler).update_page_title("page-1", "New", "older")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.CONFLICT
    assert result.error.retryable is False
    assert paths == ["/api/pages/info"]


def test_update_page_title_timeout_is_outcome_unknown_without_retry() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "page-1",
                        "slugId": "page-slug",
                        "updatedAt": "same",
                    }
                ),
            )
        raise httpx.WriteTimeout("ambiguous")

    result = client_for(handler).update_page_title("page-1", "New", "same")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert paths == ["/api/pages/info", "/api/pages/update"]


def test_update_page_title_success_envelope_with_invalid_page_is_outcome_unknown() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "page-1",
                        "slugId": "page-slug",
                        "updatedAt": "same",
                    }
                ),
            )
        return httpx.Response(200, json=envelope({}))

    result = client_for(handler).update_page_title("page-1", "New", "same")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.error.retryable is False
    assert "search or read" in result.error.message
    assert paths == ["/api/pages/info", "/api/pages/update"]


def test_create_comment_canonicalizes_page_and_sends_json_encoded_tiptap_once() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "id": "page-canonical",
                        "slugId": "page-slug",
                    }
                ),
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "comment-1",
                    "pageId": "page-canonical",
                    "content": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "A note"}],
                            }
                        ],
                    },
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ),
        )

    result = client_for(handler).create_comment("page-input", "A **note**")

    assert result.ok is True and result.data is not None
    assert result.data.id == "comment-1"
    assert [request.url.path for request in seen] == [
        "/api/pages/info",
        "/api/comments/create",
    ]
    assert request_json(seen[0]) == {"pageId": "page-input"}
    payload = request_json(seen[1])
    assert payload["pageId"] == "page-canonical"
    assert payload["type"] == "page"
    assert json.loads(str(payload["content"])) == {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "A "},
                    {"type": "text", "text": "note", "marks": [{"type": "bold"}]},
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "markdown",
    ["<b>raw</b>", "![image](https://example.test/x.png)", "[x](javascript:alert(1))"],
)
def test_create_comment_rejects_unsafe_markdown_before_any_request(markdown: str) -> None:
    result = client_for(lambda _: pytest.fail("request must not be sent")).create_comment(
        "page-1", markdown
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.INVALID_MARKDOWN


def test_create_comment_rejects_ordered_list_marker_over_nine_digits_before_any_request() -> None:
    result = client_for(lambda _: pytest.fail("request must not be sent")).create_comment(
        "page-1", "1234567890. oversized marker"
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.INVALID_MARKDOWN


def test_create_comment_timeout_is_outcome_unknown_and_not_retried() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope({"id": "page-1", "slugId": "page-slug", "content": "Body"}),
            )
        raise httpx.ReadTimeout("ambiguous")

    result = client_for(handler).create_comment("page-1", "Note")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert paths == ["/api/pages/info", "/api/comments/create"]


def test_create_comment_success_envelope_with_invalid_comment_is_outcome_unknown() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope({"id": "page-1", "slugId": "page-slug", "content": "Body"}),
            )
        return httpx.Response(200, json=envelope({}))

    result = client_for(handler).create_comment("page-1", "Note")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.error.retryable is False
    assert "search or read" in result.error.message
    assert paths == ["/api/pages/info", "/api/comments/create"]
