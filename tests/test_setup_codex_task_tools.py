"""Exercise the real installer with isolated, synthetic external processes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup-codex-task-tools.sh"
PLUGIN = ROOT / "plugins/codex-task-tools"
VERSION = "0.1.1"


def healthy_status(**changes: object) -> dict:
    broker = {
        "running": True,
        "backendConnected": True,
        "appServerVersion": "0.159.0",
        "backendIdentity": "synthetic-backend",
        "activeTaskCount": 0,
        "pendingApprovalCount": 0,
        "quiesced": False,
        "eventProcessingError": False,
    }
    broker.update(changes)
    return {"ok": True, "installed": True, "loaded": True, "broker": broker}


def disconnected_status() -> dict:
    return healthy_status(
        backendConnected=False, appServerVersion=None, backendIdentity=None,
        activeTaskCount=None, pendingApprovalCount=None,
    )


def stopped_status() -> dict:
    result = disconnected_status()
    result["loaded"] = False
    result["broker"]["running"] = False
    return result


def upgrade_receipt(**changes: object) -> dict:
    return {
        "ok": True, "fromVersion": "0.1.0", "toVersion": VERSION,
        "appServerVersion": "0.159.0", "stopped": True, "runtimeInstalled": True,
        "verifiedTerminalTaskCount": 1, **changes,
    }


# Every external command is confined to this fixture. The stable Python wrapper
# executes the installer's actual metadata and health-check code, with only the
# synthetic installed package added to its import path.
FAKE_TOOL = r'''
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["TASK_SETUP_FIXTURE_STATE"])
state = json.loads(state_path.read_text())
name = Path(sys.argv[0]).name
args = sys.argv[1:]
event = {"tool": name, "args": args}
if name == "uv":
    event["virtual_env"] = os.environ.get("VIRTUAL_ENV")
    event["uv_project_environment"] = os.environ.get("UV_PROJECT_ENVIRONMENT")
if name == "codex-task-tools-service" and args == ["status"]:
    event["status"] = state["status"]
with Path(os.environ["TASK_SETUP_FIXTURE_LOG"]).open("a") as stream:
    stream.write(json.dumps(event) + "\n")

def save():
    state_path.write_text(json.dumps(state))

def reject():
    raise SystemExit("Unexpected fixture command: " + name + " " + repr(args))

def inject_interrupted_marker(stage):
    if state.get("inject_marker_at") == stage:
        marker = Path(os.environ["CODEX_HOME"]) / "state/codex-task-tools/upgrade-install.json"
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text('{"fixture":"interrupted"}\n')

if name == "uname":
    if args != ["-s"]:
        reject()
    print("Darwin")
elif name == "sleep":
    if args != ["1"]:
        reject()
elif name == "codex":
    if args == ["mcp", "get", "codex_task_tools", "--json"]:
        print(json.dumps(state["mcp_entry"]))
    elif args == ["plugin", "marketplace", "list", "--json"]:
        print(json.dumps(state["marketplaces"]))
    else:
        reject()
elif name == "python":
    sys.path.insert(0, os.environ["TASK_SETUP_FIXTURE_SITE"])
    if len(args) == 3 and args[:2] == ["-I", "-c"]:
        inject_interrupted_marker("metadata")
        code = args[2]
    elif args == ["-I", "-"]:
        code = sys.stdin.read()
    else:
        reject()
    exec(compile(code, "<installer-runtime-check>", "exec"), {"__name__": "__main__"})
elif name == "uv":
    if args[0] == "lock":
        if args[1:3] != ["--check", "--directory"]:
            reject()
    elif args[0] == "run":
        if state.get("proof_exit", 0):
            raise SystemExit(state["proof_exit"])
        project = args[args.index("--install-project") + 1]
        uv_executable = args[args.index("--uv-executable") + 1]
        if not Path(project).is_dir() or uv_executable != str(Path(sys.argv[0]).absolute()):
            reject()
        with Path(os.environ["TASK_SETUP_FIXTURE_LOG"]).open("a") as stream:
            stream.write(json.dumps({
                "tool": "codex_task_tools.upgrade", "args": ["sync"],
                "install_project": project, "uv_executable": uv_executable,
            }) + "\n")
        if state.get("upgrade_sync_exit", 0):
            raise SystemExit(state["upgrade_sync_exit"])
        metadata = Path(os.environ["TASK_SETUP_FIXTURE_METADATA"])
        metadata.write_text("Name: codex-task-tools\nVersion: 0.1.1\n")
        state["status"] = state.get("post_proof_status", state["stopped_status"])
        save()
        sys.stdout.write(state["helper_stdout"])
    elif args[0] == "sync":
        metadata = Path(os.environ["TASK_SETUP_FIXTURE_METADATA"])
        metadata.write_text("Name: codex-task-tools\nVersion: 0.1.1\n")
    else:
        reject()
elif name == "codex-task-tools-service":
    if args == ["status"]:
        inject_interrupted_marker("status")
        print(json.dumps(state["status"]))
    elif args == ["stop"]:
        if state.get("stop_exit", 0):
            raise SystemExit(state["stop_exit"])
        state["status"] = state.get("post_stop_status", state["stopped_status"])
        save()
    elif args == ["install"]:
        pass
    elif args == ["start"]:
        state["status"] = state["final_status"]
        save()
    else:
        reject()
else:
    reject()
'''


class CodexTaskSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="codex-task-setup-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "checkout"
        self.script = self.checkout / "scripts/setup-codex-task-tools.sh"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SETUP, self.script)
        (self.checkout / "plugins/codex-task-tools").mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.codex_home = self.root / "codex-home"
        self.plugin = self.codex_home / f"plugins/cache/jialuo-codex-toolbox/codex-task-tools/{VERSION}"
        for relative in (".codex-plugin/plugin.json", ".mcp.json", "server/pyproject.toml", "server/uv.lock"):
            destination = self.plugin / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PLUGIN / relative, destination)
        self.runtime = self.codex_home / "runtime/codex-task-tools"
        self.venv = self.runtime / ".venv"
        self.runtime.mkdir(parents=True, mode=0o700)
        self.runtime.chmod(0o700)
        self.site = self.root / "fixture-site"
        package = self.site / "codex_task_tools"
        package.mkdir(parents=True)
        for name in ("__init__.py", "compatibility.py"):
            shutil.copyfile(PLUGIN / "server/src/codex_task_tools" / name, package / name)
        self.metadata = self.site / "codex_task_tools-0.1.0.dist-info/METADATA"
        self.metadata.parent.mkdir()
        self.state_path = self.root / "state.json"
        self.log = self.root / "commands.jsonl"
        for command in ("codex", "uv", "uname", "sleep"):
            self.executable(self.bin / command)
        for command in ("python", "codex-task-tools-service"):
            self.executable(self.venv / "bin" / command)
        (self.bin / "python3").symlink_to(sys.executable)
        prerequisite = self.script.parent / "setup-codex-prerequisites.py"
        prerequisite.write_text(
            "import os, sys\n"
            "assert sys.argv[1:] == ['resolve-codex']\n"
            "print(os.environ['TASK_SETUP_FIXTURE_CODEX'])\n"
        )
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.root),
            "CODEX_HOME": str(self.codex_home),
            "TASK_SETUP_FIXTURE_STATE": str(self.state_path),
            "TASK_SETUP_FIXTURE_LOG": str(self.log),
            "TASK_SETUP_FIXTURE_SITE": str(self.site),
            "TASK_SETUP_FIXTURE_METADATA": str(self.metadata),
            "TASK_SETUP_FIXTURE_CODEX": str(self.bin / "codex"),
            "UV_PROJECT_ENVIRONMENT": str(self.root / "unrelated-uv-environment"),
            "VIRTUAL_ENV": str(self.root / "unrelated-virtualenv"),
        }
        self.configure()

    def executable(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
        path.chmod(0o755)

    def configure(self, *, version: str = VERSION, status: dict | None = None, **changes: object) -> None:
        mcp = json.loads((self.plugin / ".mcp.json").read_text())["mcpServers"]["codex_task_tools"]
        state = {
            "mcp_entry": {"transport": {**mcp, "type": "stdio", "cwd": str(self.plugin)}},
            "marketplaces": {"marketplaces": [{
                "name": "jialuo-codex-toolbox",
                "marketplaceSource": {
                    "sourceType": "git", "source": "https://github.com/jialuohu/codex-toolbox.git",
                },
            }]},
            "status": healthy_status() if status is None else status,
            "stopped_status": stopped_status(),
            "final_status": healthy_status(),
            "helper_stdout": json.dumps(upgrade_receipt()) + "\n",
            **changes,
        }
        self.state_path.write_text(json.dumps(state))
        self.metadata.write_text(f"Name: codex-task-tools\nVersion: {version}\n")
        self.log.write_text("")

    def run_setup(self, action: str = "--install") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(self.script), action], env=self.env,
            capture_output=True, text=True, timeout=15, check=False,
        )

    def events(self, tool: str | None = None) -> list[dict]:
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [event for event in events if tool is None or event["tool"] == tool]

    def assert_no_runtime_mutations(self) -> None:
        self.assertEqual(self.events("codex_task_tools.upgrade"), [])
        self.assert_no_shell_mutations()

    def assert_no_shell_mutations(self) -> None:
        self.assertFalse(any(event["args"][0] == "sync" for event in self.events("uv")))
        self.assertFalse(any(event["args"] != ["status"] for event in self.events("codex-task-tools-service")))

    def assert_install_succeeded(self, result: subprocess.CompletedProcess[str], *, guarded: bool = False) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["broker"]["appServerVersion"], "0.159.0")
        events = self.events()
        if guarded:
            self.assertEqual(json.loads(result.stderr), upgrade_receipt())
            self.assertFalse(any(event["args"][0] == "sync" for event in self.events("uv")))
            self.assertEqual(self.events("codex_task_tools.upgrade"), [{
                "tool": "codex_task_tools.upgrade", "args": ["sync"],
                "install_project": str(self.plugin / "server"), "uv_executable": str(self.bin / "uv"),
            }])
            upgrade_index = next(index for index, event in enumerate(events)
                                 if event["tool"] == "codex_task_tools.upgrade")
            readback = events[upgrade_index + 1]
            self.assertEqual((readback["tool"], readback["args"]), ("codex-task-tools-service", ["status"]))
            self.assertEqual(readback["status"], stopped_status())
            self.assertEqual([event["args"] for event in events[upgrade_index + 2:]
                              if event["tool"] == "codex-task-tools-service"],
                             [["install"], ["start"], ["status"]])
            return
        sync_index = next(index for index, event in enumerate(events)
                          if event["tool"] == "uv" and event["args"][0] == "sync")
        preceding = events[sync_index - 1]
        self.assertEqual((preceding["tool"], preceding["args"]), ("codex-task-tools-service", ["status"]))
        self.assertEqual(preceding["status"], stopped_status())
        sync = events[sync_index]
        self.assertEqual(sync["virtual_env"], str(self.venv))
        self.assertIsNone(sync["uv_project_environment"])
        self.assertEqual(sync["args"], [
            "sync", "--active", "--locked", "--no-dev", "--no-editable",
            "--project", str(self.plugin / "server"),
        ])
        self.assertEqual([event["args"] for event in events[sync_index + 1:]
                          if event["tool"] == "codex-task-tools-service"],
                         [["install"], ["start"], ["status"]])

    def test_current_cache_and_healthy_runtime_use_guarded_stop(self) -> None:
        self.assert_install_succeeded(self.run_setup())
        self.assertEqual([event["args"] for event in self.events("codex-task-tools-service")],
                         [["status"], ["stop"], ["status"], ["install"], ["start"], ["status"]])
        self.assertFalse(any(event["args"][0] == "run" for event in self.events("uv")))

    def test_wrong_cache_directory_is_rejected_before_runtime_access(self) -> None:
        wrong = self.plugin.with_name("0.1.0")
        shutil.copytree(self.plugin, wrong)
        state = json.loads(self.state_path.read_text())
        state["mcp_entry"]["transport"]["cwd"] = str(wrong)
        self.state_path.write_text(json.dumps(state))
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the selected marketplace", result.stderr)
        self.assertEqual(self.events("uv"), [])
        self.assertEqual(self.events("codex-task-tools-service"), [])

    def test_mismatched_manifest_package_or_lock_version_is_rejected(self) -> None:
        for relative in (".codex-plugin/plugin.json", "server/pyproject.toml", "server/uv.lock"):
            with self.subTest(file=relative):
                path = self.plugin / relative
                original = path.read_text()
                try:
                    path.write_text(original.replace('"0.1.1"', '"0.1.0"'))
                    self.log.write_text("")
                    result = self.run_setup()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("unexpected", result.stderr)
                    self.assertEqual(self.events("uv"), [])
                    self.assertEqual(self.events("codex-task-tools-service"), [])
                finally:
                    path.write_text(original)

    def test_unknown_active_or_pending_health_never_stops_or_syncs(self) -> None:
        states = [disconnected_status(), healthy_status(activeTaskCount=None),
                  healthy_status(pendingApprovalCount=None), healthy_status(activeTaskCount=1),
                  healthy_status(pendingApprovalCount=1), healthy_status(activeTaskCount=False),
                  healthy_status(pendingApprovalCount="0"), healthy_status(eventProcessingError=True)]
        for state in states:
            with self.subTest(status=state):
                self.configure(status=state)
                result = self.run_setup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active or unverified", result.stderr)
                self.assert_no_runtime_mutations()
                self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock"])

    def test_legacy_proof_failure_never_stops_or_replaces_runtime(self) -> None:
        self.configure(version="0.1.0", status=disconnected_status(), proof_exit=9)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not complete a guarded runtime replacement", result.stderr)
        self.assert_no_runtime_mutations()
        proof = next(event for event in self.events("uv") if event["args"][0] == "run")
        self.assertEqual(proof["args"], [
            "run", "--isolated", "--frozen", "--no-dev", "--no-editable", "--no-env-file",
            "--refresh-package", "codex-task-tools",
            "--project", str(self.plugin / "server"), "python", "-I", "-m", "codex_task_tools.upgrade",
            "--from-version", "0.1.0", "--to-version", VERSION,
            "--state-dir", str(self.codex_home / "state/codex-task-tools"),
            "--install-project", str(self.plugin / "server"), "--uv-executable", str(self.bin / "uv"),
        ])
        self.assertIsNone(proof["virtual_env"])
        self.assertIsNone(proof["uv_project_environment"])

    def test_legacy_uncertain_or_active_health_does_not_enter_disconnected_upgrade(self) -> None:
        states = [healthy_status(activeTaskCount=1), healthy_status(pendingApprovalCount=1)]
        for changes in ({"eventProcessingError": True}, {"quiesced": None},
                        {"running": False}, {"appServerVersion": "0.999.0"}):
            state = disconnected_status()
            state["broker"].update(changes)
            states.append(state)
        for state in states:
            with self.subTest(status=state):
                self.configure(version="0.1.0", status=state)
                result = self.run_setup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active or unverified", result.stderr)
                self.assert_no_runtime_mutations()
                self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock"])

    def test_legacy_upgrade_syncs_once_then_checks_stopped_status_before_start(self) -> None:
        self.configure(version="0.1.0", status=disconnected_status())
        self.assert_install_succeeded(self.run_setup(), guarded=True)
        self.assertNotIn(["stop"], [event["args"] for event in self.events("codex-task-tools-service")])
        self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock", "run"])

    def test_changed_status_after_legacy_upgrade_blocks_service_start(self) -> None:
        for state in (healthy_status(), disconnected_status()):
            with self.subTest(status=state):
                self.configure(version="0.1.0", status=disconnected_status(), post_proof_status=state)
                result = self.run_setup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not remain stopped", result.stderr)
                self.assert_no_shell_mutations()
                self.assertEqual(len(self.events("codex_task_tools.upgrade")), 1)

    def test_guarded_sync_failure_is_not_retried_by_shell(self) -> None:
        self.configure(version="0.1.0", status=disconnected_status(), upgrade_sync_exit=9)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not complete a guarded runtime replacement", result.stderr)
        self.assert_no_shell_mutations()
        self.assertEqual(len(self.events("codex_task_tools.upgrade")), 1)
        self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock", "run"])

    def test_invalid_helper_receipts_never_start_or_retry_runtime_replacement(self) -> None:
        missing_field = upgrade_receipt()
        del missing_field["runtimeInstalled"]
        receipts = ["", "{", "null", "false", "{}", json.dumps(missing_field),
                    json.dumps(upgrade_receipt())[:-1] + ',"ok":true}',
                    json.dumps(upgrade_receipt(extra=True))]
        for changes in ({"ok": False}, {"stopped": False}, {"runtimeInstalled": False},
                        {"fromVersion": "0.0.9"}, {"toVersion": "0.9.9"},
                        {"appServerVersion": "0.999.0"}, {"verifiedTerminalTaskCount": False},
                        {"verifiedTerminalTaskCount": -1}):
            receipts.append(json.dumps(upgrade_receipt(**changes)))
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                self.configure(version="0.1.0", status=disconnected_status(), helper_stdout=receipt)
                result = self.run_setup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid completion receipt; refusing startup", result.stderr)
                self.assert_no_shell_mutations()
                self.assertEqual(len(self.events("codex_task_tools.upgrade")), 1)
                self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock", "run"])

    def test_interrupted_install_marker_blocks_partial_runtime_before_import_or_mutation(self) -> None:
        marker = self.codex_home / "state/codex-task-tools/upgrade-install.json"
        marker.parent.mkdir(parents=True, mode=0o700)
        for version in ("0.1.0", "0.1.1", None):
            for kind in ("file", "broken-symlink"):
                with self.subTest(version=version, kind=kind):
                    self.configure(version=version or VERSION, status=stopped_status())
                    if version is None:
                        self.metadata.unlink()
                    if kind == "file":
                        marker.write_text("{}\n")
                    else:
                        marker.symlink_to(self.root / "absent-marker-target")
                    try:
                        result = self.run_setup()
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Interrupted Codex Task Tools installation requires reviewed recovery", result.stderr)
                        self.assert_no_runtime_mutations()
                        self.assertEqual(self.events("python"), [])
                        self.assertFalse(any(event["args"][0] == "run" for event in self.events("uv")))
                    finally:
                        marker.unlink()

    def test_marker_created_during_runtime_inspection_blocks_ordinary_install(self) -> None:
        marker = self.codex_home / "state/codex-task-tools/upgrade-install.json"
        for stage in ("metadata", "status"):
            with self.subTest(stage=stage):
                self.configure(version=VERSION, status=stopped_status(), inject_marker_at=stage)
                self.assertFalse(marker.exists())
                try:
                    result = self.run_setup()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Interrupted Codex Task Tools installation requires reviewed recovery", result.stderr)
                    self.assertEqual(marker.read_text(), '{"fixture":"interrupted"}\n')
                    self.assert_no_runtime_mutations()
                    self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock"])
                    self.assertTrue(any(event["args"][:2] == ["-I", "-c"]
                                        for event in self.events("python")))
                    if stage == "status":
                        self.assertEqual([event["args"] for event in self.events("codex-task-tools-service")],
                                         [["status"]])
                finally:
                    marker.unlink(missing_ok=True)

    def test_unloaded_legacy_runtime_still_requires_proof(self) -> None:
        self.configure(version="0.1.0", status=stopped_status(), proof_exit=9)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_runtime_mutations()
        self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock", "run"])

    def test_changed_status_after_normal_stop_blocks_replacement(self) -> None:
        self.configure(post_stop_status=healthy_status())
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not remain stopped", result.stderr)
        self.assertEqual([event["args"][0] for event in self.events("uv")], ["lock"])
        self.assertEqual([event["args"] for event in self.events("codex-task-tools-service")],
                         [["status"], ["stop"], ["status"]])

    def test_unrecognized_stable_package_version_is_rejected(self) -> None:
        self.configure(version="0.9.9")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a supported upgrade source", result.stderr)
        self.assert_no_runtime_mutations()
        self.assertEqual(self.events("codex-task-tools-service"), [])

    def test_final_health_executes_installed_allowlist_and_strict_count_checks(self) -> None:
        for broker_change in ({"appServerVersion": "0.999.0"}, {"backendConnected": False},
                              {"activeTaskCount": None}, {"pendingApprovalCount": False},
                              {"activeTaskCount": -1}, {"eventProcessingError": True}):
            with self.subTest(broker_change=broker_change):
                self.configure(final_status=healthy_status(**broker_change))
                result = self.run_setup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not become healthy", result.stderr)
                health_calls = [event for event in self.events("python") if event["args"] == ["-I", "-"]]
                self.assertEqual(len(health_calls), 3)

    def test_check_accepts_retained_runtime_without_service_mutations(self) -> None:
        self.configure(status=healthy_status(appServerVersion="0.156.1"))
        result = self.run_setup("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["broker"]["appServerVersion"], "0.156.1")
        self.assertEqual(self.events("uv"), [])
        self.assertEqual([event["args"] for event in self.events("codex-task-tools-service")], [["status"]])

    def test_check_legacy_runtime_explains_install_before_importing_compatibility(self) -> None:
        self.configure(version="0.1.0", status=disconnected_status())
        (self.site / "codex_task_tools/compatibility.py").unlink()
        result = self.run_setup("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime 0.1.0 must be upgraded with --install before --check", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assert_no_runtime_mutations()
        self.assertEqual(self.events("uv"), [])
        self.assertFalse(any(event["args"] == ["-I", "-"] for event in self.events("python")))

    def test_status_remains_readable_with_interrupted_marker_and_missing_metadata(self) -> None:
        self.configure(version="0.1.0", status=disconnected_status())
        self.metadata.unlink()
        marker = self.codex_home / "state/codex-task-tools/upgrade-install.json"
        marker.parent.mkdir(parents=True, mode=0o700)
        marker.write_text("{}\n")
        result = self.run_setup("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), disconnected_status())
        self.assertEqual(self.events("python"), [])
        self.assertEqual(self.events("uv"), [])
        self.assertEqual([event["args"] for event in self.events("codex-task-tools-service")], [["status"]])


if __name__ == "__main__":
    unittest.main()
