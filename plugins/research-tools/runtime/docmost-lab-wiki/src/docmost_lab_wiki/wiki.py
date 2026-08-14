"""Transactional Docmost snapshot application and Lab Wiki maintenance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from docmost_lab_wiki.config import WikiConfig
from docmost_lab_wiki.constants import INDEX_SCHEMA_VERSION, NOTE_SCHEMA_VERSION
from docmost_lab_wiki.embedding import EmbeddingBackend
from docmost_lab_wiki.index import IndexBuildReport, build_index, read_status
from docmost_lab_wiki.notes import (
    ExistingNote,
    NoteConflict,
    SourceDocument,
    SourceStatus,
    active_managed_body,
    build_source_note,
    deleted_managed_body,
    parse_existing_note,
    parse_frontmatter,
    quarantined_managed_body,
    sanitize_markdown,
    scan_for_secrets,
    source_document_from_note,
    stable_component,
    utc_now,
)


class SnapshotValidationError(RuntimeError):
    """A snapshot is incomplete, changed, or outside the expected contract."""


@dataclass(frozen=True)
class SnapshotSpace:
    id: str
    name: str
    slug: str | None


@dataclass(frozen=True)
class SnapshotPage:
    id: str
    space_id: str
    parent: str | None
    title: str
    ancestor_ids: tuple[str, ...]
    ancestor_titles: tuple[str, ...]
    created_at: str | None
    updated_at: str | None
    url: str
    markdown: str
    markdown_sha256: str


@dataclass(frozen=True)
class CompleteSnapshot:
    workspace_id: str
    generated_at: str
    sha256: str
    spaces: tuple[SnapshotSpace, ...]
    pages: tuple[SnapshotPage, ...]


@dataclass(frozen=True)
class SyncReport:
    workspace_id: str
    snapshot_sha256: str
    pages: int
    chunks: int
    changed_files: int
    unchanged_files: int
    embedded_chunks: int
    reused_chunks: int
    quarantines: int
    tombstones: int
    conflicts: int
    warnings: tuple[str, ...]

    @property
    def attention_required(self) -> bool:
        return bool(self.warnings)


def initialize_wiki(config: WikiConfig) -> dict[str, object]:
    """Create only the separate Lab Wiki scaffold."""

    root = config.wiki_root
    for relative in (
        "Sources/Docmost",
        "Maps",
        "Concepts",
        "Questions",
        "Analyses",
    ):
        (root / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    schema = root / "_schema.md"
    index = root / "index.md"
    log = root / "log.md"
    created: list[str] = []
    defaults = {
        schema: _schema_note(),
        index: "# Lab Wiki\n\nNo complete Docmost snapshot has been synchronized yet.\n",
        log: "# Lab Wiki sync log\n",
    }
    for path, content in defaults.items():
        if not path.exists():
            _atomic_write(path, content)
            created.append(path.relative_to(root).as_posix())
    return {"wiki_root": str(root), "created": created, "existing": len(defaults) - len(created)}


def load_complete_snapshot(path: Path, expected_sha256: str) -> CompleteSnapshot:
    """Validate the receipt checksum, JSONL schema, identities, hierarchy, and trailer."""

    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise SnapshotValidationError("Workspace snapshot path is missing or unsafe")
    digest = hashlib.sha256()
    records: list[dict[str, object]] = []
    try:
        with path.open("rb") as source:
            for raw_line in source:
                digest.update(raw_line)
                parsed = json.loads(raw_line.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise SnapshotValidationError("Workspace snapshot record is invalid")
                records.append(cast(dict[str, object], parsed))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotValidationError("Workspace snapshot is unreadable or invalid") from error
    if digest.hexdigest() != expected_sha256 or len(expected_sha256) != 64:
        raise SnapshotValidationError("Workspace snapshot checksum does not match its receipt")
    if len(records) < 2 or records[0].get("record_type") != "header":
        raise SnapshotValidationError("Workspace snapshot header is missing")
    header = records[0]
    if header.get("schema_version") != "docmost.workspace-snapshot.v1":
        raise SnapshotValidationError("Workspace snapshot schema is unsupported")
    raw_workspace = header.get("workspace")
    if not isinstance(raw_workspace, dict):
        raise SnapshotValidationError("Workspace snapshot identity is invalid")
    workspace = cast(dict[str, object], raw_workspace)
    if not isinstance(workspace.get("id"), str):
        raise SnapshotValidationError("Workspace snapshot identity is invalid")
    generated_at = header.get("generated_at")
    if not isinstance(generated_at, str):
        raise SnapshotValidationError("Workspace snapshot timestamp is invalid")
    spaces: list[SnapshotSpace] = []
    pages: list[SnapshotPage] = []
    space_ids: set[str] = set()
    page_ids: set[str] = set()
    manifest: dict[str, object] | None = None
    for index, record in enumerate(records[1:], start=1):
        kind = record.get("record_type")
        if kind == "manifest":
            if index != len(records) - 1 or manifest is not None:
                raise SnapshotValidationError("Workspace snapshot trailer is invalid")
            manifest = record
        elif manifest is not None:
            raise SnapshotValidationError("Workspace snapshot has records after its trailer")
        elif kind == "space":
            raw_space = record.get("space")
            if not isinstance(raw_space, dict):
                raise SnapshotValidationError("Workspace snapshot space record is invalid")
            space_data = cast(dict[str, object], raw_space)
            space_id = space_data.get("id")
            if not isinstance(space_id, str) or not space_id or space_id in space_ids:
                raise SnapshotValidationError("Workspace snapshot space identity is invalid")
            name = space_data.get("name")
            slug = space_data.get("slug")
            space_ids.add(space_id)
            spaces.append(
                SnapshotSpace(
                    id=space_id,
                    name=_display_text(name) if isinstance(name, str) else "Untitled space",
                    slug=slug if isinstance(slug, str) else None,
                )
            )
        elif kind == "page":
            page = _parse_snapshot_page(record.get("page"))
            if page.id in page_ids:
                raise SnapshotValidationError("Workspace snapshot page identity is duplicated")
            page_ids.add(page.id)
            pages.append(page)
        else:
            raise SnapshotValidationError("Workspace snapshot contains an unknown record")
    if manifest is None or manifest.get("complete") is not True:
        raise SnapshotValidationError("Workspace snapshot is incomplete")
    workspace_id = cast(str, workspace["id"])
    if (
        manifest.get("schema_version") != "docmost.workspace-snapshot.v1"
        or manifest.get("workspace_id") != workspace_id
        or manifest.get("space_count") != len(spaces)
        or manifest.get("page_count") != len(pages)
        or manifest.get("markdown_chars") != sum(len(page.markdown) for page in pages)
    ):
        raise SnapshotValidationError("Workspace snapshot trailer counts are inconsistent")
    if any(page.space_id not in space_ids for page in pages):
        raise SnapshotValidationError("Workspace snapshot page references an unknown space")
    for page in pages:
        if page.parent is None:
            if page.ancestor_ids:
                raise SnapshotValidationError("Workspace snapshot root hierarchy is invalid")
        elif not page.ancestor_ids or page.ancestor_ids[-1] != page.parent:
            raise SnapshotValidationError("Workspace snapshot parent hierarchy is invalid")
        if page.id in page.ancestor_ids or len(page.ancestor_ids) != len(set(page.ancestor_ids)):
            raise SnapshotValidationError("Workspace snapshot hierarchy is cyclic")
        if any(ancestor not in page_ids for ancestor in page.ancestor_ids):
            raise SnapshotValidationError("Workspace snapshot hierarchy is incomplete")
    return CompleteSnapshot(
        workspace_id=workspace_id,
        generated_at=generated_at,
        sha256=expected_sha256,
        spaces=tuple(spaces),
        pages=tuple(pages),
    )


def sync_snapshot(
    config: WikiConfig,
    snapshot_path: Path,
    expected_sha256: str,
    backend: EmbeddingBackend,
    *,
    fail_after_replacements: int | None = None,
) -> SyncReport:
    """Stage a complete generation and commit files plus SQLite with rollback."""

    snapshot = load_complete_snapshot(snapshot_path, expected_sha256)
    if not config.wiki_root.is_dir() or config.wiki_root.is_symlink():
        raise RuntimeError("Lab Wiki is not initialized")
    synced_at = utc_now()
    existing_by_id = _existing_sources(config.wiki_root)
    desired: dict[Path, str] = {}
    deletions: set[Path] = set()
    documents: list[SourceDocument] = []
    conflict_ids: set[str] = set()
    quarantine_ids: set[str] = set()
    tombstone_ids: set[str] = set()
    page_note_titles: dict[str, str] = {}
    unchanged_files = 0

    spaces = {space.id: space for space in snapshot.spaces}
    snapshot_ids = {page.id for page in snapshot.pages}
    for page in snapshot.pages:
        destination = _source_path(config.wiki_root, page.space_id, page.id)
        previous = existing_by_id.get(page.id)
        scan = scan_for_secrets(page.title, page.markdown)
        status = "quarantined" if scan.quarantined else "active"
        title = "Quarantined source" if scan.redact_title else _display_text(page.title)
        page_note_titles[page.id] = title
        managed_body = (
            quarantined_managed_body()
            if scan.quarantined
            else active_managed_body(sanitize_markdown(page.markdown))
        )
        normalized_hash = hashlib.sha256(managed_body.encode("utf-8")).hexdigest()
        metadata: dict[str, object] = {
            "docmost_workspace_id": snapshot.workspace_id,
            "docmost_space_id": page.space_id,
            "docmost_space_name": spaces[page.space_id].name,
            "docmost_page_id": page.id,
            "docmost_parent_id": page.parent,
            "title": title,
            "hierarchy": list(page.ancestor_titles),
            "docmost_url": page.url,
            "docmost_created_at": page.created_at,
            "docmost_updated_at": page.updated_at,
            "original_hash": page.markdown_sha256,
            "normalized_hash": normalized_hash,
            "status": status,
            "last_sync": synced_at,
        }
        personal_notes = ""
        previous_parsed: ExistingNote | None = None
        if previous is not None:
            try:
                previous_parsed = parse_existing_note(previous.read_text(encoding="utf-8"))
                personal_notes = previous_parsed.personal_notes
            except (OSError, UnicodeError, NoteConflict):
                if not scan.quarantined:
                    conflict_ids.add(page.id)
                    page_note_titles[page.id] = page.title
                    continue
                personal_notes = _recover_personal_notes(previous)
                conflict_ids.add(page.id)
            if previous != destination:
                deletions.add(previous)
        if previous_parsed is not None and _same_source_metadata(previous_parsed, metadata):
            prior_sync = previous_parsed.frontmatter.get("last_sync")
            if isinstance(prior_sync, str):
                metadata["last_sync"] = prior_sync
        rendered = build_source_note(
            metadata=metadata,
            managed_body=managed_body,
            personal_notes=personal_notes,
        )
        if previous is not None and _same_file(previous, rendered):
            unchanged_files += 1
        else:
            desired[destination] = rendered
        if scan.quarantined:
            quarantine_ids.add(page.id)
        documents.append(
            SourceDocument(
                page_id=page.id,
                space_id=page.space_id,
                title=title,
                hierarchy=page.ancestor_titles,
                updated_at=page.updated_at,
                url=page.url,
                local_relative_path=destination.relative_to(config.wiki_root).as_posix(),
                source_hash=page.markdown_sha256,
                normalized_hash=normalized_hash,
                status=cast(SourceStatus, status),
                content=managed_body,
            )
        )

    for page_id, previous in sorted(existing_by_id.items()):
        if page_id in snapshot_ids:
            continue
        tombstone_ids.add(page_id)
        conflict = False
        frontmatter: dict[str, object]
        try:
            parsed = parse_existing_note(previous.read_text(encoding="utf-8"))
            frontmatter = parsed.frontmatter
            personal_notes = parsed.personal_notes
        except (OSError, UnicodeError, NoteConflict):
            conflict = True
            conflict_ids.add(page_id)
            try:
                raw = previous.read_text(encoding="utf-8")
                frontmatter = parse_frontmatter(raw)
                personal_notes = _recover_personal_notes(previous)
            except (OSError, UnicodeError, NoteConflict):
                frontmatter = {
                    "docmost_page_id": page_id,
                    "docmost_space_id": previous.parent.name,
                    "title": "Deleted Docmost source",
                    "original_hash": "0" * 64,
                }
                personal_notes = ""
        managed_body = deleted_managed_body()
        normalized_hash = hashlib.sha256(managed_body.encode("utf-8")).hexdigest()
        space_id = _string_value(frontmatter, "docmost_space_id", previous.parent.name)
        title = _string_value(frontmatter, "title", "Deleted Docmost source")
        metadata: dict[str, object] = {
            "docmost_workspace_id": _string_value(
                frontmatter,
                "docmost_workspace_id",
                snapshot.workspace_id,
            ),
            "docmost_space_id": space_id,
            "docmost_space_name": _string_value(
                frontmatter,
                "docmost_space_name",
                "Unknown space",
            ),
            "docmost_page_id": page_id,
            "docmost_parent_id": frontmatter.get("docmost_parent_id"),
            "title": title,
            "hierarchy": frontmatter.get("hierarchy", []),
            "docmost_url": frontmatter.get("docmost_url"),
            "docmost_created_at": frontmatter.get("docmost_created_at"),
            "docmost_updated_at": frontmatter.get("docmost_updated_at"),
            "original_hash": _string_value(frontmatter, "original_hash", "0" * 64),
            "normalized_hash": normalized_hash,
            "status": "deleted",
            "last_sync": synced_at,
        }
        if frontmatter.get("status") == "deleted":
            prior_sync = frontmatter.get("last_sync")
            stable_metadata = {**metadata, "last_sync": prior_sync}
            if isinstance(prior_sync, str) and all(
                frontmatter.get(key) == value
                for key, value in stable_metadata.items()
                if key != "last_sync"
            ):
                metadata["last_sync"] = prior_sync
        rendered = build_source_note(
            metadata=metadata,
            managed_body=managed_body,
            personal_notes=personal_notes,
        )
        if _same_file(previous, rendered):
            unchanged_files += 1
        else:
            desired[previous] = rendered
        hierarchy_value = metadata["hierarchy"]
        hierarchy_items = (
            cast(list[object], hierarchy_value) if isinstance(hierarchy_value, list) else []
        )
        hierarchy = tuple(item for item in hierarchy_items if isinstance(item, str))
        documents.append(
            SourceDocument(
                page_id=page_id,
                space_id=space_id,
                title=title,
                hierarchy=hierarchy,
                updated_at=(
                    metadata["docmost_updated_at"]
                    if isinstance(metadata["docmost_updated_at"], str)
                    else None
                ),
                url=(metadata["docmost_url"] if isinstance(metadata["docmost_url"], str) else None),
                local_relative_path=previous.relative_to(config.wiki_root).as_posix(),
                source_hash=cast(str, metadata["original_hash"]),
                normalized_hash=normalized_hash,
                status="deleted",
                content=managed_body,
            )
        )
        if conflict:
            page_note_titles[page_id] = "Deleted Docmost source"

    _add_control_files(
        config,
        snapshot,
        documents,
        desired,
        page_note_titles,
        synced_at=synced_at,
        quarantine_count=len(quarantine_ids),
        conflict_count=len(conflict_ids),
        tombstone_count=len(tombstone_ids),
    )
    stage_root = Path(
        tempfile.mkdtemp(prefix=".docmost-lab-wiki-stage-", dir=config.wiki_root.parent)
    )
    index_temp = _index_temp_path(config.index_path)
    try:
        staged_files: dict[Path, Path] = {}
        for destination, content in desired.items():
            relative = destination.relative_to(config.wiki_root)
            staged = stage_root / relative
            staged.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            staged.write_text(content, encoding="utf-8")
            staged.chmod(0o600)
            staged_files[destination] = staged
        final_documents = _final_documents(config, documents, desired, conflict_ids)
        index_report = build_index(
            final_documents,
            index_temp,
            existing=config.index_path if config.index_path.is_file() else None,
            backend=backend,
            synced_at=synced_at,
            snapshot_generated_at=snapshot.generated_at,
            snapshot_sha256=snapshot.sha256,
            workspace_id=snapshot.workspace_id,
            quarantined_page_ids=quarantine_ids,
            conflict_page_ids=conflict_ids,
        )
        _commit_replacements(
            config,
            staged_files,
            index_temp,
            deletions=deletions,
            fail_after=fail_after_replacements,
        )
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
        index_temp.unlink(missing_ok=True)
    warnings: list[str] = []
    if quarantine_ids:
        warnings.append(f"{len(quarantine_ids)} source page(s) quarantined")
    if conflict_ids:
        warnings.append(f"{len(conflict_ids)} local managed-region conflict(s)")
    return SyncReport(
        workspace_id=snapshot.workspace_id,
        snapshot_sha256=snapshot.sha256,
        pages=index_report.pages,
        chunks=index_report.chunks,
        changed_files=len(desired) + len(deletions),
        unchanged_files=unchanged_files,
        embedded_chunks=index_report.embedded_chunks,
        reused_chunks=index_report.reused_chunks,
        quarantines=len(quarantine_ids),
        tombstones=len(tombstone_ids),
        conflicts=len(conflict_ids),
        warnings=tuple(warnings),
    )


def rebuild_index(
    config: WikiConfig,
    backend: EmbeddingBackend,
) -> IndexBuildReport:
    """Rebuild only from verified vault source notes; never contact Docmost."""

    documents: list[SourceDocument] = []
    conflicts: set[str] = set()
    quarantines: set[str] = set()
    for path in sorted((config.wiki_root / "Sources" / "Docmost").glob("*/*.md")):
        try:
            document = source_document_from_note(path, config.wiki_root)
        except (OSError, UnicodeError, NoteConflict):
            conflicts.add(path.stem)
            continue
        documents.append(document)
        if document.status == "quarantined":
            quarantines.add(document.page_id)
    prior: dict[str, object] = {}
    if config.index_path.is_file():
        try:
            prior = read_status(config.index_path)
        except (RuntimeError, ValueError):
            prior = {}
    temp = _index_temp_path(config.index_path)
    try:
        report = build_index(
            documents,
            temp,
            existing=config.index_path if config.index_path.is_file() else None,
            backend=backend,
            synced_at=utc_now(),
            snapshot_generated_at=str(prior.get("snapshot_generated_at", "unknown")),
            snapshot_sha256=str(prior.get("snapshot_sha256", "unknown")),
            workspace_id=str(prior.get("workspace_id", "unknown")),
            quarantined_page_ids=quarantines,
            conflict_page_ids=conflicts,
        )
        config.index_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.replace(temp, config.index_path)
        config.index_path.chmod(0o600)
        return report
    finally:
        temp.unlink(missing_ok=True)


def _parse_snapshot_page(value: object) -> SnapshotPage:
    if not isinstance(value, dict):
        raise SnapshotValidationError("Workspace snapshot page record is invalid")
    page = cast(dict[str, object], value)
    required = ("id", "space_id", "title", "url", "markdown", "markdown_sha256")
    if any(not isinstance(page.get(key), str) for key in required):
        raise SnapshotValidationError("Workspace snapshot page record is incomplete")
    markdown = cast(str, page["markdown"])
    markdown_sha256 = cast(str, page["markdown_sha256"])
    if hashlib.sha256(markdown.encode("utf-8")).hexdigest() != markdown_sha256:
        raise SnapshotValidationError("Workspace snapshot page checksum is invalid")
    ancestor_ids = page.get("ancestor_ids")
    ancestor_titles = page.get("ancestor_titles")
    ancestor_id_items = (
        cast(list[object], ancestor_ids) if isinstance(ancestor_ids, list) else None
    )
    ancestor_title_items = (
        cast(list[object], ancestor_titles) if isinstance(ancestor_titles, list) else None
    )
    if (
        ancestor_id_items is None
        or not all(isinstance(item, str) for item in ancestor_id_items)
        or ancestor_title_items is None
        or not all(isinstance(item, str) for item in ancestor_title_items)
        or len(ancestor_id_items) != len(ancestor_title_items)
    ):
        raise SnapshotValidationError("Workspace snapshot hierarchy is invalid")
    parent = page.get("parent")
    created_at = page.get("created_at")
    updated_at = page.get("updated_at")
    url = cast(str, page["url"])
    parsed_url = urlparse(url)
    if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
        raise SnapshotValidationError("Workspace snapshot canonical page URL is invalid")
    return SnapshotPage(
        id=cast(str, page["id"]),
        space_id=cast(str, page["space_id"]),
        parent=parent if isinstance(parent, str) else None,
        title=_display_text(cast(str, page["title"])),
        ancestor_ids=tuple(cast(list[str], ancestor_id_items)),
        ancestor_titles=tuple(
            _display_text(item) for item in cast(list[str], ancestor_title_items)
        ),
        created_at=created_at if isinstance(created_at, str) else None,
        updated_at=updated_at if isinstance(updated_at, str) else None,
        url=url,
        markdown=markdown,
        markdown_sha256=markdown_sha256,
    )


def _existing_sources(wiki_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    sources = wiki_root / "Sources" / "Docmost"
    if not sources.exists():
        return found
    for path in sorted(sources.glob("*/*.md")):
        try:
            values = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, NoteConflict):
            page_id = path.stem
        else:
            raw_id = values.get("docmost_page_id")
            page_id = raw_id if isinstance(raw_id, str) else path.stem
        if page_id in found:
            raise NoteConflict("Duplicate Docmost page IDs exist in the vault mirror")
        found[page_id] = path
    return found


def _source_path(root: Path, space_id: str, page_id: str) -> Path:
    return (
        root
        / "Sources"
        / "Docmost"
        / stable_component(space_id)
        / f"{stable_component(page_id)}.md"
    )


def _same_source_metadata(existing: ExistingNote, desired: Mapping[str, object]) -> bool:
    ignored = {"last_sync"}
    return all(
        existing.frontmatter.get(key) == value
        for key, value in desired.items()
        if key not in ignored
    )


def _same_file(path: Path, content: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == content
    except (OSError, UnicodeError):
        return False


def _recover_personal_notes(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    start = text.find("<!-- docmost-lab-wiki:notes:start -->\n")
    end = text.find("\n<!-- docmost-lab-wiki:notes:end -->", start + 1)
    if start < 0 or end < 0:
        return ""
    return text[start + len("<!-- docmost-lab-wiki:notes:start -->\n") : end]


def _string_value(values: Mapping[str, object], key: str, default: str) -> str:
    value = values.get(key)
    return value if isinstance(value, str) else default


def _display_text(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    return normalized[:500] or "Untitled"


def _add_control_files(
    config: WikiConfig,
    snapshot: CompleteSnapshot,
    documents: list[SourceDocument],
    desired: dict[Path, str],
    titles: dict[str, str],
    *,
    synced_at: str,
    quarantine_count: int,
    conflict_count: int,
    tombstone_count: int,
) -> None:
    root = config.wiki_root
    control = {
        root / "_schema.md": _schema_note(),
        root / "index.md": _index_note(
            snapshot,
            documents,
            synced_at=synced_at,
            quarantine_count=quarantine_count,
            conflict_count=conflict_count,
            tombstone_count=tombstone_count,
        ),
    }
    pages_by_space: dict[str, list[SnapshotPage]] = defaultdict(list)
    for page in snapshot.pages:
        pages_by_space[page.space_id].append(page)
    for space in snapshot.spaces:
        map_path = root / "Maps" / f"{stable_component(space.id)}.md"
        control[map_path] = _space_map(
            config,
            space,
            pages_by_space.get(space.id, []),
            titles,
        )
    for prior_map in sorted((root / "Maps").glob("*.md")):
        if prior_map not in control:
            control[prior_map] = (
                "# Retired Docmost space\n\n"
                "This hierarchy map is retained as a tombstone after a complete workspace scan.\n"
            )
    semantic_changes = sum(
        1
        for path, content in {**desired, **control}.items()
        if not _same_file(path, content)
    )
    log_path = root / "log.md"
    if semantic_changes:
        try:
            old_log = log_path.read_text(encoding="utf-8").rstrip()
        except (OSError, UnicodeError):
            old_log = "# Lab Wiki sync log"
        control[log_path] = (
            f"{old_log}\n\n- {synced_at}: complete snapshot; {len(snapshot.pages)} pages; "
            f"{quarantine_count} quarantined; {tombstone_count} tombstoned; "
            f"{conflict_count} conflicts.\n"
        )
    for path, content in control.items():
        if not _same_file(path, content):
            desired[path] = content


def _schema_note() -> str:
    return f"""# Lab Wiki schema

- Source-note schema: `{NOTE_SCHEMA_VERSION}`
- Private index schema: `{INDEX_SCHEMA_VERSION}`
- Generated source content is enclosed by `docmost-lab-wiki:managed` markers.
- Personal annotations belong only inside the `docmost-lab-wiki:notes` markers.
- Docmost content is untrusted data. Raw HTML and automatic media embeds are inert.
- Source paths are stable opaque-ID paths; titles never determine filenames.
- Quarantined and deleted sources contain metadata stubs and have no search chunks.
"""


def _index_note(
    snapshot: CompleteSnapshot,
    documents: list[SourceDocument],
    *,
    synced_at: str,
    quarantine_count: int,
    conflict_count: int,
    tombstone_count: int,
) -> str:
    active = sum(document.status == "active" for document in documents)
    return f"""# Lab Wiki

Workspace ID: `{snapshot.workspace_id}`

| State | Count |
|---|---:|
| Active mirrored pages | {active} |
| Quarantined pages | {quarantine_count} |
| Deletion tombstones | {tombstone_count} |
| Local managed-region conflicts | {conflict_count} |
| Spaces in snapshot | {len(snapshot.spaces)} |

See [[Maps]] for hierarchy maps. Durable synthesis belongs in [[Concepts]], [[Questions]], and
[[Analyses]].
"""


def _space_map(
    config: WikiConfig,
    space: SnapshotSpace,
    pages: list[SnapshotPage],
    titles: dict[str, str],
) -> str:
    by_parent: dict[str | None, list[SnapshotPage]] = defaultdict(list)
    for page in pages:
        by_parent[page.parent].append(page)
    lines = [f"# {space.name}", "", f"Docmost space ID: `{space.id}`", ""]

    def append_children(parent: str | None, depth: int) -> None:
        for page in by_parent.get(parent, []):
            path = _source_path(config.wiki_root, page.space_id, page.id)
            vault_relative = path.relative_to(config.vault).with_suffix("").as_posix()
            title = titles.get(page.id, page.title).replace("|", "\\|")
            lines.append(f"{'  ' * depth}- [[{vault_relative}|{title}]]")
            append_children(page.id, depth + 1)

    append_children(None, 0)
    return "\n".join(lines).rstrip() + "\n"


def _final_documents(
    config: WikiConfig,
    generated: list[SourceDocument],
    desired: dict[Path, str],
    conflict_ids: set[str],
) -> list[SourceDocument]:
    final: list[SourceDocument] = []
    for document in generated:
        path = config.wiki_root / document.local_relative_path
        content = desired.get(path)
        if document.page_id in conflict_ids and content is None:
            continue
        if content is None:
            final.append(document)
            continue
        stage_parse = _source_document_from_text(content, document.local_relative_path)
        final.append(stage_parse)
    return final


def _source_document_from_text(text: str, relative_path: str) -> SourceDocument:
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        path = root / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        return source_document_from_note(path, root)


def _index_temp_path(index_path: Path) -> Path:
    index_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".docmost-lab-wiki-index-",
        dir=index_path.parent,
    )
    os.close(descriptor)
    path = Path(raw_path)
    path.unlink()
    return path


def _commit_replacements(
    config: WikiConfig,
    staged_files: dict[Path, Path],
    staged_index: Path,
    *,
    deletions: set[Path],
    fail_after: int | None,
) -> None:
    backup_root = Path(
        tempfile.mkdtemp(prefix=".docmost-lab-wiki-backup-", dir=config.wiki_root.parent)
    )
    index_backup = config.index_path.with_name(f".{config.index_path.name}.backup")
    replaced: list[tuple[Path, Path | None]] = []
    index_had_previous = False
    index_replaced = False
    try:
        for destination in sorted(deletions, key=str):
            if not destination.exists() or destination in staged_files:
                continue
            backup = backup_root / destination.relative_to(config.wiki_root)
            backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(destination, backup)
            replaced.append((destination, backup))
        for count, (destination, staged) in enumerate(
            sorted(staged_files.items(), key=lambda item: str(item[0])),
            start=1,
        ):
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup: Path | None = None
            if destination.exists():
                backup = backup_root / destination.relative_to(config.wiki_root)
                backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.replace(destination, backup)
            try:
                os.replace(staged, destination)
            except Exception:
                if backup is not None and backup.exists():
                    os.replace(backup, destination)
                raise
            replaced.append((destination, backup))
            if fail_after is not None and count >= fail_after:
                raise OSError("injected atomic-apply failure")
        config.index_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if config.index_path.exists():
            index_backup.unlink(missing_ok=True)
            os.replace(config.index_path, index_backup)
            index_had_previous = True
        os.replace(staged_index, config.index_path)
        index_replaced = True
        config.index_path.chmod(0o600)
        index_backup.unlink(missing_ok=True)
    except Exception:
        if config.index_path.exists() and index_replaced:
            config.index_path.unlink()
        if index_had_previous and index_backup.exists():
            os.replace(index_backup, config.index_path)
        for destination, backup in reversed(replaced):
            destination.unlink(missing_ok=True)
            if backup is not None and backup.exists():
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.replace(backup, destination)
        raise
    finally:
        index_backup.unlink(missing_ok=True)
        shutil.rmtree(backup_root, ignore_errors=True)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
