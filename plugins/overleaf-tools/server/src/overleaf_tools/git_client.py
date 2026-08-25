"""Conservative Git transport for one configured Overleaf project."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from filelock import FileLock, Timeout

from overleaf_tools.config import ProjectConfig
from overleaf_tools.errors import ErrorCode, OverleafError
from overleaf_tools.permissions import (
    ensure_private_directory,
    harden_path,
    is_link_like,
    reject_link_components,
)

_REVISION_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_COMMIT_MESSAGE_RE = re.compile(r"[^\x00-\x1f\x7f]{1,200}")
_TEXT_EXTENSIONS = {
    ".bib",
    ".bst",
    ".cls",
    ".csv",
    ".json",
    ".ltx",
    ".md",
    ".sty",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
}
_EDITABLE_TEXT_LIMIT = 2 * 1024 * 1024
_IMPORT_LIMIT = 50 * 1024 * 1024
_PROJECT_WARNING_BYTES = 100 * 1024 * 1024
_PROJECT_FILE_LIMIT = 2_000
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
_ALLOWED_REMOTE_BRANCHES = {"main", "master"}
_WINDOWS_RESERVED = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID = set('<>"|?*')


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    blob_sha: str
    size: int
    path: str

    @property
    def is_text(self) -> bool:
        return PurePosixPath(self.path).suffix.lower() in _TEXT_EXTENSIONS


def validate_revision(value: str) -> str:
    lowered = value.lower()
    if _REVISION_RE.fullmatch(lowered) is None:
        raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The Git revision is invalid.")
    return lowered


def validate_expected_blob(value: str) -> str:
    if value == "absent":
        return value
    return validate_revision(value)


def validate_project_path(value: str) -> str:
    """Validate a path that must work identically on POSIX and Windows."""

    if (
        not value
        or len(value.encode("utf-8")) > 1_024
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise OverleafError(ErrorCode.INVALID_PATH, "The project path is unsafe.")
    pure = PurePosixPath(value)
    for part in pure.parts:
        base = part.split(".", 1)[0].casefold()
        if (
            part in {"", ".", ".."}
            or part.casefold() == ".git"
            or part.endswith((".", " "))
            or base in _WINDOWS_RESERVED
            or any(ord(character) < 32 or character in _WINDOWS_INVALID for character in part)
        ):
            raise OverleafError(ErrorCode.INVALID_PATH, "The project path is unsafe.")
    if pure.as_posix() != value:
        raise OverleafError(ErrorCode.INVALID_PATH, "The project path is not canonical.")
    return value


def validate_commit_message(value: str) -> str:
    if not value.strip() or _COMMIT_MESSAGE_RE.fullmatch(value) is None:
        raise OverleafError(
            ErrorCode.INVALID_ARGUMENT,
            "commit_message must be one printable line of at most 200 characters.",
        )
    return value


class GitProject:
    """Fetch, inspect, and mutate exactly one project's allowed default branch."""

    def __init__(
        self,
        *,
        project: ProjectConfig,
        private_root: Path,
        remote_url: str | None = None,
        authenticated: bool = True,
        askpass_path: str | None = None,
        lock_timeout: float = 30,
    ) -> None:
        self.project = project
        self.private_root = private_root
        self.authenticated = authenticated
        self.lock_timeout = lock_timeout
        key = hashlib.sha256(project.project_id.encode("ascii")).hexdigest()[:24]
        self.repo_path = private_root / "repos" / f"{key}.git"
        self.lock_path = private_root / "locks" / f"{key}.lock"
        self.worktree_root = private_root / "worktrees"
        self.remote_url = remote_url or f"https://git.overleaf.com/{project.project_id}"
        self.askpass_path = askpass_path
        if self.authenticated and self.askpass_path is None:
            executable = "overleaf-askpass.exe" if os.name == "nt" else "overleaf-askpass"
            candidate = Path(sys.executable).parent / executable
            self.askpass_path = str(candidate) if candidate.is_file() else None
        if self.authenticated and not self.askpass_path:
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "The bundled Overleaf askpass helper is unavailable.",
            )
        git_path = shutil.which("git")
        if git_path is None:
            raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Git is required.")
        self.git_path = git_path

    def _environment(self, *, network: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GIT_") and name != "OVERLEAF_TOKEN_FILE"
        }
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        if network and self.authenticated:
            environment.update(
                {
                    "GIT_ASKPASS": str(self.askpass_path),
                    "GIT_ASKPASS_REQUIRE": "force",
                    "OVERLEAF_TOKEN_FILE": str(self.project.token_path),
                }
            )
        if network:
            environment["GIT_ALLOW_PROTOCOL"] = "https" if self.authenticated else "file"
        if extra:
            environment.update(extra)
        return environment

    def _git(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        network: bool = False,
        check: bool = True,
        timeout: float = 120,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        command = [
            self.git_path,
            "-c",
            "credential.helper=",
            "-c",
            "core.protectHFS=true",
            "-c",
            "core.protectNTFS=true",
            *arguments,
        ]
        try:
            process = subprocess.run(
                command,
                cwd=cwd,
                env=self._environment(network=network, extra=extra_env),
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise OverleafError(
                ErrorCode.REMOTE_UNAVAILABLE,
                "The Overleaf Git operation timed out.",
            ) from exc
        if check and process.returncode != 0:
            raise OverleafError(
                ErrorCode.REMOTE_UNAVAILABLE,
                "The Overleaf Git operation failed; credentials and subprocess output "
                "were withheld.",
            )
        return process

    def _harden_repository(self) -> None:
        harden_path(self.repo_path, directory=True)
        if os.name != "nt":
            for directory, names, files in os.walk(self.repo_path):
                Path(directory).chmod(0o700)
                for name in [*names, *files]:
                    child = Path(directory) / name
                    if is_link_like(child):
                        raise OverleafError(
                            ErrorCode.CONFIGURATION_INVALID,
                            "The private Git mirror contains an unexpected link.",
                        )
                    child.chmod(0o700 if child.is_dir() else 0o600)

    def _ensure_repo(self) -> None:
        ensure_private_directory(self.private_root / "repos")
        ensure_private_directory(self.private_root / "locks")
        ensure_private_directory(self.worktree_root)
        if not self.repo_path.exists():
            self._git(["init", "--bare", "--initial-branch=master", str(self.repo_path)])
            harden_path(self.repo_path, directory=True)
            self._git(
                ["--git-dir", str(self.repo_path), "remote", "add", "origin", self.remote_url]
            )
        current = (
            self._git(["--git-dir", str(self.repo_path), "remote", "get-url", "origin"])
            .stdout.decode("utf-8", "strict")
            .strip()
        )
        if current != self.remote_url:
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "The private mirror remote does not match the configured project.",
            )
        self._harden_repository()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        ensure_private_directory(self.private_root / "locks")
        lock = FileLock(str(self.lock_path), timeout=self.lock_timeout)
        try:
            with lock:
                harden_path(self.lock_path, directory=False)
                self._ensure_repo()
                yield
        except Timeout as exc:
            raise OverleafError(
                ErrorCode.PROJECT_BUSY,
                "Another Overleaf Tools operation currently holds this project lock.",
            ) from exc

    def _default_branch(self) -> str:
        result = self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "ls-remote",
                "--symref",
                "origin",
                "HEAD",
            ],
            network=True,
        )
        try:
            lines = result.stdout.decode("ascii", "strict").splitlines()
            targets = [
                line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
                for line in lines
                if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD")
            ]
        except UnicodeError as exc:
            raise OverleafError(
                ErrorCode.REMOTE_UNAVAILABLE,
                "The Overleaf default branch response is invalid.",
            ) from exc
        if len(targets) != 1 or targets[0] not in _ALLOWED_REMOTE_BRANCHES:
            raise OverleafError(
                ErrorCode.REMOTE_UNAVAILABLE,
                "The Overleaf default branch is unsupported; expected main or master.",
            )
        return targets[0]

    def _fetch(self) -> tuple[str, str]:
        branch = self._default_branch()
        self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "origin",
                f"refs/heads/{branch}",
            ],
            network=True,
        )
        revision = (
            self._git(["--git-dir", str(self.repo_path), "rev-parse", "FETCH_HEAD"])
            .stdout.decode("ascii", "strict")
            .strip()
        )
        validate_revision(revision)
        self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "update-ref",
                f"refs/remotes/origin/{branch}",
                revision,
            ]
        )
        self._harden_repository()
        return branch, revision

    def _parse_tree(self, output: bytes) -> list[TreeEntry]:
        entries: list[TreeEntry] = []
        for record in output.split(b"\x00"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, object_type, raw_sha, raw_size = metadata.split(b" ", 3)
                path = raw_path.decode("utf-8", "strict")
                size = 0 if raw_size == b"-" else int(raw_size)
            except (UnicodeError, ValueError) as exc:
                raise OverleafError(
                    ErrorCode.UNSUPPORTED_FILE,
                    "The project contains a filename or tree entry this integration "
                    "cannot represent.",
                ) from exc
            entries.append(
                TreeEntry(
                    mode=mode.decode("ascii"),
                    object_type=object_type.decode("ascii"),
                    blob_sha=raw_sha.decode("ascii"),
                    size=size,
                    path=path,
                )
            )
        return entries

    def _entries(self, revision: str) -> list[TreeEntry]:
        output = self._git(
            ["--git-dir", str(self.repo_path), "ls-tree", "-r", "-z", "-l", revision]
        ).stdout
        return self._parse_tree(output)

    def _entry(self, revision: str, path: str) -> TreeEntry | None:
        validate_project_path(path)
        output = self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "ls-tree",
                "-z",
                "-l",
                revision,
                "--",
                path,
            ]
        ).stdout
        entries = self._parse_tree(output)
        return entries[0] if entries else None

    def _assert_supported_entry(self, entry: TreeEntry) -> None:
        validate_project_path(entry.path)
        if entry.object_type != "blob" or entry.mode not in {"100644", "100755"}:
            raise OverleafError(
                ErrorCode.UNSUPPORTED_FILE,
                "Symlinks, submodules, and non-regular Git entries are unsupported.",
            )

    def _assert_writeable_tree(self, entries: list[TreeEntry]) -> None:
        if len(entries) > _PROJECT_FILE_LIMIT:
            raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "The project exceeds 2,000 files.")
        seen: set[str] = set()
        for entry in entries:
            self._assert_supported_entry(entry)
            key = unicodedata.normalize("NFC", entry.path).casefold()
            if key in seen:
                raise OverleafError(
                    ErrorCode.UNSUPPORTED_FILE,
                    "The project contains cross-platform filename collisions.",
                )
            seen.add(key)

    def _assert_no_case_collision(self, entries: list[TreeEntry], path: str) -> None:
        key = unicodedata.normalize("NFC", path).casefold()
        collision = next(
            (
                entry
                for entry in entries
                if entry.path != path and unicodedata.normalize("NFC", entry.path).casefold() == key
            ),
            None,
        )
        if collision is not None:
            raise OverleafError(
                ErrorCode.FILE_ALREADY_EXISTS,
                "The destination collides with an existing filename on macOS or Windows.",
            )

    def _read_blob(self, entry: TreeEntry, *, limit: int | None = None) -> bytes:
        self._assert_supported_entry(entry)
        if limit is not None and entry.size > limit:
            raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "The requested file exceeds the limit.")
        content = self._git(
            ["--git-dir", str(self.repo_path), "cat-file", "blob", entry.blob_sha]
        ).stdout
        if content.startswith(_LFS_PREFIX):
            raise OverleafError(ErrorCode.UNSUPPORTED_FILE, "Git LFS pointers are unsupported.")
        return content

    def _check_revision(self, expected: str, current: str) -> None:
        if validate_revision(expected) != current:
            raise OverleafError(
                ErrorCode.STALE_REVISION,
                "The project changed after it was read.",
                outcome="stale",
                data={"remoteRevision": current},
            )

    def _check_blob(self, expected: str, entry: TreeEntry | None) -> None:
        expected = validate_expected_blob(expected)
        if expected == "absent":
            if entry is not None:
                raise OverleafError(
                    ErrorCode.STALE_BLOB,
                    "The destination exists but absence was expected.",
                    outcome="stale",
                    data={"remoteBlobSha": entry.blob_sha},
                )
            return
        if entry is None or entry.blob_sha != expected:
            raise OverleafError(
                ErrorCode.STALE_BLOB,
                "The file changed after it was read.",
                outcome="stale",
                data={"remoteBlobSha": entry.blob_sha if entry else "absent"},
            )

    @contextmanager
    def _worktree(self, revision: str) -> Iterator[Path]:
        temporary = Path(tempfile.mkdtemp(prefix="worktree-", dir=self.worktree_root))
        temporary.rmdir()
        added = False
        try:
            self._git(
                [
                    "--git-dir",
                    str(self.repo_path),
                    "worktree",
                    "add",
                    "--detach",
                    str(temporary),
                    revision,
                ]
            )
            added = True
            harden_path(temporary, directory=True)
            if os.name != "nt":
                for directory, names, files in os.walk(temporary):
                    Path(directory).chmod(0o700)
                    for name in names:
                        (Path(directory) / name).chmod(0o700)
                    for name in files:
                        file_path = Path(directory) / name
                        mode = file_path.stat().st_mode
                        file_path.chmod(0o700 if mode & 0o111 else 0o600)
            yield temporary
        finally:
            if added:
                self._git(
                    [
                        "--git-dir",
                        str(self.repo_path),
                        "worktree",
                        "remove",
                        "--force",
                        str(temporary),
                    ],
                    check=False,
                )
                self._git(["--git-dir", str(self.repo_path), "worktree", "prune"], check=False)
            shutil.rmtree(temporary, ignore_errors=True)

    def _remote_contains(self, candidate: str) -> tuple[bool, str]:
        validate_revision(candidate)
        exists = self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "cat-file",
                "-e",
                f"{candidate}^{{commit}}",
            ],
            check=False,
        )
        if exists.returncode != 0:
            raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The candidate commit is unknown.")
        _branch, remote_revision = self._fetch()
        ancestor = self._git(
            [
                "--git-dir",
                str(self.repo_path),
                "merge-base",
                "--is-ancestor",
                candidate,
                remote_revision,
            ],
            check=False,
        )
        if ancestor.returncode not in {0, 1}:
            raise OverleafError(
                ErrorCode.REMOTE_UNAVAILABLE,
                "Unable to reconcile the candidate commit.",
            )
        return ancestor.returncode == 0, remote_revision

    def _commit_and_push(
        self,
        worktree: Path,
        *,
        branch: str,
        old_revision: str,
        paths: list[str],
        commit_message: str,
    ) -> dict[str, Any]:
        if branch not in _ALLOWED_REMOTE_BRANCHES:
            raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The remote branch is unsupported.")
        validate_commit_message(commit_message)
        self._git(["add", "-A", "--", *paths], cwd=worktree)
        changed = self._git(["diff", "--cached", "--quiet"], cwd=worktree, check=False)
        if changed.returncode == 0:
            return {
                "oldRevision": old_revision,
                "newRevision": old_revision,
                "commit": old_revision,
                "changed": False,
            }
        if changed.returncode != 1:
            raise OverleafError(ErrorCode.REMOTE_UNAVAILABLE, "Unable to inspect staged changes.")
        identity = {
            "GIT_AUTHOR_NAME": "Codex Overleaf Tools",
            "GIT_AUTHOR_EMAIL": "overleaf-tools@localhost",
            "GIT_COMMITTER_NAME": "Codex Overleaf Tools",
            "GIT_COMMITTER_EMAIL": "overleaf-tools@localhost",
        }
        self._git(
            ["commit", "--no-gpg-sign", "-m", commit_message], cwd=worktree, extra_env=identity
        )
        candidate = self._git(["rev-parse", "HEAD"], cwd=worktree).stdout.decode("ascii").strip()
        validate_revision(candidate)
        timed_out = False
        try:
            push = self._git(
                ["push", "origin", f"HEAD:refs/heads/{branch}"],
                cwd=worktree,
                network=True,
                check=False,
                timeout=120,
            )
        except OverleafError as error:
            if error.code != ErrorCode.REMOTE_UNAVAILABLE:
                raise
            push = None
            timed_out = True
        try:
            committed, remote_revision = self._remote_contains(candidate)
        except OverleafError as reconcile_error:
            raise OverleafError(
                ErrorCode.OUTCOME_UNKNOWN,
                "The push result could not be reconciled. Do not retry this mutation.",
                outcome="unknown",
                data={"oldRevision": old_revision, "candidateCommit": candidate},
            ) from reconcile_error
        if committed:
            return {
                "oldRevision": old_revision,
                "newRevision": remote_revision,
                "commit": candidate,
                "changed": True,
            }
        if push is not None and push.returncode == 0:
            raise OverleafError(
                ErrorCode.OUTCOME_UNKNOWN,
                "The push succeeded but the candidate is no longer visible remotely. "
                "Do not retry; reconcile later.",
                outcome="unknown",
                data={
                    "oldRevision": old_revision,
                    "remoteRevision": remote_revision,
                    "candidateCommit": candidate,
                },
            )
        if timed_out:
            raise OverleafError(
                ErrorCode.OUTCOME_UNKNOWN,
                "The timed-out push is not currently visible remotely. Do not retry; "
                "reconcile later.",
                outcome="unknown",
                data={
                    "oldRevision": old_revision,
                    "remoteRevision": remote_revision,
                    "candidateCommit": candidate,
                },
            )
        assert push is not None
        stderr = push.stderr.decode("utf-8", "replace").lower()
        if push.returncode != 0 and any(
            marker in stderr for marker in ("non-fast-forward", "[rejected]", "fetch first")
        ):
            raise OverleafError(
                ErrorCode.STALE_REVISION,
                "The remote branch changed before the push completed.",
                outcome="stale",
                data={
                    "oldRevision": old_revision,
                    "remoteRevision": remote_revision,
                    "candidateCommit": candidate,
                },
            )
        raise OverleafError(
            ErrorCode.REMOTE_UNAVAILABLE,
            "The push failed and the candidate commit is not present remotely.",
            data={"oldRevision": old_revision, "candidateCommit": candidate},
        )

    def status(self) -> dict[str, Any]:
        with self._locked():
            branch, revision = self._fetch()
            entries = self._entries(revision)
            total = sum(entry.size for entry in entries)
            unsupported = [
                entry.path for entry in entries if entry.mode not in {"100644", "100755"}
            ]
            return {
                "project": self.project.alias,
                "displayName": self.project.display_name,
                "revision": revision,
                "branch": branch,
                "fileCount": len(entries),
                "totalBytes": total,
                "warnings": (
                    ["Project size exceeds the recommended 100 MiB Git target."]
                    if total > _PROJECT_WARNING_BYTES
                    else []
                ),
                "unsupportedEntryCount": len(unsupported),
            }

    def list_files(self) -> tuple[str, list[TreeEntry]]:
        with self._locked():
            _branch, revision = self._fetch()
            entries = self._entries(revision)
            for entry in entries:
                self._assert_supported_entry(entry)
            return revision, entries

    def read_text(self, path: str) -> dict[str, Any]:
        path = validate_project_path(path)
        if PurePosixPath(path).suffix.lower() not in _TEXT_EXTENSIONS:
            raise OverleafError(
                ErrorCode.UNSUPPORTED_FILE, "The requested path is not editable text."
            )
        with self._locked():
            _branch, revision = self._fetch()
            entry = self._entry(revision, path)
            if entry is None:
                raise OverleafError(ErrorCode.FILE_NOT_FOUND, "The requested file does not exist.")
            content = self._read_blob(entry, limit=_EDITABLE_TEXT_LIMIT)
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OverleafError(
                    ErrorCode.UNSUPPORTED_FILE,
                    "Editable text files must contain valid UTF-8.",
                ) from exc
            return {
                "project": self.project.alias,
                "path": path,
                "revision": revision,
                "blobSha": entry.blob_sha,
                "size": entry.size,
                "content": text,
            }

    def _mutate_file(
        self,
        *,
        path: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
        transform: Callable[[bytes | None], bytes],
    ) -> dict[str, Any]:
        path = validate_project_path(path)
        with self._locked():
            branch, revision = self._fetch()
            self._check_revision(expected_revision, revision)
            entries = self._entries(revision)
            self._assert_writeable_tree(entries)
            entry = self._entry(revision, path)
            self._check_blob(expected_blob_sha, entry)
            if entry is None and len(entries) >= _PROJECT_FILE_LIMIT:
                raise OverleafError(
                    ErrorCode.LIMIT_EXCEEDED, "Creating another file would exceed 2,000 files."
                )
            if entry is None:
                self._assert_no_case_collision(entries, path)
            old_content = self._read_blob(entry) if entry else None
            content = transform(old_content)
            if content.startswith(_LFS_PREFIX):
                raise OverleafError(ErrorCode.UNSUPPORTED_FILE, "Git LFS pointers are unsupported.")
            with self._worktree(revision) as worktree:
                destination = worktree.joinpath(*PurePosixPath(path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                result = self._commit_and_push(
                    worktree,
                    branch=branch,
                    old_revision=revision,
                    paths=[path],
                    commit_message=commit_message,
                )
            new_entry = self._entry(result["commit"], path)
            result.update(
                {
                    "project": self.project.alias,
                    "paths": [path],
                    "oldBlobSha": entry.blob_sha if entry else "absent",
                    "newBlobSha": new_entry.blob_sha if new_entry else "absent",
                }
            )
            return result

    def write_text(
        self,
        *,
        path: str,
        content: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]:
        path = validate_project_path(path)
        if PurePosixPath(path).suffix.lower() not in _TEXT_EXTENSIONS:
            raise OverleafError(ErrorCode.UNSUPPORTED_FILE, "The destination is not editable text.")
        encoded = content.encode("utf-8")
        if len(encoded) > _EDITABLE_TEXT_LIMIT:
            raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "Editable text is limited to 2 MiB.")
        return self._mutate_file(
            path=path,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
            transform=lambda _old: encoded,
        )

    def edit_text(
        self,
        *,
        path: str,
        old_text: str,
        new_text: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]:
        if not old_text:
            raise OverleafError(ErrorCode.INVALID_ARGUMENT, "old_text must not be empty.")

        def replace(content: bytes | None) -> bytes:
            if content is None:
                raise OverleafError(ErrorCode.FILE_NOT_FOUND, "The requested file does not exist.")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OverleafError(
                    ErrorCode.UNSUPPORTED_FILE, "The file is not UTF-8 text."
                ) from exc
            if text.count(old_text) != 1:
                raise OverleafError(
                    ErrorCode.TEXT_NOT_UNIQUE,
                    "old_text must occur exactly once in the current file.",
                )
            updated = text.replace(old_text, new_text, 1).encode("utf-8")
            if len(updated) > _EDITABLE_TEXT_LIMIT:
                raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "Editable text is limited to 2 MiB.")
            return updated

        return self._mutate_file(
            path=path,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
            transform=replace,
        )

    def _read_import(self, source: Path, roots: tuple[Path, ...], expected_sha: str) -> bytes:
        if not source.is_absolute() or not source.exists() or is_link_like(source):
            raise OverleafError(
                ErrorCode.IMPORT_NOT_ALLOWED,
                "source_path must be an existing absolute non-link regular file.",
            )
        reject_link_components(source)
        canonical = source.resolve(strict=True)
        if not canonical.is_file() or not any(canonical.is_relative_to(root) for root in roots):
            raise OverleafError(
                ErrorCode.IMPORT_NOT_ALLOWED,
                "source_path is outside the configured allowed import roots.",
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(canonical, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _IMPORT_LIMIT:
                raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "Imports are limited to 50 MiB.")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                content = handle.read(_IMPORT_LIMIT + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if len(content) > _IMPORT_LIMIT:
            raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "Imports are limited to 50 MiB.")
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise OverleafError(
                ErrorCode.IMPORT_NOT_ALLOWED, "The source file changed during import."
            )
        current = canonical.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        ):
            raise OverleafError(
                ErrorCode.IMPORT_NOT_ALLOWED, "The source path changed during import."
            )
        reject_link_components(canonical)
        if canonical.resolve(strict=True) != canonical:
            raise OverleafError(
                ErrorCode.IMPORT_NOT_ALLOWED,
                "The source path became link-backed during import.",
            )
        digest = hashlib.sha256(content).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha.lower())
            or digest != expected_sha.lower()
        ):
            raise OverleafError(ErrorCode.STALE_BLOB, "source_sha256 does not match source_path.")
        if content.startswith(_LFS_PREFIX):
            raise OverleafError(ErrorCode.UNSUPPORTED_FILE, "Git LFS pointers are unsupported.")
        return content

    def import_file(
        self,
        *,
        source_path: str,
        source_sha256: str,
        destination_path: str,
        allowed_roots: tuple[Path, ...],
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]:
        destination_path = validate_project_path(destination_path)
        content = self._read_import(Path(source_path), allowed_roots, source_sha256)
        if PurePosixPath(destination_path).suffix.lower() in _TEXT_EXTENSIONS:
            if len(content) > _EDITABLE_TEXT_LIMIT:
                raise OverleafError(ErrorCode.LIMIT_EXCEEDED, "Editable text is limited to 2 MiB.")
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OverleafError(
                    ErrorCode.UNSUPPORTED_FILE,
                    "Editable text imports must contain valid UTF-8.",
                ) from exc
        return self._mutate_file(
            path=destination_path,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
            transform=lambda _old: content,
        )

    def move_file(
        self,
        *,
        source_path: str,
        destination_path: str,
        expected_revision: str,
        expected_source_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]:
        source_path = validate_project_path(source_path)
        destination_path = validate_project_path(destination_path)
        if source_path == destination_path:
            raise OverleafError(ErrorCode.INVALID_ARGUMENT, "Source and destination must differ.")
        with self._locked():
            branch, revision = self._fetch()
            self._check_revision(expected_revision, revision)
            entries = self._entries(revision)
            self._assert_writeable_tree(entries)
            source = self._entry(revision, source_path)
            if source is None:
                raise OverleafError(ErrorCode.FILE_NOT_FOUND, "The source file does not exist.")
            self._assert_supported_entry(source)
            self._check_blob(expected_source_blob_sha, source)
            if self._entry(revision, destination_path) is not None:
                raise OverleafError(
                    ErrorCode.FILE_ALREADY_EXISTS, "The destination already exists."
                )
            self._assert_no_case_collision(entries, destination_path)
            self._read_blob(source)
            with self._worktree(revision) as worktree:
                source_local = worktree.joinpath(*PurePosixPath(source_path).parts)
                destination_local = worktree.joinpath(*PurePosixPath(destination_path).parts)
                destination_local.parent.mkdir(parents=True, exist_ok=True)
                source_local.rename(destination_local)
                result = self._commit_and_push(
                    worktree,
                    branch=branch,
                    old_revision=revision,
                    paths=[source_path, destination_path],
                    commit_message=commit_message,
                )
            result.update(
                {
                    "project": self.project.alias,
                    "paths": [source_path, destination_path],
                    "oldBlobSha": source.blob_sha,
                    "newBlobSha": source.blob_sha,
                }
            )
            return result

    def delete_file(
        self,
        *,
        path: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]:
        path = validate_project_path(path)
        with self._locked():
            branch, revision = self._fetch()
            self._check_revision(expected_revision, revision)
            entries = self._entries(revision)
            self._assert_writeable_tree(entries)
            entry = self._entry(revision, path)
            if entry is None:
                raise OverleafError(ErrorCode.FILE_NOT_FOUND, "The file does not exist.")
            self._check_blob(expected_blob_sha, entry)
            self._read_blob(entry)
            with self._worktree(revision) as worktree:
                worktree.joinpath(*PurePosixPath(path).parts).unlink()
                result = self._commit_and_push(
                    worktree,
                    branch=branch,
                    old_revision=revision,
                    paths=[path],
                    commit_message=commit_message,
                )
            result.update(
                {
                    "project": self.project.alias,
                    "paths": [path],
                    "oldBlobSha": entry.blob_sha,
                    "newBlobSha": "absent",
                }
            )
            return result

    def reconcile(self, candidate_commit: str) -> dict[str, Any]:
        candidate_commit = validate_revision(candidate_commit)
        with self._locked():
            try:
                committed, revision = self._remote_contains(candidate_commit)
            except OverleafError as error:
                if error.code == ErrorCode.INVALID_ARGUMENT:
                    raise
                raise OverleafError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "The candidate commit could not be reconciled.",
                    outcome="unknown",
                    data={"candidateCommit": candidate_commit},
                ) from error
            return {
                "project": self.project.alias,
                "candidateCommit": candidate_commit,
                "remoteRevision": revision,
                "committed": committed,
            }
