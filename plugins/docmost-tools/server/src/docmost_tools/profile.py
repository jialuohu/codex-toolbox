"""Safe lifecycle helpers for Docmost's isolated Chromium profile."""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class ProfilePathError(ValueError):
    """The configured profile would not remain inside the secrets directory."""


class ProfileBusyError(RuntimeError):
    """Another authentication operation has the profile lock."""


@dataclass(frozen=True)
class ProfilePaths:
    """Validated, isolated profile paths rooted in ``CODEX_SECRETS_DIR``."""

    root: Path

    @property
    def parent(self) -> Path:
        return self.root / "docmost"

    @property
    def profile(self) -> Path:
        return self.parent / "browser-profile"

    @property
    def lock(self) -> Path:
        return self.parent / ".browser-profile.lock"

    def ensure_profile_directory(self) -> Path:
        """Create and secure the sole Chromium profile directory."""

        self._ensure_private_parent()
        self._validate_profile_path()
        self.profile.mkdir(mode=0o700, exist_ok=True)
        self.profile.chmod(0o700)
        self._require_mode(self.profile, 0o700)
        return self.profile

    def remove_profile(self) -> None:
        """Delete only the validated isolated profile, never its parent or root."""

        self._validate_profile_path()
        if self.profile.exists():
            shutil.rmtree(self.profile)

    def prepare_lock_directory(self) -> None:
        """Create the private lock parent and validate the lock's containment."""

        self._ensure_private_parent()
        self._require_beneath_root(self.lock)

    def _ensure_private_parent(self) -> None:
        self._validate_parent_path()
        self.parent.mkdir(mode=0o700, exist_ok=True)
        self.parent.chmod(0o700)
        self._require_mode(self.parent, 0o700)

    def _validate_parent_path(self) -> None:
        self._require_beneath_root(self.parent)
        if self.parent.is_symlink():
            msg = "Docmost profile parent must not be a symlink"
            raise ProfilePathError(msg)
        if self.parent.exists() and not self.parent.is_dir():
            msg = "Docmost profile parent must be a directory"
            raise ProfilePathError(msg)

    def _validate_profile_path(self) -> None:
        self._validate_parent_path()
        self._require_beneath_root(self.profile)
        if self.profile.is_symlink():
            msg = "Docmost browser profile must not be a symlink"
            raise ProfilePathError(msg)
        if self.profile.exists() and not self.profile.is_dir():
            msg = "Docmost browser profile must be a directory"
            raise ProfilePathError(msg)

    def _require_beneath_root(self, candidate: Path) -> None:
        try:
            candidate.resolve(strict=False).relative_to(self.root)
        except ValueError as error:
            msg = "Docmost browser profile must remain beneath CODEX_SECRETS_DIR"
            raise ProfilePathError(msg) from error

    @staticmethod
    def _require_mode(path: Path, expected: int) -> None:
        if stat.S_IMODE(path.stat().st_mode) != expected:
            msg = f"Docmost profile path has unsafe mode: {path}"
            raise ProfilePathError(msg)


def profile_paths(secrets_dir: Path | str | None = None) -> ProfilePaths:
    """Resolve a pre-existing ``CODEX_SECRETS_DIR`` without allowing path escape."""

    raw_root = os.environ.get("CODEX_SECRETS_DIR") if secrets_dir is None else str(secrets_dir)
    if not raw_root:
        msg = "CODEX_SECRETS_DIR must name an existing directory"
        raise ProfilePathError(msg)
    configured_root = Path(raw_root).expanduser()
    if not configured_root.is_dir():
        msg = "CODEX_SECRETS_DIR must name an existing directory"
        raise ProfilePathError(msg)
    return ProfilePaths(root=configured_root.resolve(strict=True))


@contextmanager
def profile_lock(paths: ProfilePaths) -> Iterator[None]:
    """Hold the profile's nonblocking, process-wide exclusive lock."""

    paths.prepare_lock_directory()
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        parent_descriptor = os.open(paths.parent, parent_flags)
    except OSError as error:
        msg = "Docmost browser profile lock has unsafe parent metadata"
        raise ProfilePathError(msg) from error
    descriptor: int | None = None
    try:
        nofollow_flag = getattr(os, "O_NOFOLLOW", None)
        if nofollow_flag is None:
            msg = "Docmost browser profile lock cannot be opened safely"
            raise ProfilePathError(msg)
        try:
            descriptor = os.open(
                paths.lock.name,
                os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | nofollow_flag,
                0o600,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            msg = "Docmost browser profile lock has unsafe path metadata"
            raise ProfilePathError(msg) from error
        lock_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.getuid()
            or lock_stat.st_nlink != 1
        ):
            msg = "Docmost browser profile lock has unsafe file metadata"
            raise ProfilePathError(msg)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProfileBusyError("PROFILE_BUSY: Docmost browser profile is in use") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)
