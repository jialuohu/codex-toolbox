from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "overleaf-tools"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MCP = PLUGIN / ".mcp.json"
PYPROJECT = PLUGIN / "server" / "pyproject.toml"
UV_LOCK = PLUGIN / "server" / "uv.lock"
PACKAGE_INIT = PLUGIN / "server" / "src" / "overleaf_tools" / "__init__.py"
SERVER = PLUGIN / "server" / "src" / "overleaf_tools" / "server.py"
GIT_CLIENT = PLUGIN / "server" / "src" / "overleaf_tools" / "git_client.py"
ASKPASS = PLUGIN / "server" / "src" / "overleaf_tools" / "askpass.py"
SKILL = PLUGIN / "skills" / "overleaf" / "SKILL.md"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SETUP = ROOT / "scripts" / "setup-codex-toolbox.sh"
CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"
WORKFLOW = ROOT / ".github" / "workflows" / "overleaf-tools.yml"


class OverleafToolsContractTests(unittest.TestCase):
    def test_manifest_marketplace_and_versions_are_consistent(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        marketplace = json.loads(MARKETPLACE.read_text())
        self.assertEqual(manifest["name"], "overleaf-tools")
        self.assertEqual(manifest["version"], "0.1.2")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertIn('version = "0.1.2"', PYPROJECT.read_text())
        self.assertRegex(
            UV_LOCK.read_text(), r'(?ms)^name = "overleaf-tools"\nversion = "0\.1\.2"$'
        )
        self.assertIn('__version__ = "0.1.2"', PACKAGE_INIT.read_text())
        entry = next(item for item in marketplace["plugins"] if item["name"] == manifest["name"])
        self.assertEqual(
            entry["source"], {"source": "local", "path": "./plugins/overleaf-tools"}
        )
        self.assertEqual(
            entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
        )

    def test_plugin_is_opt_in_and_write_tools_prompt(self) -> None:
        setup = SETUP.read_text()
        defaults = setup.split("DEFAULT_PLUGINS=(", 1)[1].split(")", 1)[0]
        managed = setup.split("MANAGED_MCP_SERVERS=(", 1)[1].split(")", 1)[0]
        self.assertNotIn('"overleaf-tools"', defaults)
        self.assertNotIn('"overleaf"', managed)
        server = json.loads(MCP.read_text())["mcpServers"]["overleaf"]
        self.assertEqual(server["command"], "uv")
        self.assertEqual(
            server["args"],
            [
                "run",
                "--frozen",
                "--no-dev",
                "--no-editable",
                "--no-env-file",
                "--project",
                "server",
                "overleaf-mcp",
            ],
        )
        self.assertEqual(server["default_tools_approval_mode"], "auto")
        self.assertEqual(
            set(server["tools"]),
            {
                "overleaf_edit_text_file",
                "overleaf_write_text_file",
                "overleaf_import_file",
                "overleaf_move_file",
                "overleaf_delete_file",
            },
        )
        self.assertTrue(
            all(value == {"approval_mode": "prompt"} for value in server["tools"].values())
        )

    def test_tool_and_security_contracts_are_static(self) -> None:
        source = SERVER.read_text()
        tools = re.findall(r'@server\.tool\(name="([^"]+)"', source)
        self.assertEqual(len(tools), 12)
        self.assertEqual(len(tools), len(set(tools)))
        combined = GIT_CLIENT.read_text() + ASKPASS.read_text()
        self.assertNotIn("shell=True", combined)
        self.assertNotIn("https://git:", combined)
        self.assertNotIn("@git.overleaf.com", combined)
        for expected in (
            "GIT_ASKPASS_REQUIRE",
            "GIT_CONFIG_GLOBAL",
            "credential.helper=",
            "HEAD:refs/heads/{branch}",
            '_ALLOWED_REMOTE_BRANCHES = {"main", "master"}',
            "OUTCOME_UNKNOWN",
            "expected_blob_sha",
        ):
            self.assertIn(expected, combined)
        skill = SKILL.read_text()
        self.assertIn("Never retry an `OUTCOME_UNKNOWN` mutation", skill)
        self.assertIn("Do not use browser automation or raw Git", skill)

    def test_checker_and_cross_platform_ci_cover_plugin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workflow = WORKFLOW.read_text()
        for expected in ("ubuntu-latest", "macos-latest", "windows-latest", "uv sync --frozen"):
            self.assertIn(expected, workflow)
        self.assertRegex(
            workflow,
            r"(?s)- name: Run package tests\s+"
            r"working-directory: plugins/overleaf-tools/server\s+"
            r"run: uv run --frozen pytest -q",
        )


if __name__ == "__main__":
    unittest.main()
