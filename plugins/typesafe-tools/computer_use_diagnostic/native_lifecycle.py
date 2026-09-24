"""Reset only the disposable native fixture used by the preparation diagnostic."""

from __future__ import annotations

import os
import plistlib
import re
import signal
import subprocess
import time
from pathlib import Path

APP_PATH = Path("/private/tmp/codex-toolbox-cu-prep-diagnostic/JevCUFixture.app")
EXECUTABLE_PATH = APP_PATH / "Contents/MacOS/JevCUFixture"
BUNDLE_ID = "ai.typesafe.codex.JevCUFixture"
CASE_ID = re.compile(r"native-(?:duplicate_label|long_tree)-0\Z")


class NativeResetError(RuntimeError):
    """The fixture could not be reset without touching another process."""


def _fixture_pids() -> set[int]:
    try:
        result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                                text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise NativeResetError("native process inventory is unavailable") from error
    pinned = os.path.realpath(EXECUTABLE_PATH)
    matches = set()
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\d+)\s+(\S+)(?:\s|$)", line)
        if match and os.path.realpath(match.group(2)) == pinned:
            matches.add(int(match.group(1)))
    return matches


def _validate_bundle_identity() -> None:
    try:
        with (APP_PATH / "Contents/Info.plist").open("rb") as source:
            info = plistlib.load(source)
    except (OSError, ValueError, TypeError) as error:
        raise NativeResetError("pinned native fixture identity is unavailable") from error
    if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleExecutable") != EXECUTABLE_PATH.name:
        raise NativeResetError("pinned native fixture bundle identity changed")


def reset_native(case_id: str) -> None:
    """Terminate only the pinned app executable, then relaunch the given case."""
    if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id):
        raise ValueError("unsupported native diagnostic case")
    if not EXECUTABLE_PATH.is_file():
        raise NativeResetError("pinned native fixture executable is missing")
    _validate_bundle_identity()
    pids = _fixture_pids()
    if os.getpid() in pids:
        raise NativeResetError("refusing to terminate controller process")
    for pid in sorted(pids):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise NativeResetError("pinned native fixture could not be terminated") from error
    if pids:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            remaining = pids & _fixture_pids()
            if not remaining:
                break
            time.sleep(0.05)
        else:
            if pids & _fixture_pids():
                raise NativeResetError("pinned native fixture did not terminate")
    try:
        subprocess.run(["open", "-n", "-a", str(APP_PATH), "--args", "--case-id", case_id],
                       capture_output=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise NativeResetError("pinned native fixture failed to launch") from error
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        launched = _fixture_pids()
        if len(launched) == 1:
            return
        if len(launched) > 1:
            raise NativeResetError("pinned native fixture has multiple running instances")
        time.sleep(0.05)
    raise NativeResetError("pinned native fixture window process did not start")
