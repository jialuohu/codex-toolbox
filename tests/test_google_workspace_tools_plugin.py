import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
PLUGIN = REPO_ROOT / "plugins" / "google-workspace-tools"
SKILLS = (
    "gws-shared",
    "gws-gmail",
    "gws-gmail-read",
    "gws-gmail-triage",
    "gws-gmail-send",
    "gws-gmail-reply",
    "gws-gmail-reply-all",
    "gws-gmail-forward",
)
UPSTREAM_TAG = "v0.22.5"
UPSTREAM_COMMIT = "705fb0ecac6f4249679958f6325b809b63fdde17"


def frontmatter(path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        raise AssertionError(f"missing frontmatter: {path}")
    values = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"invalid frontmatter line: {line}")
        values[key] = value.strip().strip('"')
    return values


def parse_openai_yaml(path: Path) -> dict:
    """Parse the deliberately small scalar-only openai.yaml contract."""
    parsed: dict[str, dict] = {}
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, separator, value = line.partition(":")
            if not separator or value.strip():
                raise AssertionError(f"invalid top-level YAML: {line}")
            parsed[key] = {}
            section = key
            continue
        key, separator, value = line.strip().partition(":")
        if section is None or not separator:
            raise AssertionError(f"invalid YAML: {line}")
        value = value.strip()
        parsed[section][key] = value == "true" if value in {"true", "false"} else value.strip('"')
    return parsed


class GoogleWorkspaceToolsPluginTests(unittest.TestCase):
    def test_plugin_has_exact_gmail_only_inventory_and_provenance(self):
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "google-workspace-tools")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertFalse((PLUGIN / ".mcp.json").exists())
        self.assertFalse((PLUGIN / ".app.json").exists())
        self.assertFalse((PLUGIN / "hooks").exists())
        self.assertFalse((PLUGIN / "assets").exists())
        self.assertEqual(
            {item.name for item in (PLUGIN / "skills").iterdir() if item.is_dir()}, set(SKILLS)
        )
        self.assertIn("Apache License", (PLUGIN / "LICENSE").read_text(encoding="utf-8"))
        provenance = (PLUGIN / "PROVENANCE.md").read_text(encoding="utf-8")
        for required in ("https://github.com/googleworkspace/cli", UPSTREAM_TAG, UPSTREAM_COMMIT, *SKILLS):
            self.assertIn(required, provenance)

    def test_every_skill_is_discoverable_and_reuses_shared_contract(self):
        for name in SKILLS:
            skill = PLUGIN / "skills" / name / "SKILL.md"
            metadata = PLUGIN / "skills" / name / "agents" / "openai.yaml"
            self.assertTrue(skill.is_file(), name)
            self.assertTrue(metadata.is_file(), name)
            fields = frontmatter(skill)
            self.assertEqual(set(fields), {"name", "description"})
            self.assertEqual(fields["name"], name)
            self.assertTrue(fields["description"].startswith("Use when"))
            self.assertNotIn("disable-model-invocation", skill.read_text(encoding="utf-8"))
            self.assertEqual(set(parse_openai_yaml(metadata)), {"interface", "policy"})
            if name != "gws-shared":
                self.assertIn("../gws-shared/SKILL.md", skill.read_text(encoding="utf-8"), name)

    def test_shared_skill_fails_closed_and_mutations_are_explicit(self):
        shared = " ".join((PLUGIN / "skills" / "gws-shared" / "SKILL.md").read_text(encoding="utf-8").split())
        for required in (
            "explicit alias",
            "profile.json",
            "gws auth status",
            "GOOGLE_WORKSPACE_CLI_CONFIG_DIR",
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "missing profile-local sentinel",
            "-u GOOGLE_WORKSPACE_CLI_CREDENTIAL",
            "from `/`",
            "exact case-insensitive email match",
            "token_valid: true",
            "https://mail.google.com/",
            "absolute attachment paths",
            "no same-request Gmail connector fallback",
            "Fail closed",
        ):
            self.assertIn(required, shared)
        all_skill_text = "\n".join(
            (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8") for name in SKILLS
        ).lower()
        self.assertIn("--draft", all_skill_text)
        self.assertIn("explicit user intent", all_skill_text)
        self.assertIn("identity/recipient preview", all_skill_text)
        for prohibited in ("permanent delete", "gmail settings", "delegation", "cse", "non-gmail service"):
            self.assertNotIn(prohibited, all_skill_text)

    def test_marketplace_and_setup_install_plugin_but_never_manage_gws_mcp(self):
        marketplace = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        entry = next(item for item in marketplace["plugins"] if item["name"] == "google-workspace-tools")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/google-workspace-tools"})
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        setup = (REPO_ROOT / "scripts" / "setup-codex-toolbox.sh").read_text(encoding="utf-8")
        default_block = re.search(r"DEFAULT_PLUGINS=\((.*?)\n\)", setup, re.DOTALL)
        managed_block = re.search(r"MANAGED_MCP_SERVERS=\((.*?)\n\)", setup, re.DOTALL)
        self.assertIsNotNone(default_block)
        self.assertIn('"google-workspace-tools"', default_block.group(1))
        self.assertIsNotNone(managed_block)
        self.assertNotIn("gws", managed_block.group(1).lower())


if __name__ == "__main__":
    unittest.main()
