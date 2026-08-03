"""Fail-closed fingerprint for the installed Docmost runtime package."""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

_FORMAT_MARKER = b"docmost-tools-runtime-stamp-v1\0"


def _project_inputs(project: Path) -> Iterator[Path]:
    for name in ("pyproject.toml", "uv.lock", "scripts/docmost-auth"):
        path = project / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Docmost runtime source inputs are incomplete")
        yield path
    source_root = project / "src"
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("Docmost runtime source inputs are incomplete")
    source_files = sorted(path for path in source_root.rglob("*.py") if path.is_file())
    if not source_files:
        raise ValueError("Docmost runtime source inputs are incomplete")
    if any(path.is_symlink() for path in source_files):
        raise ValueError("Docmost runtime source inputs are incomplete")
    yield from source_files


def fingerprint(project: Path) -> str:
    """Hash lock, package metadata, and Python source with stable path framing."""

    resolved_project = project.resolve(strict=True)
    digest = hashlib.sha256(_FORMAT_MARKER)
    for path in _project_inputs(resolved_project):
        relative = path.relative_to(resolved_project).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _remove_existing_stamp(stamp: Path) -> None:
    if stamp.is_symlink() or stamp.is_file():
        stamp.unlink()
    elif stamp.exists():
        raise ValueError("Docmost runtime stamp must be a regular file")


def write_stamp(project: Path, stamp: Path, *, expected: str) -> None:
    """Atomically record the project fingerprint in the installed runtime."""

    _remove_existing_stamp(stamp)
    value = fingerprint(project)
    if value != expected:
        raise ValueError("Docmost source changed during runtime installation")
    stamp.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = stamp.with_name(f".{stamp.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(f"{value}\n")
        temporary.chmod(0o600)
        temporary.replace(stamp)
    finally:
        if temporary.exists():
            temporary.unlink()


def check_stamp(project: Path, stamp: Path) -> bool:
    """Return whether a regular stamp exactly matches current project inputs."""

    try:
        if not stamp.is_file() or stamp.is_symlink():
            return False
        recorded = stamp.read_text().strip()
        invalid_character = any(
            character not in "0123456789abcdef" for character in recorded
        )
        if len(recorded) != 64 or invalid_character:
            return False
        return recorded == fingerprint(project)
    except (OSError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    """Write or verify a runtime fingerprint without exposing local paths."""

    parser = argparse.ArgumentParser(prog="docmost-runtime-stamp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("project", type=Path)
    for command in ("write", "check"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("project", type=Path)
        command_parser.add_argument("stamp", type=Path)
        if command == "write":
            command_parser.add_argument("--expected", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "fingerprint":
        try:
            print(fingerprint(arguments.project))
        except (OSError, ValueError):
            return 1
        return 0
    if arguments.command == "check":
        return 0 if check_stamp(arguments.project, arguments.stamp) else 1
    try:
        write_stamp(arguments.project, arguments.stamp, expected=arguments.expected)
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
