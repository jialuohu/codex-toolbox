"""Complete, read-only Docmost workspace snapshots in private temporary storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Protocol, TypeVar

from docmost_tools.models import (
    CurrentUser,
    CursorPage,
    ErrorCode,
    OperationResult,
    Page,
    PageList,
    Space,
    WorkspaceSnapshotReceipt,
    WorkspaceSnapshotRelease,
)

SNAPSHOT_SCHEMA_VERSION = "docmost.workspace-snapshot.v1"
_PAGE_WINDOW_CHARS = 100_000
_SNAPSHOT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_MAX_SPACES = 1_000
_MAX_REVISION_RETRIES = 2
_INCOMPLETE_MESSAGE = "Docmost workspace snapshot was incomplete; no receipt was created"
_CONFLICT_MESSAGE = "Docmost page changed repeatedly during snapshot; no receipt was created"
_CAP_MESSAGE = "Docmost workspace snapshot exceeded its configured safety cap"
_STORAGE_MESSAGE = "Private Docmost snapshot storage is unavailable or unsafe"

ResultItem = TypeVar("ResultItem")


class WorkspaceReadProtocol(Protocol):
    """The only operations reachable from the snapshot crawler."""

    def current_user(self) -> OperationResult[CurrentUser]: ...

    def list_spaces(
        self, *, limit: int, cursor: str | None = None
    ) -> OperationResult[CursorPage[Space]]: ...

    def get_page(
        self, page_id: str, *, offset: int, max_chars: int
    ) -> OperationResult[Page]: ...

    def list_pages(
        self, space_id: str, *, limit: int, cursor: str | None = None
    ) -> OperationResult[PageList]: ...

    def list_child_pages(
        self, page_id: str, *, limit: int, cursor: str | None = None
    ) -> OperationResult[PageList]: ...


class SnapshotBuildError(RuntimeError):
    """Sanitized failure raised while building a complete snapshot."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable


@dataclass(frozen=True)
class _StagedSnapshot:
    token: str
    path: Path
    sha256: str
    size_bytes: int


class WorkspaceSnapshotStore:
    """Stream snapshots beneath ``CODEX_SECRETS_DIR`` and release by token."""

    def __init__(self, secrets_dir: Path | None = None) -> None:
        self._configured_secrets_dir = secrets_dir
        self._session_root: Path | None = None
        self._paths: dict[str, Path] = {}
        self._closed = False
        self._lock = Lock()

    def stage(self, records: Iterable[dict[str, object]]) -> _StagedSnapshot:
        token, token_directory, destination = self._allocate()
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with destination.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                for record in records:
                    encoded = (
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                        + b"\n"
                    )
                    output.write(encoded)
                    digest.update(encoded)
                    size_bytes += len(encoded)
                output.flush()
                os.fsync(output.fileno())
            if size_bytes == 0:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            with self._lock:
                if self._closed:
                    raise SnapshotBuildError(ErrorCode.INTERNAL_ERROR, _STORAGE_MESSAGE)
                self._paths[token] = destination
            return _StagedSnapshot(
                token=token,
                path=destination.resolve(),
                sha256=digest.hexdigest(),
                size_bytes=size_bytes,
            )
        except Exception:
            shutil.rmtree(token_directory, ignore_errors=True)
            raise

    def release(self, token: str) -> bool:
        """Remove a managed snapshot; repeated release is harmless."""

        if _SNAPSHOT_TOKEN_PATTERN.fullmatch(token) is None:
            return False
        with self._lock:
            destination = self._paths.pop(token, None)
        if destination is None:
            return False
        shutil.rmtree(destination.parent, ignore_errors=True)
        return True

    def close(self) -> None:
        """Release all snapshots on MCP shutdown."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            session_root = self._session_root
            self._session_root = None
            self._paths.clear()
        if session_root is not None:
            shutil.rmtree(session_root, ignore_errors=True)

    def _allocate(self) -> tuple[str, Path, Path]:
        with self._lock:
            if self._closed:
                raise SnapshotBuildError(ErrorCode.INTERNAL_ERROR, _STORAGE_MESSAGE)
            if self._session_root is None:
                self._session_root = self._create_session_root()
            session_root = self._session_root
            token = secrets.token_urlsafe(32)
            while token in self._paths or (session_root / token).exists():
                token = secrets.token_urlsafe(32)
            token_directory = session_root / token
            token_directory.mkdir(mode=0o700)
        return token, token_directory, token_directory / "workspace.jsonl"

    def _create_session_root(self) -> Path:
        configured = self._configured_secrets_dir
        if configured is None:
            raw = os.environ.get("CODEX_SECRETS_DIR")
            if not raw:
                raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, _STORAGE_MESSAGE)
            configured = Path(raw)
        if not configured.is_absolute() or configured.is_symlink():
            raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, _STORAGE_MESSAGE)
        try:
            configured.mkdir(mode=0o700, parents=True, exist_ok=True)
            mode = configured.stat().st_mode & 0o777
            if not configured.is_dir() or mode & 0o077:
                raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, _STORAGE_MESSAGE)
            snapshots_root = configured / "docmost-workspace-snapshots"
            if snapshots_root.is_symlink():
                raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, _STORAGE_MESSAGE)
            snapshots_root.mkdir(mode=0o700, exist_ok=True)
            snapshots_root.chmod(0o700)
            session_root = Path(
                tempfile.mkdtemp(prefix="session-", dir=snapshots_root)
            )
            session_root.chmod(0o700)
            return session_root
        except SnapshotBuildError:
            raise
        except OSError as error:
            raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, _STORAGE_MESSAGE) from error


class WorkspaceSnapshotBuilder:
    """Traverse every selected page through a read-only protocol and stage JSONL."""

    def __init__(self, client: WorkspaceReadProtocol, store: WorkspaceSnapshotStore) -> None:
        self._client = client
        self._store = store

    def prepare(
        self,
        *,
        all_spaces: bool,
        space_ids: list[str] | None,
        max_pages: int,
        max_page_chars: int,
    ) -> OperationResult[WorkspaceSnapshotReceipt]:
        try:
            selected_space_ids = self._validate_scope(all_spaces, space_ids)
            if not 1 <= max_pages <= 5_000:
                raise SnapshotBuildError(ErrorCode.CONFIGURATION_INVALID, "max_pages is invalid")
            if not 1 <= max_page_chars <= 2_000_000:
                raise SnapshotBuildError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "max_page_chars is invalid",
                )
            current_user = self._required(self._client.current_user())
            spaces = self._select_spaces(selected_space_ids)
            counters = {"pages": 0, "markdown_chars": 0}
            staged = self._store.stage(
                self._records(
                    current_user,
                    spaces,
                    max_pages=max_pages,
                    max_page_chars=max_page_chars,
                    counters=counters,
                )
            )
            return OperationResult[WorkspaceSnapshotReceipt].success(
                WorkspaceSnapshotReceipt(
                    snapshot_token=staged.token,
                    local_path=str(staged.path),
                    sha256=staged.sha256,
                    schema_version=SNAPSHOT_SCHEMA_VERSION,
                    workspace_id=current_user.workspace.id,
                    space_count=len(spaces),
                    page_count=counters["pages"],
                    markdown_chars=counters["markdown_chars"],
                    size_bytes=staged.size_bytes,
                )
            )
        except SnapshotBuildError as error:
            return OperationResult[WorkspaceSnapshotReceipt].failure(
                error.code,
                error.public_message,
                retryable=error.retryable,
            )
        except (OSError, TypeError, ValueError):
            return OperationResult[WorkspaceSnapshotReceipt].failure(
                ErrorCode.SNAPSHOT_INCOMPLETE,
                _INCOMPLETE_MESSAGE,
            )

    def release(self, token: str) -> OperationResult[WorkspaceSnapshotRelease]:
        if _SNAPSHOT_TOKEN_PATTERN.fullmatch(token) is None:
            return OperationResult[WorkspaceSnapshotRelease].failure(
                ErrorCode.CONFIGURATION_INVALID,
                "snapshot_token is invalid",
            )
        return OperationResult[WorkspaceSnapshotRelease].success(
            WorkspaceSnapshotRelease(released=self._store.release(token))
        )

    @staticmethod
    def _validate_scope(all_spaces: bool, space_ids: list[str] | None) -> set[str] | None:
        if all_spaces:
            if space_ids is not None:
                raise SnapshotBuildError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "Choose all_spaces or space_ids, not both",
                )
            return None
        if not space_ids:
            raise SnapshotBuildError(
                ErrorCode.CONFIGURATION_INVALID,
                "space_ids is required when all_spaces is false",
            )
        if len(space_ids) != len(set(space_ids)):
            raise SnapshotBuildError(
                ErrorCode.CONFIGURATION_INVALID,
                "space_ids contains duplicates",
            )
        return set(space_ids)

    def _select_spaces(self, selected_ids: set[str] | None) -> list[Space]:
        spaces = self._collect_space_pages(
            lambda cursor: self._client.list_spaces(limit=100, cursor=cursor),
            max_items=_MAX_SPACES,
        )
        by_id: dict[str, Space] = {}
        for space in spaces:
            if space.id in by_id:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            by_id[space.id] = space
        if selected_ids is None:
            selected = spaces
        else:
            if selected_ids - by_id.keys():
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            selected = [space for space in spaces if space.id in selected_ids]
        if not selected:
            raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
        return selected

    def _records(
        self,
        current_user: CurrentUser,
        spaces: list[Space],
        *,
        max_pages: int,
        max_page_chars: int,
        counters: dict[str, int],
    ) -> Iterator[dict[str, object]]:
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        yield {
            "record_type": "header",
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generated_at": generated_at,
            "workspace": current_user.workspace.model_dump(mode="json"),
        }
        seen_pages: set[str] = set()
        for space in spaces:
            yield {
                "record_type": "space",
                "space": space.model_dump(mode="json"),
            }
            roots = self._collect_page_pages(
                lambda cursor, space_id=space.id: self._client.list_pages(
                    space_id,
                    limit=100,
                    cursor=cursor,
                ),
                max_items=max_pages,
            )
            stack: list[tuple[Page, str | None, tuple[str, ...], tuple[str, ...]]] = [
                (page, None, (), ()) for page in reversed(roots)
            ]
            while stack:
                summary, expected_parent, ancestor_ids, ancestor_titles = stack.pop()
                if summary.id in ancestor_ids or summary.id in seen_pages:
                    raise SnapshotBuildError(
                        ErrorCode.SNAPSHOT_INCOMPLETE,
                        _INCOMPLETE_MESSAGE,
                    )
                if counters["pages"] >= max_pages:
                    raise SnapshotBuildError(ErrorCode.SNAPSHOT_SAFETY_CAP, _CAP_MESSAGE)
                if summary.parent is not None and summary.parent != expected_parent:
                    raise SnapshotBuildError(
                        ErrorCode.SNAPSHOT_INCOMPLETE,
                        _INCOMPLETE_MESSAGE,
                    )
                seen_pages.add(summary.id)
                page, markdown = self._read_consistent_page(
                    summary.id,
                    max_page_chars=max_page_chars,
                )
                if page.id != summary.id:
                    raise SnapshotBuildError(
                        ErrorCode.SNAPSHOT_INCOMPLETE,
                        _INCOMPLETE_MESSAGE,
                    )
                if page.space_id is not None and page.space_id != space.id:
                    raise SnapshotBuildError(
                        ErrorCode.SNAPSHOT_INCOMPLETE,
                        _INCOMPLETE_MESSAGE,
                    )
                if page.parent is not None and page.parent != expected_parent:
                    raise SnapshotBuildError(
                        ErrorCode.SNAPSHOT_INCOMPLETE,
                        _INCOMPLETE_MESSAGE,
                    )
                counters["pages"] += 1
                counters["markdown_chars"] += len(markdown)
                yield {
                    "record_type": "page",
                    "page": {
                        **page.model_dump(
                            mode="json",
                            exclude={"markdown", "truncated", "next_offset"},
                        ),
                        "space_id": space.id,
                        "parent": expected_parent,
                        "title": page.title or summary.title or "Untitled",
                        "url": page.url or summary.url,
                        "ancestor_ids": list(ancestor_ids),
                        "ancestor_titles": list(ancestor_titles),
                        "markdown": markdown,
                        "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                    },
                }
                children = self._collect_page_pages(
                    lambda cursor, page_id=page.id: self._client.list_child_pages(
                        page_id,
                        limit=100,
                        cursor=cursor,
                    ),
                    max_items=max_pages,
                )
                next_ancestor_ids = (*ancestor_ids, page.id)
                next_ancestor_titles = (*ancestor_titles, page.title or "Untitled")
                for child in reversed(children):
                    if child.id in next_ancestor_ids:
                        raise SnapshotBuildError(
                            ErrorCode.SNAPSHOT_INCOMPLETE,
                            _INCOMPLETE_MESSAGE,
                        )
                    stack.append(
                        (child, page.id, next_ancestor_ids, next_ancestor_titles)
                    )
        yield {
            "record_type": "manifest",
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "complete": True,
            "workspace_id": current_user.workspace.id,
            "space_count": len(spaces),
            "page_count": counters["pages"],
            "markdown_chars": counters["markdown_chars"],
        }

    def _read_consistent_page(self, page_id: str, *, max_page_chars: int) -> tuple[Page, str]:
        for _attempt in range(_MAX_REVISION_RETRIES + 1):
            try:
                page, markdown = self._read_page_once(
                    page_id,
                    max_page_chars=max_page_chars,
                )
            except SnapshotBuildError as error:
                if error.code is ErrorCode.SNAPSHOT_CONFLICT:
                    continue
                raise
            if page.updated_at is None:
                check_page, check_markdown = self._read_page_once(
                    page_id,
                    max_page_chars=max_page_chars,
                )
                if self._same_revision(page, check_page) and markdown == check_markdown:
                    return check_page, check_markdown
                continue
            probe = self._required(
                self._client.get_page(page_id, offset=0, max_chars=1)
            )
            if self._same_revision(page, probe) and probe.markdown == markdown[:1]:
                return page, markdown
        raise SnapshotBuildError(ErrorCode.SNAPSHOT_CONFLICT, _CONFLICT_MESSAGE, retryable=True)

    def _read_page_once(self, page_id: str, *, max_page_chars: int) -> tuple[Page, str]:
        offset = 0
        reference: Page | None = None
        parts: list[str] = []
        while True:
            page = self._required(
                self._client.get_page(
                    page_id,
                    offset=offset,
                    max_chars=min(_PAGE_WINDOW_CHARS, max_page_chars - offset),
                )
            )
            if page.id != page_id or page.markdown is None:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            if reference is None:
                reference = page
            elif not self._same_revision(reference, page):
                raise SnapshotBuildError(
                    ErrorCode.SNAPSHOT_CONFLICT,
                    _CONFLICT_MESSAGE,
                    retryable=True,
                )
            parts.append(page.markdown)
            consumed = sum(len(part) for part in parts)
            if consumed > max_page_chars:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_SAFETY_CAP, _CAP_MESSAGE)
            if page.next_offset is None:
                if page.truncated:
                    raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
                assert reference is not None
                return reference, "".join(parts)
            if (
                not page.truncated
                or page.next_offset != offset + len(page.markdown)
                or page.next_offset <= offset
                or page.next_offset >= max_page_chars
            ):
                code = (
                    ErrorCode.SNAPSHOT_SAFETY_CAP
                    if page.next_offset >= max_page_chars
                    else ErrorCode.SNAPSHOT_INCOMPLETE
                )
                message = (
                    _CAP_MESSAGE
                    if code is ErrorCode.SNAPSHOT_SAFETY_CAP
                    else _INCOMPLETE_MESSAGE
                )
                raise SnapshotBuildError(code, message)
            offset = page.next_offset

    @staticmethod
    def _same_revision(left: Page, right: Page) -> bool:
        return all(
            getattr(left, field) == getattr(right, field)
            for field in (
                "id",
                "title",
                "slug_id",
                "space_id",
                "parent",
                "created_at",
                "updated_at",
                "url",
            )
        )

    def _collect_space_pages(
        self,
        fetch: Callable[[str | None], OperationResult[CursorPage[Space]]],
        *,
        max_items: int,
    ) -> list[Space]:
        items: list[Space] = []
        cursor: str | None = None
        cursors: set[str] = set()
        while True:
            page = self._required(fetch(cursor))
            items.extend(page.items)
            if len(items) > max_items:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_SAFETY_CAP, _CAP_MESSAGE)
            if page.next_cursor is None:
                return items
            if page.next_cursor in cursors:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            cursors.add(page.next_cursor)
            cursor = page.next_cursor

    def _collect_page_pages(
        self,
        fetch: Callable[[str | None], OperationResult[PageList]],
        *,
        max_items: int,
    ) -> list[Page]:
        items: list[Page] = []
        cursor: str | None = None
        cursors: set[str] = set()
        while True:
            page = self._required(fetch(cursor))
            items.extend(page.items)
            if len(items) > max_items:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_SAFETY_CAP, _CAP_MESSAGE)
            if page.next_cursor is None:
                return items
            if page.next_cursor in cursors:
                raise SnapshotBuildError(ErrorCode.SNAPSHOT_INCOMPLETE, _INCOMPLETE_MESSAGE)
            cursors.add(page.next_cursor)
            cursor = page.next_cursor

    @staticmethod
    def _required(result: OperationResult[ResultItem]) -> ResultItem:
        if result.ok and result.data is not None:
            return result.data
        error = result.error
        if error is not None and error.code is ErrorCode.AUTH_REQUIRED:
            raise SnapshotBuildError(error.code, error.message, retryable=error.retryable)
        raise SnapshotBuildError(
            ErrorCode.SNAPSHOT_INCOMPLETE,
            _INCOMPLETE_MESSAGE,
            retryable=bool(error and error.retryable),
        )
