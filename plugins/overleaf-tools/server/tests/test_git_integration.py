from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import run_git
from filelock import FileLock

from overleaf_tools.config import ConfigStore, ProjectConfig
from overleaf_tools.errors import ErrorCode, OverleafError
from overleaf_tools.git_client import GitProject
from overleaf_tools.operations import Operations


def git_project_for_branch(
    tmp_path: Path, branch: str
) -> tuple[GitProject, Path, ConfigStore]:
    remote = tmp_path / f"remote-{branch}.git"
    remote.mkdir()
    run_git(remote, "init", "--bare", f"--initial-branch={branch}")

    seed = tmp_path / f"seed-{branch}"
    seed.mkdir()
    run_git(seed, "init", f"--initial-branch={branch}")
    run_git(seed, "config", "user.name", "Fixture")
    run_git(seed, "config", "user.email", "fixture@example.invalid")
    (seed / "main.tex").write_text("\\section{Introduction}\nOriginal text.\n", encoding="utf-8")
    run_git(seed, "add", "main.tex")
    run_git(seed, "commit", "-m", "Initial fixture")
    run_git(seed, "remote", "add", "origin", str(remote))
    run_git(seed, "push", "origin", branch)

    store = ConfigStore(tmp_path / f"secrets-{branch}")
    store.initialize()
    token = store.set_token("fixture", "not-a-real-token")
    project = GitProject(
        project=ProjectConfig(
            alias="fixture",
            project_id="project12345678",
            token_path=token,
            display_name="Fixture",
        ),
        private_root=store.root,
        remote_url=str(remote),
        authenticated=False,
    )
    return project, remote, store


def test_main_default_branch_is_detected_and_written(tmp_path: Path) -> None:
    project, remote, _store = git_project_for_branch(tmp_path, "main")
    status = project.status()
    assert status["branch"] == "main"
    original = project.read_text("main.tex")
    created = project.write_text(
        path="codex-smoke.txt",
        content="phase=created\n",
        expected_revision=original["revision"],
        expected_blob_sha="absent",
        commit_message="Add smoke file",
    )
    assert run_git(remote, "rev-parse", "main") == created["newRevision"]


def test_unsupported_default_branch_fails_closed(tmp_path: Path) -> None:
    project, _remote, _store = git_project_for_branch(tmp_path, "develop")
    with pytest.raises(OverleafError, match="expected main or master") as caught:
        project.status()
    assert caught.value.code == ErrorCode.REMOTE_UNAVAILABLE


def test_full_local_bare_repository_workflow(
    git_project: tuple[GitProject, Path, ConfigStore, Path], tmp_path: Path
) -> None:
    project, remote, _store, _seed = git_project
    status = project.status()
    assert status["branch"] == "master"
    assert status["fileCount"] == 1

    revision, files = project.list_files()
    assert [entry.path for entry in files] == ["main.tex"]
    original = project.read_text("main.tex")
    assert original["revision"] == revision

    edited = project.edit_text(
        path="main.tex",
        old_text="Original text.",
        new_text="Updated text.",
        expected_revision=revision,
        expected_blob_sha=original["blobSha"],
        commit_message="Edit report text",
    )
    assert edited["changed"] is True
    assert edited["newRevision"] == edited["commit"]

    created = project.write_text(
        path="references.bib",
        content="@article{fixture, title={Fixture}}\n",
        expected_revision=edited["newRevision"],
        expected_blob_sha="absent",
        commit_message="Add bibliography",
    )
    assert created["oldBlobSha"] == "absent"

    imports = tmp_path / "imports"
    imports.mkdir()
    image = imports / "figure.bin"
    image.write_bytes(b"\x00fixture-binary\xff")
    imported = project.import_file(
        source_path=str(image),
        source_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        destination_path="figures/figure.bin",
        allowed_roots=(imports.resolve(),),
        expected_revision=created["newRevision"],
        expected_blob_sha="absent",
        commit_message="Import figure",
    )
    assert imported["newBlobSha"] != "absent"

    moved = project.move_file(
        source_path="references.bib",
        destination_path="bib/references.bib",
        expected_revision=imported["newRevision"],
        expected_source_blob_sha=created["newBlobSha"],
        commit_message="Move bibliography",
    )
    assert moved["paths"] == ["references.bib", "bib/references.bib"]

    deleted = project.delete_file(
        path="figures/figure.bin",
        expected_revision=moved["newRevision"],
        expected_blob_sha=imported["newBlobSha"],
        commit_message="Delete obsolete figure",
    )
    assert deleted["newBlobSha"] == "absent"
    assert project.reconcile(edited["commit"])["committed"] is True
    assert not any(project.worktree_root.iterdir())
    assert run_git(remote, "log", "-1", "--format=%an <%ae>") == (
        "Codex Overleaf Tools <overleaf-tools@localhost>"
    )


def test_stale_revision_and_blob_fail_before_commit(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
) -> None:
    project, remote, _store, _seed = git_project
    revision, _files = project.list_files()
    original = project.read_text("main.tex")
    with pytest.raises(OverleafError) as blob_error:
        project.write_text(
            path="main.tex",
            content="replacement\n",
            expected_revision=revision,
            expected_blob_sha="0" * 40,
            commit_message="Should fail",
        )
    assert blob_error.value.code == ErrorCode.STALE_BLOB
    assert run_git(remote, "rev-parse", "master") == revision

    with pytest.raises(OverleafError) as revision_error:
        project.write_text(
            path="main.tex",
            content="replacement\n",
            expected_revision="1" * 40,
            expected_blob_sha=original["blobSha"],
            commit_message="Should fail",
        )
    assert revision_error.value.code == ErrorCode.STALE_REVISION
    assert run_git(remote, "rev-parse", "master") == revision


def test_case_colliding_destination_is_rejected(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
) -> None:
    project, remote, _store, _seed = git_project
    revision, _files = project.list_files()
    with pytest.raises(OverleafError) as caught:
        project.write_text(
            path="MAIN.TEX",
            content="collision\n",
            expected_revision=revision,
            expected_blob_sha="absent",
            commit_message="Should not collide",
        )
    assert caught.value.code == ErrorCode.FILE_ALREADY_EXISTS
    assert run_git(remote, "rev-parse", "master") == revision


def test_import_requires_allowlist_digest_and_regular_file(
    git_project: tuple[GitProject, Path, ConfigStore, Path], tmp_path: Path
) -> None:
    project, _remote, _store, _seed = git_project
    revision, _files = project.list_files()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "data.bin"
    source.write_bytes(b"data")
    with pytest.raises(OverleafError) as digest_error:
        project.import_file(
            source_path=str(source),
            source_sha256="0" * 64,
            destination_path="data.bin",
            allowed_roots=(allowed.resolve(),),
            expected_revision=revision,
            expected_blob_sha="absent",
            commit_message="Bad digest",
        )
    assert digest_error.value.code == ErrorCode.STALE_BLOB

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"data")
    with pytest.raises(OverleafError) as allowlist_error:
        project.import_file(
            source_path=str(outside),
            source_sha256=hashlib.sha256(b"data").hexdigest(),
            destination_path="data.bin",
            allowed_roots=(allowed.resolve(),),
            expected_revision=revision,
            expected_blob_sha="absent",
            commit_message="Outside root",
        )
    assert allowlist_error.value.code == ErrorCode.IMPORT_NOT_ALLOWED


def test_non_fast_forward_returns_stale_and_candidate_can_be_reconciled(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
    tmp_path: Path,
    external_commit: Callable[..., str],
) -> None:
    project, remote, store, _seed = git_project
    original = project.read_text("main.tex")

    class RacingProject(GitProject):
        def _commit_and_push(self, worktree: Path, **kwargs: Any) -> dict[str, Any]:
            external_commit(remote, tmp_path)
            return super()._commit_and_push(worktree, **kwargs)

    racing = RacingProject(
        project=project.project,
        private_root=store.root,
        remote_url=str(remote),
        authenticated=False,
    )
    with pytest.raises(OverleafError) as caught:
        racing.edit_text(
            path="main.tex",
            old_text="Original text.",
            new_text="Racing text.",
            expected_revision=original["revision"],
            expected_blob_sha=original["blobSha"],
            commit_message="Race browser edit",
        )
    assert caught.value.code == ErrorCode.STALE_REVISION
    assert caught.value.outcome == "stale"
    assert caught.value.data is not None
    candidate = str(caught.value.data["candidateCommit"])
    assert project.reconcile(candidate)["committed"] is False


def test_ambiguous_push_returns_unknown_and_is_reconciled(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
) -> None:
    project, remote, store, _seed = git_project
    original = project.read_text("main.tex")

    class AmbiguousProject(GitProject):
        calls = 0

        def _remote_contains(self, candidate: str) -> tuple[bool, str]:
            self.calls += 1
            if self.calls == 1:
                raise OverleafError(ErrorCode.REMOTE_UNAVAILABLE, "simulated readback failure")
            return super()._remote_contains(candidate)

    ambiguous = AmbiguousProject(
        project=project.project,
        private_root=store.root,
        remote_url=str(remote),
        authenticated=False,
    )
    with pytest.raises(OverleafError) as caught:
        ambiguous.edit_text(
            path="main.tex",
            old_text="Original text.",
            new_text="Ambiguous text.",
            expected_revision=original["revision"],
            expected_blob_sha=original["blobSha"],
            commit_message="Ambiguous push",
        )
    assert caught.value.code == ErrorCode.OUTCOME_UNKNOWN
    assert caught.value.outcome == "unknown"
    assert caught.value.data is not None
    candidate = str(caught.value.data["candidateCommit"])
    assert project.reconcile(candidate)["committed"] is True


def test_project_lock_fails_closed(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
) -> None:
    project, _remote, _store, _seed = git_project
    project.lock_timeout = 0.01
    project.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(project.lock_path)):
        with pytest.raises(OverleafError) as caught:
            project.status()
    assert caught.value.code == ErrorCode.PROJECT_BUSY


def test_symlink_tree_entry_is_rejected(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
) -> None:
    if os.name == "nt":
        pytest.skip("Windows test runners may not permit symlink creation")
    project, _remote, _store, seed = git_project
    (seed / "linked.tex").symlink_to("main.tex")
    run_git(seed, "add", "linked.tex")
    run_git(seed, "commit", "-m", "Add unsupported symlink")
    run_git(seed, "push", "origin", "master")
    with pytest.raises(OverleafError) as caught:
        project.list_files()
    assert caught.value.code == ErrorCode.UNSUPPORTED_FILE


def test_network_environment_contains_token_path_but_not_value(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _remote, _store, _seed = git_project
    authenticated = GitProject(
        project=project.project,
        private_root=project.private_root,
        remote_url="https://git.overleaf.com/project12345678",
        authenticated=True,
    )
    assert authenticated.askpass_path is not None
    assert Path(authenticated.askpass_path).is_file()
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("OVERLEAF_TOKEN_FILE", "attacker-controlled")
    environment = authenticated._environment(  # pyright: ignore[reportPrivateUsage]
        network=True
    )
    assert environment["OVERLEAF_TOKEN_FILE"] == str(project.project.token_path)
    assert "not-a-real-token" not in environment.values()
    assert "not-a-real-token" not in authenticated.remote_url
    assert "GIT_CONFIG_COUNT" not in environment
    assert environment["GIT_ALLOW_PROTOCOL"] == "https"


def test_file_list_cursor_is_bound_to_remote_revision(
    git_project: tuple[GitProject, Path, ConfigStore, Path],
    tmp_path: Path,
    external_commit: Callable[..., str],
) -> None:
    project, remote, store, _seed = git_project
    initial = project.read_text("main.tex")
    project.write_text(
        path="second.tex",
        content="second\n",
        expected_revision=initial["revision"],
        expected_blob_sha="absent",
        commit_message="Add second file",
    )
    operations = Operations(
        store=store,
        repository_factory=lambda _project, _root: project,
    )
    first = operations.list_files("fixture", limit=1, cursor=None)
    assert first["ok"] is True
    cursor = str(first["data"]["nextCursor"])
    assert ":" in cursor
    second = operations.list_files("fixture", limit=1, cursor=cursor)
    assert second["ok"] is True
    external_commit(remote, tmp_path)
    stale = operations.list_files("fixture", limit=1, cursor=cursor)
    assert stale["ok"] is False
    assert stale["outcome"] == "stale"
    assert stale["error"]["code"] == ErrorCode.STALE_REVISION.value
