import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional


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
GWS_BINARY_SHA256 = "0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e"
REQUIRED_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)
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


def shared_bash_blocks(source: Optional[str] = None) -> list[str]:
    if source is None:
        source = (PLUGIN / "skills" / "gws-shared" / "SKILL.md").read_text(encoding="utf-8")
    return re.findall(r"```bash\n(.*?)\n```", source, re.DOTALL)


def shared_preflight_script(
    source: Optional[str] = None,
) -> str:
    blocks = shared_bash_blocks(source)
    if len(blocks) != 3:
        raise AssertionError(f"expected three ordered shared bash blocks, found {len(blocks)}")
    return "\n\n".join((*blocks, "printf 'PREFLIGHT_OK\\n'"))


def profile_validator_python(source: Optional[str] = None) -> str:
    first_block = shared_bash_blocks(source)[0]
    match = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", first_block, re.DOTALL)
    if match is None:
        raise AssertionError("profile-validator Python heredoc not found")
    return match.group(1)


class GoogleWorkspaceToolsPluginTests(unittest.TestCase):
    def test_plugin_has_exact_gmail_only_inventory_and_provenance(self):
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "google-workspace-tools")
        self.assertEqual(manifest["version"], "0.2.1")
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
        for required in (
            "https://github.com/googleworkspace/cli",
            UPSTREAM_TAG,
            UPSTREAM_COMMIT,
            "quota-project runtime-client split is a local safety and compatibility patch",
            *SKILLS,
        ):
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
            'RUNTIME_DIR_PATH="$gws_runtime_dir"',
            "metadata = os.lstat(component)",
            "metadata.st_uid not in trusted_owners",
            "mode & (stat.S_IWGRP | stat.S_IWOTH)",
            "not stat.S_ISREG(metadata.st_mode)",
            '/usr/bin/shasum -a 256 "$gws_bin"',
            GWS_BINARY_SHA256,
            '"$gws_bin" --version',
            'first_line',
            'gws 0.22.5',
            '"$gws_bin" auth status',
            'same absolute `$gws_bin`',
            'Fail closed',
        ):
            self.assertIn(required, shared)
        self.assertEqual(shared_source.count(GWS_BINARY_SHA256), 1)
        self.assertEqual(shared_source.count("/usr/bin/python3 -I - <<'PY'"), 4)
        self.assertIn("/usr/bin/env -u GOOGLE_WORKSPACE_CLI_TOKEN", shared_source)
        self.assertIn("same scrubbed absolute `/usr/bin/env` prefix", shared)
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
            "secrets_root",
            'profile="$accounts_root/$alias"',
            "canonical",
            "direct child",
            "secrets root, accounts root, profile, or descendant symlink",
            "profile.json",
            "client_secret.json",
            "credentials.enc",
            ".encryption_key",
            "rejects `credentials.json`",
            "imported_authorized_user",
            "existing_grant",
            "source_sha256",
            "lowercase 64-hex",
            "single-link `credentials.json`",
            "duplicate keys",
            "current user",
            "Boolean `true` is invalid",
            "regular file",
            "700",
            "600",
            "traversal error",
            "schema_version",
            "expected_email",
            '"$gws_bin" auth status',
            "GOOGLE_WORKSPACE_CLI_CONFIG_DIR",
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file",
            'GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json"',
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
            "-u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE",
            "-u GOOGLE_WORKSPACE_CLI_SANITIZE_MODE",
            "-u GOOGLE_APPLICATION_CREDENTIALS",
            "from `/`",
            "exact case-insensitive email match",
            "token_valid: true",
            "storage",
            "encrypted",
            "keyring_backend",
            "encrypted_credentials_exists",
            "plain_credentials_exists",
            "status.get(\"plain_credentials_exists\") is False",
            "encryption_valid",
            "has_refresh_token",
            "plain_credentials",
            "client_config",
            "https://www.googleapis.com/auth/gmail.modify",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "len(scopes) == len(required_scopes)",
            "set(scopes) == required_scopes",
            "https://mail.google.com/",
            "absolute attachment paths",
            "no same-request Gmail connector fallback",
            "Fail closed",
        ):
            self.assertIn(required, shared)

        validation_end = shared.index("profile validation passed")
        gws_start = shared.index('"$gws_bin" --version')
        self.assertLess(validation_end, gws_start)

    def test_each_compose_skill_requires_authoritative_draft_readback_and_send_boundary(self):
        expected_helpers = {
            "gws-gmail-send": "+send",
            "gws-gmail-reply": "+reply",
            "gws-gmail-reply-all": "+reply-all",
            "gws-gmail-forward": "+forward",
        }
        for name in COMPOSE_SKILLS:
            text = normalized(PLUGIN / "skills" / name / "SKILL.md").lower()
            self.assertIn("../gws-shared/skill.md", text, name)
            self.assertIn("--draft", text, name)
            self.assertRegex(
                text,
                rf'"\$gws_bin" gmail {re.escape(expected_helpers[name])} '
                rf'[^\n]*--from "\$expected_email"[^\n]*--draft',
                name,
            )
            self.assertIn("explicit user intent to send", text, name)
            self.assertIn("identity/recipient preview", text, name)
            self.assertIn('"$gws_bin" gmail', text, name)
            for authoritative_requirement in (
                "primary verified identity is the only permitted from",
                "always create a server-side draft first",
                "parse exactly one draft id",
                "users.drafts.get",
                "full draft",
                "case-insensitively",
                "actual from",
                "to/cc/bcc",
                "subject",
                "thread context",
                "attachment names and count",
                "decoded body content",
                "`text/plain` and `text/html`",
                "canonical mime content digest",
                "body content against the requested body",
                "preview the decoded body",
                "preview the readback",
                "draft-only request stops",
                "immediate unchanged readback",
                "body bytes and canonical mime content digest",
                "users.drafts.send",
                "exact newly created draft",
                "mismatch",
                "fail closed",
            ):
                self.assertIn(
                    authoritative_requirement,
                    text,
                    f"{name}: {authoritative_requirement}",
                )
            for command_requirement in (
                "gws v0.22.5 schema",
                "isolated_gws()",
                "cd / || exit 1",
                "/usr/bin/env -u google_workspace_cli_token",
                'google_workspace_cli_config_dir="$profile"',
                "google_workspace_cli_keyring_backend=file",
                'isolated_gws gmail users drafts get --params "$draft_get_params"',
                'draft_json_again="$(isolated_gws gmail users drafts get '
                '--params "$draft_get_params")" || exit 1',
                'isolated_gws gmail users drafts send --params \'{"userid":"me"}\' '
                '--json "$draft_send_body" || exit 1',
                '"userid": "me"',
                '"format": "full"',
            ):
                self.assertIn(command_requirement, text, f"{name}: {command_requirement}")
            self.assertGreaterEqual(
                text.count('"id": os.environ["draft_id"]'),
                2,
                f"{name}: raw get params and send body must use the exact parsed draft ID",
            )
            for attachment_requirement in (
                "attachment safety contract",
                "private temporary directory",
                "initial lstat",
                "device/inode",
                "sha-256",
                "byte size",
                "copy the exact bytes",
                "post-copy",
                "restat and rehash",
                "staged digest",
                "original absolute path",
                "basename",
                "size and digest",
                "only the staged copy",
                "final staged digest",
                "cleanup",
            ):
                self.assertIn(attachment_requirement, text, f"{name}: {attachment_requirement}")

        forward = normalized(PLUGIN / "skills" / "gws-gmail-forward" / "SKILL.md").lower()
        self.assertIn("server-side original attachments", forward)
        self.assertIn("separate", forward)
        self.assertIn("authoritative attachment names and count", forward)
        reply_all = normalized(PLUGIN / "skills" / "gws-gmail-reply-all" / "SKILL.md").lower()
        self.assertIn("authoritative resolved recipients", reply_all)

    def test_shared_attachment_contract_stages_exact_bytes_and_revalidates_identity(self):
        shared = normalized(PLUGIN / "skills" / "gws-shared" / "SKILL.md").lower()
        for required in (
            "before draft or send",
            "user-supplied attachment",
            "absolute path",
            "initial `lstat`",
            "regular final object",
            "final symlink",
            "canonical target path",
            "device/inode",
            "sha-256 digest",
            "byte size",
            "private temporary directory",
            "copy the exact bytes",
            "post-copy",
            "restat and rehash",
            "staged digest",
            "identity/recipient preview",
            "original absolute path",
            "basename",
            "size",
            "digest",
            "final staged digest",
            "only the staged copy",
            "cleanup",
            "fail closed",
            "trusted `/usr/bin/python3 -i`",
            "never path-resolved `python3`",
        ):
            self.assertIn(required, shared)

    def test_raw_gmail_surface_is_read_only_and_mutations_require_exact_preview(self):
        gmail = normalized(PLUGIN / "skills" / "gws-gmail" / "SKILL.md").lower()
        for required in (
            "raw gmail resource access is read-only",
            "list/get/search",
            "users.messages.send",
            "users.drafts.send",
            "helper skills",
            "exact newly created",
            "immediate unchanged readback",
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
            "raw draft create/update/delete",
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


class SharedPreflightExecutionTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name).resolve()
        self.secrets = self.root / "secrets"
        self.accounts = self.secrets / "gws" / "accounts"
        self.accounts.mkdir(parents=True)
        self.secrets.chmod(0o700)
        (self.secrets / "gws").chmod(0o700)
        self.accounts.chmod(0o700)
        self.registered_client = self.secrets / "gws" / "client_secret.json"
        self.registered_client.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "id",
                        "client_secret": "secret",
                        "project_id": "registered-project",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.registered_client.chmod(0o600)
        self.data = self.root / "data"
        self.log = self.root / "gws.log"
        self.shim_log = self.root / "hostile-shims.log"
        self.hostile_bin = self.root / "hostile-bin"
        self.hostile_bin.mkdir()
        self.hostile_pythonpath = self.root / "hostile-pythonpath"
        self.hostile_pythonpath.mkdir()
        (self.hostile_bin / "python3").write_text(
            """#!/bin/sh
printf 'python3\n' >> "$FAKE_SHIM_LOG"
printf 'personal@example.com\n'
exit 0
""",
            encoding="utf-8",
        )
        (self.hostile_bin / "env").write_text(
            """#!/bin/sh
printf 'env\n' >> "$FAKE_SHIM_LOG"
printf '%s\n' '{"user":"personal@example.com","token_valid":true,"scopes":["https://www.googleapis.com/auth/gmail.modify"],"storage":"encrypted","keyring_backend":"file","encrypted_credentials_exists":true,"encryption_valid":true}'
exit 0
""",
            encoding="utf-8",
        )
        (self.hostile_bin / "python3").chmod(0o755)
        (self.hostile_bin / "env").chmod(0o755)
        (self.hostile_pythonpath / "sitecustomize.py").write_text(
            """import json
import os
import stat
from types import SimpleNamespace

if os.environ.get("FORCE_GWS_VALIDATORS_HEALTHY") == "1":
    with open(os.environ["FAKE_SHIM_LOG"], "a", encoding="utf-8") as log:
        log.write("sitecustomize\\n")

    original_lstat = os.lstat

    def safe_lstat(path):
        metadata = original_lstat(path)
        if stat.S_ISDIR(metadata.st_mode):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700)
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600)

    os.lstat = safe_lstat
    json.load = lambda source: {
        "schema_version": 1,
        "expected_email": "personal@example.com",
    }
    json.loads = lambda source: {
        "user": "personal@example.com",
        "token_valid": True,
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        "storage": "encrypted",
        "keyring_backend": "file",
        "encrypted_credentials_exists": True,
        "encryption_valid": True,
    }
""",
            encoding="utf-8",
        )
        self.gws_bin = self.data / "codex-toolbox" / "gws" / "0.22.5" / "gws"
        self.gws_bin.parent.mkdir(parents=True)
        self.gws_bin.write_text(
            """#!/bin/sh
printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
  "$*" "$PWD" \
  "${GOOGLE_WORKSPACE_CLI_CONFIG_DIR:-}" \
  "${GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND:-}" \
  "${GOOGLE_APPLICATION_CREDENTIALS:-}" \
  "${GOOGLE_WORKSPACE_CLI_TOKEN:-}" \
  "${GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE:-}" \
  "${GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE:-}" \
  "${GOOGLE_WORKSPACE_CLI_CLIENT_ID:-}" \
  "${GOOGLE_WORKSPACE_CLI_CLIENT_SECRET:-}" \
  "${GOOGLE_WORKSPACE_PROJECT_ID:-}" \
  "${GOOGLE_WORKSPACE_CLI_LOG:-}" \
  "${GOOGLE_WORKSPACE_CLI_LOG_FILE:-}" \
  "${GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE:-}" \
  "${GOOGLE_WORKSPACE_CLI_SANITIZE_MODE:-}" >> "$FAKE_GWS_LOG"
if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then
  printf 'gws 0.22.5\nThis software is not an officially supported Google product.\n'
  exit 0
fi
if [ "$#" -eq 2 ] && [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  if [ "${FAKE_STATUS_CREATE_KEY:-0}" = "1" ]; then
    printf 'fake-key\n' > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key"
    chmod 600 "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key"
  fi
  printf '%s\n' "$FAKE_GWS_STATUS"
  exit "${FAKE_STATUS_EXIT:-0}"
fi
if [ "$#" -eq 7 ] && [ "$1" = "gmail" ] && [ "$2" = "users" ] && [ "$3" = "getProfile" ] && [ "$4" = "--params" ] && [ "$5" = '{"userId":"me"}' ] && [ "$6" = "--format" ] && [ "$7" = "json" ]; then
  /bin/mkdir -p "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/cache"
  printf '%s\n' '{"fake":"discovery-cache"}' > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/cache/gmail_v1.json"
  printf '%s\n' "$FAKE_GWS_GET_PROFILE"
  exit "${FAKE_GWS_GET_PROFILE_EXIT:-0}"
fi
exit 97
""",
            encoding="utf-8",
        )
        self.gws_bin.chmod(0o755)
        self.test_binary_sha256 = hashlib.sha256(self.gws_bin.read_bytes()).hexdigest()
        self.profile = self.make_profile("personal")
        self.status = {
            "user": "personal@example.com",
            "token_valid": True,
            "scopes": list(REQUIRED_SCOPES),
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "plain_credentials_exists": False,
            "encryption_valid": True,
        }

    def make_profile(self, alias: str, email: str = "personal@example.com") -> Path:
        profile = self.accounts / alias
        profile.mkdir()
        profile.chmod(0o700)
        files = {
            "profile.json": json.dumps({"schema_version": 1, "expected_email": email}),
            "client_secret.json": json.dumps(
                {
                    "installed": {
                        "client_id": "id",
                        "client_secret": "secret",
                        "project_id": "",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            "credentials.enc": "encrypted",
            ".encryption_key": "encryption-key",
        }
        for name, contents in files.items():
            path = profile / name
            path.write_text(contents, encoding="utf-8")
            path.chmod(0o600)
        return profile

    def configure_imported_profile(
        self, credential_bytes: Optional[bytes] = None
    ) -> tuple[Path, dict]:
        for name in ("credentials.enc", ".encryption_key", "credentials.json"):
            path = self.profile / name
            if path.exists() or path.is_symlink():
                path.unlink()
        if credential_bytes is None:
            credential_bytes = json.dumps(
                {
                    "type": "authorized_user",
                    "client_id": "id",
                    "client_secret": "secret",
                    "refresh_token": "refresh-token",
                },
                separators=(",", ":"),
            ).encode()
        credentials = self.profile / "credentials.json"
        credentials.write_bytes(credential_bytes)
        credentials.chmod(0o600)
        client = self.profile / "client_secret.json"
        client.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "id",
                        "client_secret": "secret",
                        "project_id": "",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            encoding="utf-8",
        )
        client.chmod(0o600)
        (self.profile / "profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "expected_email": "personal@example.com",
                    "credential_mode": "imported_authorized_user",
                    "scope_policy": "existing_grant",
                    "source_sha256": hashlib.sha256(credential_bytes).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        status = {
            "user": "PERSONAL@example.com",
            "token_valid": True,
            "scopes": [*REQUIRED_SCOPES, "https://www.googleapis.com/auth/gmail.labels"],
            "storage": "plaintext",
            "keyring_backend": "file",
            "encrypted_credentials_exists": False,
            "plain_credentials_exists": True,
            "has_refresh_token": True,
            "plain_credentials": str(credentials),
            "client_config": str(self.profile / "client_secret.json"),
        }
        return credentials, status

    def assert_preflight_rejects_before_gws(self, **kwargs) -> None:
        result = self.run_preflight(**kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.log.exists(), "invalid profile must fail before invoking gws")

    def run_preflight(
        self,
        *,
        alias: str = "personal",
        status: Optional[dict] = None,
        status_exit: int = 0,
        status_create_key: bool = False,
        live_profile: Optional[object] = None,
        live_profile_raw: Optional[str] = None,
        live_profile_exit: int = 0,
        secrets_dir: Optional[Path] = None,
        script: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        if self.log.exists():
            self.log.unlink()
        if self.shim_log.exists():
            self.shim_log.unlink()
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.root / "home"),
                "XDG_DATA_HOME": str(self.data),
                "CODEX_SECRETS_DIR": str(self.secrets if secrets_dir is None else secrets_dir),
                "FAKE_GWS_LOG": str(self.log),
                "FAKE_GWS_STATUS": json.dumps(self.status if status is None else status),
                "FAKE_STATUS_EXIT": str(status_exit),
                "FAKE_STATUS_CREATE_KEY": "1" if status_create_key else "0",
                "FAKE_GWS_GET_PROFILE": (
                    json.dumps(
                        {"emailAddress": "PERSONAL@example.com"}
                        if live_profile is None
                        else live_profile
                    )
                    if live_profile_raw is None
                    else live_profile_raw
                ),
                "FAKE_GWS_GET_PROFILE_EXIT": str(live_profile_exit),
                "GOOGLE_WORKSPACE_CLI_TOKEN": "ambient-token",
                "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/ambient/credentials.json",
                "GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE": "/ambient/credential.json",
                "GOOGLE_WORKSPACE_CLI_CLIENT_ID": "ambient-client",
                "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET": "ambient-secret",
                "GOOGLE_WORKSPACE_PROJECT_ID": "ambient-project",
                "GOOGLE_WORKSPACE_CLI_LOG": "ambient-log",
                "GOOGLE_WORKSPACE_CLI_LOG_FILE": "/ambient/gws.log",
                "GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE": "ambient-template",
                "GOOGLE_WORKSPACE_CLI_SANITIZE_MODE": "model-armor",
                "GOOGLE_APPLICATION_CREDENTIALS": "/ambient/school-adc.json",
                "PATH": os.pathsep.join((str(self.hostile_bin), env["PATH"])),
                "PYTHONPATH": str(self.hostile_pythonpath),
                "FORCE_GWS_VALIDATORS_HEALTHY": "1",
                "FAKE_SHIM_LOG": str(self.shim_log),
                "alias": alias,
            }
        )
        return subprocess.run(
            [
                "bash",
                "-c",
                (
                    self.copied_preflight_script(binary_sha256=self.test_binary_sha256)
                    if script is None
                    else script
                ),
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def copied_preflight_script(
        self,
        *,
        binary_sha256: str,
        replace: Optional[tuple[str, str]] = None,
    ) -> str:
        source_path = PLUGIN / "skills" / "gws-shared" / "SKILL.md"
        copied_path = self.root / f"gws-shared-copy-{len(list(self.root.glob('gws-shared-copy-*')))}.md"
        source = source_path.read_text(encoding="utf-8")
        self.assertEqual(
            source.count(GWS_BINARY_SHA256),
            1,
            "source skill must contain one canonical managed-binary digest",
        )
        source = source.replace(GWS_BINARY_SHA256, binary_sha256, 1)
        if replace is not None:
            old, new = replace
            self.assertIn(old, source, "requested temporary-copy mutation is absent")
            source = source.replace(old, new)
        copied_path.write_text(source, encoding="utf-8")
        return shared_preflight_script(copied_path.read_text(encoding="utf-8"))

    def run_profile_validator(
        self,
        *,
        body: Optional[str] = None,
        walk_error: bool = False,
    ) -> subprocess.CompletedProcess:
        validator = profile_validator_python() if body is None else body
        if walk_error:
            validator = f"""import os

def failing_walk(top, *args, **kwargs):
    callback = kwargs.get("onerror")
    if callback is not None:
        callback(PermissionError("simulated traversal failure"))
    return iter(())

os.walk = failing_walk
exec(compile({validator!r}, "<extracted-profile-validator>", "exec"))
"""
        env = os.environ.copy()
        env.update(
            {
                "SECRETS_ROOT": str(self.secrets.resolve()),
                "GWS_ROOT": str((self.secrets / "gws").resolve()),
                "ACCOUNTS_ROOT": str(self.accounts.resolve()),
                "PROFILE_DIR": str(self.profile.resolve()),
                "PROFILE_ALIAS": "personal",
            }
        )
        return subprocess.run(
            ["/usr/bin/python3", "-I", "-c", validator],
            cwd="/",
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_profile_runs_exact_isolated_status(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "PREFLIGHT_OK\n")
        calls = [line.split("|") for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [call[0] for call in calls],
            [
                "--version",
                "auth status",
                'gmail users getProfile --params {"userId":"me"} --format json',
            ],
        )
        status_call = calls[1]
        self.assertEqual(status_call[1], "/")
        self.assertEqual(status_call[2], str(self.profile.resolve()))
        self.assertEqual(status_call[3], "file")
        self.assertEqual(status_call[4], str(self.profile.resolve() / "missing-adc.json"))
        self.assertEqual(status_call[5:], [""] * 10)
        self.assertFalse(self.shim_log.exists())

    def test_preflight_requires_static_runtime_client_contract_before_gws(self):
        """Catches accepting a legacy, malformed, mismatched, or untrusted runtime client."""
        client = self.profile / "client_secret.json"
        registered = json.loads(self.registered_client.read_text(encoding="utf-8"))
        mutations = {
            "nonempty runtime project": lambda document: document["installed"].__setitem__(
                "project_id", "registered-project"
            ),
            "missing runtime project": lambda document: document["installed"].pop("project_id"),
            "nonstring runtime project": lambda document: document["installed"].__setitem__(
                "project_id", 7
            ),
            "mismatched client id": lambda document: document["installed"].__setitem__(
                "client_id", "other"
            ),
            "untrusted auth endpoint": lambda document: document["installed"].__setitem__(
                "auth_uri", "https://evil.example.invalid/auth"
            ),
            "empty client secret": lambda document: document["installed"].__setitem__(
                "client_secret", ""
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                runtime = json.loads(json.dumps(registered))
                runtime["installed"]["project_id"] = ""
                mutate(runtime)
                client.write_text(json.dumps(runtime), encoding="utf-8")
                client.chmod(0o600)
                self.assert_preflight_rejects_before_gws()

        client.write_text(
            json.dumps({"installed": {"project_id": ""}}), encoding="utf-8"
        )
        client.chmod(0o600)
        self.assert_preflight_rejects_before_gws()

    def test_preflight_rejects_alias_transaction_siblings_before_gws(self):
        """Catches direct gws use selecting a profile with an in-flight or failed transaction."""
        for suffix in (
            "lock",
            "add.candidate",
            "import.candidate",
            "migrate.candidate",
            "reauth.candidate",
            "backup.recovery",
        ):
            with self.subTest(suffix=suffix):
                transaction_entry = self.accounts / f".personal.{suffix}"
                transaction_entry.mkdir(mode=0o700)
                self.assert_preflight_rejects_before_gws()
                transaction_entry.rmdir()

        other_alias_lock = self.accounts / ".other.lock"
        other_alias_lock.mkdir(mode=0o700)
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "PREFLIGHT_OK\n")

    def test_preflight_requires_protected_registered_client_before_gws(self):
        """Catches trusting a missing, exposed, or symlinked registered OAuth client."""
        original = self.registered_client.read_bytes()
        self.registered_client.unlink()
        self.assert_preflight_rejects_before_gws()

        self.registered_client.write_bytes(original)
        self.registered_client.chmod(0o644)
        self.assert_preflight_rejects_before_gws()

        self.registered_client.chmod(0o600)
        replacement = self.root / "registered-client.json"
        replacement.write_bytes(original)
        replacement.chmod(0o600)
        self.registered_client.unlink()
        self.registered_client.symlink_to(replacement)
        self.assert_preflight_rejects_before_gws()

    def test_preflight_validates_registered_client_semantics_before_comparison(self):
        """Catches a checker that compares client files without validating the registered client."""
        original = json.loads(self.registered_client.read_text(encoding="utf-8"))
        mutations = {
            "empty registered project": lambda document: document["installed"].__setitem__(
                "project_id", ""
            ),
            "untrusted token endpoint": lambda document: document["installed"].__setitem__(
                "token_uri", "https://evil.example.invalid/token"
            ),
            "empty registered client secret": lambda document: document["installed"].__setitem__(
                "client_secret", ""
            ),
        }
        for mode in ("encrypted", "imported"):
            for name, mutate in mutations.items():
                with self.subTest(mode=mode, name=name):
                    if mode == "imported":
                        self.configure_imported_profile()
                    registered = json.loads(json.dumps(original))
                    mutate(registered)
                    runtime = json.loads(json.dumps(registered))
                    runtime["installed"]["project_id"] = ""
                    self.registered_client.write_text(json.dumps(registered), encoding="utf-8")
                    self.registered_client.chmod(0o600)
                    client = self.profile / "client_secret.json"
                    client.write_text(json.dumps(runtime), encoding="utf-8")
                    client.chmod(0o600)
                    self.assert_preflight_rejects_before_gws()

    def test_preflight_rejects_invalid_or_duplicate_registered_client_json_before_gws(self):
        """Catches accepting malformed or duplicate-key registered client documents."""
        for contents in (
            "{",
            '{"installed":{"client_id":"id","client_id":"other"}}',
        ):
            with self.subTest(contents=contents):
                self.registered_client.write_text(contents, encoding="utf-8")
                self.registered_client.chmod(0o600)
                self.assert_preflight_rejects_before_gws()

    def test_preflight_rejects_a_base_secrets_decoy_without_gws_registered_client(self):
        """Catches resolving the registered client outside the isolated gws root."""
        decoy = self.secrets / "client_secret.json"
        self.registered_client.replace(decoy)

        self.assert_preflight_rejects_before_gws()

    def test_preflight_uses_live_mailbox_identity_after_healthy_status(self):
        """Catches treating auth status as mailbox proof or altering the pinned Gmail argv."""
        result = self.run_preflight()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [line.split("|") for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [call[0] for call in calls],
            [
                "--version",
                "auth status",
                'gmail users getProfile --params {"userId":"me"} --format json',
            ],
        )
        live_call = calls[2]
        self.assertEqual(live_call[1], "/")
        self.assertEqual(live_call[2], str(self.profile.resolve()))
        self.assertEqual(live_call[3], "file")
        self.assertEqual(live_call[4], str(self.profile.resolve() / "missing-adc.json"))
        self.assertEqual(live_call[5:], [""] * 10)
        self.assertNotIn("personal@example.com", result.stdout + result.stderr)

    def test_live_mailbox_readback_fails_closed_for_bad_or_wrong_identity(self):
        """Catches accepting a failed, malformed, missing, or mismatched Gmail identity response."""
        for name, payload, raw_payload, exit_code in (
            ("failed", {"emailAddress": "personal@example.com"}, None, 43),
            ("malformed JSON", None, "{", 0),
            ("valid JSON non-object", "not an identity object", None, 0),
            ("missing email", {}, None, 0),
            ("nonstring email", {"emailAddress": 7}, None, 0),
            ("wrong email", {"emailAddress": "other@example.com"}, None, 0),
        ):
            with self.subTest(name=name):
                result = self.run_preflight(
                    live_profile=payload,
                    live_profile_raw=raw_payload,
                    live_profile_exit=exit_code,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [
                    line.split("|")[0]
                    for line in self.log.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(calls, ["--version", "auth status", 'gmail users getProfile --params {"userId":"me"} --format json'])

    def test_imported_live_mailbox_readback_uses_the_same_isolated_environment(self):
        """Catches an imported profile that validates status but skips isolated live identity proof."""
        credentials, status = self.configure_imported_profile()

        result = self.run_preflight(status=status)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [line.split("|") for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [call[0] for call in calls],
            [
                "--version",
                "auth status",
                'gmail users getProfile --params {"userId":"me"} --format json',
            ],
        )
        self.assertEqual(calls[2][1], "/")
        self.assertEqual(calls[2][2], str(self.profile.resolve()))
        self.assertEqual(calls[2][3], "file")
        self.assertEqual(calls[2][4], str(self.profile.resolve() / "missing-adc.json"))
        self.assertEqual(calls[2][5], "")
        self.assertEqual(calls[2][6], str(credentials))
        self.assertEqual(calls[2][7:], [""] * 8)

    def test_preflight_private_umask_protects_later_gws_cache_and_next_preflight(self):
        preflight = self.copied_preflight_script(
            binary_sha256=self.test_binary_sha256
        )
        completion = "printf 'PREFLIGHT_OK\\n'"
        self.assertEqual(preflight.count(completion), 1)
        direct_operation = (
            'GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile" '
            '"$gws_bin" gmail users getProfile '
            "--params '{\"userId\":\"me\"}' --format json >/dev/null || exit 1"
        )
        script = "umask 022\n" + preflight.replace(
            completion,
            direct_operation + "\n" + completion,
            1,
        )

        first = self.run_preflight(script=script)

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        cache = self.profile / "cache"
        discovery = cache / "gmail_v1.json"
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
        self.assertEqual(discovery.stat().st_mode & 0o777, 0o600)

        second = self.run_preflight()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_valid_imported_profile_runs_exact_isolated_plaintext_status(self):
        credentials, status = self.configure_imported_profile()

        result = self.run_preflight(status=status)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "PREFLIGHT_OK\n")
        calls = [line.split("|") for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [call[0] for call in calls],
            [
                "--version",
                "auth status",
                'gmail users getProfile --params {"userId":"me"} --format json',
            ],
        )
        status_call = calls[1]
        self.assertEqual(status_call[1], "/")
        self.assertEqual(status_call[2], str(self.profile))
        self.assertEqual(status_call[3], "file")
        self.assertEqual(status_call[4], str(self.profile / "missing-adc.json"))
        self.assertEqual(status_call[5], "")
        self.assertEqual(status_call[6], str(credentials))
        self.assertEqual(status_call[7:], [""] * 8)
        self.assertFalse(self.shim_log.exists())

    def test_imported_profile_requires_exact_complete_mode_metadata(self):
        self.configure_imported_profile()
        baseline = json.loads((self.profile / "profile.json").read_text(encoding="utf-8"))
        cases = {
            "implicit legacy marker": {
                "schema_version": 1,
                "expected_email": "personal@example.com",
            },
            "partial marker": {
                "schema_version": 1,
                "expected_email": "personal@example.com",
                "credential_mode": "imported_authorized_user",
            },
            "unknown mode": {**baseline, "credential_mode": "unknown_mode"},
            "unknown policy": {**baseline, "scope_policy": "unknown_policy"},
            "uppercase digest": {**baseline, "source_sha256": baseline["source_sha256"].upper()},
            "extra metadata key": {**baseline, "unexpected": "value"},
            "boolean schema": {**baseline, "schema_version": True},
        }
        for name, metadata in cases.items():
            with self.subTest(name=name):
                self.configure_imported_profile()
                (self.profile / "profile.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                self.assert_preflight_rejects_before_gws()

    def test_imported_profile_rejects_malformed_or_mismatched_credentials(self):
        valid = {
            "type": "authorized_user",
            "client_id": "id",
            "client_secret": "secret",
            "refresh_token": "refresh-token",
        }
        credential_cases = {
            "invalid JSON": b"{",
            "duplicate key": (
                b'{"type":"authorized_user","client_id":"id","client_secret":"secret",'
                b'"refresh_token":"first","refresh_token":"second"}'
            ),
            "missing key": json.dumps(
                {key: value for key, value in valid.items() if key != "refresh_token"}
            ).encode(),
            "extra key": json.dumps({**valid, "token_uri": "https://example.invalid"}).encode(),
            "wrong type": json.dumps({**valid, "type": "service_account"}).encode(),
            "empty value": json.dumps({**valid, "refresh_token": ""}).encode(),
            "non-string value": json.dumps({**valid, "client_secret": 7}).encode(),
        }
        for name, credential_bytes in credential_cases.items():
            with self.subTest(name=name):
                self.configure_imported_profile(credential_bytes)
                self.assert_preflight_rejects_before_gws()

        self.configure_imported_profile()
        (self.profile / "client_secret.json").write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "different-id",
                        "client_secret": "secret",
                        "project_id": "project",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assert_preflight_rejects_before_gws()

        self.configure_imported_profile()
        metadata = json.loads((self.profile / "profile.json").read_text(encoding="utf-8"))
        metadata["source_sha256"] = "0" * 64
        (self.profile / "profile.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.assert_preflight_rejects_before_gws()

    def test_imported_profile_rejects_mixed_or_unsafe_filesystem_state(self):
        self.configure_imported_profile()
        encrypted = self.profile / "credentials.enc"
        encrypted.write_text("encrypted", encoding="utf-8")
        encrypted.chmod(0o600)
        self.assert_preflight_rejects_before_gws()

        credentials, _ = self.configure_imported_profile()
        credentials.chmod(0o644)
        self.assert_preflight_rejects_before_gws()

        credentials, _ = self.configure_imported_profile()
        hardlink = self.profile / "credentials-hardlink.json"
        os.link(credentials, hardlink)
        self.assert_preflight_rejects_before_gws()
        hardlink.unlink()

        credentials, _ = self.configure_imported_profile()
        credentials.unlink()
        external = self.root / "imported-credentials.json"
        external.write_text("{}", encoding="utf-8")
        external.chmod(0o600)
        credentials.symlink_to(external)
        self.assert_preflight_rejects_before_gws()

        self.configure_imported_profile()
        client = self.profile / "client_secret.json"
        client.chmod(0o644)
        self.assert_preflight_rejects_before_gws()

    def test_imported_status_rejects_wrong_state_paths_or_scopes(self):
        _, healthy_status = self.configure_imported_profile()
        cases = (
            {"user": "other@example.com"},
            {"token_valid": False},
            {"storage": "encrypted"},
            {"keyring_backend": "keychain"},
            {"plain_credentials_exists": False},
            {"encrypted_credentials_exists": True},
            {"has_refresh_token": False},
            {"plain_credentials": str(self.profile / "other-credentials.json")},
            {"client_config": str(self.profile / "other-client.json")},
            {"scopes": list(REQUIRED_SCOPES[1:])},
            {"scopes": [*REQUIRED_SCOPES, REQUIRED_SCOPES[0]]},
            {"scopes": [*REQUIRED_SCOPES, "https://mail.google.com/"]},
            {"scopes": [*REQUIRED_SCOPES, 7]},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                status = dict(healthy_status)
                status.update(changes)
                result = self.run_preflight(status=status)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

        for missing in (
            "user",
            "token_valid",
            "scopes",
            "storage",
            "keyring_backend",
            "plain_credentials_exists",
            "encrypted_credentials_exists",
            "has_refresh_token",
            "plain_credentials",
            "client_config",
        ):
            with self.subTest(missing=missing):
                status = dict(healthy_status)
                status.pop(missing)
                result = self.run_preflight(status=status)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_profile_field_transfer_preserves_trailing_newline_without_shell_evaluation(self):
        _, status = self.configure_imported_profile()
        metadata = json.loads((self.profile / "profile.json").read_text(encoding="utf-8"))
        metadata["expected_email"] = "neutral$(exit 44)@example.com\n"
        (self.profile / "profile.json").write_text(json.dumps(metadata), encoding="utf-8")
        status["user"] = "NEUTRAL$(EXIT 44)@example.com\n"

        result = self.run_preflight(
            status=status, live_profile={"emailAddress": "NEUTRAL$(EXIT 44)@example.com\n"}
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "PREFLIGHT_OK\n")

    def test_profile_validator_rejects_wrong_owner(self):
        body = profile_validator_python()

        def with_wrong_owner(validator: str) -> str:
            return f"""import os
from types import SimpleNamespace

original_lstat = os.lstat

def wrong_owner_lstat(path):
    metadata = original_lstat(path)
    return SimpleNamespace(
        st_mode=metadata.st_mode,
        st_uid=os.getuid() + 1,
        st_nlink=metadata.st_nlink,
    )

os.lstat = wrong_owner_lstat
exec(compile({validator!r}, "<wrong-owner-profile-validator>", "exec"))
"""

        rejected = self.run_profile_validator(body=with_wrong_owner(body))
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)

        without_owner_check = body.replace("metadata.st_uid != os.getuid() or ", "", 1)
        self.assertNotEqual(without_owner_check, body, "ownership mutation did not apply")
        false_success = self.run_profile_validator(body=with_wrong_owner(without_owner_check))
        self.assertEqual(false_success.returncode, 0, false_success.stdout + false_success.stderr)

    def test_preflight_rejects_non_private_or_noncanonical_secrets_root_before_status(self):
        self.secrets.chmod(0o755)
        exposed = self.run_preflight()
        self.assertNotEqual(exposed.returncode, 0, exposed.stdout + exposed.stderr)
        self.assertFalse(self.log.exists(), "unsafe secrets root must fail before invoking gws")

        self.secrets.chmod(0o700)
        secrets_link = self.root / "secrets-link"
        secrets_link.symlink_to(self.secrets, target_is_directory=True)
        linked = self.run_preflight(secrets_dir=secrets_link)
        self.assertNotEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        self.assertFalse(self.log.exists(), "symlinked secrets root must fail before invoking gws")

    def test_missing_credentials_or_key_never_calls_status_or_creates_key(self):
        credentials = self.profile / "credentials.enc"
        credentials.unlink()
        missing_credentials = self.run_preflight(status_create_key=True)
        self.assertNotEqual(
            missing_credentials.returncode,
            0,
            missing_credentials.stdout + missing_credentials.stderr,
        )
        calls = (
            [line.split("|")[0] for line in self.log.read_text(encoding="utf-8").splitlines()]
            if self.log.exists()
            else []
        )
        self.assertNotIn("auth status", calls)

        credentials.write_text("encrypted", encoding="utf-8")
        credentials.chmod(0o600)
        encryption_key = self.profile / ".encryption_key"
        encryption_key.unlink()
        missing_key = self.run_preflight(status_create_key=True)
        self.assertNotEqual(missing_key.returncode, 0, missing_key.stdout + missing_key.stderr)
        calls = (
            [line.split("|")[0] for line in self.log.read_text(encoding="utf-8").splitlines()]
            if self.log.exists()
            else []
        )
        self.assertNotIn("auth status", calls)
        self.assertFalse(encryption_key.exists(), "preflight must not let auth status create a key")

    def test_profile_rejects_plain_credentials_before_status(self):
        plaintext = self.profile / "credentials.json"
        plaintext.write_text('{"type":"authorized_user"}', encoding="utf-8")
        plaintext.chmod(0o600)
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (
            [line.split("|")[0] for line in self.log.read_text(encoding="utf-8").splitlines()]
            if self.log.exists()
            else []
        )
        self.assertNotIn("auth status", calls)

    def test_hostile_path_and_pythonpath_cannot_force_profile_or_status_healthy(self):
        credentials = self.profile / "credentials.enc"
        credentials.chmod(0o644)
        exposed = self.run_preflight()
        self.assertNotEqual(exposed.returncode, 0, exposed.stdout + exposed.stderr)
        self.assertFalse(self.log.exists(), "profile validation must fail before invoking gws")
        self.assertFalse(self.shim_log.exists(), "hostile interpreter hooks must not run")

        credentials.chmod(0o600)
        unhealthy = dict(self.status)
        unhealthy["user"] = "school@example.com"
        wrong_identity = self.run_preflight(status=unhealthy)
        self.assertNotEqual(
            wrong_identity.returncode,
            0,
            wrong_identity.stdout + wrong_identity.stderr,
        )
        calls = [line.split("|")[0] for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, ["--version", "auth status"])
        self.assertFalse(self.shim_log.exists(), "hostile interpreter hooks must not run")

    def test_alias_validation_rejects_entire_newline_or_control_value(self):
        for alias in ("personal\nother", "personal\rbad", "personal\x01bad"):
            with self.subTest(alias=repr(alias)):
                self.make_profile(alias)
                result = self.run_preflight(alias=alias)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.log.exists(), "invalid aliases must fail before invoking gws")

    def test_status_rejects_wrong_identity_scope_token_storage_or_backend(self):
        cases = (
            {"user": "school@example.com"},
            {"scopes": []},
            {"scopes": list(REQUIRED_SCOPES[1:])},
            {"scopes": [*REQUIRED_SCOPES, "https://mail.google.com/"]},
            {"scopes": [*REQUIRED_SCOPES, REQUIRED_SCOPES[0]]},
            {"token_valid": False},
            {"storage": "plaintext"},
            {"keyring_backend": "keychain"},
            {"encrypted_credentials_exists": False},
            {"plain_credentials_exists": True},
            {"encryption_valid": False},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                status = dict(self.status)
                status.update(changes)
                result = self.run_preflight(status=status)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

        missing_plaintext_state = dict(self.status)
        missing_plaintext_state.pop("plain_credentials_exists")
        result = self.run_preflight(status=missing_plaintext_state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_profile_rejects_exposed_file_and_descendant_symlink(self):
        credentials = self.profile / "credentials.enc"
        credentials.chmod(0o644)
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.log.exists())

        credentials.chmod(0o600)
        secret = self.root / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        (self.profile / "leak").symlink_to(secret)
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.log.exists())

    def test_extracted_profile_validator_propagates_walk_onerror(self):
        result = self.run_profile_validator(walk_error=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

        body = profile_validator_python()
        without_onerror = body.replace(", onerror=reject", "", 1)
        self.assertNotEqual(without_onerror, body, "onerror mutation did not apply")
        false_success = self.run_profile_validator(body=without_onerror, walk_error=True)
        self.assertEqual(false_success.returncode, 0, false_success.stdout + false_success.stderr)
        self.assertEqual(
            false_success.stdout,
            "706572736f6e616c406578616d706c652e636f6d\n"
            "encrypted_oauth\n"
            "exact_required\n"
            "profile validation passed\n",
        )

    def test_failed_or_suffixed_status_cannot_pass(self):
        failed = self.run_preflight(status_exit=41)
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines()[-1].split("|")[0],
            "auth status",
        )

        mutated = self.copied_preflight_script(
            binary_sha256=self.test_binary_sha256,
            replace=(
                '"$gws_bin" auth status',
                '"$gws_bin" auth status --bogus',
            ),
        )
        suffixed = self.run_preflight(script=mutated)
        self.assertNotEqual(suffixed.returncode, 0, suffixed.stdout + suffixed.stderr)
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines()[-1].split("|")[0],
            "auth status --bogus",
        )

    def test_binary_digest_and_non_symlink_checks_fail_closed(self):
        pinned_script = self.copied_preflight_script(binary_sha256=self.test_binary_sha256)
        self.gws_bin.write_text(
            self.gws_bin.read_text(encoding="utf-8") + "\n# unexpected replacement\n",
            encoding="utf-8",
        )
        self.gws_bin.chmod(0o755)
        replaced = self.run_preflight(script=pinned_script)
        self.assertNotEqual(replaced.returncode, 0, replaced.stdout + replaced.stderr)
        self.assertFalse(self.log.exists(), "untrusted binary must fail before invocation")

        self.gws_bin.unlink()
        target = self.gws_bin.parent / "gws-target"
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
        self.gws_bin.symlink_to(target)
        symlink_script = self.copied_preflight_script(
            binary_sha256=hashlib.sha256(target.read_bytes()).hexdigest()
        )
        symlinked = self.run_preflight(script=symlink_script)
        self.assertNotEqual(symlinked.returncode, 0, symlinked.stdout + symlinked.stderr)
        self.assertFalse(self.log.exists(), "symlinked binary must fail before invocation")


if __name__ == "__main__":
    unittest.main()
