#!/usr/bin/env python3
"""Deterministic contracts for private paper-review reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urlparse


class ReviewContractError(ValueError):
    """A stable validation failure without private source content."""


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ZOTERO_KEY = re.compile(r"[A-Z0-9]{8}\Z")
_MANAGED_PREFIXES = ("Paper Review ID:", "Docmost:", "Zotero:")
_DEFAULT_ASSIGNEE_ALIASES = ("Jialuo Hu", "Jialuo")
_REVIEW_TABLE_COLUMNS = ("Paper Number", "Review Comments", "Word Count")
_ASSIGNEE_COLUMNS = ("Reviewer", "Assigned To")
_VENUE_ALIASES = {
    "socc": "socc",
    "acm socc": "socc",
    "acm symposium on cloud computing": "socc",
    "tmc": "tmc",
    "ieee tmc": "tmc",
    "ieee transactions on mobile computing": "tmc",
}


def _single_line(value: object, field: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if not normalized or _CONTROL.search(normalized):
        raise ReviewContractError(f"invalid_{field}")
    return normalized


def normalize_paper_number(value: object) -> str:
    """Normalize whitespace while preserving the source paper-number spelling."""

    number = " ".join(_single_line(value, "paper_number").split())
    if "|" in number or len(number) > 250:
        raise ReviewContractError("invalid_paper_number")
    return number


def normalize_venue_slug(value: object) -> str:
    """Return the stable venue slug shared by all managed objects."""

    venue = " ".join(_single_line(value, "venue").casefold().split())
    if len(venue) > 250:
        raise ReviewContractError("invalid_venue")
    alias = _VENUE_ALIASES.get(venue)
    if alias is not None:
        return alias
    slug = _NON_ALNUM.sub("-", venue).strip("-")
    if not slug:
        raise ReviewContractError("invalid_venue")
    return slug


def paper_review_identity(venue: object, year: object, paper_number: object) -> str:
    """Build ``<venue>|<year>|<paper-number>`` with bounded components."""

    year_text = _single_line(year, "year")
    if re.fullmatch(r"\d{4}", year_text) is None:
        raise ReviewContractError("invalid_year")
    return f"{normalize_venue_slug(venue)}|{year_text}|{normalize_paper_number(paper_number)}"


def normalize_assignee(value: object) -> str:
    """Normalize exactly one plain Docmost mention marker, failing closed on multiples."""

    assignee = unicodedata.normalize("NFKC", str(value)).strip()
    if assignee.startswith("@"):
        assignee = assignee[1:].strip()
    if not assignee or "@" in assignee or _CONTROL.search(assignee):
        raise ReviewContractError("invalid_assignee")
    return " ".join(assignee.split())


def _row_assignee(row: Mapping[str, object]) -> str:
    values: list[str] = []
    for field in ("Reviewer", "Assigned To"):
        raw = row.get(field)
        if raw is not None and str(raw).strip():
            values.append(normalize_assignee(raw))
    if not values:
        raise ReviewContractError("missing_assignee")
    if len(set(values)) != 1:
        raise ReviewContractError("conflicting_assignee_columns")
    return values[0]


def active_assignment_rows(
    rows: Sequence[Mapping[str, object]], *, target: str | None = None
) -> list[dict[str, object]]:
    """Filter rows by confirmed exact assignee aliases and blank word counts."""

    targets = _DEFAULT_ASSIGNEE_ALIASES if target is None else (target,)
    target_names = {normalize_assignee(value) for value in targets}
    active: list[dict[str, object]] = []
    for row in rows:
        try:
            assignee = _row_assignee(row)
        except ReviewContractError as error:
            if str(error) == "conflicting_assignee_columns":
                raise
            continue
        word_count = str(row.get("Word Count", ""))
        if assignee in target_names and not word_count.strip():
            active.append(dict(row))
    return active


def resolve_edition_folder(
    assignment_paper_numbers: Sequence[object],
    edition_folders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Resolve one pre-existing edition folder from assignment/child overlap.

    Callers must first limit ``edition_folders`` to one already-resolved
    conference folder. A deadline year is intentionally not an input.
    """

    if isinstance(assignment_paper_numbers, (str, bytes)):
        raise ReviewContractError("invalid_assignment_paper_numbers")
    assignment_numbers = {
        normalize_paper_number(number) for number in assignment_paper_numbers
    }
    if not assignment_numbers:
        raise ReviewContractError("missing_assignment_paper_numbers")

    matches: list[dict[str, object]] = []
    for candidate in edition_folders:
        folder_id = _single_line(candidate.get("id", ""), "edition_folder_id")
        folder_title = _single_line(
            candidate.get("title", ""), "edition_folder_title"
        )
        raw_numbers = candidate.get("paper_numbers")
        if not isinstance(raw_numbers, Sequence) or isinstance(raw_numbers, (str, bytes)):
            raise ReviewContractError("invalid_edition_paper_numbers")
        child_numbers = {normalize_paper_number(number) for number in raw_numbers}
        overlap = sorted(assignment_numbers & child_numbers)
        if overlap:
            matches.append(
                {"id": folder_id, "title": folder_title, "overlap": overlap}
            )

    if not matches:
        raise ReviewContractError("missing_edition_mapping")
    if len(matches) != 1:
        raise ReviewContractError("ambiguous_edition_mapping")
    return matches[0]


def _safe_filename(value: object) -> str:
    filename = _single_line(value, "filename")
    if filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ReviewContractError("invalid_filename")
    return filename


def _attachment_id(value: object) -> str:
    return _single_line(value, "attachment_id")


def _full_number_match(stem: str, paper_number: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(paper_number.casefold())}(?![a-z0-9])"
    return re.search(pattern, stem.casefold()) is not None


def match_row_attachments(
    paper_number: object, attachments: Sequence[Mapping[str, object]]
) -> dict[str, str | None]:
    """Resolve exactly one PDF and at most one TXT without using list order."""

    number = normalize_paper_number(paper_number)
    numeric = number.isdecimal()
    pdf_matches: list[str] = []
    text_matches: list[str] = []
    for attachment in attachments:
        filename = _safe_filename(attachment.get("filename", ""))
        identifier = _attachment_id(attachment.get("attachment_id", ""))
        lower = filename.casefold()
        stem, dot, extension = lower.rpartition(".")
        if not dot:
            continue
        full_match = _full_number_match(stem, number)
        pdf_match = full_match or (
            numeric
            and re.search(
                rf"(?<![a-z0-9])paper{re.escape(number)}(?![a-z0-9])", stem
            )
            is not None
        )
        text_match = full_match or (
            numeric
            and re.search(
                rf"(?<![a-z0-9])review{re.escape(number)}(?![a-z0-9])", stem
            )
            is not None
        )
        if extension == "pdf" and pdf_match:
            pdf_matches.append(identifier)
        elif extension == "txt" and text_match:
            text_matches.append(identifier)
    if len(pdf_matches) != 1:
        raise ReviewContractError("missing_or_ambiguous_pdf")
    if len(text_matches) > 1:
        raise ReviewContractError("ambiguous_review_form")
    return {"pdf_attachment_id": pdf_matches[0], "txt_attachment_id": text_matches[0] if text_matches else None}


def _https_url(value: object, field: str) -> str:
    url = _single_line(value, field)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ReviewContractError(f"invalid_{field}")
    return url


def _zotero_key(value: object, field: str) -> str:
    key = _single_line(value, field)
    if _ZOTERO_KEY.fullmatch(key) is None:
        raise ReviewContractError(f"invalid_{field}")
    return key


def managed_description_lines(
    *,
    identity: object,
    assignment_url: object,
    review_page_url: object | None,
    attachment_key: object | None,
    parent_key: object | None,
) -> list[str]:
    """Build exactly the three Todoist-owned description lines."""

    review_id = _single_line(identity, "identity")
    assignment = _https_url(assignment_url, "assignment_url")
    if review_page_url is None:
        docmost = f"Docmost: [Review assignment]({assignment}) · Review page: repair-needed"
    else:
        page = _https_url(review_page_url, "review_page_url")
        docmost = f"Docmost: [Review assignment]({assignment}) · [Review page]({page})"
    if attachment_key is None and parent_key is None:
        zotero = "Zotero: repair-needed"
    elif attachment_key is None or parent_key is None:
        raise ReviewContractError("partial_zotero_keys")
    else:
        attachment = _zotero_key(attachment_key, "attachment_key")
        parent = _zotero_key(parent_key, "parent_key")
        zotero = (
            f"Zotero: [Open PDF](zotero://open-pdf/library/items/{attachment}) · "
            f"[Show item](zotero://select/library/items/{parent})"
        )
    return [f"Paper Review ID: {review_id}", docmost, zotero]


def merge_managed_description(description: str, managed_lines: Sequence[str]) -> str:
    """Replace/deduplicate managed lines and preserve every unrelated line."""

    if len(managed_lines) != len(_MANAGED_PREFIXES):
        raise ReviewContractError("invalid_managed_lines")
    replacements = {
        prefix: _single_line(line, "managed_line")
        for prefix, line in zip(_MANAGED_PREFIXES, managed_lines)
    }
    output: list[str] = []
    emitted: set[str] = set()
    for line in description.splitlines():
        prefix = next((candidate for candidate in _MANAGED_PREFIXES if line.startswith(candidate)), None)
        if prefix is None:
            output.append(line)
        elif prefix not in emitted:
            output.append(replacements[prefix])
            emitted.add(prefix)
    missing = [replacements[prefix] for prefix in _MANAGED_PREFIXES if prefix not in emitted]
    if missing:
        while output and output[-1] == "":
            output.pop()
        if output:
            output.append("")
        output.extend(missing)
    return "\n".join(output)


def classify_reconciliation(
    *,
    task_matches: int,
    zotero_matches: int,
    page_matches: int,
    task_healthy: bool,
    zotero_healthy: bool,
    page_healthy: bool,
) -> Literal["new", "healthy", "repair-needed", "ambiguous"]:
    """Classify one assignment without proposing duplicate creation."""

    counts = (task_matches, zotero_matches, page_matches)
    if any(count < 0 for count in counts):
        raise ReviewContractError("invalid_match_count")
    if any(count > 1 for count in counts):
        return "ambiguous"
    if counts == (0, 0, 0):
        return "new"
    if counts == (1, 1, 1) and task_healthy and zotero_healthy and page_healthy:
        return "healthy"
    return "repair-needed"


def _uuid_text(value: object, field: str) -> str:
    raw = _single_line(value, field)
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as error:
        raise ReviewContractError(f"invalid_{field}") from error
    if str(parsed) != raw.casefold():
        raise ReviewContractError(f"invalid_{field}")
    return str(parsed)


def _slug_id(value: object) -> str:
    slug = _single_line(value, "slug_id")
    if len(slug) > 100 or re.fullmatch(r"[A-Za-z0-9_-]+", slug) is None:
        raise ReviewContractError("invalid_slug_id")
    return slug


def _node_text(node: object) -> str:
    """Render user-visible ProseMirror text, including mention labels."""

    if not isinstance(node, Mapping):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "mention":
        attrs = node.get("attrs")
        return str(attrs.get("label", "")) if isinstance(attrs, Mapping) else ""
    content = node.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return ""
    separator = "" if node_type in {"paragraph", "heading"} else "\n"
    return separator.join(_node_text(child) for child in content)


def _normalized_node_text(node: object) -> str:
    return " ".join(_node_text(node).split())


def _iter_nodes(node: object):
    if not isinstance(node, Mapping):
        return
    yield node
    content = node.get("content")
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        for child in content:
            yield from _iter_nodes(child)


def _has_nonmention_link(node: Mapping[str, object]) -> bool:
    for candidate in _iter_nodes(node):
        if candidate.get("type") == "link":
            return True
        marks = candidate.get("marks")
        if isinstance(marks, Sequence) and not isinstance(marks, (str, bytes)):
            if any(
                isinstance(mark, Mapping) and mark.get("type") == "link"
                for mark in marks
            ):
                return True
    return False


def _document_nodes(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    if document.get("type") != "doc":
        raise ReviewContractError("invalid_review_assignment_document")
    content = document.get("content")
    if not isinstance(content, list) or not all(isinstance(node, Mapping) for node in content):
        raise ReviewContractError("invalid_review_assignment_document")
    return content


def _table_headers(table: Mapping[str, object]) -> dict[str, int] | None:
    rows = table.get("content")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
        return None
    header_row = rows[0]
    if header_row.get("type") != "tableRow":
        return None
    cells = header_row.get("content")
    if not isinstance(cells, list) or not cells:
        return None

    headers: dict[str, int] = {}
    for index, cell in enumerate(cells):
        if not isinstance(cell, Mapping) or cell.get("type") != "tableHeader":
            return None
        attrs = cell.get("attrs")
        if not isinstance(attrs, Mapping):
            raise ReviewContractError("unsupported_review_table_shape")
        if attrs.get("colspan", 1) != 1 or attrs.get("rowspan", 1) != 1:
            raise ReviewContractError("unsupported_review_table_shape")
        label = _normalized_node_text(cell)
        if not label:
            return None
        if label in headers:
            raise ReviewContractError("duplicate_review_table_header")
        headers[label] = index

    required = set(_REVIEW_TABLE_COLUMNS)
    if not required.issubset(headers):
        return None
    if not any(column in headers for column in _ASSIGNEE_COLUMNS):
        return None
    return headers


def _section_table(
    document_nodes: Sequence[Mapping[str, object]], section_heading: str
) -> tuple[int, Mapping[str, object], int, Mapping[str, object], dict[str, int]] | dict[str, str]:
    heading_matches = [
        index
        for index, node in enumerate(document_nodes)
        if node.get("type") == "heading"
        and _normalized_node_text(node) == section_heading
    ]
    if not heading_matches:
        return {"status": "conflict", "reason": "missing_section"}
    if len(heading_matches) != 1:
        return {"status": "conflict", "reason": "duplicate_section"}

    heading_index = heading_matches[0]
    heading_node = document_nodes[heading_index]
    attrs = heading_node.get("attrs")
    heading_level = attrs.get("level", 6) if isinstance(attrs, Mapping) else 6
    section_end = len(document_nodes)
    for index in range(heading_index + 1, len(document_nodes)):
        candidate = document_nodes[index]
        candidate_attrs = candidate.get("attrs")
        candidate_level = (
            candidate_attrs.get("level", 6)
            if isinstance(candidate_attrs, Mapping)
            else 6
        )
        if candidate.get("type") == "heading" and candidate_level <= heading_level:
            section_end = index
            break

    table_matches: list[tuple[int, Mapping[str, object], dict[str, int]]] = []
    try:
        for index in range(heading_index + 1, section_end):
            candidate = document_nodes[index]
            if candidate.get("type") != "table":
                continue
            headers = _table_headers(candidate)
            if headers is not None:
                table_matches.append((index, candidate, headers))
    except ReviewContractError as error:
        return {"status": "conflict", "reason": str(error)}
    if not table_matches:
        return {"status": "conflict", "reason": "missing_review_table"}
    if len(table_matches) != 1:
        return {"status": "conflict", "reason": "duplicate_review_table"}
    table_index, table, headers = table_matches[0]
    return heading_index, heading_node, table_index, table, headers


def _review_target(value: Mapping[str, object]) -> dict[str, str]:
    paper_number = normalize_paper_number(value.get("paper_number", ""))
    section_heading = " ".join(
        _single_line(value.get("section_heading", ""), "section_heading").split()
    )
    page_title = normalize_paper_number(value.get("title", ""))
    if page_title != paper_number:
        raise ReviewContractError("page_title_mismatch")
    return {
        "paper_number": paper_number,
        "section_heading": section_heading,
        "page_id": _uuid_text(value.get("page_id", ""), "page_id"),
        "slug_id": _slug_id(value.get("slug_id", "")),
        "page_title": page_title,
        "page_url": _https_url(value.get("url", ""), "page_url"),
        "mention_id": _uuid_text(value.get("mention_id", ""), "mention_id"),
    }


def _classify_review_comment_cell(
    cell: Mapping[str, object], target: Mapping[str, str]
) -> tuple[str, str | None, Mapping[str, object] | None]:
    mentions = [node for node in _iter_nodes(cell) if node.get("type") == "mention"]
    page_mentions = [
        node
        for node in mentions
        if isinstance(node.get("attrs"), Mapping)
        and node["attrs"].get("entityType") == "page"
    ]
    canonical_mentions = [
        node
        for node in page_mentions
        if node["attrs"].get("label") == target["paper_number"]
        and node["attrs"].get("entityId") == target["page_id"]
        and node["attrs"].get("slugId") == target["slug_id"]
    ]
    other_mentions = [node for node in mentions if node not in page_mentions]
    has_link = _has_nonmention_link(cell)

    if len(canonical_mentions) == 1 and len(page_mentions) == 1 and not other_mentions and not has_link:
        return "linked", None, canonical_mentions[0]
    if mentions or has_link:
        if len(canonical_mentions) > 1:
            return "conflict", "duplicate_canonical_link", None
        return "conflict", "wrong_or_non_native_link", None
    if _normalized_node_text(cell):
        return "conflict", "nonblank_without_canonical_link", None

    content = cell.get("content")
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], Mapping)
        or content[0].get("type") != "paragraph"
    ):
        return "conflict", "unsupported_blank_cell_shape", None
    return "blank", None, content[0]


def _locate_review_comment_target(
    document_nodes: Sequence[Mapping[str, object]], target: Mapping[str, str]
) -> dict[str, object]:
    section = _section_table(document_nodes, target["section_heading"])
    if isinstance(section, dict):
        return section
    heading_index, heading_node, table_index, table, headers = section
    rows = table.get("content")
    if not isinstance(rows, list):
        return {"status": "conflict", "reason": "unsupported_review_table_shape"}

    paper_index = headers["Paper Number"]
    matches: list[tuple[int, list[Mapping[str, object]]]] = []
    for row_index, row in enumerate(rows[1:], start=1):
        if not isinstance(row, Mapping) or row.get("type") != "tableRow":
            continue
        cells = row.get("content")
        if not isinstance(cells, list) or not all(isinstance(cell, Mapping) for cell in cells):
            return {"status": "conflict", "reason": "unsupported_review_table_shape"}
        if len(cells) != len(headers):
            return {"status": "conflict", "reason": "unsupported_review_table_shape"}
        if any(
            not isinstance(cell.get("attrs"), Mapping)
            or cell["attrs"].get("colspan", 1) != 1
            or cell["attrs"].get("rowspan", 1) != 1
            for cell in cells
        ):
            return {"status": "conflict", "reason": "unsupported_review_table_shape"}
        if _normalized_node_text(cells[paper_index]) == target["paper_number"]:
            matches.append((row_index, cells))
    if not matches:
        return {"status": "conflict", "reason": "missing_paper_row"}
    if len(matches) != 1:
        return {"status": "conflict", "reason": "duplicate_paper_row"}

    row_index, cells = matches[0]
    row_values = {
        column: _normalized_node_text(cells[index]) for column, index in headers.items()
    }
    try:
        assignee = _row_assignee(row_values)
    except ReviewContractError as error:
        return {"status": "conflict", "reason": str(error)}
    if assignee not in _DEFAULT_ASSIGNEE_ALIASES:
        return {"status": "conflict", "reason": "reviewer_mismatch"}
    if row_values["Word Count"]:
        return {"status": "conflict", "reason": "word_count_filled"}

    comments_index = headers["Review Comments"]
    comments_cell = cells[comments_index]
    status, reason, matched_node = _classify_review_comment_cell(comments_cell, target)
    base_path = f"/content/{table_index}/content/{row_index}/content"
    result: dict[str, object] = {
        "status": status,
        "paper_number": target["paper_number"],
        "section_heading": target["section_heading"],
        "page_url": target["page_url"],
        "cell_path": f"{base_path}/{comments_index}",
    }
    if reason is not None:
        result["reason"] = reason
        return result
    if status == "linked":
        result["mention"] = matched_node
        return result

    mention = {
        "type": "mention",
        "attrs": {
            "id": target["mention_id"],
            "label": target["paper_number"],
            "slugId": target["slug_id"],
            "entityId": target["page_id"],
            "creatorId": target["creator_id"],
            "entityType": "page",
        },
    }
    reviewer_indexes = [headers[column] for column in _ASSIGNEE_COLUMNS if column in headers]
    result["mention"] = mention
    result["patch"] = [
        {"op": "test", "path": f"/content/{heading_index}", "value": heading_node},
        {
            "op": "test",
            "path": f"/content/{table_index}/content/0",
            "value": rows[0],
        },
        {
            "op": "test",
            "path": f"{base_path}/{paper_index}",
            "value": cells[paper_index],
        },
        *[
            {
                "op": "test",
                "path": f"{base_path}/{index}",
                "value": cells[index],
            }
            for index in reviewer_indexes
        ],
        {
            "op": "test",
            "path": f"{base_path}/{comments_index}",
            "value": comments_cell,
        },
        {
            "op": "test",
            "path": f"{base_path}/{headers['Word Count']}",
            "value": cells[headers["Word Count"]],
        },
        {
            "op": "add",
            "path": f"{base_path}/{comments_index}/content/0/content",
            "value": [mention],
        },
    ]
    return result


def plan_review_comments_links(
    document: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
    *,
    creator_id: object,
) -> dict[str, object]:
    """Classify canonical review links and emit one guarded batch patch."""

    document_nodes = _document_nodes(document)
    creator = _uuid_text(creator_id, "creator_id")
    if isinstance(targets, (str, bytes)) or not targets:
        raise ReviewContractError("invalid_review_link_targets")
    normalized_targets: list[dict[str, str]] = []
    target_keys: set[tuple[str, str]] = set()
    mention_ids: set[str] = set()
    for raw_target in targets:
        if not isinstance(raw_target, Mapping):
            raise ReviewContractError("invalid_review_link_target")
        target = _review_target(raw_target)
        target["creator_id"] = creator
        key = (target["section_heading"], target["paper_number"])
        if key in target_keys:
            raise ReviewContractError("duplicate_review_link_target")
        if target["mention_id"] in mention_ids:
            raise ReviewContractError("duplicate_mention_id")
        target_keys.add(key)
        mention_ids.add(target["mention_id"])
        normalized_targets.append(target)

    results = [
        _locate_review_comment_target(document_nodes, target)
        for target in normalized_targets
    ]
    if any(result["status"] == "conflict" for result in results):
        for result in results:
            result.pop("patch", None)
        return {"ready": False, "results": results, "patch": []}
    patch = [operation for result in results for operation in result.get("patch", [])]
    for result in results:
        result.pop("patch", None)
    return {"ready": True, "results": results, "patch": patch}


def _json_stdin() -> Any:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        raise ReviewContractError("invalid_json_input") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identity = commands.add_parser("identity")
    identity.add_argument("--venue", required=True)
    identity.add_argument("--year", required=True)
    identity.add_argument("--paper-number", required=True)
    active = commands.add_parser("active-rows")
    active.add_argument("--target")
    match = commands.add_parser("match-attachments")
    match.add_argument("--paper-number", required=True)
    commands.add_parser("resolve-edition-folder")
    commands.add_parser("review-comments-link")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "identity":
            result: object = paper_review_identity(args.venue, args.year, args.paper_number)
        elif args.command == "active-rows":
            rows = _json_stdin()
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ReviewContractError("invalid_rows")
            result = active_assignment_rows(rows, target=args.target)
        elif args.command == "match-attachments":
            attachments = _json_stdin()
            if not isinstance(attachments, list) or not all(
                isinstance(attachment, dict) for attachment in attachments
            ):
                raise ReviewContractError("invalid_attachments")
            result = match_row_attachments(args.paper_number, attachments)
        elif args.command == "resolve-edition-folder":
            payload = _json_stdin()
            if not isinstance(payload, dict):
                raise ReviewContractError("invalid_edition_input")
            assignment_numbers = payload.get("assignment_paper_numbers")
            edition_folders = payload.get("edition_folders")
            if (
                not isinstance(assignment_numbers, list)
                or not isinstance(edition_folders, list)
                or not all(isinstance(folder, dict) for folder in edition_folders)
            ):
                raise ReviewContractError("invalid_edition_input")
            result = resolve_edition_folder(assignment_numbers, edition_folders)
        else:
            payload = _json_stdin()
            if not isinstance(payload, dict):
                raise ReviewContractError("invalid_review_link_input")
            document = payload.get("document")
            targets = payload.get("targets")
            if not isinstance(document, dict) or not isinstance(targets, list):
                raise ReviewContractError("invalid_review_link_input")
            result = plan_review_comments_links(
                document,
                targets,
                creator_id=payload.get("creator_id", ""),
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ReviewContractError as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
