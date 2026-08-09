#!/usr/bin/env python3
"""Deterministic contracts for private paper-review reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urlparse


class ReviewContractError(ValueError):
    """A stable validation failure without private source content."""


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ZOTERO_KEY = re.compile(r"[A-Z0-9]{8}\Z")
_MANAGED_PREFIXES = ("Paper Review ID:", "Docmost:", "Zotero:")
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
    rows: Sequence[Mapping[str, object]], *, target: str = "Jialuo Hu"
) -> list[dict[str, object]]:
    """Filter parsed table rows by exact assignee and blank review comments."""

    target_name = normalize_assignee(target)
    active: list[dict[str, object]] = []
    for row in rows:
        try:
            assignee = _row_assignee(row)
        except ReviewContractError as error:
            if str(error) == "conflicting_assignee_columns":
                raise
            continue
        comments = str(row.get("Review Comments", ""))
        if assignee == target_name and not comments.strip():
            active.append(dict(row))
    return active


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
    active.add_argument("--target", default="Jialuo Hu")
    match = commands.add_parser("match-attachments")
    match.add_argument("--paper-number", required=True)
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
        else:
            attachments = _json_stdin()
            if not isinstance(attachments, list) or not all(
                isinstance(attachment, dict) for attachment in attachments
            ):
                raise ReviewContractError("invalid_attachments")
            result = match_row_attachments(args.paper_number, attachments)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ReviewContractError as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
