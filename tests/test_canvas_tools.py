from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "canvas-tools"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MCP = PLUGIN / ".mcp.json"
LAUNCHER = PLUGIN / "scripts" / "run-canvas-mcp.sh"
SKILL = PLUGIN / "skills" / "canvas-student-planning" / "SKILL.md"
OPENAI = SKILL.parent / "agents" / "openai.yaml"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SETUP = ROOT / "scripts" / "setup-codex-toolbox.sh"

READ_TOOLS = {
    "get_assignment_details",
    "get_my_course_grades",
    "get_my_enrollments",
    "get_my_peer_reviews_todo",
    "get_my_profile",
    "get_my_submission",
    "get_my_submission_status",
    "get_my_todo_items",
    "get_my_upcoming_assignments",
    "list_assignments",
    "list_courses",
}
WRITE_TOOLS = {"comment_on_my_submission", "submit_assignment"}


class CanvasToolsContractTests(unittest.TestCase):
    def test_manifest_and_marketplace_are_consistent(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        marketplace = json.loads(MARKETPLACE.read_text())

        self.assertEqual(manifest["name"], "canvas-tools")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertLessEqual(len(manifest["interface"]["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in manifest["interface"]["defaultPrompt"]))

        entry = next(item for item in marketplace["plugins"] if item["name"] == "canvas-tools")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/canvas-tools"})
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertNotIn('  "canvas-tools"', SETUP.read_text().split("THIRD_PARTY_DEFAULT_PLUGINS=", 1)[0])

    def test_mcp_has_exact_student_allowlist_and_write_prompts(self) -> None:
        server = json.loads(MCP.read_text())["mcpServers"]["canvas"]

        self.assertEqual(set(server["enabled_tools"]), READ_TOOLS | WRITE_TOOLS)
        self.assertEqual(server["default_tools_approval_mode"], "auto")
        self.assertEqual(
            server["tools"],
            {name: {"approval_mode": "prompt"} for name in sorted(WRITE_TOOLS)},
        )
        for forbidden in (
            "execute_typescript",
            "mark_module_item_done",
            "create_assignment",
            "update_assignment",
            "delete_assignment_with_confirmation",
            "send_conversation",
        ):
            self.assertNotIn(forbidden, server["enabled_tools"])

    def test_skill_owns_canvas_mapping_and_delegates_todoist_writes(self) -> None:
        text = " ".join(SKILL.read_text().split())
        metadata = OPENAI.read_text()

        for expected in (
            "Canvas as the authoritative source",
            "Todoist as the durable source",
            "Canvas: course_id=<COURSE_ID>; assignment_id=<ASSIGNMENT_ID>",
            "Confirm a multi-task preview",
            "Delegate Todoist mutations to `$todoist-task-planning`",
            "Choose exactly one Todoist surface",
            "Never automatically complete, reopen, or delete",
            "two-call preview-and-confirm",
            "Never submit group assignments",
            "does not automatically complete its Todoist task",
            "Read back every changed task",
        ):
            self.assertIn(expected, text)
        for expected in ('value: "canvas"', 'value: "todoist"', 'url: "https://ai.todoist.net/mcp"'):
            self.assertIn(expected, metadata)


class CanvasLauncherTests(unittest.TestCase):
    def run_launcher(self, secret_text: str, mode: int = 0o600, argument: str | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secrets = root / "secrets" / "canvas-tools"
            secrets.mkdir(parents=True)
            secret = secrets / "canvas.env"
            secret.write_text(secret_text)
            secret.chmod(mode)

            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_uvx = bin_dir / "uvx"
            fake_uvx.write_text(
                "#!/bin/sh\n"
                "printf 'args=%s\\n' \"$*\"\n"
                "printf 'role=%s\\nwrites=%s\\npolicy=%s\\nexec=%s\\n' "
                '"$CANVAS_ROLE" "$STUDENT_WRITE_TOOLS" "$COURSE_AGENT_POLICY_ENABLED" "$EXECUTE_TYPESCRIPT_ENABLED"\n'
            )
            fake_uvx.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "CODEX_SECRETS_DIR": str(root / "secrets"),
                "CODEX_LOCAL_BIN_DIR": str(bin_dir),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
            })
            command = ["/bin/sh", str(LAUNCHER)]
            if argument:
                command.append(argument)
            return subprocess.run(command, env=env, text=True, capture_output=True, check=False)

    def test_launcher_reports_resolved_path_when_configuration_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / "codex-home"
            env = os.environ.copy()
            env.pop("CODEX_SECRETS_DIR", None)
            env["CODEX_HOME"] = str(codex_home)

            result = subprocess.run(
                ["/bin/sh", str(LAUNCHER)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            expected = codex_home / "secrets" / "canvas-tools" / "canvas.env"
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(expected), result.stderr)
            self.assertNotIn("parameter not set", result.stderr)

    def test_launcher_pins_upstream_and_overrides_widening_attempts(self) -> None:
        token = "super-secret-token"
        result = self.run_launcher(
            "CANVAS_API_URL=https://example.instructure.com/api/v1\n"
            f"CANVAS_API_TOKEN={token}\n"
            "CANVAS_ROLE=all\n"
            "STUDENT_WRITE_TOOLS=mark_module_item_done\n"
            "COURSE_AGENT_POLICY_ENABLED=true\n"
            "EXECUTE_TYPESCRIPT_ENABLED=true\n",
            argument="--test",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--from canvas-mcp==1.12.0 canvas-mcp-server --test --role student", result.stdout)
        self.assertIn("role=student", result.stdout)
        self.assertIn("writes=submit_assignment,comment_on_my_submission", result.stdout)
        self.assertIn("policy=false", result.stdout)
        self.assertIn("exec=false", result.stdout)
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_launcher_rejects_insecure_or_incomplete_configuration(self) -> None:
        insecure = self.run_launcher(
            "CANVAS_API_URL=http://example.instructure.com/api/v1\n"
            "CANVAS_API_TOKEN=secret\n"
        )
        self.assertNotEqual(insecure.returncode, 0)
        self.assertIn("HTTPS URL ending in /api/v1", insecure.stderr)

        missing = self.run_launcher("CANVAS_API_URL=https://example.instructure.com/api/v1\n")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("must define CANVAS_API_URL and CANVAS_API_TOKEN", missing.stderr)

    def test_launcher_rejects_permissive_secret_mode(self) -> None:
        result = self.run_launcher(
            "CANVAS_API_URL=https://example.instructure.com/api/v1\n"
            "CANVAS_API_TOKEN=secret\n",
            mode=0o644,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must have mode 600", result.stderr)


if __name__ == "__main__":
    unittest.main()
