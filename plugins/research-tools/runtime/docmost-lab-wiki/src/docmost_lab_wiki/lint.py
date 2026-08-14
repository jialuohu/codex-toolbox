"""Strictly read-only Lab Wiki validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from docmost_lab_wiki.config import WikiConfig
from docmost_lab_wiki.index import indexed_page_hashes
from docmost_lab_wiki.notes import (
    NoteConflict,
    SourceDocument,
    parse_frontmatter,
    source_document_from_note,
)


@dataclass(frozen=True)
class LintIssue:
    code: str
    path: str
    page_id: str | None = None


@dataclass(frozen=True)
class LintReport:
    source_notes: int
    synthesis_notes: int
    stale_syntheses: int
    issues: tuple[LintIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def lint_wiki(config: WikiConfig) -> LintReport:
    """Validate notes and index without creating SQLite journals or vault files."""

    issues: list[LintIssue] = []
    sources: dict[str, SourceDocument] = {}
    source_paths = sorted((config.wiki_root / "Sources" / "Docmost").glob("*/*.md"))
    for path in source_paths:
        relative = path.relative_to(config.wiki_root).as_posix()
        try:
            document = source_document_from_note(path, config.wiki_root)
        except (OSError, UnicodeError, NoteConflict):
            issues.append(LintIssue(code="invalid-managed-source", path=relative))
            continue
        if document.page_id in sources:
            issues.append(
                LintIssue(
                    code="duplicate-source-id",
                    path=relative,
                    page_id=document.page_id,
                )
            )
            continue
        sources[document.page_id] = document
        if document.status == "active" and not document.url:
            issues.append(
                LintIssue(
                    code="missing-docmost-url",
                    path=relative,
                    page_id=document.page_id,
                )
            )
    try:
        indexed = indexed_page_hashes(config.index_path)
    except (RuntimeError, ValueError):
        indexed = {}
        issues.append(LintIssue(code="missing-or-invalid-index", path="(private index)"))
    expected_index = {
        page_id: (document.normalized_hash, document.status)
        for page_id, document in sources.items()
    }
    for page_id in sorted(set(expected_index) | set(indexed)):
        if expected_index.get(page_id) != indexed.get(page_id):
            path = sources[page_id].local_relative_path if page_id in sources else "(private index)"
            issues.append(LintIssue(code="index-coverage-mismatch", path=path, page_id=page_id))

    synthesis_paths: list[Path] = []
    for directory in ("Concepts", "Questions", "Analyses"):
        synthesis_paths.extend(sorted((config.wiki_root / directory).glob("*.md")))
    stale = 0
    for path in synthesis_paths:
        relative = path.relative_to(config.wiki_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(text)
        except (OSError, UnicodeError, NoteConflict):
            issues.append(LintIssue(code="invalid-synthesis-frontmatter", path=relative))
            continue
        citations = frontmatter.get("source_citations")
        if not isinstance(citations, dict) or not citations:
            issues.append(LintIssue(code="missing-synthesis-citations", path=relative))
            continue
        note_stale = False
        citation_map = cast(dict[object, object], citations)
        for page_id, raw_citation in citation_map.items():
            if not isinstance(page_id, str) or not isinstance(raw_citation, dict):
                issues.append(LintIssue(code="invalid-synthesis-citation", path=relative))
                continue
            citation = cast(dict[object, object], raw_citation)
            source = sources.get(page_id)
            source_hash = citation.get("hash")
            local = citation.get("local")
            url = citation.get("url")
            if (
                source is None
                or source.status != "active"
                or not isinstance(source_hash, str)
                or source.source_hash != source_hash
            ):
                note_stale = True
            if (
                not isinstance(local, str)
                or not isinstance(url, str)
                or f"[[{local}" not in text
                or url not in text
            ):
                issues.append(
                    LintIssue(
                        code="missing-synthesis-citation-link",
                        path=relative,
                        page_id=page_id,
                    )
                )
        if note_stale:
            stale += 1
            issues.append(LintIssue(code="stale-synthesis", path=relative))
    return LintReport(
        source_notes=len(source_paths),
        synthesis_notes=len(synthesis_paths),
        stale_syntheses=stale,
        issues=tuple(issues),
    )
