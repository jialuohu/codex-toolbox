"""Cross-process lock protecting the mutable installed runtime."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

LockMode = Literal["shared", "exclusive"]
LOCK_NAME = ".apple-mail-tools-runtime.lock"
LOCK_FD_ENV = "APPLE_MAIL_RUNTIME_LOCK_FD"
LOCK_MODE_ENV = "APPLE_MAIL_RUNTIME_LOCK_MODE"


class RuntimeLockError(RuntimeError):
    pass


def _root(path: Path) -> Path:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeLockError("Apple Mail runtime lock root is unsafe")
    return path.absolute()


def _open(path: Path) -> int:
    lock_path = _root(path) / LOCK_NAME
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    metadata = os.fstat(descriptor)
    current = lock_path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        raise RuntimeLockError("Apple Mail runtime lock is unsafe")
    os.fchmod(descriptor, 0o600)
    return descriptor


def _operation(mode: LockMode) -> int:
    return (fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX) | fcntl.LOCK_NB


def run_locked(root: Path, mode: LockMode, command: Sequence[str]) -> int:
    if not command:
        raise RuntimeLockError("Apple Mail runtime lock command is missing")
    descriptor = _open(root)
    try:
        try:
            fcntl.flock(descriptor, _operation(mode))
        except BlockingIOError:
            print(
                "Apple Mail runtime is busy; close active tasks using it and retry", file=sys.stderr
            )
            return 75
        os.set_inheritable(descriptor, True)
        environment = os.environ.copy()
        environment[LOCK_FD_ENV] = str(descriptor)
        environment[LOCK_MODE_ENV] = mode
        os.execvpe(command[0], list(command), environment)
    finally:
        os.close(descriptor)
    return 1


def validate(root: Path, mode: LockMode, descriptor: int) -> bool:
    try:
        lock_path = _root(root) / LOCK_NAME
        metadata = os.fstat(descriptor)
        current = lock_path.lstat()
        if descriptor <= 2 or (metadata.st_dev, metadata.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            return False
        fcntl.flock(descriptor, _operation(mode))
        probe = _open(root)
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                exclusive_available = True
            except BlockingIOError:
                exclusive_available = False
        finally:
            os.close(probe)
        return not exclusive_available
    except (OSError, RuntimeLockError, BlockingIOError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apple-mail-runtime-lock")
    parser.add_argument("--mode", choices=("shared", "exclusive"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--validate-fd", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    try:
        if arguments.validate_fd:
            mode = arguments.mode or os.environ.get(LOCK_MODE_ENV)
            raw_descriptor = os.environ.get(LOCK_FD_ENV, "")
            if mode not in ("shared", "exclusive") or not raw_descriptor.isdecimal():
                return 1
            return 0 if validate(arguments.root, mode, int(raw_descriptor)) else 1
        if arguments.mode is None:
            parser.error("--mode is required")
        command = list(arguments.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run_locked(arguments.root, arguments.mode, command)
    except (OSError, RuntimeLockError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
