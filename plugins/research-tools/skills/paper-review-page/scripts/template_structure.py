#!/usr/bin/env python3
"""Extract blank review structure from peer Markdown and discard substantive content."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


_ATX = re.compile(r"^#{1,6}\s+(.{1,120}?)\s*$")
_BOLD = re.compile(r"^\*\*([^*\n]{1,120}?)\*\*\s*$")
_HOTCRP = re.compile(r"^\\?==\*==\s+(.{1,120}?)\s*$")
_UNCHECKED = re.compile(r"^- \[ \]\s+(.{1,80}?)\s*$")
_ALLOWED_FIELDS = {
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
    "strengths",
    "summary",
    "summary and contributions",
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
    parser.add_argument("--fallback", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = extract_blank_structure(sys.stdin.read(), args.fallback.read_text(encoding="utf-8"))
    sys.stdout.write(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
