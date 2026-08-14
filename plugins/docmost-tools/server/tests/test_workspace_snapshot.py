"""Read-only, complete workspace snapshot contract tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest

from docmost_tools.client import DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import (
    CurrentUser,
    CursorPage,
    ErrorCode,
    OperationResult,
    Page,
    PageList,
    Space,
    User,
    Workspace,
)
from docmost_tools.workspace_snapshot import (
    WorkspaceReadProtocol,
    WorkspaceSnapshotBuilder,
    WorkspaceSnapshotStore,
)


class FakeWorkspaceReader:
    """Small crawler fixture deliberately exposing no write methods."""

    def __init__(self, body: str = "body") -> None:
        self.body = body
        self.spaces = [Space(id="space-1", name="Research", slug="research")]
        self.roots = [Page(id="page-1", title="Root", parent=None, space_id="space-1")]
        self.children: dict[str, list[Page]] = {
            "page-1": [
                Page(id="page-2", title="Child", parent="page-1", space_id="space-1")
            ],
            "page-2": [],
        }
        self.page_calls: dict[str, int] = {}

    def current_user(self) -> OperationResult[CurrentUser]:
        return OperationResult[CurrentUser].success(
            CurrentUser(
                user=User(id="user-1"),
                workspace=Workspace(id="workspace-1", name="Lab", slug="lab"),
            )
        )

    def list_spaces(
        self, *, limit: int, cursor: str | None = None
    ) -> OperationResult[CursorPage[Space]]:
        del limit
        if cursor is None and len(self.spaces) > 1:
            page = CursorPage[Space](items=self.spaces[:1], next_cursor="spaces-2")
        else:
            page = CursorPage[Space](items=self.spaces[1:] if cursor else self.spaces)
        return OperationResult[CursorPage[Space]].success(page)

    def list_pages(
        self, space_id: str, *, limit: int, cursor: str | None = None
    ) -> OperationResult[PageList]:
        del limit, cursor
        items = self.roots if space_id == "space-1" else []
        return OperationResult[PageList].success(PageList(items=items, root_only=True))

    def list_child_pages(
        self, page_id: str, *, limit: int, cursor: str | None = None
    ) -> OperationResult[PageList]:
        del limit, cursor
        return OperationResult[PageList].success(
            PageList(items=self.children.get(page_id, []), root_only=False)
        )

    def get_page(
        self, page_id: str, *, offset: int, max_chars: int
    ) -> OperationResult[Page]:
        self.page_calls[page_id] = self.page_calls.get(page_id, 0) + 1
        body = self.body if page_id == "page-1" else "child body"
        window = body[offset : offset + max_chars]
        next_offset = offset + len(window) if offset + len(window) < len(body) else None
        parent = None if page_id == "page-1" else "page-1"
        return OperationResult[Page].success(
            Page(
                id=page_id,
                title="Root" if page_id == "page-1" else "Child",
                slugId=f"{page_id}-slug",
                space_id="space-1",
                space_name="Research",
                space_slug="research",
                parent=parent,
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-02T00:00:00Z",
                url=f"https://docs.example.test/p/{page_id}",
                markdown=window,
                truncated=next_offset is not None,
                next_offset=next_offset,
            )
        )


def test_snapshot_streams_paginated_spaces_long_pages_and_releases(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    reader = FakeWorkspaceReader("x" * 120_123)
    reader.spaces.append(Space(id="space-2", name="Empty", slug="empty"))
    store = WorkspaceSnapshotStore(tmp_path)
    builder = WorkspaceSnapshotBuilder(reader, store)

    result = builder.prepare(
        all_spaces=True,
        space_ids=None,
        max_pages=10,
        max_page_chars=200_000,
    )

    assert result.ok is True and result.data is not None
    receipt = result.data
    assert receipt.workspace_id == "workspace-1"
    assert receipt.space_count == 2
    assert receipt.page_count == 2
    assert receipt.markdown_chars == 120_123 + len("child body")
    assert "markdown" not in receipt.model_dump(mode="json")
    path = Path(receipt.local_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["record_type"] for record in records] == [
        "header",
        "space",
        "page",
        "page",
        "space",
        "manifest",
    ]
    assert records[2]["page"]["markdown"] == "x" * 120_123
    assert records[-1]["complete"] is True
    assert reader.page_calls == {"page-1": 3, "page-2": 2}
    first_release = builder.release(receipt.snapshot_token)
    second_release = builder.release(receipt.snapshot_token)
    assert first_release.ok and first_release.data is not None and first_release.data.released
    assert second_release.ok and second_release.data is not None
    assert second_release.data.released is False
    assert not path.exists()
    store.close()


def test_snapshot_rejects_cycles_and_removes_partial_file(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    reader = FakeWorkspaceReader()
    reader.children["page-1"] = [
        Page(id="page-1", title="Cycle", parent="page-1", space_id="space-1")
    ]
    store = WorkspaceSnapshotStore(tmp_path)

    result = WorkspaceSnapshotBuilder(reader, store).prepare(
        all_spaces=True,
        space_ids=None,
        max_pages=10,
        max_page_chars=10_000,
    )

    assert result.ok is False and result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.SNAPSHOT_INCOMPLETE
    assert list(tmp_path.rglob("workspace.jsonl")) == []
    store.close()


def test_snapshot_normalizes_a_missing_page_title(tmp_path: Path) -> None:
    class UntitledReader(FakeWorkspaceReader):
        def get_page(
            self, page_id: str, *, offset: int, max_chars: int
        ) -> OperationResult[Page]:
            result = super().get_page(page_id, offset=offset, max_chars=max_chars)
            assert result.data is not None
            return OperationResult[Page].success(result.data.model_copy(update={"title": None}))

    tmp_path.chmod(0o700)
    reader = UntitledReader()
    reader.roots = [
        Page(id="page-1", title=None, parent=None, space_id="space-1")
    ]
    reader.children = {"page-1": []}
    store = WorkspaceSnapshotStore(tmp_path)
    result = WorkspaceSnapshotBuilder(reader, store).prepare(
        all_spaces=True,
        space_ids=None,
        max_pages=10,
        max_page_chars=10_000,
    )

    assert result.ok is True and result.data is not None
    records = [json.loads(line) for line in Path(result.data.local_path).read_text().splitlines()]
    page_record = next(record for record in records if record["record_type"] == "page")
    assert page_record["page"]["title"] == "Untitled"
    assert WorkspaceSnapshotBuilder(reader, store).release(result.data.snapshot_token).ok
    store.close()


class RacingReader(FakeWorkspaceReader):
    def __init__(self, *, settles: bool) -> None:
        super().__init__("body")
        self.children = {"page-1": []}
        self.settles = settles

    def get_page(
        self, page_id: str, *, offset: int, max_chars: int
    ) -> OperationResult[Page]:
        result = super().get_page(page_id, offset=offset, max_chars=max_chars)
        assert result.data is not None
        call = self.page_calls[page_id]
        if self.settles:
            revision = "v1" if call == 1 else "v2"
        else:
            revision = f"v{call}"
        return OperationResult[Page].success(
            result.data.model_copy(update={"updated_at": revision})
        )


@pytest.mark.parametrize(
    ("settles", "expected_ok", "expected_calls"),
    [(True, True, 4), (False, False, 6)],
)
def test_snapshot_retries_revision_races_twice(
    tmp_path: Path,
    settles: bool,
    expected_ok: bool,
    expected_calls: int,
) -> None:
    tmp_path.chmod(0o700)
    reader = RacingReader(settles=settles)
    store = WorkspaceSnapshotStore(tmp_path)
    result = WorkspaceSnapshotBuilder(reader, store).prepare(
        all_spaces=True,
        space_ids=None,
        max_pages=10,
        max_page_chars=10_000,
    )

    assert result.ok is expected_ok
    assert reader.page_calls["page-1"] == expected_calls
    if not expected_ok:
        assert result.data is None and result.error is not None
        assert result.error.code is ErrorCode.SNAPSHOT_CONFLICT
        assert list(tmp_path.rglob("workspace.jsonl")) == []
    elif result.data is not None:
        builder = WorkspaceSnapshotBuilder(reader, store)
        assert builder.release(result.data.snapshot_token).ok
    store.close()


def test_snapshot_protocol_exposes_only_read_operations() -> None:
    methods = {
        name
        for name, value in WorkspaceReadProtocol.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    assert methods == {
        "current_user",
        "list_spaces",
        "get_page",
        "list_pages",
        "list_child_pages",
    }
    assert all(not name.startswith(("create_", "update_", "delete_")) for name in methods)


def test_http_endpoint_spy_observes_no_write_route(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    seen: list[str] = []

    def envelope(data: dict[str, object]) -> dict[str, object]:
        return {"data": data, "success": True, "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/api/users/me":
            return httpx.Response(
                200,
                json=envelope(
                    {"user": {"id": "user-1"}, "workspace": {"id": "workspace-1"}}
                ),
            )
        if request.url.path == "/api/spaces":
            return httpx.Response(
                200,
                json=envelope({"items": [{"id": "space-1"}], "meta": {}}),
            )
        if request.url.path == "/api/pages/sidebar-pages":
            items = (
                [{"id": "page-1", "spaceId": "space-1"}]
                if body.get("spaceId") == "space-1"
                else []
            )
            return httpx.Response(200, json=envelope({"items": items, "meta": {}}))
        assert request.url.path == "/api/pages/info"
        if body.get("format") == "markdown":
            return httpx.Response(
                200,
                json=envelope(
                    {
                        "page": {
                            "id": "page-1",
                            "spaceId": "space-1",
                            "updatedAt": "2026-01-01T00:00:00Z",
                            "space": {"id": "space-1"},
                        },
                        "content": "read-only body",
                    }
                ),
            )
        return httpx.Response(200, json=envelope({"id": "page-1", "spaceId": "space-1"}))

    client = DocmostReadClient(
        DocmostSettings.model_validate({"base_url": "https://docs.example.test"}),
        "session-secret",
        transport=httpx.MockTransport(handler),
        snapshot_store=WorkspaceSnapshotStore(tmp_path),
    )
    result = client.prepare_workspace_snapshot(
        all_spaces=True,
        space_ids=None,
        max_pages=10,
        max_page_chars=10_000,
    )

    assert result.ok is True and result.data is not None
    assert set(seen) <= {
        "/api/users/me",
        "/api/spaces",
        "/api/pages/sidebar-pages",
        "/api/pages/info",
    }
    assert not set(seen) & {
        "/api/pages/import",
        "/api/pages/move",
        "/api/pages/update",
        "/api/comments/create",
    }
    assert client.release_workspace_snapshot(result.data.snapshot_token).ok
    client.close()
