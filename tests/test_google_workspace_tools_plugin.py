import json
import os
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
COMPOSE_SKILLS = (
    "gws-gmail-send",
    "gws-gmail-reply",
    "gws-gmail-reply-all",
    "gws-gmail-forward",
)


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


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def markdown_references(path: Path) -> set[str]:
    return {
        target.split("#", 1)[0]
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
        if target and not re.match(r"(?:https?://|mailto:|#)", target)
    }


def lexical_reference(path: Path, target: str) -> str:
    relative_parent = path.parent.relative_to(PLUGIN)
    return Path(os.path.normpath(str(relative_parent / target))).as_posix()


def active_shell_array_entries(script: str, name: str) -> list[str]:
    match = re.search(rf"^{re.escape(name)}=\((.*?)^\)", script, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"missing shell array: {name}")
    entries = []
    for raw_line in match.group(1).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        entry = re.fullmatch(r'"([^"]+)"', line)
        if entry:
            entries.append(entry.group(1))
    return entries


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
        inventory = {
            path.relative_to(PLUGIN).as_posix()
            for path in PLUGIN.rglob("*")
            if path.is_file()
        }
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
            self.assertNotRegex(
                skill.read_text(encoding="utf-8"),
                r"(?m)^\s*gws (?:--version|auth|gmail|schema)\b",
                name,
            )
            self.assertEqual(set(parse_openai_yaml(metadata)), {"interface", "policy"})
            if name != "gws-shared":
                self.assertIn("../gws-shared/SKILL.md", skill.read_text(encoding="utf-8"), name)
            for reference in markdown_references(skill):
                self.assertIn(
                    lexical_reference(skill, reference),
                    inventory,
                    f"{name} has an unresolved markdown reference: {reference}",
                )

    def test_shared_skill_uses_managed_binary_and_plain_status_command(self):
        shared = normalized(PLUGIN / "skills" / "gws-shared" / "SKILL.md")
        shared_source = (PLUGIN / "skills" / "gws-shared" / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            '${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws',
            'gws_bin=',
            '[ -x "$gws_bin" ]',
            '"$gws_bin" --version',
            'first_line',
            'gws 0.22.5',
            '"$gws_bin" auth status',
            'same absolute `$gws_bin`',
            'Fail closed',
        ):
            self.assertIn(required, shared)
        self.assertNotIn("auth status --format", shared)
        self.assertNotRegex(shared_source, r"(?m)^\s*gws (?:--version|auth|gmail)\b")

    def test_shared_skill_validates_profile_privacy_before_gws(self):
        shared = normalized(PLUGIN / "skills" / "gws-shared" / "SKILL.md")
        for required in (
            "explicit alias",
            "^[a-z0-9][a-z0-9._-]{0,62}$",
            "`.`",
            "`..`",
            "accounts_root",
            'profile="$accounts_root/$alias"',
            "canonical",
            "direct child",
            "root, profile, or descendant symlink",
            "profile.json",
            "client_secret.json",
            "regular file",
            "700",
            "600",
            "traversal error",
            "schema_version",
            "expected_email",
            '"$gws_bin" auth status',
            "GOOGLE_WORKSPACE_CLI_CONFIG_DIR",
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "missing profile-local sentinel",
            "-u GOOGLE_WORKSPACE_CLI_TOKEN",
            "-u GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
            "-u GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE",
            "-u GOOGLE_WORKSPACE_CLI_CLIENT_ID",
            "-u GOOGLE_WORKSPACE_CLI_CLIENT_SECRET",
            "-u GOOGLE_WORKSPACE_CLI_LOG",
            "-u GOOGLE_WORKSPACE_CLI_LOG_FILE",
            "-u GOOGLE_WORKSPACE_PROJECT_ID",
            "-u GOOGLE_APPLICATION_CREDENTIALS",
            "from `/`",
            "exact case-insensitive email match",
            "token_valid: true",
            "storage",
            "encrypted",
            "keyring_backend",
            "encrypted_credentials_exists",
            "encryption_valid",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://mail.google.com/",
            "absolute attachment paths",
            "no same-request Gmail connector fallback",
            "Fail closed",
        ):
            self.assertIn(required, shared)

        validation_end = shared.index("profile validation passed")
        gws_start = shared.index('"$gws_bin" --version')
        self.assertLess(validation_end, gws_start)

    def test_each_compose_skill_independently_enforces_draft_and_send_boundary(self):
        for name in COMPOSE_SKILLS:
            text = normalized(PLUGIN / "skills" / name / "SKILL.md").lower()
            self.assertIn("../gws-shared/skill.md", text, name)
            self.assertIn("--draft", text, name)
            self.assertIn("explicit user intent to send", text, name)
            self.assertIn("identity/recipient preview", text, name)
            self.assertIn('"$gws_bin" gmail', text, name)

    def test_raw_gmail_surface_is_read_only_and_mutations_require_exact_preview(self):
        gmail = normalized(PLUGIN / "skills" / "gws-gmail" / "SKILL.md").lower()
        for required in (
            "raw gmail resource access is read-only",
            "list/get/search",
            "users.messages.send",
            "users.drafts.send",
            "helper skills",
            "explicit user intent",
            "exact action",
            "explicit alias",
            "verified identity",
            "query snapshot",
            "count",
            "exact message/thread ids",
            "labels",
            "target preview",
            "trash/untrash",
            "bounded batch mutation",
            "raw label",
            "raw draft",
        ):
            self.assertIn(required, gmail)
        all_skill_text = "\n".join(
            (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            for name in SKILLS
        ).lower()
        for prohibited in ("permanent delete", "gmail settings", "delegation", "cse", "non-gmail service"):
            self.assertNotIn(prohibited, all_skill_text)

    def test_marketplace_and_setup_install_plugin_but_never_manage_gws_mcp(self):
        marketplace = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        entry = next(item for item in marketplace["plugins"] if item["name"] == "google-workspace-tools")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/google-workspace-tools"})
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        setup = (REPO_ROOT / "scripts" / "setup-codex-toolbox.sh").read_text(encoding="utf-8")
        default_plugins = active_shell_array_entries(setup, "DEFAULT_PLUGINS")
        self.assertIn("google-workspace-tools", default_plugins)
        self.assertNotIn(
            "google-workspace-tools",
            active_shell_array_entries(
                'DEFAULT_PLUGINS=(\n  # "google-workspace-tools"\n)\n',
                "DEFAULT_PLUGINS",
            ),
        )
        managed_block = re.search(r"MANAGED_MCP_SERVERS=\((.*?)\n\)", setup, re.DOTALL)
        self.assertIsNotNone(managed_block)
        self.assertNotIn("gws", managed_block.group(1).lower())


if __name__ == "__main__":
    unittest.main()
