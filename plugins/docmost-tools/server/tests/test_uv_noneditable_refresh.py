from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def _copy_locked_project(destination: Path) -> None:
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy2(PROJECT / name, destination / name)
    shutil.copytree(PROJECT / "src", destination / "src")
    shutil.copytree(PROJECT / "scripts", destination / "scripts")


def _run(command: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _installed_probe(python: Path, *, environment: dict[str, str]) -> tuple[str, Path]:
    result = _run(
        [
            str(python),
            "-c",
            (
                "import json; import docmost_tools.refresh_probe as probe; "
                "print(json.dumps([probe.VALUE, probe.__file__]))"
            ),
        ],
        environment=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value, module_path = json.loads(result.stdout)
    return value, Path(module_path).resolve()


def test_uv_reinstall_package_refreshes_noneditable_source_only_change(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")

    project = tmp_path / "project"
    project.mkdir()
    _copy_locked_project(project)
    probe = project / "src" / "docmost_tools" / "refresh_probe.py"
    probe.write_text('VALUE = "before-source-change"\n')
    runtime = tmp_path / "runtime"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment.update(
        {
            "UV_PROJECT_ENVIRONMENT": str(runtime),
            "UV_NO_PROGRESS": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )
    sync = [
        uv,
        "sync",
        "--frozen",
        "--no-dev",
        "--no-editable",
        "--reinstall-package",
        "docmost-tools",
        "--offline",
        "--directory",
        str(project),
    ]

    first_sync = _run(sync, environment=environment)
    if first_sync.returncode != 0 and "offline" in first_sync.stderr.casefold():
        pytest.skip("the locked Docmost dependencies are not available in the local uv cache")
    assert first_sync.returncode == 0, first_sync.stdout + first_sync.stderr

    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    before, installed_path = _installed_probe(python, environment=environment)
    assert before == "before-source-change"
    assert installed_path.is_relative_to(runtime.resolve())

    probe.write_text('VALUE = "after-source-change"\n')
    still_installed, _ = _installed_probe(python, environment=environment)
    assert still_installed == "before-source-change"

    second_sync = _run(sync, environment=environment)
    assert second_sync.returncode == 0, second_sync.stdout + second_sync.stderr
    refreshed, refreshed_path = _installed_probe(python, environment=environment)
    assert refreshed == "after-source-change"
    assert refreshed_path.is_relative_to(runtime.resolve())
