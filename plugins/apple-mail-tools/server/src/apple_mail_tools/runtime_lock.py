"""Cross-process locks for Apple Mail setup and runtime generations."""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

LockMode = Literal["shared", "exclusive"]
LockKind = Literal["setup", "generation"]

SETUP_LOCK_NAME = ".setup.lock"
SETUP_LOCK_FD_ENV = "APPLE_MAIL_SETUP_LOCK_FD"
SETUP_LOCK_MODE_ENV = "APPLE_MAIL_SETUP_LOCK_MODE"
GENERATION_LOCK_FD_ENV = "APPLE_MAIL_GENERATION_LOCK_FD"
GENERATION_LOCK_MODE_ENV = "APPLE_MAIL_GENERATION_LOCK_MODE"
GENERATION_ID_ENV = "APPLE_MAIL_GENERATION_ID"
BUSY_EXIT = 75

_GENERATION_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class RuntimeLockError(RuntimeError):
    """Raised when a runtime lock cannot be trusted."""


def _validated_root(root: Path) -> Path:
    try:
        metadata = root.lstat()
    except OSError as error:
        raise RuntimeLockError("Apple Mail runtime lock configuration is invalid") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
    ):
        raise RuntimeLockError("Apple Mail runtime lock configuration is invalid")
    return root.absolute()


def _validated_generation(value: str | None) -> str:
    if value is None or _GENERATION_PATTERN.fullmatch(value) is None:
        raise RuntimeLockError("Apple Mail runtime generation is invalid")
    return value


def _lock_path(root: Path, kind: LockKind, generation: str | None = None) -> Path:
    validated_root = _validated_root(root)
    if kind == "setup":
        return validated_root / SETUP_LOCK_NAME
    generation_id = _validated_generation(generation)
    locks = validated_root / "locks"
    try:
        metadata = locks.lstat()
    except OSError as error:
        raise RuntimeLockError("Apple Mail runtime lock configuration is invalid") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
    ):
        raise RuntimeLockError("Apple Mail runtime lock configuration is invalid")
    return locks / f"{generation_id}.lock"


def _open_lock_path(lock_path: Path) -> int:
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
            raise RuntimeLockError("Apple Mail runtime lock configuration is invalid")
        os.fchmod(descriptor, 0o600)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise RuntimeLockError("Apple Mail runtime lock configuration is invalid")
    except (OSError, RuntimeLockError) as error:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(error, RuntimeLockError):
            raise
        raise RuntimeLockError("Apple Mail runtime lock configuration is invalid") from error
    return descriptor


def open_generation_lock(root: Path, generation: str) -> int:
    """Open one immutable runtime generation's usage lock."""

    return _open_lock_path(_lock_path(root, "generation", generation))


def open_setup_lock(root: Path) -> int:
    """Open the setup-only serialization lock."""

    return _open_lock_path(_lock_path(root, "setup"))


def _operation(mode: LockMode) -> int:
    operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
    return operation | fcntl.LOCK_NB


def _probe_lock(lock_path: Path, operation: int) -> bool:
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


def _validate_inherited_path(lock_path: Path, mode: LockMode, descriptor: int) -> bool:
    try:
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
        shared_probe = _probe_lock(lock_path, fcntl.LOCK_SH)
        exclusive_probe = _probe_lock(lock_path, fcntl.LOCK_EX)
        expected = (
            (not shared_probe and not exclusive_probe)
            if mode == "exclusive"
            else (shared_probe and not exclusive_probe)
        )
        if not expected:
            return False
        fcntl.flock(descriptor, _operation(mode))
        shared_probe = _probe_lock(lock_path, fcntl.LOCK_SH)
        exclusive_probe = _probe_lock(lock_path, fcntl.LOCK_EX)
    except (OSError, RuntimeLockError):
        return False
    if mode == "exclusive":
        return not shared_probe and not exclusive_probe
    return shared_probe and not exclusive_probe


def validate_inherited_generation_lock(
    root: Path,
    generation: str,
    mode: LockMode,
    descriptor: int,
) -> bool:
    try:
        path = _lock_path(root, "generation", generation)
    except RuntimeLockError:
        return False
    return _validate_inherited_path(path, mode, descriptor)


def validate_inherited_setup_lock(root: Path, mode: LockMode, descriptor: int) -> bool:
    try:
        path = _lock_path(root, "setup")
    except RuntimeLockError:
        return False
    return _validate_inherited_path(path, mode, descriptor)


def _lock_environment(kind: LockKind) -> tuple[str, str]:
    if kind == "setup":
        return SETUP_LOCK_FD_ENV, SETUP_LOCK_MODE_ENV
    return GENERATION_LOCK_FD_ENV, GENERATION_LOCK_MODE_ENV


def _busy_message(kind: LockKind) -> str:
    if kind == "setup":
        return "Apple Mail runtime setup is busy; wait for the active setup command, then retry"
    return "Apple Mail runtime generation is busy; wait for its active process, then retry"


def run_kind_locked(
    root: Path,
    kind: LockKind,
    mode: LockMode,
    command: Sequence[str],
    *,
    generation: str | None = None,
) -> int:
    """Acquire one requested lock and replace this process with the command."""

    if not command:
        raise RuntimeLockError("Apple Mail runtime lock command is missing")
    lock_path = _lock_path(root, kind, generation)
    descriptor = _open_lock_path(lock_path)
    try:
        try:
            fcntl.flock(descriptor, _operation(mode))
        except BlockingIOError:
            print(_busy_message(kind), file=sys.stderr)
            return BUSY_EXIT
        os.set_inheritable(descriptor, True)
        environment = os.environ.copy()
        descriptor_env, mode_env = _lock_environment(kind)
        environment[descriptor_env] = str(descriptor)
        environment[mode_env] = mode
        if kind == "generation":
            environment[GENERATION_ID_ENV] = _validated_generation(generation)
        os.execvpe(command[0], list(command), environment)
    except OSError as error:
        raise RuntimeLockError("Unable to start the locked Apple Mail command") from error
    finally:
        os.close(descriptor)
    return 1


def _parse_descriptor(value: str | None) -> int | None:
    if value is None or not value.isdecimal():
        return None
    descriptor = int(value)
    return descriptor if descriptor > 2 else None


def _validate_from_environment(
    root: Path,
    kind: LockKind,
    mode: LockMode,
    generation: str | None,
) -> bool:
    descriptor_env, _ = _lock_environment(kind)
    descriptor = _parse_descriptor(os.environ.get(descriptor_env))
    if descriptor is None:
        return False
    if kind == "setup":
        return validate_inherited_setup_lock(root, mode, descriptor)
    generation_id = _validated_generation(generation)
    if os.environ.get(GENERATION_ID_ENV) != generation_id:
        return False
    return validate_inherited_generation_lock(root, generation_id, mode, descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apple-mail-runtime-lock")
    parser.add_argument("--kind", choices=("setup", "generation"), required=True)
    parser.add_argument("--mode", choices=("shared", "exclusive"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--generation")
    parser.add_argument("--validate-fd", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    kind = arguments.kind
    try:
        if kind == "generation":
            _validated_generation(arguments.generation)
        elif arguments.generation is not None:
            parser.error("--generation is valid only with --kind generation")
        if arguments.validate_fd:
            _, mode_env = _lock_environment(kind)
            mode = arguments.mode or os.environ.get(mode_env)
            if mode not in ("shared", "exclusive"):
                return 1
            return (
                0
                if _validate_from_environment(arguments.root, kind, mode, arguments.generation)
                else 1
            )
        if arguments.mode is None:
            parser.error("--mode is required unless --validate-fd is used")
        command = list(arguments.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run_kind_locked(
            arguments.root,
            kind,
            arguments.mode,
            command,
            generation=arguments.generation,
        )
    except RuntimeLockError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
