#!/usr/bin/env python3
"""Build the deterministic basename for a PaperRead note."""

from __future__ import annotations

import argparse
import re
import unicodedata


class FilenameError(ValueError):
    """Raised when a required filename component is invalid."""


def _slug(value: str, *, lowercase: bool) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        raise FilenameError("filename component must not be empty")

    output: list[str] = []
    for character in text:
        if character.isalnum():
            output.append(character.lower() if lowercase else character)
        elif output and output[-1] != "-":
            output.append("-")

    slug = "".join(output).strip("-")
    if not slug:
        raise FilenameError("filename component has no letters or numbers")
    return slug


def build_filename(author_family: str, year: str | int, method: str) -> str:
    year_text = str(year).strip()
    if not re.fullmatch(r"\d{4}", year_text):
        raise FilenameError("publication year must contain exactly four digits")

    author_slug = _slug(author_family, lowercase=True)
    method_slug = _slug(method, lowercase=False)
    return f"{author_slug}{year_text[-2:]}-{method_slug}.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-family", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--method", required=True)
    arguments = parser.parse_args()

    try:
        filename = build_filename(
            arguments.author_family,
            arguments.year,
            arguments.method,
        )
    except FilenameError as error:
        parser.error(str(error))

    print(filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
