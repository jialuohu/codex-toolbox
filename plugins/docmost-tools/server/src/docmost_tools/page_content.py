"""Bounded ProseMirror inspection and guarded RFC 6902 application."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

import jsonpatch  # pyright: ignore[reportMissingTypeStubs]
from jsonpointer import JsonPointerException  # pyright: ignore[reportMissingTypeStubs]
from pydantic import JsonValue, TypeAdapter, ValidationError

from docmost_tools.models import JsonPatchMove, JsonPatchOperation

MAX_PROSEMIRROR_DEPTH = 100
MAX_PROSEMIRROR_NODES = 100_000
MAX_PROSEMIRROR_TEXT_CHARS = 1_000_000
MAX_PROSEMIRROR_JSON_BYTES = 4_000_000
MAX_JSON_PATCH_BYTES = 2_000_000
MAX_JSON_PATCH_OPERATIONS = 100

_PATCH_ADAPTER = TypeAdapter(list[JsonPatchOperation])


class InvalidPageContent(ValueError):
    """The current or patched value is not a bounded ProseMirror document."""


class InvalidPagePatch(ValueError):
    """The patch is malformed, prohibited, or produces no body change."""


class PagePatchConflict(RuntimeError):
    """The valid patch cannot be applied to the exact current document."""


@dataclass(frozen=True)
class InspectedPageContent:
    """A validated document plus its deterministic serialized form and hash."""

    document: dict[str, JsonValue]
    canonical_bytes: bytes
    content_sha256: str


def inspect_page_content(document: object) -> InspectedPageContent:
    """Validate generic ProseMirror structure and enforce resource bounds."""

    if not isinstance(document, dict):
        raise InvalidPageContent("page content must be a ProseMirror object")
    raw_document = cast(dict[str, object], document)
    if raw_document.get("type") != "doc":
        raise InvalidPageContent("page content must be a ProseMirror document")

    node_count = 0
    text_chars = 0
    stack: list[tuple[dict[str, object], int]] = [(raw_document, 0)]
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > MAX_PROSEMIRROR_NODES or depth > MAX_PROSEMIRROR_DEPTH:
            raise InvalidPageContent("page content exceeded structural safety bounds")

        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            raise InvalidPageContent("ProseMirror node type is invalid")

        raw_attrs = node.get("attrs")
        if raw_attrs is not None and not isinstance(raw_attrs, dict):
            raise InvalidPageContent("ProseMirror node attrs are invalid")

        raw_marks = node.get("marks")
        if raw_marks is not None:
            if not isinstance(raw_marks, list):
                raise InvalidPageContent("ProseMirror node marks are invalid")
            for raw_mark in cast(list[object], raw_marks):
                if not isinstance(raw_mark, dict):
                    raise InvalidPageContent("ProseMirror mark is invalid")
                mark = cast(dict[str, object], raw_mark)
                mark_type = mark.get("type")
                if not isinstance(mark_type, str) or not mark_type:
                    raise InvalidPageContent("ProseMirror mark type is invalid")
                mark_attrs = mark.get("attrs")
                if mark_attrs is not None and not isinstance(mark_attrs, dict):
                    raise InvalidPageContent("ProseMirror mark attrs are invalid")

        raw_children = node.get("content")
        if raw_children is not None and not isinstance(raw_children, list):
            raise InvalidPageContent("ProseMirror node content is invalid")
        children = cast(list[object], raw_children) if isinstance(raw_children, list) else None

        raw_text = node.get("text")
        if node_type == "text":
            if not isinstance(raw_text, str) or not raw_text or children is not None:
                raise InvalidPageContent("ProseMirror text node is invalid")
            text_chars += len(raw_text)
            if text_chars > MAX_PROSEMIRROR_TEXT_CHARS:
                raise InvalidPageContent("page text exceeded safety bounds")
        elif raw_text is not None:
            raise InvalidPageContent("non-text ProseMirror node contained text")

        if children is not None:
            if len(children) > MAX_PROSEMIRROR_NODES:
                raise InvalidPageContent("page content exceeded structural safety bounds")
            for child in reversed(children):
                if not isinstance(child, dict):
                    raise InvalidPageContent("ProseMirror child node is invalid")
                stack.append((cast(dict[str, object], child), depth + 1))

    canonical_bytes = _canonical_json_bytes(raw_document, InvalidPageContent)
    if len(canonical_bytes) > MAX_PROSEMIRROR_JSON_BYTES:
        raise InvalidPageContent("page JSON exceeded safety bounds")
    return InspectedPageContent(
        document=cast(dict[str, JsonValue], raw_document),
        canonical_bytes=canonical_bytes,
        content_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def validate_patch_operations(patch: object) -> list[JsonPatchOperation]:
    """Parse a strict, body-scoped, bounded RFC 6902 operation list."""

    try:
        operations = _PATCH_ADAPTER.validate_python(patch)
    except ValidationError as error:
        raise InvalidPagePatch("JSON Patch operations are invalid") from error
    if not operations or len(operations) > MAX_JSON_PATCH_OPERATIONS:
        raise InvalidPagePatch("JSON Patch must contain between 1 and 100 operations")
    raw_patch = [operation.model_dump(mode="json", by_alias=True) for operation in operations]
    patch_bytes = _canonical_json_bytes(raw_patch, InvalidPagePatch)
    if len(patch_bytes) > MAX_JSON_PATCH_BYTES:
        raise InvalidPagePatch("JSON Patch exceeded safety bounds")
    if not any(operation.op != "test" for operation in operations):
        raise InvalidPagePatch("JSON Patch must contain a mutating operation")
    return operations


def apply_page_patch(
    current: InspectedPageContent,
    operations: list[JsonPatchOperation],
) -> InspectedPageContent:
    """Apply all RFC 6902 operations to a copy and validate the final document."""

    for operation in operations:
        if isinstance(operation, JsonPatchMove) and operation.path.startswith(
            f"{operation.from_}/"
        ):
            raise PagePatchConflict("JSON Patch cannot move a value into its child")

    raw_patch = [operation.model_dump(mode="json", by_alias=True) for operation in operations]
    try:
        patched = cast(
            object,
            jsonpatch.JsonPatch(raw_patch).apply(  # pyright: ignore[reportUnknownMemberType]
                current.document, in_place=False
            ),
        )
    except (
        JsonPointerException,
        jsonpatch.JsonPatchConflict,
        jsonpatch.JsonPatchTestFailed,
    ) as error:
        raise PagePatchConflict("JSON Patch did not match current page content") from error
    except jsonpatch.JsonPatchException as error:
        raise InvalidPagePatch("JSON Patch is invalid") from error

    try:
        inspected = inspect_page_content(patched)
    except InvalidPageContent as error:
        raise InvalidPagePatch("JSON Patch produced invalid page content") from error
    if inspected.content_sha256 == current.content_sha256:
        raise InvalidPagePatch("JSON Patch did not change page content")
    return inspected


def _canonical_json_bytes(
    value: object,
    error_type: type[InvalidPageContent] | type[InvalidPagePatch],
) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError) as error:
        raise error_type("value is not canonical JSON") from error
