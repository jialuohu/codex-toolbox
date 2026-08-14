"""SQLite FTS5 plus exact-cosine hybrid retrieval."""

from __future__ import annotations

import math
import re
import sqlite3
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from docmost_lab_wiki.constants import (
    FINAL_CONTEXT_CHUNKS,
    FRESHNESS_WARNING_HOURS,
    INDEX_SCHEMA_VERSION,
    MAX_CHUNKS_PER_PAGE,
    RETRIEVAL_CANDIDATES,
    RRF_K,
)
from docmost_lab_wiki.embedding import EmbeddingBackend, chunk_markdown
from docmost_lab_wiki.notes import SourceDocument

_SEARCH_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")


@dataclass(frozen=True)
class IndexBuildReport:
    pages: int
    chunks: int
    embedded_chunks: int
    reused_chunks: int


@dataclass(frozen=True)
class SearchHit:
    page_id: str
    title: str
    heading: str
    text: str
    local_relative_path: str
    docmost_url: str | None
    source_hash: str
    score: float


@dataclass(frozen=True)
class QueryResult:
    hits: list[SearchHit]
    freshness_warning: str | None
    synced_at: str
    model_version: str


def build_index(
    documents: list[SourceDocument],
    destination: Path,
    *,
    existing: Path | None,
    backend: EmbeddingBackend,
    synced_at: str,
    snapshot_generated_at: str,
    snapshot_sha256: str,
    workspace_id: str,
    quarantined_page_ids: set[str],
    conflict_page_ids: set[str],
) -> IndexBuildReport:
    """Build a complete replacement DB, reusing unchanged vectors when safe."""

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    old = _open_read_only(existing) if existing is not None and existing.is_file() else None
    old_reusable = old is not None and _metadata_matches(
        old,
        backend.model_version,
        backend.dimensions,
    )
    embedded_chunks = 0
    reused_chunks = 0
    chunk_count = 0
    connection = sqlite3.connect(destination)
    try:
        _create_schema(connection)
        metadata = {
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "model_version": backend.model_version,
            "embedding_dimensions": str(backend.dimensions),
            "synced_at": synced_at,
            "snapshot_generated_at": snapshot_generated_at,
            "snapshot_sha256": snapshot_sha256,
            "workspace_id": workspace_id,
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            metadata.items(),
        )
        for document in sorted(documents, key=lambda item: item.page_id):
            connection.execute(
                """
                INSERT INTO pages(
                    page_id, space_id, title, hierarchy, updated_at, docmost_url,
                    local_relative_path, source_hash, normalized_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.page_id,
                    document.space_id,
                    document.title,
                    " > ".join(document.hierarchy),
                    document.updated_at,
                    document.url,
                    document.local_relative_path,
                    document.source_hash,
                    document.normalized_hash,
                    document.status,
                ),
            )
            if document.status != "active":
                continue
            reused = False
            if old_reusable and old is not None:
                reused = _reuse_page_chunks(old, connection, document)
            if reused:
                reused_for_page = connection.execute(
                    "SELECT count(*) FROM chunks WHERE page_id = ?",
                    (document.page_id,),
                ).fetchone()[0]
                reused_chunks += int(reused_for_page)
                chunk_count += int(reused_for_page)
                continue
            prefix = _context_prefix(document)
            chunks = chunk_markdown(
                document.content,
                context_prefix=prefix,
                backend=backend,
            )
            vectors = backend.embed_documents([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("Embedding output count did not match chunk count")
            for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                _insert_chunk(
                    connection,
                    document=document,
                    ordinal=ordinal,
                    heading=chunk.heading,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    vector=vector,
                    dimensions=backend.dimensions,
                )
            embedded_chunks += len(chunks)
            chunk_count += len(chunks)
        connection.executemany(
            "INSERT INTO quarantines(page_id) VALUES (?)",
            ((page_id,) for page_id in sorted(quarantined_page_ids)),
        )
        connection.executemany(
            "INSERT INTO conflicts(page_id) VALUES (?)",
            ((page_id,) for page_id in sorted(conflict_page_ids)),
        )
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.commit()
    finally:
        connection.close()
        if old is not None:
            old.close()
    destination.chmod(0o600)
    return IndexBuildReport(
        pages=len(documents),
        chunks=chunk_count,
        embedded_chunks=embedded_chunks,
        reused_chunks=reused_chunks,
    )


def query_index(path: Path, question: str, backend: EmbeddingBackend) -> QueryResult:
    if not question.strip():
        raise ValueError("question must not be empty")
    connection = _required_read_only(path)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("index_schema_version") != INDEX_SCHEMA_VERSION:
            raise RuntimeError("Lab Wiki index schema is stale; rebuild the index")
        if metadata.get("model_version") != backend.model_version:
            raise RuntimeError("Lab Wiki embedding model changed; rebuild the index")
        lexical_ids = _lexical_candidates(connection, question)
        semantic_ids = _semantic_candidates(connection, question, backend)
        fused: dict[str, float] = {}
        for ranking in (lexical_ids, semantic_ids):
            for rank, chunk_id in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        selected: list[SearchHit] = []
        per_page: dict[str, int] = {}
        for chunk_id, score in sorted(fused.items(), key=lambda item: (-item[1], item[0])):
            row = connection.execute(
                """
                SELECT c.page_id, p.title, c.heading, c.content, p.local_relative_path,
                       p.docmost_url, p.source_hash
                FROM chunks AS c JOIN pages AS p ON p.page_id = c.page_id
                WHERE c.chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            page_id = str(row[0])
            if per_page.get(page_id, 0) >= MAX_CHUNKS_PER_PAGE:
                continue
            per_page[page_id] = per_page.get(page_id, 0) + 1
            selected.append(
                SearchHit(
                    page_id=page_id,
                    title=str(row[1]),
                    heading=str(row[2]),
                    text=str(row[3]),
                    local_relative_path=str(row[4]),
                    docmost_url=str(row[5]) if row[5] is not None else None,
                    source_hash=str(row[6]),
                    score=score,
                )
            )
            if len(selected) >= FINAL_CONTEXT_CHUNKS:
                break
        synced_at = metadata.get("synced_at", "")
        return QueryResult(
            hits=selected,
            freshness_warning=_freshness_warning(synced_at),
            synced_at=synced_at,
            model_version=metadata.get("model_version", "unknown"),
        )
    finally:
        connection.close()


def read_status(path: Path) -> dict[str, object]:
    connection = _required_read_only(path)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        counts = {
            "pages": int(connection.execute("SELECT count(*) FROM pages").fetchone()[0]),
            "active_pages": int(
                connection.execute("SELECT count(*) FROM pages WHERE status = 'active'").fetchone()[
                    0
                ]
            ),
            "chunks": int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0]),
            "quarantines": int(
                connection.execute("SELECT count(*) FROM quarantines").fetchone()[0]
            ),
            "conflicts": int(connection.execute("SELECT count(*) FROM conflicts").fetchone()[0]),
        }
        return {
            **metadata,
            **counts,
            "freshness_warning": _freshness_warning(metadata.get("synced_at", "")),
        }
    finally:
        connection.close()


def source_rows(path: Path, page_ids: list[str]) -> list[dict[str, str | None]]:
    connection = _required_read_only(path)
    try:
        rows: list[dict[str, str | None]] = []
        for page_id in page_ids:
            row = connection.execute(
                """
                SELECT page_id, title, local_relative_path, docmost_url, source_hash, status
                FROM pages WHERE page_id = ?
                """,
                (page_id,),
            ).fetchone()
            if row is None or row[5] != "active":
                raise ValueError("A selected source is missing or excluded from search")
            rows.append(
                {
                    "page_id": str(row[0]),
                    "title": str(row[1]),
                    "local_relative_path": str(row[2]),
                    "docmost_url": str(row[3]) if row[3] is not None else None,
                    "source_hash": str(row[4]),
                }
            )
        return rows
    finally:
        connection.close()


def indexed_page_hashes(path: Path) -> dict[str, tuple[str, str]]:
    connection = _required_read_only(path)
    try:
        return {
            str(page_id): (str(normalized_hash), str(status))
            for page_id, normalized_hash, status in connection.execute(
                "SELECT page_id, normalized_hash, status FROM pages"
            )
        }
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE pages(
            page_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            title TEXT NOT NULL,
            hierarchy TEXT NOT NULL,
            updated_at TEXT,
            docmost_url TEXT,
            local_relative_path TEXT NOT NULL UNIQUE,
            source_hash TEXT NOT NULL,
            normalized_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'quarantined', 'deleted'))
        );
        CREATE TABLE chunks(
            chunk_id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            heading TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            vector BLOB NOT NULL,
            vector_norm REAL NOT NULL,
            UNIQUE(page_id, ordinal)
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(content, chunk_id UNINDEXED, page_id UNINDEXED);
        CREATE TABLE quarantines(page_id TEXT PRIMARY KEY);
        CREATE TABLE conflicts(page_id TEXT PRIMARY KEY);
        """
    )


def _reuse_page_chunks(
    old: sqlite3.Connection,
    new: sqlite3.Connection,
    document: SourceDocument,
) -> bool:
    old_page = old.execute(
        "SELECT normalized_hash, source_hash, status FROM pages WHERE page_id = ?",
        (document.page_id,),
    ).fetchone()
    if old_page != (document.normalized_hash, document.source_hash, "active"):
        return False
    rows = list(
        old.execute(
            """
            SELECT chunk_id, ordinal, heading, content, token_count, source_hash,
                   vector, vector_norm
            FROM chunks WHERE page_id = ? ORDER BY ordinal
            """,
            (document.page_id,),
        )
    )
    for row in rows:
        new.execute(
            """
            INSERT INTO chunks(
                chunk_id, page_id, ordinal, heading, content, token_count,
                source_hash, vector, vector_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row[0], document.page_id, *row[1:]),
        )
        new.execute(
            "INSERT INTO chunks_fts(content, chunk_id, page_id) VALUES (?, ?, ?)",
            (row[3], row[0], document.page_id),
        )
    return True


def _insert_chunk(
    connection: sqlite3.Connection,
    *,
    document: SourceDocument,
    ordinal: int,
    heading: str,
    text: str,
    token_count: int,
    vector: list[float],
    dimensions: int,
) -> None:
    if len(vector) != dimensions:
        raise RuntimeError("Embedding vector dimension mismatch")
    vector_norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(vector_norm) or vector_norm == 0:
        raise RuntimeError("Embedding vector norm is invalid")
    chunk_id = f"{document.page_id}:{ordinal}:{document.normalized_hash[:16]}"
    blob = struct.pack(f"<{dimensions}f", *vector)
    connection.execute(
        """
        INSERT INTO chunks(
            chunk_id, page_id, ordinal, heading, content, token_count,
            source_hash, vector, vector_norm
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            document.page_id,
            ordinal,
            heading,
            text,
            token_count,
            document.source_hash,
            blob,
            vector_norm,
        ),
    )
    connection.execute(
        "INSERT INTO chunks_fts(content, chunk_id, page_id) VALUES (?, ?, ?)",
        (text, chunk_id, document.page_id),
    )


def _lexical_candidates(connection: sqlite3.Connection, question: str) -> list[str]:
    terms = list(dict.fromkeys(term.lower() for term in _SEARCH_TERM.findall(question)))
    if not terms:
        return []
    query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:20])
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT chunk_id FROM chunks_fts
            WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?
            """,
            (query, RETRIEVAL_CANDIDATES),
        )
    ]


def _semantic_candidates(
    connection: sqlite3.Connection,
    question: str,
    backend: EmbeddingBackend,
) -> list[str]:
    query = backend.embed_query(question)
    if len(query) != backend.dimensions:
        raise RuntimeError("Query embedding dimension mismatch")
    query_norm = math.sqrt(sum(value * value for value in query))
    if not math.isfinite(query_norm) or query_norm == 0:
        raise RuntimeError("Query embedding norm is invalid")
    scored: list[tuple[float, str]] = []
    for chunk_id, blob, vector_norm in connection.execute(
        "SELECT chunk_id, vector, vector_norm FROM chunks"
    ):
        vector = struct.unpack(f"<{backend.dimensions}f", blob)
        score = sum(left * right for left, right in zip(query, vector, strict=True)) / (
            query_norm * float(vector_norm)
        )
        scored.append((score, str(chunk_id)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [chunk_id for _, chunk_id in scored[:RETRIEVAL_CANDIDATES]]


def _context_prefix(document: SourceDocument) -> str:
    hierarchy = " > ".join((*document.hierarchy, document.title))
    return (
        f"Space: {document.space_id}\n"
        f"Hierarchy: {hierarchy}\n"
        f"Title: {document.title}\n"
        f"Updated: {document.updated_at or 'unknown'}"
    )


def _metadata_matches(
    connection: sqlite3.Connection,
    model_version: str,
    dimensions: int,
) -> bool:
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.Error:
        return False
    return (
        metadata.get("index_schema_version") == INDEX_SCHEMA_VERSION
        and metadata.get("model_version") == model_version
        and metadata.get("embedding_dimensions") == str(dimensions)
    )


def _freshness_warning(synced_at: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
    except ValueError:
        return "Lab Wiki freshness is unknown; run an explicit sync."
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if datetime.now(UTC) - parsed > timedelta(hours=FRESHNESS_WARNING_HOURS):
        return "Lab Wiki index is older than 36 hours; run an explicit sync."
    return None


def _required_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Lab Wiki index is missing; initialize or rebuild it")
    connection = _open_read_only(path)
    assert connection is not None
    return connection


def _open_read_only(path: Path | None) -> sqlite3.Connection | None:
    if path is None:
        return None
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection
