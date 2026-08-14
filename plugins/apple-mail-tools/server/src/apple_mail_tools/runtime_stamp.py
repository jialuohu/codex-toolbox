"""Fail-closed fingerprint for the installed Apple Mail runtime."""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

_FORMAT_MARKER = b"apple-mail-tools-runtime-stamp-v1\0"


def _project_inputs(project: Path) -> Iterator[Path]:
    for name in ("pyproject.toml", "uv.lock", "scripts/mail_bridge.applescript"):
        path = project / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Apple Mail runtime source inputs are incomplete")
        yield path
    source_root = project / "src"
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("Apple Mail runtime source inputs are incomplete")
    source_files = sorted(path for path in source_root.rglob("*.py") if path.is_file())
    if not source_files or any(path.is_symlink() for path in source_files):
        raise ValueError("Apple Mail runtime source inputs are incomplete")
    yield from source_files


def fingerprint(project: Path) -> str:
    resolved = project.resolve(strict=True)
    digest = hashlib.sha256(_FORMAT_MARKER)
    for path in _project_inputs(resolved):
        relative = path.relative_to(resolved).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def write_stamp(project: Path, stamp: Path, *, expected: str) -> None:
    if stamp.is_symlink() or stamp.is_file():
        stamp.unlink()
    elif stamp.exists():
        raise ValueError("Apple Mail runtime stamp is unsafe")
    value = fingerprint(project)
    if value != expected:
        raise ValueError("Apple Mail source changed during installation")
    temporary = stamp.with_name(f".{stamp.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(f"{value}\n")
        temporary.chmod(0o600)
        temporary.replace(stamp)
    finally:
        if temporary.exists():
            temporary.unlink()


def check_stamp(project: Path, stamp: Path) -> bool:
    try:
        recorded = stamp.read_text().strip()
        return (
            stamp.is_file()
            and not stamp.is_symlink()
            and len(recorded) == 64
            and all(character in "0123456789abcdef" for character in recorded)
            and recorded == fingerprint(project)
        )
    except (OSError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apple-mail-runtime-stamp")
    commands = parser.add_subparsers(dest="command", required=True)
    fingerprint_parser = commands.add_parser("fingerprint")
    fingerprint_parser.add_argument("project", type=Path)
    for command in ("write", "check"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("project", type=Path)
        command_parser.add_argument("stamp", type=Path)
        if command == "write":
            command_parser.add_argument("--expected", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "fingerprint":
        try:
            print(fingerprint(arguments.project))
            return 0
        except (OSError, ValueError):
            return 1
    if arguments.command == "check":
        return 0 if check_stamp(arguments.project, arguments.stamp) else 1
    try:
        write_stamp(arguments.project, arguments.stamp, expected=arguments.expected)
        return 0
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
