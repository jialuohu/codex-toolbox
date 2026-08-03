"""Behavioral tests for the intentionally small comment Markdown subset."""

from __future__ import annotations

import pytest

from docmost_tools.comment_markdown import MarkdownValidationError, markdown_to_tiptap


def test_paragraph_inline_markup_converts_to_tiptap_nodes() -> None:
    result = markdown_to_tiptap(
        "Plain **bold** *italic* `code` [docs](https://example.test/path)."
    )

    assert result == {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Plain "},
                    {"type": "text", "text": "bold", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": " "},
                    {"type": "text", "text": "italic", "marks": [{"type": "italic"}]},
                    {"type": "text", "text": " "},
                    {"type": "text", "text": "code", "marks": [{"type": "code"}]},
                    {"type": "text", "text": " "},
                    {
                        "type": "text",
                        "text": "docs",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://example.test/path"}}
                        ],
                    },
                    {"type": "text", "text": "."},
                ],
            }
        ],
    }


def test_flat_lists_and_fenced_code_convert_to_starter_kit_nodes() -> None:
    result = markdown_to_tiptap(
        "- first\n- second\n\n1. ordered\n2. next\n\n```python\nprint('safe')\n```"
    )

    assert result == {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "first"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "second"}],
                            }
                        ],
                    },
                ],
            },
            {
                "type": "orderedList",
                "attrs": {"start": 1},
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "ordered"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "next"}],
                            }
                        ],
                    },
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "print('safe')"}],
            },
        ],
    }


def test_plain_paragraph_may_contain_a_pipe_without_becoming_a_table() -> None:
    result = markdown_to_tiptap("latency | throughput")

    assert result["content"] == [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "latency | throughput"}],
        }
    ]


@pytest.mark.parametrize(
    "markdown",
    [
        "<strong>raw</strong>",
        "<!-- raw comment -->",
        "<!DOCTYPE html>",
        "![alt](https://example.test/image.png)",
        "![alt][image-ref]\n\n[image-ref]: https://example.test/image.png",
        "bare ![ image token",
        "| A | B |\n| --- | --- |\n| 1 | 2 |",
        "# unsupported heading",
        "> unsupported quote",
        "- [ ] unsupported task",
        "- parent\n  - nested",
        "[unsafe](javascript:alert(1))",
        "[unsupported](ftp://example.test/file)",
        "**unclosed",
        "````\nunclosed",
        "",
        "   ",
    ],
)
def test_unsupported_or_unsafe_markdown_is_rejected(markdown: str) -> None:
    with pytest.raises(MarkdownValidationError):
        markdown_to_tiptap(markdown)
