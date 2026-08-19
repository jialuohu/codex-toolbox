from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "plugins" / "research-tools"
SKILL = RESEARCH / "skills" / "docmost-lab-wiki" / "SKILL.md"
RUNTIME = RESEARCH / "runtime" / "docmost-lab-wiki"
SETUP = ROOT / "scripts" / "setup-docmost-lab-wiki.sh"
RUNNER = RESEARCH / "scripts" / "docmost-lab-wiki.sh"


class DocmostLabWikiContractTests(unittest.TestCase):
    def test_research_plugin_exposes_the_separate_lab_wiki(self) -> None:
        manifest = json.loads((RESEARCH / ".codex-plugin" / "plugin.json").read_text())
        prompts = manifest["interface"]["defaultPrompt"]

        self.assertEqual(manifest["version"], "0.8.0")
        self.assertIn("$docmost-lab-wiki", " ".join(prompts))
        self.assertIn("Research LLM Wiki", manifest["interface"]["longDescription"])
        self.assertIn("separate read-only Docmost-to-Obsidian Lab Wiki", manifest["interface"]["longDescription"])

    def test_skill_makes_only_snapshot_and_release_reachable_in_docmost(self) -> None:
        text = SKILL.read_text()
        self.assertIn("docmost_prepare_workspace_snapshot", text)
        self.assertIn("docmost_release_workspace_snapshot", text)
        self.assertIn("finally", text)
        self.assertNotIn("docmost_create_page", text)
        self.assertNotIn("docmost_update_page_title", text)
        self.assertNotIn("docmost_edit_page_text", text)
        self.assertNotIn("docmost_create_comment", text)
        self.assertIn("Never open, print, parse, summarize", text)

    def test_runtime_and_model_are_exactly_pinned(self) -> None:
        project = (RUNTIME / "pyproject.toml").read_text()
        lock = (RUNTIME / "uv.lock").read_text()
        constants = (RUNTIME / "src" / "docmost_lab_wiki" / "constants.py").read_text()
        setup = SETUP.read_text()

        self.assertIn('"fastembed==0.8.0"', project)
        self.assertIn('requires-python = ">=3.12,<3.13"', project)
        self.assertIn('name = "fastembed"', lock)
        self.assertIn('version = "0.8.0"', lock)
        for expected in (
            "c32e6154d1bb7a0e47c5e745fd895e7700f44385",
            "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431",
        ):
            self.assertIn(expected, constants)
            self.assertIn(expected, setup)

    def test_runner_forces_offline_normal_operation(self) -> None:
        text = RUNNER.read_text()
        self.assertTrue(RUNNER.stat().st_mode & 0o111)
        self.assertTrue(SETUP.stat().st_mode & 0o111)
        self.assertIn("HF_HUB_OFFLINE=1", text)
        self.assertIn("TRANSFORMERS_OFFLINE=1", text)
        self.assertNotIn("uv run", text)
        self.assertNotIn("pip install", text)

    def test_runtime_is_created_at_its_final_nonrelocatable_path(self) -> None:
        setup = SETUP.read_text()
        self.assertIn('UV_PROJECT_ENVIRONMENT="$RUNTIME"', setup)
        self.assertNotIn('UV_PROJECT_ENVIRONMENT="$candidate"', setup)

    def test_locked_runtime_is_fresh(self) -> None:
        result = subprocess.run(
            ["uv", "lock", "--check"],
            cwd=RUNTIME,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_docmost_snapshot_timeout_and_version_are_current(self) -> None:
        mcp = json.loads((ROOT / "plugins" / "docmost-tools" / ".mcp.json").read_text())
        manifest = json.loads(
            (ROOT / "plugins" / "docmost-tools" / ".codex-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["version"], "0.6.0")
        server = mcp["mcpServers"]["docmost"]
        self.assertEqual(server["tool_timeout_sec"], 900)
        self.assertEqual(server["command"], "/bin/bash")
        self.assertEqual(server["args"], ["server/scripts/docmost-mcp"])
        self.assertEqual(server["env_vars"], ["CODEX_SECRETS_DIR", "CODEX_HOME"])


if __name__ == "__main__":
    unittest.main()
