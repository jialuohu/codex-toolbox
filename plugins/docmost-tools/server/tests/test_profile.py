from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from docmost_tools.profile import ProfileBusyError, ProfilePathError, profile_lock, profile_paths


def test_profile_paths_create_private_parent_and_profile(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)

    paths.ensure_profile_directory()

    assert paths.parent == tmp_path / "docmost"
    assert paths.profile == tmp_path / "docmost" / "browser-profile"
    assert stat.S_IMODE(paths.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.profile.stat().st_mode) == 0o700


def test_profile_directory_can_be_reopened_for_a_persistent_session(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)
    first = paths.ensure_profile_directory()
    (first / "browser-state").write_text("persist")

    reopened = paths.ensure_profile_directory()

    assert reopened == first
    assert (reopened / "browser-state").read_text() == "persist"
    assert stat.S_IMODE(reopened.stat().st_mode) == 0o700


def test_profile_paths_reject_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (tmp_path / "docmost").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProfilePathError, match="beneath CODEX_SECRETS_DIR"):
        profile_paths(tmp_path).ensure_profile_directory()


def test_profile_lock_is_nonblocking_and_exclusive(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)

    with profile_lock(paths):
        with pytest.raises(ProfileBusyError, match="PROFILE_BUSY"):
            with profile_lock(paths):
                pass


def test_logout_removes_only_the_isolated_browser_profile(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)
    paths.ensure_profile_directory()
    marker = paths.profile / "session-data"
    marker.write_text("only this tree may be removed")
    sibling = paths.parent / "unrelated-secret"
    sibling.write_text("preserve")

    paths.remove_profile()

    assert not paths.profile.exists()
    assert sibling.read_text() == "preserve"
    assert paths.parent.is_dir()
    assert tmp_path.is_dir()


def test_profile_paths_reject_a_profile_symlink_even_when_it_targets_inside_root(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "docmost"
    parent.mkdir()
    target = parent / "another-profile"
    target.mkdir()
    (parent / "browser-profile").symlink_to(target, target_is_directory=True)

    with pytest.raises(ProfilePathError, match="symlink"):
        profile_paths(tmp_path).remove_profile()


def test_profile_paths_require_an_existing_secrets_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ProfilePathError, match="existing directory"):
        profile_paths(missing)


def test_lock_file_is_private(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)

    with profile_lock(paths):
        assert stat.S_IMODE(paths.lock.stat().st_mode) == 0o600


@pytest.mark.parametrize("outside_root", [False, True])
def test_profile_lock_rejects_symlink_without_mutating_its_target(
    tmp_path: Path,
    outside_root: bool,
) -> None:
    paths = profile_paths(tmp_path)
    paths.prepare_lock_directory()
    target_root = tmp_path.parent if outside_root else paths.parent
    target = target_root / "lock-target"
    target.write_text("do not mutate")
    target.chmod(0o644)
    paths.lock.symlink_to(target)

    with pytest.raises(ProfilePathError):
        with profile_lock(paths):
            pass

    assert target.read_text() == "do not mutate"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_profile_lock_rejects_hardlink_without_mutating_its_target(tmp_path: Path) -> None:
    paths = profile_paths(tmp_path)
    paths.prepare_lock_directory()
    target = paths.parent / "lock-target"
    target.write_text("do not mutate")
    target.chmod(0o644)
    try:
        os.link(target, paths.lock)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")

    with pytest.raises(ProfilePathError, match="unsafe"):
        with profile_lock(paths):
            pass

    assert target.read_text() == "do not mutate"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
