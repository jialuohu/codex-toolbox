"""Install and operate only the toolbox-owned macOS LaunchAgent."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .broker import state_directory
from .ipc import BrokerUnavailable, broker_request
from .ledger import private_dir

LABEL = "com.jialuohu.codex-task-tools"


class ServiceError(RuntimeError):
    pass


def _paths() -> tuple[Path, Path, Path]:
    if platform.system() != "Darwin":
        raise ServiceError("The managed task broker currently requires macOS")
    home = Path(os.getenv("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
    stable_venv = home / "runtime" / "codex-task-tools" / ".venv"
    broker_exe = stable_venv / "bin" / "codex-task-tools-broker"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    return stable_venv, broker_exe, plist_path


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args], text=True, capture_output=True, timeout=15, check=False
    )


def _loaded() -> bool:
    return _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0


async def _broker_status() -> dict[str, Any] | None:
    try:
        answer = await broker_request("service_status", timeout=10)
        if answer.get("ok") and isinstance(answer.get("result"), dict):
            return answer["result"]
    except BrokerUnavailable:
        pass
    return None


def _status() -> dict[str, Any]:
    _venv, _broker, plist_path = _paths()
    live = asyncio.run(_broker_status())
    return {
        "installed": plist_path.is_file(),
        "loaded": _loaded(),
        "broker": live or {"running": False, "activeTaskCount": None,
                           "pendingApprovalCount": None},
    }


def _set_quiesced(enabled: bool) -> dict[str, Any]:
    try:
        answer = asyncio.run(
            broker_request("service_quiesce", {"enabled": enabled}, timeout=120)
        )
    except BrokerUnavailable as exc:
        raise ServiceError("Could not coordinate with the toolbox broker") from exc
    result = answer.get("result")
    if not answer.get("ok") or not isinstance(result, dict):
        raise ServiceError("Toolbox broker did not confirm the stop barrier")
    return result


def _install() -> dict[str, Any]:
    stable_venv, broker_exe, plist_path = _paths()
    if not broker_exe.is_file() or stable_venv not in Path(sys.executable).absolute().parents:
        raise ServiceError("Install the package into the stable Codex task tools venv first")
    state_dir = private_dir(state_directory())
    args = [str(broker_exe), "--state-dir", str(state_dir)]
    content = {
        "Label": LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "Umask": 0o077,
        "ProcessType": "Background",
        "StandardOutPath": str(state_dir / "broker.out.log"),
        "StandardErrorPath": str(state_dir / "broker.err.log"),
        "EnvironmentVariables": {"CODEX_HOME": str(state_dir.parent.parent)},
    }
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    if plist_path.is_symlink():
        raise ServiceError("LaunchAgent path may not be a symlink")
    desired = plistlib.dumps(content)
    if plist_path.exists():
        if plist_path.read_bytes() == desired:
            return _status()
        current = _status()
        if current["loaded"]:
            raise ServiceError("Stop the idle toolbox broker before changing its LaunchAgent")
    temp = plist_path.with_suffix(".plist.tmp")
    if temp.exists() or temp.is_symlink():
        raise ServiceError("LaunchAgent temporary path is occupied")
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(desired)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, plist_path)
    finally:
        temp.unlink(missing_ok=True)
    return _status()


def _start() -> dict[str, Any]:
    _venv, _broker, plist_path = _paths()
    if not plist_path.is_file():
        raise ServiceError("LaunchAgent is not installed")
    if not _loaded():
        result = _launchctl("bootstrap", _domain(), str(plist_path))
        if result.returncode:
            raise ServiceError("Could not start the toolbox LaunchAgent")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = _status()
        broker = status["broker"]
        if status["loaded"] and broker.get("running") and broker.get("backendConnected"):
            return status
        time.sleep(0.25)
    raise ServiceError("Toolbox LaunchAgent did not become healthy and connect to App Server")


def _stop() -> dict[str, Any]:
    status = _status()
    if status["loaded"]:
        broker = status["broker"]
        if not broker.get("running"):
            raise ServiceError("Broker health is unknown; refusing to interrupt a possible active task")
        if broker.get("activeTaskCount") != 0 or broker.get("pendingApprovalCount") != 0:
            raise ServiceError("Broker has an active task or pending approval")
        stopped = False
        try:
            settled = _set_quiesced(True)
            if settled.get("activeTaskCount") != 0 or settled.get("pendingApprovalCount") != 0:
                raise ServiceError("Broker became active before the stop barrier")
            status = _status()
            if status["broker"].get("activeTaskCount") != 0 or status["broker"].get("pendingApprovalCount") != 0:
                raise ServiceError("Broker became active before LaunchAgent shutdown")
            result = _launchctl("bootout", f"{_domain()}/{LABEL}")
            if result.returncode:
                raise ServiceError("Could not stop the toolbox LaunchAgent")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = _status()
                if not status["loaded"] and not status["broker"].get("running"):
                    stopped = True
                    return status
                time.sleep(0.25)
            raise ServiceError("Toolbox LaunchAgent did not finish stopping")
        finally:
            if not stopped:
                try:
                    _set_quiesced(False)
                except ServiceError:
                    # If bootout is still completing, the old broker may be gone.
                    pass
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage only the Codex Task Tools LaunchAgent")
    parser.add_argument("action", choices=("install", "start", "stop", "restart", "status"))
    args = parser.parse_args()
    try:
        if args.action == "install":
            result = _install()
        elif args.action == "start":
            result = _start()
        elif args.action == "stop":
            result = _stop()
        elif args.action == "restart":
            _stop()
            result = _start()
        else:
            result = _status()
        print(json.dumps({"ok": True, **result}, separators=(",", ":")))
        return 0
    except (ServiceError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
