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


def shared_preflight_script(source: Optional[str] = None) -> str:
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
        self.assertEqual(shared_source.count("/usr/bin/python3 -I - <<'PY'"), 2)
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
            for attachment_requirement in (
                "before draft or send",
                "attachment safety contract",
                "user-supplied path",
                "absolute",
                "lstat",
                "regular final object",
                "final symlink",
                "canonical target path",
                "basename",
                "immediately revalidate",
                "same path and canonical target",
                "fail closed on change",
            ):
                self.assertIn(attachment_requirement, text, f"{name}: {attachment_requirement}")

        forward = normalized(PLUGIN / "skills" / "gws-gmail-forward" / "SKILL.md").lower()
        self.assertIn("server-side original attachments", forward)
        self.assertIn("separate", forward)

    def test_shared_attachment_contract_rejects_symlinks_and_revalidates_identity(self):
        shared = normalized(PLUGIN / "skills" / "gws-shared" / "SKILL.md").lower()
        for required in (
            "before draft or send",
            "user-supplied attachment",
            "absolute path",
            "lstat",
            "regular final object",
            "final symlink",
            "canonical target path",
            "basename",
            "device/inode",
            "identity/recipient preview",
            "immediately before invoking",
            "same user-supplied path",
            "same canonical target",
            "fail closed on any change",
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


class SharedPreflightExecutionTests(unittest.TestCase):
    SCOPE = "https://www.googleapis.com/auth/gmail.modify"

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.secrets = self.root / "secrets"
        self.accounts = self.secrets / "gws" / "accounts"
        self.accounts.mkdir(parents=True)
        self.accounts.chmod(0o700)
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
printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
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
  "${GOOGLE_WORKSPACE_CLI_LOG_FILE:-}" >> "$FAKE_GWS_LOG"
if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then
  printf 'gws 0.22.5\nThis software is not an officially supported Google product.\n'
  exit 0
fi
if [ "$#" -eq 2 ] && [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  printf '%s\n' "$FAKE_GWS_STATUS"
  exit "${FAKE_STATUS_EXIT:-0}"
fi
exit 97
""",
            encoding="utf-8",
        )
        self.gws_bin.chmod(0o755)
        self.profile = self.make_profile("personal")
        self.status = {
            "user": "personal@example.com",
            "token_valid": True,
            "scopes": [self.SCOPE],
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "encryption_valid": True,
        }

    def make_profile(self, alias: str, email: str = "personal@example.com") -> Path:
        profile = self.accounts / alias
        profile.mkdir()
        profile.chmod(0o700)
        files = {
            "profile.json": json.dumps({"schema_version": 1, "expected_email": email}),
            "client_secret.json": json.dumps(
                {"installed": {"client_id": "id", "client_secret": "secret", "project_id": "project"}}
            ),
            "credentials.enc": "encrypted",
        }
        for name, contents in files.items():
            path = profile / name
            path.write_text(contents, encoding="utf-8")
            path.chmod(0o600)
        return profile

    def run_preflight(
        self,
        *,
        alias: str = "personal",
        status: Optional[dict] = None,
        status_exit: int = 0,
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
                "CODEX_SECRETS_DIR": str(self.secrets),
                "FAKE_GWS_LOG": str(self.log),
                "FAKE_GWS_STATUS": json.dumps(self.status if status is None else status),
                "FAKE_STATUS_EXIT": str(status_exit),
                "GOOGLE_WORKSPACE_CLI_TOKEN": "ambient-token",
                "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/ambient/credentials.json",
                "GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE": "/ambient/credential.json",
                "GOOGLE_WORKSPACE_CLI_CLIENT_ID": "ambient-client",
                "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET": "ambient-secret",
                "GOOGLE_WORKSPACE_PROJECT_ID": "ambient-project",
                "GOOGLE_WORKSPACE_CLI_LOG": "ambient-log",
                "GOOGLE_WORKSPACE_CLI_LOG_FILE": "/ambient/gws.log",
                "GOOGLE_APPLICATION_CREDENTIALS": "/ambient/school-adc.json",
                "PATH": os.pathsep.join((str(self.hostile_bin), env["PATH"])),
                "PYTHONPATH": str(self.hostile_pythonpath),
                "FORCE_GWS_VALIDATORS_HEALTHY": "1",
                "FAKE_SHIM_LOG": str(self.shim_log),
                "alias": alias,
            }
        )
        return subprocess.run(
            ["bash", "-c", shared_preflight_script() if script is None else script],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

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
        self.assertEqual([call[0] for call in calls], ["--version", "auth status"])
        status_call = calls[1]
        self.assertEqual(status_call[1], "/")
        self.assertEqual(status_call[2], str(self.profile.resolve()))
        self.assertEqual(status_call[3], "file")
        self.assertEqual(status_call[4], str(self.profile.resolve() / "missing-adc.json"))
        self.assertEqual(status_call[5:], [""] * 8)
        self.assertFalse(self.shim_log.exists())

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
            {"scopes": [self.SCOPE, "https://mail.google.com/"]},
            {"token_valid": False},
            {"storage": "plaintext"},
            {"keyring_backend": "keychain"},
            {"encrypted_credentials_exists": False},
            {"encryption_valid": False},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                status = dict(self.status)
                status.update(changes)
                result = self.run_preflight(status=status)
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
        self.assertEqual(false_success.stdout, "personal@example.com\n")

    def test_failed_or_suffixed_status_cannot_pass(self):
        failed = self.run_preflight(status_exit=41)
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines()[-1].split("|")[0],
            "auth status",
        )

        mutated = shared_preflight_script().replace(
            '"$gws_bin" auth status',
            '"$gws_bin" auth status --bogus',
            1,
        )
        suffixed = self.run_preflight(script=mutated)
        self.assertNotEqual(suffixed.returncode, 0, suffixed.stdout + suffixed.stderr)
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines()[-1].split("|")[0],
            "auth status --bogus",
        )


if __name__ == "__main__":
    unittest.main()
