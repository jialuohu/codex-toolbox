"""Explicit, source-pinned durable synthesis notes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal, cast

from docmost_lab_wiki.config import WikiConfig
from docmost_lab_wiki.constants import NOTES_END, NOTES_START, SYNTHESIS_END, SYNTHESIS_START
from docmost_lab_wiki.index import source_rows
from docmost_lab_wiki.notes import NoteConflict, parse_frontmatter, sanitize_markdown, utc_now

SynthesisKind = Literal["concept", "question", "analysis"]
_SYNTHESIS = re.compile(
    re.escape(SYNTHESIS_START) + r"\n(.*?)\n" + re.escape(SYNTHESIS_END),
    re.DOTALL,
)
_NOTES = re.compile(
    re.escape(NOTES_START) + r"\n(.*?)\n" + re.escape(NOTES_END),
    re.DOTALL,
)


def distill(
    config: WikiConfig,
    *,
    kind: SynthesisKind,
    title: str,
    scope: str,
    body_file: Path,
    source_ids: list[str],
) -> Path:
    """Create or explicitly refresh one synthesis note with immutable source hashes."""

    clean_title = " ".join(title.split()).strip()
    if not clean_title or len(clean_title) > 200:
        raise ValueError("Synthesis title is invalid")
    if not scope.strip() or len(scope) > 2_000:
        raise ValueError("Synthesis scope is invalid")
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("Synthesis sources must be a nonempty unique list")
    if not body_file.is_absolute() or not body_file.is_file() or body_file.is_symlink():
        raise ValueError("Synthesis body file is missing or unsafe")
    body = body_file.read_text(encoding="utf-8")
    if not body.strip() or len(body) > 2_000_000:
        raise ValueError("Synthesis body is empty or too large")
    body = sanitize_markdown(body).strip()
    rows = source_rows(config.index_path, source_ids)
    citations: dict[str, dict[str, str]] = {}
    provenance: list[str] = ["## Source provenance", ""]
    for row in rows:
        page_id = cast(str, row["page_id"])
        local_relative = cast(str, row["local_relative_path"])
        local = (
            Path(*config.wiki_root_relative.parts) / Path(local_relative)
        ).with_suffix("").as_posix()
        url = row["docmost_url"]
        if not isinstance(url, str):
            raise ValueError("A selected source lacks its canonical Docmost URL")
        source_hash = cast(str, row["source_hash"])
        citations[page_id] = {"hash": source_hash, "local": local, "url": url}
        provenance.append(
            f"- [[{local}|Local source]] · [Canonical Docmost]({url}) · "
            f"`sha256:{source_hash}`"
        )
    managed = f"{body}\n\n" + "\n".join(provenance)
    destination = config.wiki_root / _kind_directory(kind) / f"{_slug(clean_title)}.md"
    now = utc_now()
    created_at = now
    personal_notes = ""
    if destination.exists():
        existing = destination.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(existing)
        synthesis_match = _SYNTHESIS.search(existing)
        notes_match = _NOTES.search(existing)
        if synthesis_match is None or notes_match is None:
            raise NoteConflict("Existing synthesis note is not managed by docmost-lab-wiki")
        existing_digest = frontmatter.get("synthesis_hash")
        actual_digest = hashlib.sha256(synthesis_match.group(1).encode("utf-8")).hexdigest()
        if existing_digest != actual_digest:
            raise NoteConflict("Existing synthesis managed region was edited locally")
        personal_notes = notes_match.group(1)
        if isinstance(frontmatter.get("created_at"), str):
            created_at = cast(str, frontmatter["created_at"])
    synthesis_hash = hashlib.sha256(managed.encode("utf-8")).hexdigest()
    metadata: dict[str, object] = {
        "schema": "docmost.lab-wiki-synthesis.v1",
        "title": clean_title,
        "kind": kind,
        "scope": scope.strip(),
        "created_at": created_at,
        "updated_at": now,
        "synthesis_hash": synthesis_hash,
        "source_citations": citations,
    }
    frontmatter_text = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        for key, value in metadata.items()
    )
    rendered = (
        f"---\n{frontmatter_text}\n---\n\n"
        f"{SYNTHESIS_START}\n{managed}\n{SYNTHESIS_END}\n\n"
        f"{NOTES_START}\n{personal_notes}\n{NOTES_END}\n"
    )
    _atomic_write(destination, rendered)
    return destination


def _kind_directory(kind: SynthesisKind) -> str:
    return {"concept": "Concepts", "question": "Questions", "analysis": "Analyses"}[kind]


def _slug(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not normalized:
        normalized = "synthesis"
    return f"{normalized[:80]}-{hashlib.sha256(title.encode('utf-8')).hexdigest()[:8]}"


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
