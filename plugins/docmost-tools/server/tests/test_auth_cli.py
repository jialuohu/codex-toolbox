from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

import pytest

from docmost_tools import auth_cli
from docmost_tools.models import ErrorCode, OperationResult
from docmost_tools.runtime_lock import LOCK_FD_ENV, LOCK_MODE_ENV, open_runtime_lock

AUTH_REQUIRED_SENTENCE = (
    "Authentication required. Close the active task, run "
    "`CODEX_TOOLBOX_ROOT=\"${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}\" "
    "\"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh\" --login`, then start a "
    "fresh task or reconnect Docmost."
)


class FakeAuthService:
    calls: ClassVar[list[str]] = []
    result: ClassVar[OperationResult[dict[str, object]]]

    def __init__(self, *_: object) -> None:
        pass

    def login(self) -> OperationResult[dict[str, object]]:
        self.calls.append("login")
        return self.result

    def status(self) -> OperationResult[dict[str, object]]:
        self.calls.append("status")
        return self.result

    def logout(self) -> OperationResult[dict[str, object]]:
        self.calls.append("logout")
        return self.result

    @classmethod
    def logout_paths(cls, *_: object) -> OperationResult[dict[str, object]]:
        cls.calls.append("logout")
        return cls.result


@contextmanager
def inherited_runtime_lock(
    root: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    runtime_parent = root / "runtime"
    runtime_parent.mkdir(exist_ok=True)
    descriptor = open_runtime_lock(runtime_parent)
    operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
    fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
    monkeypatch.setenv("CODEX_HOME", str(root))
    monkeypatch.setenv(LOCK_FD_ENV, str(descriptor))
    monkeypatch.setenv(LOCK_MODE_ENV, mode)
    try:
        yield
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("command", ["login", "status", "logout"])
def test_cli_prints_a_success_result_for_each_auth_command(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAuthService.calls = []
    FakeAuthService.result = OperationResult[dict[str, object]](ok=True, data={"state": "ok"})
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DOCMOST_BASE_URL", "http://127.0.0.1:9321")
    monkeypatch.setattr(auth_cli, "AuthService", FakeAuthService)

    required_mode = "shared" if command == "status" else "exclusive"
    with inherited_runtime_lock(tmp_path, required_mode, monkeypatch):
        exit_code = auth_cli.main([command])

    assert exit_code == 0
    assert FakeAuthService.calls == [command]
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "data": {"state": "ok"},
        "error": None,
    }


def test_cli_returns_nonzero_and_prints_stable_error_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeAuthService.calls = []
    FakeAuthService.result = OperationResult.failure(
        ErrorCode.AUTH_REQUIRED,
        AUTH_REQUIRED_SENTENCE,
    )
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DOCMOST_BASE_URL", "http://127.0.0.1:9321")
    monkeypatch.setattr(auth_cli, "AuthService", FakeAuthService)

    with inherited_runtime_lock(tmp_path, "shared", monkeypatch):
        exit_code = auth_cli.main(["status"])

    assert exit_code == 1
    assert FakeAuthService.calls == ["status"]
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "data": None,
        "error": {
            "code": "auth_required",
            "message": AUTH_REQUIRED_SENTENCE,
            "retryable": False,
            "details": {},
        },
    }


def test_cli_redacts_invalid_credential_bearing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv(
        "DOCMOST_BASE_URL",
        "https://private-user:dummy-password@docs.example.test",
    )

    with inherited_runtime_lock(tmp_path, "exclusive", monkeypatch):
        exit_code = auth_cli.main(["login"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["error"]["code"] == "configuration_invalid"
    assert payload["error"]["message"] == "Docmost MCP configuration is invalid"
    assert "private-user" not in output
    assert "dummy-password" not in output


def test_cli_logout_does_not_require_docmost_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("DOCMOST_BASE_URL", raising=False)
    profile = tmp_path / "docmost" / "browser-profile"
    profile.mkdir(parents=True, mode=0o700)
    profile.parent.chmod(0o700)
    profile.chmod(0o700)
    (profile / "session-state").write_text("sensitive")

    with inherited_runtime_lock(tmp_path, "exclusive", monkeypatch):
        exit_code = auth_cli.main(["logout"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"] == {"logged_out": True}
    assert not profile.exists()


@pytest.mark.parametrize("command", ["login", "logout"])
def test_direct_auth_change_cannot_bypass_an_active_shared_lifetime_lock(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAuthService.calls = []
    FakeAuthService.result = OperationResult[dict[str, object]](ok=True, data={})
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DOCMOST_BASE_URL", "http://127.0.0.1:9321")
    monkeypatch.delenv(LOCK_FD_ENV, raising=False)
    monkeypatch.delenv(LOCK_MODE_ENV, raising=False)
    monkeypatch.setattr(auth_cli, "AuthService", FakeAuthService)
    profile_touches: list[str] = []
    monkeypatch.setattr(
        auth_cli,
        "profile_paths",
        lambda: profile_touches.append("profile") or object(),
    )
    runtime_parent = tmp_path / "runtime"
    runtime_parent.mkdir()
    holder = open_runtime_lock(runtime_parent)
    fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
    try:
        exit_code = auth_cli.main([command])
    finally:
        os.close(holder)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"] == {
        "code": "configuration_invalid",
        "message": "Docmost authentication runtime lock is invalid",
        "retryable": False,
        "details": {},
    }
    assert profile_touches == []
    assert FakeAuthService.calls == []


@pytest.mark.parametrize(
    ("command", "held_mode"),
    [("status", "exclusive"), ("login", "shared"), ("logout", "shared")],
)
def test_internal_auth_rejects_an_inherited_lock_mode_mismatch(
    command: str,
    held_mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAuthService.calls = []
    FakeAuthService.result = OperationResult[dict[str, object]](ok=True, data={})
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DOCMOST_BASE_URL", "http://127.0.0.1:9321")
    monkeypatch.setattr(auth_cli, "AuthService", FakeAuthService)
    profile_touches: list[str] = []
    monkeypatch.setattr(
        auth_cli,
        "profile_paths",
        lambda: profile_touches.append("profile") or object(),
    )

    with inherited_runtime_lock(tmp_path, held_mode, monkeypatch):
        exit_code = auth_cli.main([command])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"]["message"] == "Docmost authentication runtime lock is invalid"
    assert profile_touches == []
    assert FakeAuthService.calls == []


def test_internal_auth_rejects_status_without_an_inherited_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv(LOCK_FD_ENV, raising=False)
    monkeypatch.delenv(LOCK_MODE_ENV, raising=False)
    profile_touches: list[str] = []
    monkeypatch.setattr(
        auth_cli,
        "profile_paths",
        lambda: profile_touches.append("profile") or object(),
    )

    exit_code = auth_cli.main(["status"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"]["message"] == "Docmost authentication runtime lock is invalid"
    assert profile_touches == []
