from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docmost_tools.runtime_stamp import check_stamp, fingerprint, write_stamp


def make_project(root: Path) -> Path:
    (root / "src" / "docmost_tools").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='docmost-tools'\n")
    (root / "uv.lock").write_text("version = 1\n")
    (root / "src" / "docmost_tools" / "example.py").write_text("VALUE = 1\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "docmost-auth").write_text("#!/bin/sh\nexit 0\n")
    (root / "scripts" / "docmost-mcp").write_text("#!/bin/sh\nexit 0\n")
    return root


def test_stamp_matches_only_the_installed_project_inputs(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    stamp = tmp_path / "runtime" / ".source-fingerprint"

    expected = fingerprint(project)
    write_stamp(project, stamp, expected=expected)

    assert check_stamp(project, stamp) is True
    assert stamp.read_text().strip() == fingerprint(project)
    (project / "src" / "docmost_tools" / "example.py").write_text("VALUE = 2\n")
    assert check_stamp(project, stamp) is False


def test_stamp_rejects_nonprivate_or_hardlinked_state(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    stamp = tmp_path / "runtime" / ".source-fingerprint"
    expected = fingerprint(project)
    write_stamp(project, stamp, expected=expected)

    stamp.chmod(0o644)
    assert check_stamp(project, stamp) is False
    stamp.chmod(0o600)
    linked = stamp.with_name("linked-stamp")
    linked.hardlink_to(stamp)
    assert stamp.stat().st_nlink == 2
    assert check_stamp(project, stamp) is False


def test_stamp_is_published_as_private_regular_state(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    stamp = tmp_path / "runtime" / ".source-fingerprint"

    write_stamp(project, stamp, expected=fingerprint(project))

    metadata = stamp.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1


def test_stamp_rejects_source_changed_after_the_expected_fingerprint(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "project")
    stamp = tmp_path / "runtime" / ".source-fingerprint"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("0" * 64 + "\n")
    expected = fingerprint(project)
    (project / "src" / "docmost_tools" / "example.py").write_text("VALUE = 2\n")

    with pytest.raises(ValueError, match="changed during runtime installation"):
        write_stamp(project, stamp, expected=expected)

    assert not stamp.exists()


def test_fingerprint_includes_the_installed_auth_wrapper(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    original = fingerprint(project)

    (project / "scripts" / "docmost-auth").write_text("#!/bin/sh\nexit 1\n")

    assert fingerprint(project) != original


def test_fingerprint_includes_the_mcp_bootstrap(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    original = fingerprint(project)

    (project / "scripts" / "docmost-mcp").write_text("#!/bin/sh\nexit 1\n")

    assert fingerprint(project) != original


def test_stamp_rejects_missing_or_malformed_state(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    stamp = tmp_path / "runtime" / ".source-fingerprint"

    assert check_stamp(project, stamp) is False
    stamp.parent.mkdir(parents=True)
    stamp.write_text("not-a-sha256\n")
    assert check_stamp(project, stamp) is False


def test_fingerprint_rejects_symlinked_source_files(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n")
    (project / "src" / "docmost_tools" / "linked.py").symlink_to(outside)

    try:
        fingerprint(project)
    except ValueError as error:
        assert str(error) == "Docmost runtime source inputs are incomplete"
    else:
        raise AssertionError("symlinked source must be rejected")
