from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from apple_mail_tools.bridge import AppleScriptRunner
from apple_mail_tools.config import RuntimePaths
from apple_mail_tools.models import AppleMailError, ErrorCode


def test_bridge_uses_fixed_script_argument_array_and_private_json(
    private_paths: RuntimePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apple_mail_tools.bridge.platform.system", lambda: "Darwin")
    script = tmp_path / "bridge.applescript"
    script.write_text('return "fixed"')
    osascript = tmp_path / "osascript"
    osascript.write_text("binary")
    observed: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        request = Path(command[2])
        observed["command"] = command
        observed["request"] = json.loads(request.read_text())
        observed["mode"] = stat.S_IMODE(request.stat().st_mode)
        observed["path"] = request
        return subprocess.CompletedProcess(command, 0, b'{"ok":true,"data":{"value":1}}', b"")

    hostile = '"; do shell script "leak"\n${HOME}'
    runner = AppleScriptRunner(
        private_paths, script_path=script, osascript_path=osascript, command_runner=run
    )
    assert runner.invoke("health", {"hostile": hostile}) == {"value": 1}
    assert observed["command"] == [str(osascript), str(script), str(observed["path"])]
    assert observed["request"] == {
        "version": 1,
        "action": "health",
        "params": {"hostile": hostile},
    }
    assert observed["mode"] == 0o600
    assert not Path(str(observed["path"])).exists()


def test_bridge_maps_timeout_and_permission_without_stderr_leak(
    private_paths: RuntimePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apple_mail_tools.bridge.platform.system", lambda: "Darwin")
    script = tmp_path / "bridge.applescript"
    script.write_text("fixed")
    osascript = tmp_path / "osascript"
    osascript.write_text("binary")

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired("osascript", 1)

    with pytest.raises(AppleMailError) as expired:
        AppleScriptRunner(
            private_paths,
            script_path=script,
            osascript_path=osascript,
            command_runner=timeout,
        ).invoke("health")
    assert expired.value.code is ErrorCode.TIMEOUT

    def denied(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, b"", b"not authorized secret-body -1743")

    with pytest.raises(AppleMailError) as permission:
        AppleScriptRunner(
            private_paths,
            script_path=script,
            osascript_path=osascript,
            command_runner=denied,
        ).invoke("health")
    assert permission.value.code is ErrorCode.PERMISSION_REQUIRED
    assert "secret-body" not in permission.value.message


def test_bridge_rejects_non_darwin_and_malformed_output(
    private_paths: RuntimePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "bridge.applescript"
    script.write_text("fixed")
    osascript = tmp_path / "osascript"
    osascript.write_text("binary")
    runner = AppleScriptRunner(private_paths, script_path=script, osascript_path=osascript)

    monkeypatch.setattr("apple_mail_tools.bridge.platform.system", lambda: "Linux")
    with pytest.raises(AppleMailError) as unsupported:
        runner.invoke("health")
    assert unsupported.value.code is ErrorCode.UNSUPPORTED_PLATFORM

    def malformed(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b"not-json", b"")

    monkeypatch.setattr("apple_mail_tools.bridge.platform.system", lambda: "Darwin")
    malformed_runner = AppleScriptRunner(
        private_paths,
        script_path=script,
        osascript_path=osascript,
        command_runner=malformed,
    )
    with pytest.raises(AppleMailError) as invalid:
        malformed_runner.invoke("health")
    assert invalid.value.code is ErrorCode.BRIDGE_ERROR
