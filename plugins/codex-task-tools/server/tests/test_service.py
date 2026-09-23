"""LaunchAgent lifecycle tests use only mocked service state and launchctl calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from codex_task_tools import service


def status(
    *, loaded: bool, running: bool, connected: bool = False,
    active: int | None = 0, pending: int | None = 0,
) -> dict[str, object]:
    return {
        "installed": True,
        "loaded": loaded,
        "broker": {
            "running": running,
            "backendConnected": connected,
            "activeTaskCount": active,
            "pendingApprovalCount": pending,
        },
    }


def test_restart_waits_for_delayed_bootout_then_connected_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plist = tmp_path / "toolbox.plist"
    plist.write_text("fixture")
    monkeypatch.setattr(service, "_paths", lambda: (tmp_path, tmp_path / "broker", plist))
    states = iter([
        status(loaded=True, running=True),   # initial idle check
        status(loaded=True, running=True),   # state after quiesce barrier
        status(loaded=True, running=True),   # bootout has not unloaded yet
        status(loaded=False, running=True),  # launchd unloaded; old socket still responds
        status(loaded=False, running=False), # old broker fully gone
        status(loaded=False, running=False), # bootstrap has not loaded yet
        status(loaded=True, running=True),   # broker exists; backend not connected
        status(loaded=True, running=True, connected=True),
    ])
    monkeypatch.setattr(service, "_status", lambda: next(states))
    monkeypatch.setattr(service, "_loaded", lambda: False)
    quiesce_calls: list[bool] = []

    def fake_quiesce(enabled: bool) -> dict[str, object]:
        quiesce_calls.append(enabled)
        return {"activeTaskCount": 0, "pendingApprovalCount": 0}

    monkeypatch.setattr(service, "_set_quiesced", fake_quiesce)
    launchctl_calls: list[tuple[str, ...]] = []
    sleeps: list[float] = []

    def fake_launchctl(*args: str) -> subprocess.CompletedProcess[str]:
        launchctl_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(service, "_launchctl", fake_launchctl)
    monkeypatch.setattr(service.time, "sleep", sleeps.append)
    monkeypatch.setattr(service.sys, "argv", ["codex-task-tools-service", "restart"])

    assert service.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["loaded"] is True
    assert result["broker"]["backendConnected"] is True
    assert launchctl_calls == [
        ("bootout", f"gui/{service.os.getuid()}/{service.LABEL}"),
        ("bootstrap", f"gui/{service.os.getuid()}", str(plist)),
    ]
    assert quiesce_calls == [True]
    assert sleeps == [0.25, 0.25, 0.25, 0.25]


def test_restart_refuses_bootstrap_when_old_broker_never_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plist = tmp_path / "toolbox.plist"
    plist.write_text("fixture")
    monkeypatch.setattr(service, "_paths", lambda: (tmp_path, tmp_path / "broker", plist))
    monkeypatch.setattr(service, "_status", lambda: status(loaded=True, running=True))
    launchctl_calls: list[tuple[str, ...]] = []
    quiesce_calls: list[bool] = []

    def fake_quiesce(enabled: bool) -> dict[str, object]:
        quiesce_calls.append(enabled)
        return {"activeTaskCount": 0, "pendingApprovalCount": 0}

    monkeypatch.setattr(service, "_set_quiesced", fake_quiesce)

    def fake_launchctl(*args: str) -> subprocess.CompletedProcess[str]:
        launchctl_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    ticks = iter([0.0, 1.0, 11.0, 21.0, 31.0])
    monkeypatch.setattr(service, "_launchctl", fake_launchctl)
    monkeypatch.setattr(service.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(service.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(service.sys, "argv", ["codex-task-tools-service", "restart"])

    assert service.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "did not finish stopping" in result["error"]
    assert launchctl_calls == [("bootout", f"gui/{service.os.getuid()}/{service.LABEL}")]
    assert quiesce_calls == [True, False]


def test_failed_bootout_releases_stop_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "_status", lambda: status(loaded=True, running=True))
    quiesce_calls: list[bool] = []

    def fake_quiesce(enabled: bool) -> dict[str, object]:
        quiesce_calls.append(enabled)
        return {"activeTaskCount": 0, "pendingApprovalCount": 0}

    monkeypatch.setattr(service, "_set_quiesced", fake_quiesce)
    monkeypatch.setattr(
        service, "_launchctl", lambda *args: subprocess.CompletedProcess(args, 1, "", "error")
    )

    with pytest.raises(service.ServiceError, match="Could not stop"):
        service._stop()  # noqa: SLF001 - lifecycle contract
    assert quiesce_calls == [True, False]
