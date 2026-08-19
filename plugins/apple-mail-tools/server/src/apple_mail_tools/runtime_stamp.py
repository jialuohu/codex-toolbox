"""Fail-closed fingerprint for an immutable Apple Mail runtime generation."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from collections.abc import Iterator, Sequence
from pathlib import Path

_FORMAT_MARKER = b"apple-mail-tools-runtime-stamp-v2\0"


def _project_inputs(project: Path) -> Iterator[Path]:
    for name in (
        "pyproject.toml",
        "uv.lock",
        "scripts/apple-mail-mcp",
        "scripts/mail_bridge.applescript",
    ):
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
    """Hash the dependency lock, launcher, bridge, and package source."""

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


def _validate_stamp_parent(stamp: Path) -> None:
    metadata = stamp.parent.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Apple Mail runtime stamp directory is unsafe")


def _remove_existing_stamp(stamp: Path) -> None:
    if stamp.is_symlink() or stamp.is_file():
        stamp.unlink()
    elif stamp.exists():
        raise ValueError("Apple Mail runtime stamp must be a regular file")


def write_stamp(project: Path, stamp: Path, *, expected: str) -> None:
    """Atomically record the source fingerprint after installation."""

    _remove_existing_stamp(stamp)
    value = fingerprint(project)
    if value != expected:
        raise ValueError("Apple Mail source changed during installation")
    stamp.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    _validate_stamp_parent(stamp)
    temporary = stamp.with_name(f".{stamp.name}.{os.getpid()}.tmp")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "w") as stream:
            descriptor = None
            stream.write(f"{value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(stamp)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()


def check_stamp(project: Path, stamp: Path) -> bool:
    """Return whether a private regular stamp matches the current source."""

    try:
        _validate_stamp_parent(stamp)
        metadata = stamp.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            return False
        recorded = stamp.read_text().strip()
        return (
            len(recorded) == 64
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
