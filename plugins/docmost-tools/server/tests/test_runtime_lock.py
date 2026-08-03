"""Tests for the shared/exclusive Docmost runtime lock."""

from __future__ import annotations

import fcntl
import os
import stat
from pathlib import Path

from docmost_tools.runtime_lock import LOCK_NAME, open_runtime_lock, validate_inherited_lock


def test_shared_holder_blocks_exclusive_but_allows_shared(tmp_path: Path) -> None:
    descriptor = open_runtime_lock(tmp_path)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert validate_inherited_lock(tmp_path, "shared", descriptor)
        other = os.open(tmp_path / LOCK_NAME, os.O_RDWR)
        try:
            fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(other, fcntl.LOCK_UN)
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("exclusive lock unexpectedly succeeded")
        finally:
            os.close(other)
    finally:
        os.close(descriptor)


def test_exclusive_holder_blocks_shared_and_validates_mode(tmp_path: Path) -> None:
    descriptor = open_runtime_lock(tmp_path)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert validate_inherited_lock(tmp_path, "exclusive", descriptor)
        assert not validate_inherited_lock(tmp_path, "shared", descriptor)
        other = os.open(tmp_path / LOCK_NAME, os.O_RDWR)
        try:
            try:
                fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("shared lock unexpectedly succeeded")
        finally:
            os.close(other)
    finally:
        os.close(descriptor)


def test_unlocked_descriptor_cannot_borrow_another_exclusive_lock(tmp_path: Path) -> None:
    holder = open_runtime_lock(tmp_path)
    forged = os.open(tmp_path / LOCK_NAME, os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not validate_inherited_lock(tmp_path, "exclusive", forged)
    finally:
        os.close(forged)
        os.close(holder)


def test_validating_an_unlocked_shared_descriptor_makes_it_a_real_holder(
    tmp_path: Path,
) -> None:
    first_holder = open_runtime_lock(tmp_path)
    inherited = os.open(tmp_path / LOCK_NAME, os.O_RDWR)
    probe = os.open(tmp_path / LOCK_NAME, os.O_RDWR)
    try:
        fcntl.flock(first_holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert validate_inherited_lock(tmp_path, "shared", inherited)
        fcntl.flock(first_holder, fcntl.LOCK_UN)
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("validated descriptor did not retain its shared lock")
    finally:
        os.close(probe)
        os.close(inherited)
        os.close(first_holder)


def test_symlinked_runtime_root_is_rejected_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "runtime"
    link.symlink_to(target, target_is_directory=True)

    try:
        open_runtime_lock(link)
    except RuntimeError as error:
        assert "configuration is invalid" in str(error)
    else:
        raise AssertionError("symlinked runtime root was accepted")

    assert list(target.iterdir()) == []


def test_created_lock_is_private_regular_and_owned(tmp_path: Path) -> None:
    descriptor = open_runtime_lock(tmp_path)
    try:
        metadata = (tmp_path / LOCK_NAME).stat()
        assert stat.S_ISREG(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_uid == os.geteuid()
        assert metadata.st_nlink == 1
    finally:
        os.close(descriptor)
