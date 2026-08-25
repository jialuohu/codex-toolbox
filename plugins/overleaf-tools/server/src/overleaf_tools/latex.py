"""Small read-only LaTeX heading parser."""

from __future__ import annotations

import re
from typing import Any

_HEADING = re.compile(
    r"\\(?P<level>part|chapter|section|subsection|subsubsection)\*?\s*"
    r"(?:\[[^\]]*\]\s*)?\{",
    re.MULTILINE,
)


def _without_comments(source: str) -> str:
    output: list[str] = []
    for line in source.splitlines(keepends=True):
        comment = None
        for index, character in enumerate(line):
            if character != "%":
                continue
            slashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slashes += 1
                cursor -= 1
            if slashes % 2 == 0:
                comment = index
                break
        if comment is None:
            output.append(line)
        elif line.endswith("\n"):
            output.append(line[:comment] + "\n")
        else:
            output.append(line[:comment])
    return "".join(output)


def extract_outline(source: str) -> list[dict[str, Any]]:
    """Extract balanced-brace sectioning commands without executing TeX."""

    clean = _without_comments(source)
    headings: list[dict[str, Any]] = []
    for match in _HEADING.finditer(clean):
        depth = 1
        index = match.end()
        title: list[str] = []
        escaped = False
        while index < len(clean) and depth:
            character = clean[index]
            if escaped:
                title.append(character)
                escaped = False
            elif character == "\\":
                title.append(character)
                escaped = True
            elif character == "{":
                depth += 1
                title.append(character)
            elif character == "}":
                depth -= 1
                if depth:
                    title.append(character)
            else:
                title.append(character)
            index += 1
        if depth == 0:
            headings.append(
                {
                    "level": match.group("level"),
                    "title": "".join(title).strip(),
                    "line": clean.count("\n", 0, match.start()) + 1,
                }
            )
    return headings
