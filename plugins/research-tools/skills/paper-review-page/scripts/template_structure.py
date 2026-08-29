#!/usr/bin/env python3
"""Blank authoritative HotCRP forms or extract safe structure from peer Markdown."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


_ATX = re.compile(r"^#{1,6}\s+(.{1,120}?)\s*$")
_BOLD = re.compile(r"^\*\*([^*\n]{1,120}?)\*\*:?\s*$")
_HOTCRP = re.compile(r"^\\?==\\?\*==\s+(.{1,120}?)\s*$")
_HOTCRP_CONTROL = re.compile(r"^\\?==(?:\\?\*|\+|-)==(?:\s+|$)")
_HOTCRP_REVIEWER = re.compile(
    r"^(?P<prefix>\\?==\+==\s+Reviewer:)(?:\s+.*)?$", re.IGNORECASE
)
_UNCHECKED = re.compile(r"^- \[ \]\s+(.{1,80}?)\s*$")
_HOTCRP_PLACEHOLDERS = {"(No entry)", "(Your choice here)"}
_REVIEWER_MARKDOWN = "Hao Wang [hwang9@stevens.edu](mailto:hwang9@stevens.edu)"
_ALLOWED_FIELDS = {
    "comments",
    "comments for pc",
    "confidential comments to the committee",
    "confidential comments to the editor",
    "decision",
    "detailed comments",
    "minor comments",
    "overall merit",
    "paper summary",
    "proper use of ai",
    "questions for authors' response",
    "questions for the authors",
    "recommendation",
    "review readiness",
    "reviewer confidence",
    "reviewer expertise",
    "strength",
    "strengths",
    "summary",
    "summary and contributions",
    "weakness",
    "weaknesses",
}
_ALLOWED_OPTIONS = {
    "accept",
    "expert",
    "knowledgeable",
    "major revision",
    "minor revision",
    "no familiarity",
    "reject",
    "some familiarity",
    "strong accept",
    "strong reject",
    "weak accept",
    "weak reject",
}


@dataclass(frozen=True)
class TemplateResult:
    markdown: str
    source: str


def _normalized_label(value: str) -> str:
    return " ".join(value.strip().rstrip(":").replace("’", "'").casefold().split())


def blank_hotcrp_assignment_form(
    markdown: str,
    reviewer_markdown: str = _REVIEWER_MARKDOWN,
) -> str:
    """Preserve a HotCRP form, set its linked reviewer, and clear response data."""

    if not reviewer_markdown.strip() or "\n" in reviewer_markdown or "\r" in reviewer_markdown:
        raise ValueError("invalid_reviewer_identity")

    output: list[str] = []
    control_lines = 0
    reviewer_lines = 0
    for raw_line in markdown.splitlines():
        reviewer = _HOTCRP_REVIEWER.fullmatch(raw_line.strip())
        if reviewer is not None:
            output.append(f'{reviewer.group("prefix")} {reviewer_markdown}')
            reviewer_lines += 1
            control_lines += 1
            continue
        if _HOTCRP_CONTROL.match(raw_line.strip()) is not None:
            output.append(raw_line)
            control_lines += 1
            continue
        if not raw_line.strip() or raw_line.strip() in _HOTCRP_PLACEHOLDERS:
            output.append(raw_line)
            continue
        # In HotCRP's offline format, non-control lines are entered values or
        # prose. Preserve their line position while clearing their content.
        output.append("")

    if control_lines < 2 or reviewer_lines != 1:
        raise ValueError("unsupported_hotcrp_assignment_form")
    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def extract_blank_structure(peer_markdown: str, fallback_markdown: str) -> TemplateResult:
    """Keep only allowlisted labels and unselected options; otherwise use fallback."""

    output: list[str] = []
    seen_fields: set[str] = set()
    option_context = False
    for raw_line in peer_markdown.splitlines():
        line = raw_line.strip().replace("\u00a0", " ")
        match = _ATX.fullmatch(line) or _BOLD.fullmatch(line) or _HOTCRP.fullmatch(line)
        if match is not None:
            label = match.group(1).strip()
            normalized = _normalized_label(label)
            if normalized in _ALLOWED_FIELDS:
                if normalized in seen_fields:
                    option_context = normalized in {
                        "decision",
                        "overall merit",
                        "recommendation",
                        "reviewer expertise",
                    }
                    continue
                if output and output[-1] != "":
                    output.append("")
                output.append(f"## {label.rstrip(':')}")
                output.append("")
                seen_fields.add(normalized)
                option_context = normalized in {
                    "decision",
                    "overall merit",
                    "recommendation",
                    "reviewer expertise",
                }
                continue
        option = _UNCHECKED.fullmatch(line)
        if option is not None and option_context:
            label = option.group(1).strip()
            if _normalized_label(label) in _ALLOWED_OPTIONS:
                output.append(f"- [ ] {label}")

    if len(seen_fields) < 2:
        return TemplateResult(markdown=fallback_markdown.rstrip() + "\n", source="fallback")
    while output and output[-1] == "":
        output.pop()
    return TemplateResult(markdown="\n".join(output) + "\n", source="same-venue")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fallback", type=Path)
    mode.add_argument("--assignment-form", action="store_true")
    parser.add_argument("--reviewer", default=_REVIEWER_MARKDOWN)
    return parser


def main() -> int:
    args = _parser().parse_args()
    source = sys.stdin.read()
    if args.assignment_form:
        sys.stdout.write(blank_hotcrp_assignment_form(source, args.reviewer))
    else:
        assert args.fallback is not None
        result = extract_blank_structure(
            source,
            args.fallback.read_text(encoding="utf-8"),
        )
        sys.stdout.write(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
