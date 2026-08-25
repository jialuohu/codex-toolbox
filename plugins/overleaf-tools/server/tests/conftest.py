from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from overleaf_tools.config import ConfigStore, ProjectConfig
from overleaf_tools.git_client import GitProject


def run_git(path: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )
    return process.stdout.strip()


@pytest.fixture
def git_project(tmp_path: Path) -> tuple[GitProject, Path, ConfigStore, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare", "--initial-branch=master")

    seed = tmp_path / "seed"
    seed.mkdir()
    run_git(seed, "init", "--initial-branch=master")
    run_git(seed, "config", "user.name", "Fixture")
    run_git(seed, "config", "user.email", "fixture@example.invalid")
    (seed / "main.tex").write_text(
        "\\section{Introduction}\nOriginal text.\n\\subsection{Method}\n",
        encoding="utf-8",
    )
    run_git(seed, "add", "main.tex")
    run_git(seed, "commit", "-m", "Initial fixture")
    run_git(seed, "remote", "add", "origin", str(remote))
    run_git(seed, "push", "origin", "master")

    store = ConfigStore(tmp_path / "secrets")
    store.initialize()
    token = store.set_token("fixture", "not-a-real-token")
    store.write_raw(
        {
            "version": 1,
            "projects": {
                "fixture": {
                    "projectId": "project12345678",
                    "tokenFile": "tokens/fixture.token",
                    "displayName": "Fixture",
                }
            },
            "allowedImportRoots": [],
        }
    )
    project_config = ProjectConfig(
        alias="fixture",
        project_id="project12345678",
        token_path=token,
        display_name="Fixture",
    )
    project = GitProject(
        project=project_config,
        private_root=store.root,
        remote_url=str(remote),
        authenticated=False,
    )
    return project, remote, store, seed


@pytest.fixture
def external_commit() -> Callable[..., str]:
    def commit(remote: Path, root: Path, *, filename: str = "remote.tex") -> str:
        checkout = root / f"external-{len(list(root.glob('external-*')))}"
        run_git(root, "clone", str(remote), str(checkout))
        run_git(checkout, "config", "user.name", "External")
        run_git(checkout, "config", "user.email", "external@example.invalid")
        (checkout / filename).write_text("remote change\n", encoding="utf-8")
        run_git(checkout, "add", filename)
        run_git(checkout, "commit", "-m", "Concurrent browser edit")
        run_git(checkout, "push", "origin", "master")
        return run_git(checkout, "rev-parse", "HEAD")

    return commit
