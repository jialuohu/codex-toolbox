#!/usr/bin/env python3
"""Build a safe, clickable Obsidian URI for a PaperRead note."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote


class ObsidianURIError(ValueError):
    """Raised when a vault or PaperRead note path cannot form an Obsidian URI."""


def _vault_name(vault_path: str) -> str:
    vault_name = Path(vault_path).name
    if not vault_name:
        raise ObsidianURIError("vault path must have a basename")
    return vault_name


def _validate_note_path(note_path: str) -> None:
    if Path(note_path).is_absolute():
        raise ObsidianURIError("note path must be relative")

    components = note_path.split("/")
    if (
        len(components) < 2
        or components[0] != "PaperRead"
        or any(component in {".", ".."} for component in components)
        or not note_path.endswith(".md")
    ):
        raise ObsidianURIError(
            "note path must be a Markdown file strictly beneath PaperRead/"
        )


def build_obsidian_open_uri(vault_path: str, note_path: str) -> str:
    """Return an ``obsidian://open`` URI for a validated PaperRead note."""

    vault_name = _vault_name(vault_path)
    _validate_note_path(note_path)
    return "obsidian://open?vault={}&file={}".format(
        quote(vault_name, safe=""),
        quote(note_path, safe=""),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-path", required=True)
    parser.add_argument("--note-path", required=True)
    arguments = parser.parse_args()

    try:
        uri = build_obsidian_open_uri(arguments.vault_path, arguments.note_path)
    except ObsidianURIError as error:
        parser.error(str(error))

    print(uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
