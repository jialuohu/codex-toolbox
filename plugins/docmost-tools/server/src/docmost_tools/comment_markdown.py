"""Conservative Markdown-to-Tiptap conversion for page comments.

The comment surface deliberately accepts only structures provided by Docmost's
StarterKit-based editor. Unsupported Markdown is rejected instead of being
silently flattened or interpreted as HTML.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_MAX_COMMENT_MARKDOWN = 20_000
_RAW_HTML = re.compile(
    r"</?[A-Za-z][^>]*>|<!--[\s\S]*?-->|<![A-Za-z][^>]*>",
    re.IGNORECASE,
)
_IMAGE = re.compile(r"!\[[^\]]*\]\(")
_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")
_BULLET = re.compile(r"^([-+*])\s+(.+)$")
_ORDERED = re.compile(r"^(\d+)\.\s+(.+)$")
_UNSUPPORTED_BLOCK = re.compile(
    r"^(?:\s{0,3}#{1,6}\s|\s{0,3}>\s?|\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$)"
)
_REFERENCE_DEFINITION = re.compile(r"^\s*\[[^\]]+\]:")
_TASK_ITEM = re.compile(r"^\[[ xX]\]\s")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class MarkdownValidationError(ValueError):
    """The supplied comment contains syntax outside the approved subset."""


def markdown_to_tiptap(markdown: str) -> dict[str, Any]:
    """Convert conservative comment Markdown into a Tiptap JSON document."""

    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise MarkdownValidationError("comment Markdown must not be empty")
    if len(normalized) > _MAX_COMMENT_MARKDOWN:
        raise MarkdownValidationError(
            f"comment Markdown must be at most {_MAX_COMMENT_MARKDOWN} characters"
        )
    if _CONTROL.search(normalized):
        raise MarkdownValidationError("comment Markdown contains unsupported control characters")
    if _RAW_HTML.search(normalized):
        raise MarkdownValidationError("raw HTML is not supported in comments")
    if _IMAGE.search(normalized):
        raise MarkdownValidationError("images are not supported in comments")

    lines = normalized.split("\n")
    _reject_tables(lines)
    content: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        line = lines[index]
        _validate_block_line(line)

        fence = _FENCE.fullmatch(line)
        if fence is not None:
            node, index = _code_block(lines, index, fence.group(1))
            content.append(node)
            continue

        bullet = _BULLET.fullmatch(line)
        ordered = _ORDERED.fullmatch(line)
        if bullet is not None or ordered is not None:
            node, index = _list_block(lines, index, ordered=ordered is not None)
            content.append(node)
            continue

        paragraph_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            _validate_block_line(candidate)
            if paragraph_lines and (
                _FENCE.fullmatch(candidate)
                or _BULLET.fullmatch(candidate)
                or _ORDERED.fullmatch(candidate)
            ):
                break
            paragraph_lines.append(candidate.strip())
            index += 1
        paragraph_text = " ".join(paragraph_lines)
        content.append({"type": "paragraph", "content": _inline_nodes(paragraph_text)})

    if not content:
        raise MarkdownValidationError("comment Markdown must contain content")
    return {"type": "doc", "content": content}


def _reject_tables(lines: list[str]) -> None:
    for index, line in enumerate(lines):
        if _TABLE_DELIMITER.fullmatch(line) and index > 0 and "|" in lines[index - 1]:
            raise MarkdownValidationError("tables are not supported in comments")


def _validate_block_line(line: str) -> None:
    if line.startswith((" ", "\t")) and line.strip():
        raise MarkdownValidationError("nested or indented blocks are not supported in comments")
    if _UNSUPPORTED_BLOCK.match(line):
        raise MarkdownValidationError("unsupported Markdown block")
    if _REFERENCE_DEFINITION.match(line):
        raise MarkdownValidationError("reference links are not supported in comments")
    if line.startswith("```") and _FENCE.fullmatch(line) is None:
        raise MarkdownValidationError("invalid fenced code block")
    list_match = _BULLET.fullmatch(line) or _ORDERED.fullmatch(line)
    if list_match is not None and _TASK_ITEM.match(list_match.group(2)):
        raise MarkdownValidationError("task lists are not supported in comments")


def _code_block(
    lines: list[str], start: int, language: str
) -> tuple[dict[str, Any], int]:
    code_lines: list[str] = []
    index = start + 1
    while index < len(lines) and lines[index] != "```":
        if lines[index].startswith("```"):
            raise MarkdownValidationError("nested fenced code blocks are not supported")
        code_lines.append(lines[index])
        index += 1
    if index >= len(lines):
        raise MarkdownValidationError("fenced code block is not closed")
    code = "\n".join(code_lines)
    node: dict[str, Any] = {
        "type": "codeBlock",
        "attrs": {"language": language or None},
    }
    if code:
        node["content"] = [{"type": "text", "text": code}]
    return node, index + 1


def _list_block(
    lines: list[str], start: int, *, ordered: bool
) -> tuple[dict[str, Any], int]:
    items: list[dict[str, Any]] = []
    index = start
    first_number = 1
    while index < len(lines):
        line = lines[index]
        match = _ORDERED.fullmatch(line) if ordered else _BULLET.fullmatch(line)
        if match is None:
            other = _BULLET.fullmatch(line) if ordered else _ORDERED.fullmatch(line)
            if other is not None:
                raise MarkdownValidationError("mixed list styles require a blank line")
            break
        item_text = match.group(2)
        if _TASK_ITEM.match(item_text):
            raise MarkdownValidationError("task lists are not supported in comments")
        if ordered and not items:
            first_number = int(match.group(1))
        items.append(
            {
                "type": "listItem",
                "content": [
                    {"type": "paragraph", "content": _inline_nodes(item_text.strip())}
                ],
            }
        )
        index += 1
    node: dict[str, Any] = {
        "type": "orderedList" if ordered else "bulletList",
        "content": items,
    }
    if ordered:
        node["attrs"] = {"start": first_number}
    return node, index


def _inline_nodes(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    nodes: list[dict[str, Any]] = []
    plain: list[str] = []
    index = 0

    def flush_plain() -> None:
        if plain:
            _append_text(nodes, "".join(plain))
            plain.clear()

    while index < len(text):
        if text.startswith("![", index):
            raise MarkdownValidationError("images are not supported in comments")
        if text[index] == "\\":
            if index + 1 >= len(text):
                raise MarkdownValidationError("dangling Markdown escape")
            plain.append(text[index + 1])
            index += 2
            continue
        if text[index] == "[":
            flush_plain()
            label_end = text.find("](", index + 1)
            if label_end < 0:
                raise MarkdownValidationError("link syntax is invalid")
            url_end = text.find(")", label_end + 2)
            if url_end < 0:
                raise MarkdownValidationError("link syntax is invalid")
            label = text[index + 1 : label_end]
            href = text[label_end + 2 : url_end]
            if not label or any(marker in label for marker in "[]`*"):
                raise MarkdownValidationError("link labels must be plain text")
            _validate_link(href)
            _append_text(
                nodes,
                label,
                marks=[{"type": "link", "attrs": {"href": href}}],
            )
            index = url_end + 1
            continue
        if text.startswith("**", index):
            flush_plain()
            end = text.find("**", index + 2)
            if end < 0 or end == index + 2:
                raise MarkdownValidationError("bold markup is not closed")
            value = text[index + 2 : end]
            _validate_plain_marked_text(value)
            _append_text(nodes, value, marks=[{"type": "bold"}])
            index = end + 2
            continue
        if text[index] == "*" and index + 1 < len(text) and not text[index + 1].isspace():
            flush_plain()
            end = text.find("*", index + 1)
            if end < 0 or end == index + 1:
                raise MarkdownValidationError("italic markup is not closed")
            value = text[index + 1 : end]
            _validate_plain_marked_text(value)
            _append_text(nodes, value, marks=[{"type": "italic"}])
            index = end + 1
            continue
        if text[index] == "`":
            flush_plain()
            end = text.find("`", index + 1)
            if end < 0 or end == index + 1:
                raise MarkdownValidationError("inline code is not closed")
            value = text[index + 1 : end]
            if "\n" in value:
                raise MarkdownValidationError("inline code must stay on one line")
            _append_text(nodes, value, marks=[{"type": "code"}])
            index = end + 1
            continue
        plain.append(text[index])
        index += 1

    flush_plain()
    return nodes


def _validate_plain_marked_text(value: str) -> None:
    if any(marker in value for marker in ("*", "`", "[", "]")):
        raise MarkdownValidationError("nested inline Markdown is not supported")


def _validate_link(href: str) -> None:
    if len(href) > 2048 or _CONTROL.search(href):
        raise MarkdownValidationError("link target is invalid")
    parsed = urlsplit(href)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MarkdownValidationError("only absolute HTTP(S) links are supported")


def _append_text(
    nodes: list[dict[str, Any]], text: str, *, marks: list[dict[str, Any]] | None = None
) -> None:
    if not text:
        return
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    nodes.append(node)
