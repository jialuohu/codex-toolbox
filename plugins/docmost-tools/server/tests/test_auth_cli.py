from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from docmost_tools import auth_cli
from docmost_tools.models import ErrorCode, OperationResult


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
        "Authentication required. Run `docmost-auth login`.",
    )
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DOCMOST_BASE_URL", "http://127.0.0.1:9321")
    monkeypatch.setattr(auth_cli, "AuthService", FakeAuthService)

    exit_code = auth_cli.main(["status"])

    assert exit_code == 1
    assert FakeAuthService.calls == ["status"]
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "data": None,
        "error": {
            "code": "auth_required",
            "message": "Authentication required. Run `docmost-auth login`.",
            "retryable": False,
            "details": {},
        },
    }
