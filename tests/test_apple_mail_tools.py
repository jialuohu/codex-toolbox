import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "apple-mail-tools"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MCP = PLUGIN / ".mcp.json"
SKILL = PLUGIN / "skills" / "apple-mail" / "SKILL.md"
BRIDGE = PLUGIN / "server" / "scripts" / "mail_bridge.applescript"
LAUNCHER = PLUGIN / "server" / "scripts" / "apple-mail-mcp"
SERVER = PLUGIN / "server" / "src" / "apple_mail_tools" / "server.py"
PYPROJECT = PLUGIN / "server" / "pyproject.toml"
UV_LOCK = PLUGIN / "server" / "uv.lock"
PACKAGE_INIT = PLUGIN / "server" / "src" / "apple_mail_tools" / "__init__.py"
SETUP = ROOT / "scripts" / "setup-apple-mail-tools.sh"
TOOLBOX_SETUP = ROOT / "scripts" / "setup-codex-toolbox.sh"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
APPROVED_LAUNCHER_SHA256 = "9671ef5b3df9959856f6c058f1b0e690dedd7a62574d5e1eb8e7a09b3f5d0b47"


class AppleMailToolsContractTests(unittest.TestCase):
    def test_manifest_marketplace_and_default_setup_are_consistent(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        marketplace = json.loads(MARKETPLACE.read_text())
        setup = TOOLBOX_SETUP.read_text()

        self.assertEqual(manifest["name"], "apple-mail-tools")
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertIn('version = "0.2.0"', PYPROJECT.read_text())
        self.assertRegex(
            UV_LOCK.read_text(), r'(?ms)^name = "apple-mail-tools"\nversion = "0\.2\.0"$'
        )
        self.assertIn('__version__ = "0.2.0"', PACKAGE_INIT.read_text())
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        entry = next(item for item in marketplace["plugins"] if item["name"] == manifest["name"])
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/apple-mail-tools"})
        self.assertEqual(
            entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
        )
        default_block = setup.split("DEFAULT_PLUGINS=(", 1)[1].split(")", 1)[0]
        managed_block = setup.split("MANAGED_MCP_SERVERS=(", 1)[1].split(")", 1)[0]
        self.assertIn('"apple-mail-tools"', default_block)
        self.assertIn('"apple_mail"', managed_block)

    def test_mcp_approval_surface_and_launcher_are_exact(self) -> None:
        server = json.loads(MCP.read_text())["mcpServers"]["apple_mail"]
        expected_prompts = {
            "apple_mail_commit_index_sync",
            "apple_mail_erase_index",
            "apple_mail_fetch_attachment",
            "apple_mail_create_draft",
            "apple_mail_commit_mutation",
        }
        self.assertEqual(server["default_tools_approval_mode"], "auto")
        self.assertEqual(set(server["tools"]), expected_prompts)
        self.assertTrue(
            all(server["tools"][name] == {"approval_mode": "prompt"} for name in expected_prompts)
        )
        self.assertEqual(server["command"], "/bin/bash")
        self.assertEqual(server["args"], ["server/scripts/apple-mail-mcp"])
        self.assertEqual(
            hashlib.sha256(LAUNCHER.read_bytes()).hexdigest(),
            APPROVED_LAUNCHER_SHA256,
        )
        launcher = LAUNCHER.read_text()
        self.assertNotIn("uv sync", launcher)
        self.assertIn("apple-mail-tools-generations", launcher)
        self.assertIn("--kind generation --mode shared", launcher)
        self.assertTrue(LAUNCHER.stat().st_mode & 0o111)

    def test_tool_surface_and_static_no_send_guards(self) -> None:
        server_source = SERVER.read_text()
        tools = re.findall(r'@server\.tool\(name="([^"]+)"', server_source)
        self.assertEqual(len(tools), 18)
        self.assertEqual(len(tools), len(set(tools)))
        bridge = BRIDGE.read_text().casefold()
        self.assertNotIn("do shell script", bridge)
        self.assertIsNone(re.search(r"\bsend\s+(?:draft|message|outgoing|source)", bridge))
        self.assertIsNone(re.search(r"\bdelete\s+(?:message|mailbox|account)", bridge))
        skill = SKILL.read_text()
        self.assertIn("Queries never authorize writes", skill)
        self.assertIn("user must inspect it and click Send", skill)

    def test_setup_helpers_have_valid_shell_syntax(self) -> None:
        for script in (SETUP, TOOLBOX_SETUP):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        helper = SETUP.read_text()
        for option in ("--check", "--install", "--status", "--init-config", "--prune"):
            self.assertIn(option, helper)
        self.assertIn("--reinstall-package apple-mail-tools", helper)
        self.assertIn("run_setup_locked --install-setup-locked", helper)
        self.assertIn("run_generation_locked exclusive --install-generation-locked", helper)
        self.assertIn("LEGACY_RUNTIME", helper)
        self.assertNotIn('"$APPLE_MAIL_SETUP" --prune', TOOLBOX_SETUP.read_text())


if __name__ == "__main__":
    unittest.main()
