"""Contract tests for the guarded read-only Docmost HTTP client."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from docmost_tools import DocmostReadClient as ExportedReadClient
from docmost_tools.client import AUTH_REQUIRED_MESSAGE, DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode

EXPECTED_AUTH_REQUIRED_MESSAGE = (
    "Authentication required. Close the active task, run "
    "`CODEX_TOOLBOX_ROOT=\"${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}\" "
    "\"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh\" --login`, then start a "
    "fresh task or reconnect Docmost."
)


def settings(**values: object) -> DocmostSettings:
    return DocmostSettings.model_validate({"base_url": "https://docs.example.test", **values})


def envelope(data: object, *, status: int = 200) -> dict[str, object]:
    return {"data": data, "success": True, "status": status}


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    settings_value: DocmostSettings | None = None,
    sleeper: Callable[[float], None] | None = None,
    retries: int = 2,
) -> DocmostReadClient:
    return DocmostReadClient(
        settings_value or settings(),
        "session-secret",
        transport=httpx.MockTransport(handler),
        sleeper=(lambda _: None) if sleeper is None else sleeper,
        max_retries=retries,
    )


def request_json(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)


def test_current_user_posts_fixed_endpoint_envelope_and_models() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=envelope(
                {
                    "user": {"id": "u1", "name": "Ada", "email": "ada@example.test"},
                    "workspace": {"id": "w1", "name": "Research", "slug": "research"},
                }
            ),
        )

    result = client_for(handler).current_user()

    assert result.ok is True
    assert result.data is not None
    assert result.data.user.id == "u1"
    assert result.data.workspace.slug == "research"
    assert [(item.method, item.url.path, request_json(item)) for item in seen] == [
        ("POST", "/api/users/me", {})
    ]
    assert seen[0].headers["cookie"] == "authToken=session-secret"


def test_read_client_is_exported_at_the_package_boundary() -> None:
    assert ExportedReadClient is DocmostReadClient


def test_version_is_cached_and_v095_selects_pinned_read_profile() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/version"
        return httpx.Response(200, json=envelope({"currentVersion": "0.95.2"}))

    client = client_for(handler)

    first = client.version()
    second = client.version()

    assert first.ok is True and first.data is not None
    assert first.data.current_version == "0.95.2"
    assert second.ok is True
    assert client.read_profile == "v0_95"
    assert client.writes_permitted is False
    assert calls == 1


def test_unknown_or_unavailable_version_keeps_schema_validated_reads_generic() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(
            200,
            json=envelope({"user": {"id": "u1"}, "workspace": {"id": "w1"}}),
        )

    client = client_for(handler, retries=0)
    version = client.version()
    user = client.current_user()

    assert version.ok is False
    assert user.ok is True
    assert client.read_profile == "generic"
    assert paths == ["/api/version", "/api/users/me"]


def test_space_and_search_requests_apply_contract_caps_and_pagination() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/spaces":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "items": [{"id": "s1", "name": "Research", "slug": "research"}],
                        "meta": {"nextCursor": "next-space"},
                    }
                ),
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "items": [
                        {"id": f"p{index}", "title": "Result", "slugId": f"result-{index}"}
                        for index in range(50)
                    ]
                }
            ),
        )

    client = client_for(handler)
    spaces = client.list_spaces(limit=100, cursor="cursor-safe_1")
    search = client.search("flow matching", space_id="s1", limit=50)

    assert spaces.ok is True and spaces.data is not None
    assert spaces.data.next_cursor == "next-space"
    assert search.ok is True and search.data is not None
    assert search.data.next_cursor is not None
    assert search.data.next_cursor != "50"
    assert [(item.url.path, request_json(item)) for item in seen] == [
        ("/api/spaces", {"limit": 100, "cursor": "cursor-safe_1"}),
        ("/api/search", {"query": "flow matching", "spaceId": "s1", "limit": 50, "offset": 0}),
    ]


@pytest.mark.parametrize("operation", ["spaces", "search", "pages", "comments"])
def test_paginated_reads_reject_an_upstream_response_over_the_requested_limit(
    operation: str,
) -> None:
    item = (
        {"id": "space-1"}
        if operation == "spaces"
        else {"id": "item-1", "slugId": "item-slug"}
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=envelope({"items": [item, item], "meta": {"nextCursor": "next"}}),
        )

    client = client_for(handler)
    if operation == "spaces":
        result = client.list_spaces(limit=1)
    elif operation == "search":
        result = client.search("query", limit=1)
    elif operation == "pages":
        result = client.list_pages("space-1", limit=1)
    else:
        result = client.list_comments("page-1", limit=1)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code in {ErrorCode.UPSTREAM_ERROR, ErrorCode.PAGE_UNAVAILABLE}


def test_search_uses_an_opaque_round_trippable_cursor_and_default_limit() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request_json(request))
        if len(seen) == 1:
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "items": [
                            {"id": f"p{index}", "title": "Result", "slugId": f"result-{index}"}
                            for index in range(20)
                        ]
                    }
                ),
            )
        return httpx.Response(200, json=envelope({"items": []}))

    client = client_for(handler)
    first = client.search("query")

    assert first.ok is True and first.data is not None and first.data.next_cursor is not None
    assert "offset" not in inspect.signature(client.search).parameters
    second = client.search("query", cursor=first.data.next_cursor)

    assert second.ok is True
    assert seen == [
        {"query": "query", "limit": 20, "offset": 0},
        {"query": "query", "limit": 20, "offset": 20},
    ]


@pytest.mark.parametrize("cursor", ["20", "other.v1", "docmost-search.v1.invalid***"])
def test_search_rejects_malformed_or_foreign_cursors_without_a_request(cursor: str) -> None:
    result = client_for(lambda _: pytest.fail("request must not be sent")).search(
        "query", cursor=cursor
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.CONFIGURATION_INVALID


def test_read_pagination_defaults_to_fifty_except_search() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request_json(request)
        seen.append((request.url.path, body))
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope({"id": "canonical"}))
        return httpx.Response(200, json=envelope({"items": [], "meta": {}}))

    client = client_for(handler)
    assert client.list_spaces().ok is True
    assert client.list_pages("s1").ok is True
    assert client.list_child_pages("parent").ok is True
    assert client.list_comments("page-uuid").ok is True

    assert seen == [
        ("/api/spaces", {"limit": 50}),
        ("/api/pages/sidebar-pages", {"spaceId": "s1", "limit": 50}),
        ("/api/pages/info", {"pageId": "parent", "format": "markdown"}),
        ("/api/pages/sidebar-pages", {"pageId": "canonical", "limit": 50}),
        ("/api/comments", {"pageId": "page-uuid", "limit": 50}),
    ]


@pytest.mark.parametrize(
    ("title", "slug_id", "expected_page_segment"),
    [
        ("Introduction", "intro-id", "introduction-intro-id"),
        ("", "empty-id", "untitled-empty-id"),
        ("My Page ♥ 🦄", "symbols-id", "my-page-symbols-id"),
        ("Café à la carte", "accent-id", "cafe-a-la-carte-accent-id"),
        ("A / B?!", "slash/id", "a-b-slash%2Fid"),
        ("Ångström", "angstrom-id", "angstrom-angstrom-id"),
    ],
)
def test_v095_page_urls_use_slug_id_and_documented_title_slug_approximation(
    title: str, slug_id: str, expected_page_segment: str
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "p1",
                    "title": title,
                    "slugId": slug_id,
                    "slug": "unsafe-legacy-slug",
                    "space": {"id": "s1", "slug": "research"},
                    "url": "https://attacker.example/ignored",
                    "content": "# body",
                }
            ),
        )

    result = client_for(handler).get_page("p1")

    assert result.ok is True and result.data is not None
    assert result.data.slug_id == slug_id
    assert result.data.url == f"https://docs.example.test/s/research/p/{expected_page_segment}"


@pytest.mark.parametrize("cursor", ["", "contains space", "../../escape", "x\nheader"])
def test_cursor_rejects_unsafe_values_without_a_request(cursor: str) -> None:
    client = client_for(lambda _: pytest.fail("request must not be sent"))

    result = client.list_spaces(cursor=cursor)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.CONFIGURATION_INVALID


def test_get_space_and_page_use_fixed_post_contract_and_browser_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/spaces/info":
            return httpx.Response(
                200, json=envelope({"id": "s1", "name": "Research", "slug": "research"})
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "id": "p-uuid",
                    "slugId": "intro-id",
                    "title": "Introduction",
                    "space": {"id": "s1", "name": "Research", "slug": "research"},
                    "content": "# hello",
                    "parentPageId": None,
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                }
            ),
        )

    client = client_for(handler)
    space = client.get_space("s1")
    page = client.get_page("intro")

    assert space.ok is True and space.data is not None and space.data.id == "s1"
    assert page.ok is True and page.data is not None
    assert page.data.id == "p-uuid"
    assert page.data.slug_id == "intro-id"
    assert page.data.url == "https://docs.example.test/s/research/p/introduction-intro-id"
    assert page.data.markdown == "# hello"
    assert [(item.url.path, request_json(item)) for item in seen] == [
        ("/api/spaces/info", {"spaceId": "s1"}),
        ("/api/pages/info", {"pageId": "intro", "format": "markdown"}),
    ]


def test_page_chunking_returns_a_bounded_markdown_window() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=envelope(
                {"id": "p1", "slugId": "intro-id", "title": "Intro", "content": "abcdef"}
            ),
        )

    result = client_for(handler).get_page("p1", offset=2, max_chars=3)

    assert result.ok is True and result.data is not None
    assert result.data.markdown == "cde"
    assert result.data.truncated is True
    assert result.data.next_offset == 5


def test_list_pages_is_root_only_and_children_canonicalize_through_page_info() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope({"id": "canonical-page", "slugId": "intro-id"}),
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "items": [{"id": "child", "title": "Child", "slugId": "child-id"}],
                    "meta": {},
                }
            ),
        )

    client = client_for(handler)
    roots = client.list_pages("s1", limit=20)
    children = client.list_child_pages("intro", cursor="next")

    assert roots.ok is True and roots.data is not None and roots.data.root_only is True
    assert children.ok is True and children.data is not None
    assert [(item.url.path, request_json(item)) for item in seen] == [
        ("/api/pages/sidebar-pages", {"spaceId": "s1", "limit": 20}),
        ("/api/pages/info", {"pageId": "intro", "format": "markdown"}),
        ("/api/pages/sidebar-pages", {"pageId": "canonical-page", "cursor": "next", "limit": 50}),
    ]


def test_list_comments_preserves_jsonb_prosemirror_content_and_timestamps() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=envelope(
                {
                    "items": [
                        {
                            "id": "c1",
                            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
                            "createdAt": "2026-01-01T00:00:00Z",
                            "updatedAt": "2026-01-02T00:00:00Z",
                            "editedAt": "2026-01-03T00:00:00Z",
                        },
                        {"id": "c2", "content": [{"type": "paragraph"}]},
                        {"id": "c3", "content": "legacy plain text"},
                    ],
                    "meta": {"nextCursor": "n"},
                }
            ),
        )

    result = client_for(handler).list_comments("p1", cursor="c", limit=7)

    assert result.ok is True and result.data is not None
    assert result.data.items[0].content == {"type": "doc", "content": [{"type": "paragraph"}]}
    assert result.data.items[0].created_at == "2026-01-01T00:00:00Z"
    assert result.data.items[0].updated_at == "2026-01-02T00:00:00Z"
    assert result.data.items[0].edited_at == "2026-01-03T00:00:00Z"
    assert result.data.items[1].content == [{"type": "paragraph"}]
    assert result.data.items[2].content == "legacy plain text"
    assert result.data.next_cursor == "n"
    assert request_json(seen[0]) == {"pageId": "p1", "cursor": "c", "limit": 7}


def test_transient_read_is_retried_without_exposing_request_secret() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=envelope({"user": {"id": "u1"}, "workspace": {"id": "w1"}}))

    client = client_for(handler, sleeper=delays.append)
    result = client.current_user()

    assert result.ok is True
    assert attempts == 2
    assert delays == [0.25]
    assert "session-secret" not in repr(client)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_not_retried_and_use_exact_recovery_message(status: int) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, json={"message": "no"})

    result = client_for(handler).current_user()

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert result.error.message == EXPECTED_AUTH_REQUIRED_MESSAGE
    assert attempts == 1


def test_page_errors_and_redirects_are_uniformly_unavailable_and_not_retried() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(302, headers={"Location": "https://elsewhere.example/"})

    result = client_for(handler).get_page("missing")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.PAGE_UNAVAILABLE
    assert result.error.message == "PAGE_UNAVAILABLE"
    assert attempts == 1


def test_page_scoped_forbidden_responses_are_uniformly_unavailable() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(403, json={"message": "forbidden"})

    client = client_for(handler)
    results = (
        client.get_page("page"),
        client.list_child_pages("page"),
        client.list_comments("page"),
    )

    for result in results:
        assert result.ok is False
        assert result.error is not None
        assert result.error.code is ErrorCode.PAGE_UNAVAILABLE
        assert result.error.message == "PAGE_UNAVAILABLE"
    assert seen == ["/api/pages/info", "/api/pages/info", "/api/comments"]


def test_non_page_forbidden_response_remains_auth_required() -> None:
    result = client_for(lambda _: httpx.Response(403, json={"message": "forbidden"})).current_user()

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED


def test_page_scoped_unauthorized_response_remains_auth_required() -> None:
    result = client_for(lambda _: httpx.Response(401, json={"message": "expired"})).get_page("page")

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert result.error.message == AUTH_REQUIRED_MESSAGE


def test_page_lists_normalize_camel_case_fields_and_ignore_upstream_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope({"id": "canonical", "slugId": "parent-id"}),
            )
        return httpx.Response(
            200,
            json=envelope(
                {
                    "items": [
                        {
                            "id": "p1",
                            "title": "Nested",
                            "slugId": "opaque/id",
                            "spaceId": "s1",
                            "parentPageId": "parent",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "updatedAt": "2026-01-02T00:00:00Z",
                            "space": {"id": "s1", "name": "Research", "slug": "my space"},
                            "url": "https://attacker.example/not-a-docmost-page",
                        }
                    ],
                    "meta": {},
                }
            ),
        )

    client = client_for(handler)
    roots = client.list_pages("s1")
    search = client.search("nested", limit=1)
    children = client.list_child_pages("parent")

    for result in (roots, search, children):
        assert result.ok is True and result.data is not None
        page = result.data.items[0]
        assert page.space_id == "s1"
        assert page.space_name == "Research"
        assert page.space_slug == "my space"
        assert page.parent == "parent"
        assert page.created_at == "2026-01-01T00:00:00Z"
        assert page.updated_at == "2026-01-02T00:00:00Z"
        assert page.slug_id == "opaque/id"
        assert page.url == "https://docs.example.test/s/my%20space/p/nested-opaque%2Fid"


def test_page_info_without_content_is_unavailable_but_explicit_empty_markdown_is_valid() -> None:
    responses = [
        httpx.Response(200, json=envelope({"id": "missing", "slugId": "missing-id"})),
        httpx.Response(200, json=envelope({"id": "empty", "slugId": "empty-id", "content": ""})),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = client_for(handler)
    missing = client.get_page("missing")
    empty = client.get_page("empty")

    assert missing.ok is False and missing.error is not None
    assert missing.error.code is ErrorCode.PAGE_UNAVAILABLE
    assert empty.ok is True and empty.data is not None
    assert empty.data.markdown == ""


def test_ca_bundle_is_used_without_tls_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    original = httpx.Client

    def recording_client(**kwargs: Any) -> httpx.Client:
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr("docmost_tools.client.httpx.Client", recording_client)
    client = DocmostReadClient(
        settings(ca_bundle="/private/tmp/internal-ca.pem"),
        "session-secret",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json=envelope({"user": {"id": "u1"}, "workspace": {"id": "w1"}})
            )
        ),
    )

    result = client.current_user()

    assert result.ok is True
    assert captured["verify"] == "/private/tmp/internal-ca.pem"
    assert captured["follow_redirects"] is False
    assert captured["trust_env"] is False
