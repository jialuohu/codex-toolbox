"""Cross-process shared/exclusive lock for the mutable Docmost runtime."""

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

LOCK_NAME = ".docmost-tools-runtime.lock"
LOCK_FD_ENV = "DOCMOST_RUNTIME_LOCK_FD"
LOCK_MODE_ENV = "DOCMOST_RUNTIME_LOCK_MODE"
BUSY_EXIT = 75


class RuntimeLockError(RuntimeError):
    """Raised when the runtime or its lock cannot be trusted."""


def _validated_root(root: Path) -> Path:
    try:
        metadata = root.lstat()
    except OSError as error:
        raise RuntimeLockError("Docmost runtime lock configuration is invalid") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeLockError("Docmost runtime lock configuration is invalid")
    return root.absolute()


def open_runtime_lock(root: Path) -> int:
    """Open and validate the private lock file below ``root``."""

    lock_path = _validated_root(root) / LOCK_NAME
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise RuntimeLockError("Docmost runtime lock configuration is invalid")
        os.fchmod(descriptor, 0o600)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise RuntimeLockError("Docmost runtime lock configuration is invalid")
    except (OSError, RuntimeLockError) as error:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(error, RuntimeLockError):
            raise
        raise RuntimeLockError("Docmost runtime lock configuration is invalid") from error
    return descriptor


def _operation(mode: LockMode, *, nonblocking: bool = True) -> int:
    operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
    return operation | (fcntl.LOCK_NB if nonblocking else 0)


def _probe_lock(lock_path: Path, operation: int) -> bool:
    """Return whether a separately opened descriptor can acquire ``operation``."""

    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags)
    try:
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return True
    finally:
        os.close(descriptor)


def validate_inherited_lock(root: Path, mode: LockMode, descriptor: int) -> bool:
    """Verify that ``descriptor`` is the expected live lock for ``root``."""

    try:
        lock_path = _validated_root(root) / LOCK_NAME
        inherited = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            descriptor <= 2
            or not stat.S_ISREG(inherited.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or inherited.st_uid != os.geteuid()
            or inherited.st_nlink != 1
            or (inherited.st_dev, inherited.st_ino) != (current.st_dev, current.st_ino)
        ):
            return False
        shared_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_SH)
        exclusive_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_EX)
        expected_probe_state = (
            (not shared_probe_succeeds and not exclusive_probe_succeeds)
            if mode == "exclusive"
            else (shared_probe_succeeds and not exclusive_probe_succeeds)
        )
        if not expected_probe_state:
            return False
        # Probe state alone is insufficient: an unlocked descriptor can see a
        # lock held elsewhere. Reaffirming on this descriptor proves that the
        # child itself will retain the requested lock while it acts.
        fcntl.flock(descriptor, _operation(mode))
        shared_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_SH)
        exclusive_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_EX)
    except (OSError, RuntimeLockError):
        return False

    if mode == "exclusive":
        return not shared_probe_succeeds and not exclusive_probe_succeeds
    return shared_probe_succeeds and not exclusive_probe_succeeds


def run_locked(root: Path, mode: LockMode, command: Sequence[str]) -> int:
    """Acquire the requested lock and replace this process with ``command``."""

    if not command:
        raise RuntimeLockError("Docmost runtime lock command is missing")
    descriptor = open_runtime_lock(root)
    try:
        try:
            fcntl.flock(descriptor, _operation(mode))
        except BlockingIOError:
            print(
                "Docmost runtime is busy; close any active Codex task using Docmost, "
                "or wait for an in-progress Docmost setup or auth command, then retry",
                file=sys.stderr,
            )
            return BUSY_EXIT
        os.set_inheritable(descriptor, True)
        environment = os.environ.copy()
        environment[LOCK_FD_ENV] = str(descriptor)
        environment[LOCK_MODE_ENV] = mode
        os.execvpe(command[0], list(command), environment)
    except OSError as error:
        raise RuntimeLockError("Unable to start the locked Docmost runtime command") from error
    finally:
        os.close(descriptor)
    return 1


def _parse_descriptor(value: str | None) -> int | None:
    if value is None or not value.isdecimal():
        return None
    descriptor = int(value)
    return descriptor if descriptor > 2 else None


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command under a lock, or validate an inherited lock descriptor."""

    parser = argparse.ArgumentParser(prog="docmost-runtime-lock")
    parser.add_argument("--mode", choices=("shared", "exclusive"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--validate-fd", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    try:
        if arguments.validate_fd:
            mode = arguments.mode or os.environ.get(LOCK_MODE_ENV)
            descriptor = _parse_descriptor(os.environ.get(LOCK_FD_ENV))
            if mode not in ("shared", "exclusive") or descriptor is None:
                return 1
            return 0 if validate_inherited_lock(arguments.root, mode, descriptor) else 1
        if arguments.mode is None:
            parser.error("--mode is required unless --validate-fd is used")
        command = list(arguments.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run_locked(arguments.root, arguments.mode, command)
    except RuntimeLockError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
