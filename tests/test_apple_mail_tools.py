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
SERVER = PLUGIN / "server" / "src" / "apple_mail_tools" / "server.py"
SETUP = ROOT / "scripts" / "setup-apple-mail-tools.sh"
TOOLBOX_SETUP = ROOT / "scripts" / "setup-codex-toolbox.sh"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
APPROVED_LAUNCHER_SHA256 = "41cd449f224e6f12614b53bf15f2f9e1f180787e7518b68cb5f29e29cf1e71f5"


class AppleMailToolsContractTests(unittest.TestCase):
    def test_manifest_marketplace_and_default_setup_are_consistent(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        marketplace = json.loads(MARKETPLACE.read_text())
        setup = TOOLBOX_SETUP.read_text()

        self.assertEqual(manifest["name"], "apple-mail-tools")
        self.assertEqual(manifest["version"], "0.1.0")
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
        self.assertEqual(server["command"], "/bin/zsh")
        self.assertEqual(server["args"][0], "-lc")
        self.assertEqual(
            hashlib.sha256(server["args"][1].encode()).hexdigest(),
            APPROVED_LAUNCHER_SHA256,
        )
        self.assertNotIn("uv sync", server["args"][1])
        self.assertIn("apple-mail-runtime-stamp", server["args"][1])

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
        for option in ("--check", "--install", "--status", "--init-config"):
            self.assertIn(option, helper)
        self.assertIn("--reinstall-package apple-mail-tools", helper)
        self.assertIn("run_locked exclusive --install-locked", helper)


if __name__ == "__main__":
    unittest.main()
