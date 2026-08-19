"""Pure contracts for bounded ProseMirror JSON and RFC 6902 patches."""

from __future__ import annotations

from typing import cast

import pytest

from docmost_tools.page_content import (
    InvalidPageContent,
    InvalidPagePatch,
    PagePatchConflict,
    apply_page_patch,
    inspect_page_content,
    validate_patch_operations,
)


def document() -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"id": "p-1", "a/b~c": "old"},
                "content": [{"type": "text", "text": "alpha"}],
            },
            {
                "type": "paragraph",
                "attrs": {"id": "p-2"},
                "content": [{"type": "text", "text": "beta"}],
            },
            {"type": "paragraph", "attrs": {"id": "p-3"}, "content": []},
        ],
    }


def test_inspection_hash_is_canonical_and_preserves_non_ascii_json() -> None:
    first = inspect_page_content(
        {
            "content": [
                {"content": [{"text": "研究", "type": "text"}], "type": "paragraph"}
            ],
            "type": "doc",
        }
    )
    second = inspect_page_content(
        {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "研究"}]}
            ],
        }
    )

    assert first.content_sha256 == second.content_sha256
    assert b"\\u7814" not in first.canonical_bytes
    assert first.document["type"] == "doc"


def test_full_rfc6902_patch_preserves_untouched_values_and_applies_all_operations() -> None:
    current = inspect_page_content(document())
    operations = validate_patch_operations(
        [
            {"op": "test", "path": "/content/0/content/0/text", "value": "alpha"},
            {
                "op": "copy",
                "from": "/content/0/content/0",
                "path": "/content/2/content/0",
            },
            {
                "op": "move",
                "from": "/content/1/content/0",
                "path": "/content/2/content/1",
            },
            {
                "op": "add",
                "path": "/content/0/content/0/marks",
                "value": [{"type": "textStyle", "attrs": {"color": "#ff0000"}}],
            },
            {"op": "replace", "path": "/content/0/content/0/text", "value": "red"},
            {"op": "remove", "path": "/content/2/content/0"},
        ]
    )

    patched = apply_page_patch(current, operations)

    assert current.document == document()
    assert patched.document == {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"id": "p-1", "a/b~c": "old"},
                "content": [
                    {
                        "type": "text",
                        "text": "red",
                        "marks": [
                            {"type": "textStyle", "attrs": {"color": "#ff0000"}}
                        ],
                    }
                ],
            },
            {"type": "paragraph", "attrs": {"id": "p-2"}, "content": []},
            {
                "type": "paragraph",
                "attrs": {"id": "p-3"},
                "content": [{"type": "text", "text": "beta"}],
            },
        ],
    }
    assert patched.content_sha256 != current.content_sha256


def test_json_pointer_escaping_and_array_append_follow_rfc6902() -> None:
    current = inspect_page_content(document())
    operations = validate_patch_operations(
        [
            {
                "op": "replace",
                "path": "/content/0/attrs/a~1b~0c",
                "value": "new",
            },
            {
                "op": "add",
                "path": "/content/2/content/-",
                "value": {"type": "text", "text": "appended"},
            },
        ]
    )

    patched = apply_page_patch(current, operations)

    content = patched.document["content"]
    assert isinstance(content, list)
    first, third = cast(list[object], content)[0], cast(list[object], content)[2]
    assert isinstance(first, dict)
    first_node = cast(dict[str, object], first)
    attrs = first_node.get("attrs")
    assert isinstance(attrs, dict)
    assert cast(dict[str, object], attrs).get("a/b~c") == "new"
    assert isinstance(third, dict)
    assert cast(dict[str, object], third).get("content") == [
        {"type": "text", "text": "appended"}
    ]


def test_copy_is_deep_and_does_not_alias_a_later_source_mutation() -> None:
    current = inspect_page_content(document())
    operations = validate_patch_operations(
        [
            {
                "op": "copy",
                "from": "/content/0",
                "path": "/content/-",
            },
            {"op": "replace", "path": "/content/0/content/0/text", "value": "changed"},
        ]
    )

    patched = apply_page_patch(current, operations)
    content = patched.document["content"]
    assert isinstance(content, list)
    blocks = cast(list[object], content)
    first, copied = blocks[0], blocks[3]
    assert isinstance(first, dict) and isinstance(copied, dict)
    assert cast(dict[str, object], first).get("content") == [
        {"type": "text", "text": "changed"}
    ]
    assert cast(dict[str, object], copied).get("content") == [
        {"type": "text", "text": "alpha"}
    ]


@pytest.mark.parametrize(
    "raw_patch",
    [
        [],
        [{"op": "test", "path": "/content", "value": []}],
        [{"op": "replace", "path": "", "value": {"type": "doc"}}],
        [{"op": "replace", "path": "/type", "value": "paragraph"}],
        [{"op": "replace", "path": "/content/~2", "value": "bad pointer"}],
        [{"op": "remove", "path": f"/content/{'x' * 2_040}"}],
        [{"op": "unknown", "path": "/content"}],
        [{"op": "remove", "path": "/content", "value": "extra"}],
        [{"op": "move", "path": "/content/0"}],
        [{"op": "move", "from": "/type", "path": "/content/0"}],
    ],
)
def test_invalid_or_prohibited_patch_shapes_are_rejected(raw_patch: object) -> None:
    with pytest.raises(InvalidPagePatch):
        validate_patch_operations(raw_patch)


def test_operation_count_and_serialized_patch_size_are_bounded() -> None:
    too_many: list[object] = []
    test_operation: dict[str, object] = {
        "op": "test",
        "path": "/content",
        "value": [],
    }
    for _ in range(100):
        too_many.append(test_operation)
    too_many.append(
        {"op": "add", "path": "/content/-", "value": {"type": "paragraph"}}
    )
    with pytest.raises(InvalidPagePatch, match="between 1 and 100"):
        validate_patch_operations(too_many)

    with pytest.raises(InvalidPagePatch, match="safety bounds"):
        validate_patch_operations(
            [{"op": "add", "path": "/content/-", "value": "x" * 2_000_001}]
        )


@pytest.mark.parametrize(
    "raw_patch",
    [
        [
            {"op": "test", "path": "/content/0/type", "value": "heading"},
            {"op": "remove", "path": "/content/2"},
        ],
        [{"op": "remove", "path": "/content/99"}],
        [{"op": "remove", "path": "/content/not-an-index"}],
        [{"op": "add", "path": "/content/01", "value": {"type": "paragraph"}}],
        [{"op": "move", "from": "/content/0", "path": "/content/0/content/0"}],
    ],
)
def test_non_applicable_patch_operations_are_conflicts(raw_patch: object) -> None:
    operations = validate_patch_operations(raw_patch)
    with pytest.raises(PagePatchConflict):
        apply_page_patch(inspect_page_content(document()), operations)


@pytest.mark.parametrize(
    "raw_patch",
    [
        [{"op": "replace", "path": "/content", "value": "not-a-list"}],
        [{"op": "replace", "path": "/content/0/type", "value": "text"}],
        [{"op": "replace", "path": "/content/0/content/0/text", "value": "alpha"}],
        [
            {"op": "replace", "path": "/content/0/content/0/text", "value": "changed"},
            {"op": "replace", "path": "/content/0/content/0/text", "value": "alpha"},
        ],
    ],
)
def test_invalid_or_noop_final_documents_are_rejected(raw_patch: object) -> None:
    operations = validate_patch_operations(raw_patch)
    with pytest.raises(InvalidPagePatch):
        apply_page_patch(inspect_page_content(document()), operations)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"type": "paragraph", "content": []},
        {"type": "doc", "content": "invalid"},
        {"type": "doc", "content": [{"type": "text", "text": ""}]},
        {"type": "doc", "content": [{"type": "paragraph", "marks": "bold"}]},
    ],
)
def test_malformed_prosemirror_documents_are_rejected(value: object) -> None:
    with pytest.raises(InvalidPageContent):
        inspect_page_content(value)


def test_depth_text_and_serialized_json_are_bounded() -> None:
    deepest: dict[str, object] = {"type": "paragraph"}
    for _ in range(101):
        deepest = {"type": "blockquote", "content": [deepest]}
    with pytest.raises(InvalidPageContent, match="structural"):
        inspect_page_content({"type": "doc", "content": [deepest]})

    with pytest.raises(InvalidPageContent, match="text"):
        inspect_page_content(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "x" * 1_000_001}],
                    }
                ],
            }
        )

    with pytest.raises(InvalidPageContent, match="JSON"):
        inspect_page_content(
            {
                "type": "doc",
                "attrs": {"large": "x" * 4_000_001},
                "content": [],
            }
        )


def test_node_count_is_bounded() -> None:
    paragraphs: list[object] = [{"type": "paragraph"} for _ in range(100_000)]
    with pytest.raises(InvalidPageContent, match="structural"):
        inspect_page_content({"type": "doc", "content": paragraphs})


def test_pathologically_nested_attributes_are_rejected_as_noncanonical_json() -> None:
    nested: dict[str, object] = {}
    for _ in range(10_000):
        nested = {"nested": nested}
    with pytest.raises(InvalidPageContent, match="canonical JSON"):
        inspect_page_content({"type": "doc", "attrs": nested, "content": []})
