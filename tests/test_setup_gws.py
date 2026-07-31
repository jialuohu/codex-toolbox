#!/usr/bin/env python3
"""Behavioral tests for the opt-in isolated gws bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-gws.sh"
VERSION = "0.22.5"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
IDENTITY_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)


class SetupGwsTest(unittest.TestCase):
    """Run the real shell interface with only network and CLI edges faked."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = Path(self.tempdir.name)
        self.bin_dir = self.home / "fake-bin"
        self.bin_dir.mkdir()
        self.data_home = self.home / "data"
        self.secrets_home = self.home / "secrets"
        self.local_bin = self.home / "local-bin"
        self.download = self.home / "download.tar.gz"
        self.download_log = self.home / "download.log"
        self.gws_log = self.home / "gws.log"
        self.python_hook_dir = self.home / "python-hooks"
        self.python_hook_dir.mkdir()
        self.script = self.home / "setup-gws.sh"
        self.script.write_text(SCRIPT.read_text())
        self.script.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{self.bin_dir}:/usr/bin:/bin",
            "XDG_DATA_HOME": str(self.data_home),
            "CODEX_SECRETS_DIR": str(self.secrets_home),
            "CODEX_LOCAL_BIN_DIR": str(self.local_bin),
            "FAKE_GWS_LOG": str(self.gws_log),
            "FAKE_DOWNLOAD": str(self.download),
            "FAKE_DOWNLOAD_LOG": str(self.download_log),
        })
        inherited_pythonpath = self.env.get("PYTHONPATH")
        self.env["PYTHONPATH"] = str(self.python_hook_dir) + (os.pathsep + inherited_pythonpath if inherited_pythonpath else "")
        (self.python_hook_dir / "sitecustomize.py").write_text("""import json
import os

if os.environ.get("FAKE_PYTHON_VALIDATION_BYPASS") == "1":
    if os.environ.get("PROFILE_DIR"):
        os.walk = lambda *args, **kwargs: iter(())
    if os.environ.get("STATUS_JSON"):
        json.loads = lambda *args, **kwargs: {
            "user": os.environ.get("EXPECTED_EMAIL", "wrong@example.test"),
            "token_valid": True,
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "encryption_valid": True,
        }
""")
        self.write_executable("uname", """#!/bin/sh
if [ "$1" = "-s" ]; then printf '%s\\n' "${FAKE_UNAME_S:-Darwin}"; exit 0; fi
if [ "$1" = "-m" ]; then printf '%s\\n' "${FAKE_UNAME_M:-arm64}"; exit 0; fi
exit 2
""")
        self.write_executable("curl", """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_DOWNLOAD_LOG"
out=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift 2; continue; fi
  shift
done
cp "$FAKE_DOWNLOAD" "$out"
""")

    def write_executable(self, name: str, body: str) -> Path:
        path = self.bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    @property
    def runtime_gws(self) -> Path:
        return self.data_home / "codex-toolbox" / "gws" / VERSION / "gws"

    @property
    def accounts_root(self) -> Path:
        return self.secrets_home / "gws" / "accounts"

    @property
    def client_path(self) -> Path:
        return self.secrets_home / "gws" / "client_secret.json"

    def run(self, result: object | None = None, *args: str) -> object:
        """Keep unittest's runner contract while exposing the shell interface."""
        if not isinstance(result, str):
            return super().run(result)
        return subprocess.run(["bash", str(self.script), result, *args], cwd=ROOT, env=self.env, text=True, capture_output=True, check=False)

    def pin_test_script(self, *, archive_sha: str | None = None, binary_sha: str | None = None) -> None:
        lines = self.script.read_text().splitlines()
        replacements = {"SHA256": archive_sha, "BINARY_SHA256": binary_sha}
        seen: set[str] = set()
        rewritten: list[str] = []
        for line in lines:
            name = line.split("=", 1)[0]
            if name in replacements and replacements[name] is not None:
                rewritten.append(f'{name}="{replacements[name]}"')
                seen.add(name)
            else:
                rewritten.append(line)
            if name == "SHA256" and binary_sha is not None and "BINARY_SHA256" not in seen and not any(item.startswith("BINARY_SHA256=") for item in lines):
                rewritten.append(f'BINARY_SHA256="{binary_sha}"')
                seen.add("BINARY_SHA256")
        self.script.write_text("\n".join(rewritten) + "\n")
        self.script.chmod(0o755)

    def install_fake_runtime(self) -> None:
        self.runtime_gws.parent.mkdir(parents=True)
        self.runtime_gws.write_text("""#!/bin/sh
state() { if [ "$1" = x ]; then printf 'set:%s' "$2"; else printf unset; fi; }
printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\\n' \
  "$*" "$PWD" \
  "$(state "${GOOGLE_WORKSPACE_CLI_TOKEN+x}" "${GOOGLE_WORKSPACE_CLI_TOKEN-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE+x}" "${GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE+x}" "${GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_CLIENT_ID+x}" "${GOOGLE_WORKSPACE_CLI_CLIENT_ID-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_CLIENT_SECRET+x}" "${GOOGLE_WORKSPACE_CLI_CLIENT_SECRET-}")" \
  "$(state "${GOOGLE_WORKSPACE_PROJECT_ID+x}" "${GOOGLE_WORKSPACE_PROJECT_ID-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_LOG+x}" "${GOOGLE_WORKSPACE_CLI_LOG-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_LOG_FILE+x}" "${GOOGLE_WORKSPACE_CLI_LOG_FILE-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE+x}" "${GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_SANITIZE_MODE+x}" "${GOOGLE_WORKSPACE_CLI_SANITIZE_MODE-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_CONFIG_DIR+x}" "${GOOGLE_WORKSPACE_CLI_CONFIG_DIR-}")" \
  "$(state "${GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND+x}" "${GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND-}")" \
  "$(state "${GOOGLE_APPLICATION_CREDENTIALS+x}" "${GOOGLE_APPLICATION_CREDENTIALS-}")" >> "$FAKE_GWS_LOG"
if [ "$1" = "--version" ]; then printf '%b' "${FAKE_GWS_VERSION_OUTPUT:-gws 0.22.5\\nThis software is not an officially supported Google product.\\n}"; exit 0; fi
if [ "$1" = "auth" ] && [ "$2" = "login" ]; then
  mkdir -p "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/credentials.enc"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/token-cache.json"
  if [ -n "${FAKE_GWS_POST_LOGIN_STATUS:-}" ]; then printf '%s' "$FAKE_GWS_POST_LOGIN_STATUS" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json"; fi
  if [ -n "${FAKE_GWS_SWAP_BLOCK_ROOT:-}" ]; then chmod 500 "$FAKE_GWS_SWAP_BLOCK_ROOT"; fi
  [ "${FAKE_GWS_LOGIN_MODE:-ok}" = "fail" ] && exit 1
  exit 0
fi
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  if [ -f "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json" ]; then cat "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json"; else printf '%s\\n' "$FAKE_GWS_STATUS"; fi
  exit 0
fi
exit 3
""")
        self.runtime_gws.chmod(0o755)
        self.pin_test_script(binary_sha=hashlib.sha256(self.runtime_gws.read_bytes()).hexdigest())
        self.local_bin.mkdir(exist_ok=True)
        os.chmod(self.local_bin, 0o755)
        (self.local_bin / "gws").symlink_to(self.runtime_gws)

    def write_client(self, payload: object | None = None) -> Path:
        source = self.home / "desktop-client.json"
        source.write_text(json.dumps(payload if payload is not None else {"installed": {"client_id": "desktop-id.apps.googleusercontent.com", "client_secret": "desktop-secret", "project_id": "project-id"}}))
        return source

    def register_client(self) -> None:
        result = self.run("--register-client", str(self.write_client()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def status(self, address: str, **changes: object) -> None:
        value: dict[str, object] = {"user": address, "token_valid": True, "scopes": [SCOPE, *IDENTITY_SCOPES], "storage": "encrypted", "keyring_backend": "file", "encrypted_credentials_exists": True, "encryption_valid": True}
        value.update(changes)
        self.env["FAKE_GWS_STATUS"] = json.dumps(value)

    def assert_mode(self, path: Path, mode: int) -> None:
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, path)

    def test_check_is_non_mutating_when_runtime_and_profiles_are_absent(self) -> None:
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        result = self.run("--check")
        after = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Platform: ready (macOS arm64)", result.stdout)
        self.assertIn("gws runtime: missing (expected 0.22.5)", result.stdout)
        self.assertIn("OAuth client: missing", result.stdout)
        self.assertIn("Profiles: none", result.stdout)
        self.assertEqual(before, after)

    def test_install_rejects_unsupported_platform_and_checksum_mismatch(self) -> None:
        self.env["FAKE_UNAME_S"] = "Linux"
        result = self.run("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unsupported (requires macOS arm64)", result.stderr)
        self.assertFalse(self.data_home.exists())
        self.env.pop("FAKE_UNAME_S")
        stage = self.home / "stage"
        stage.mkdir()
        (stage / "gws").write_text("not the pinned release")
        with tarfile.open(self.download, "w:gz") as archive:
            archive.add(stage / "gws", arcname="gws")
        result = self.run("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(self.runtime_gws.exists())
        download_fields = self.download_log.read_text().split()
        download_output = Path(download_fields[download_fields.index("-o") + 1])
        self.assertFalse(download_output.parent.exists(), "failed installation must clean temporary release artifacts")

    def test_install_refuses_unmanaged_binary_and_is_idempotent_when_healthy(self) -> None:
        self.local_bin.mkdir()
        outside = self.home / "outside-gws"
        outside.write_text("outside binary")
        (self.local_bin / "gws").symlink_to(outside)
        external_link = self.run("--install")
        self.assertEqual(external_link.returncode, 1, external_link.stdout + external_link.stderr)
        self.assertIn("unmanaged local gws symlink", external_link.stderr)
        (self.local_bin / "gws").unlink()
        unmanaged = self.local_bin / "gws"
        unmanaged.write_text("user binary")
        result = self.run("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("refusing to overwrite unmanaged", result.stderr)
        self.assertEqual(unmanaged.read_text(), "user binary")
        unmanaged.unlink()
        self.install_fake_runtime()
        self.assert_mode(self.local_bin, 0o755)
        result = self.run("--install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already installed", result.stdout)
        self.assertEqual((self.local_bin / "gws").resolve(), self.runtime_gws.resolve())
        self.assert_mode(self.local_bin, 0o755)

    def test_runtime_rejects_same_version_tampering_and_binary_symlink(self) -> None:
        self.install_fake_runtime()
        original = self.runtime_gws.read_bytes()
        ready = self.run("--check")
        self.assertIn("gws runtime: ready (0.22.5)", ready.stdout)
        self.runtime_gws.write_bytes(original + b"\n# tampered\n")
        tampered = self.run("--check")
        self.assertIn("gws runtime: missing (expected 0.22.5)", tampered.stdout)
        outside = self.home / "same-version-gws"
        outside.write_bytes(original)
        outside.chmod(0o755)
        self.runtime_gws.unlink()
        self.runtime_gws.symlink_to(outside)
        linked = self.run("--check")
        self.assertIn("gws runtime: missing (expected 0.22.5)", linked.stdout)

    def test_install_rejects_extracted_binary_digest_before_activation(self) -> None:
        stage = self.home / "release-stage"
        stage.mkdir()
        extracted = stage / "gws"
        extracted.write_text("#!/bin/sh\nprintf 'gws 0.22.5\\n'\n")
        extracted.chmod(0o755)
        with tarfile.open(self.download, "w:gz") as archive:
            archive.add(extracted, arcname="gws")
        archive_sha = hashlib.sha256(self.download.read_bytes()).hexdigest()
        extracted_sha = hashlib.sha256(extracted.read_bytes()).hexdigest()
        self.pin_test_script(archive_sha=archive_sha, binary_sha=hashlib.sha256(b"different trusted binary").hexdigest())
        rejected = self.run("--install")
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertIn("extracted gws checksum mismatch", rejected.stderr)
        self.assertFalse(self.runtime_gws.exists())
        self.pin_test_script(archive_sha=archive_sha, binary_sha=extracted_sha)
        installed = self.run("--install")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual(hashlib.sha256(self.runtime_gws.read_bytes()).hexdigest(), extracted_sha)

    def test_runtime_version_requires_exact_first_output_line(self) -> None:
        self.install_fake_runtime()
        for output in ("gws 0x22x5\\n", "notice before version\\ngws 0.22.5\\n"):
            self.env["FAKE_GWS_VERSION_OUTPUT"] = output
            result = self.run("--check")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("gws runtime: missing (expected 0.22.5)", result.stdout)

    def test_register_client_validates_shape_refuses_replacement_and_protects_copy(self) -> None:
        bad = self.run("--register-client", str(self.write_client({"installed": {"client_id": "only"}})))
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertFalse(self.client_path.exists())
        self.register_client()
        self.assert_mode(self.secrets_home / "gws", 0o700)
        self.assert_mode(self.client_path, 0o600)
        again = self.run("--register-client", str(self.write_client()))
        self.assertEqual(again.returncode, 1)
        self.assertIn("already registered", again.stderr)

    def test_security_validation_never_invokes_path_python_shim(self) -> None:
        shim_log = self.home / "python-shim.log"
        self.env["FAKE_PYTHON_SHIM_LOG"] = str(shim_log)
        self.write_executable("python3", """#!/bin/sh
printf invoked > "$FAKE_PYTHON_SHIM_LOG"
exit 0
""")
        malformed = self.write_client({"installed": {"client_id": "only"}})
        result = self.run("--register-client", str(malformed))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("invalid Desktop OAuth client JSON", result.stderr)
        self.assertFalse(shim_log.exists(), "PATH python3 shim must never run")

    def test_add_account_isolated_normalized_and_private(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("first.name+tag@example.test")
        result = self.run("--add-account", "First.Name+Tag@Example.Test")
        profile = self.accounts_root / "first.name-tag"
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((profile / "profile.json").read_text()), {"schema_version": 1, "expected_email": "First.Name+Tag@Example.Test"})
        self.assert_mode(profile, 0o700)
        self.assert_mode(profile / "profile.json", 0o600)
        self.assert_mode(profile / "client_secret.json", 0o600)
        login_rows = [line.split("|") for line in self.gws_log.read_text().splitlines() if line.startswith(f"auth login --scopes {SCOPE}|")]
        first_login = login_rows[-1]
        self.assertEqual(first_login[:2], [f"auth login --scopes {SCOPE}", "/"])
        self.assertEqual(first_login[2:12], ["unset"] * 10)
        self.assertRegex(first_login[12], r"^set:.*/\.first\.name-tag\.add\.[^/]+$")
        self.assertEqual(first_login[13], "set:file")
        self.assertTrue(first_login[14].startswith(first_login[12] + "/missing-adc.json"))
        self.status("second@example.test")
        second = self.run("--add-account", "second@example.test")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertRegex(self.gws_log.read_text(), r"set:.*/\.second\.add\.[^/|]+")

    def test_add_account_rejects_alias_traversal_symlink_and_expected_email_collision(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("foo@example.test")
        self.assertEqual(self.run("--add-account", "foo@example.test").returncode, 0)
        collision = self.run("--add-account", "foo@other.test")
        self.assertEqual(collision.returncode, 1)
        self.assertIn("belongs to another expected email", collision.stderr)
        for alias in ("../escape", ".", "..", ""):
            self.assertEqual(self.run("--add-account", "new@example.test", "--alias", alias).returncode, 1, alias)
        (self.accounts_root / "link").symlink_to(self.home)
        result = self.run("--add-account", "new@example.test", "--alias", "link")
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)

    def test_add_account_rejects_newline_and_control_bearing_alias_as_one_string(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("new@example.test")
        result = self.run("--add-account", "new@example.test", "--alias", "personal\n!")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("invalid account alias", result.stderr)
        self.assertFalse(self.accounts_root.exists(), "invalid alias must be rejected before creating profiles")

    def test_wrong_login_rolls_back_new_profile_without_touching_existing_profiles(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("wrong@example.test")
        result = self.run("--add-account", "right@example.test", "--alias", "right")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("identity", result.stderr)
        self.assertFalse((self.accounts_root / "right").exists())

    def test_health_checks_real_status_contract_rejects_bad_scopes_and_clears_every_ambient_override(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        self.env.update({
            "GOOGLE_WORKSPACE_CLI_TOKEN": "ambient-token",
            "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/ambient/credentials.json",
            "GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE": "/ambient/credential.json",
            "GOOGLE_WORKSPACE_CLI_CLIENT_ID": "ambient-client-id",
            "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET": "ambient-client-secret",
            "GOOGLE_WORKSPACE_PROJECT_ID": "ambient-project",
            "GOOGLE_WORKSPACE_CLI_LOG": "ambient-log",
            "GOOGLE_WORKSPACE_CLI_LOG_FILE": "/ambient/logs",
            "GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE": "projects/ambient/templates/unsafe",
            "GOOGLE_WORKSPACE_CLI_SANITIZE_MODE": "block",
            "GOOGLE_APPLICATION_CREDENTIALS": "/ambient/adc.json",
        })
        for changes in ({"user": "wrong@example.test"}, {"scopes": []}, {"scopes": [SCOPE, *IDENTITY_SCOPES[:-1]]}, {"scopes": [SCOPE, *IDENTITY_SCOPES, "https://www.googleapis.com/auth/calendar"]}, {"token_valid": False}, {"encrypted_credentials_exists": False}, {"encryption_valid": False}, {"storage": "file"}, {"keyring_backend": "keyring"}, {"scopes": [SCOPE, *IDENTITY_SCOPES, "https://mail.google.com/"]}):
            self.status("account@example.test", **changes)
            self.assertEqual(self.run("--check-account", "account").returncode, 1)
        self.status("ACCOUNT@example.test")
        result = self.run("--check-account", "account")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("account: ready", result.stdout)
        profile = self.accounts_root / "account"
        status_rows = [line.split("|") for line in self.gws_log.read_text().splitlines() if line.startswith("auth status|")]
        self.assertTrue(status_rows)
        self.assertEqual(status_rows[-1], [
            "auth status", "/", *(["unset"] * 10), f"set:{profile.resolve()}", "set:file", f"set:{(profile / 'missing-adc.json').resolve()}",
        ])

    def test_empty_accounts_and_unsafe_root_or_client_fail_closed(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.accounts_root.mkdir()
        os.chmod(self.accounts_root, 0o700)
        checked = self.run("--check")
        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
        self.assertIn("Profiles: none", checked.stdout)
        self.assertNotIn("Overall: ready", checked.stdout)
        listed = self.run("--list-accounts")
        self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
        self.assertIn("Profiles: none", listed.stdout)
        os.chmod(self.accounts_root, 0o755)
        unsafe_root = self.run("--check")
        self.assertEqual(unsafe_root.returncode, 1, unsafe_root.stdout + unsafe_root.stderr)
        self.assertIn("Profiles: unsafe", unsafe_root.stdout)
        os.chmod(self.accounts_root, 0o700)
        os.chmod(self.client_path, 0o644)
        unsafe_client = self.run("--check")
        self.assertEqual(unsafe_client.returncode, 1, unsafe_client.stdout + unsafe_client.stderr)
        self.assertIn("OAuth client: unsafe", unsafe_client.stdout)

    def test_reauth_preserves_identity_and_list_never_prints_email(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        result = self.run("--reauth-account", "account")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.accounts_root / "account" / "profile.json").read_text())["expected_email"], "account@example.test")
        listed = self.run("--list-accounts")
        self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
        self.assertIn("account: ready", listed.stdout)
        self.assertNotIn("account@example.test", listed.stdout)

    def test_reauth_repairs_an_unhealthy_token_without_changing_expected_identity(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        self.status("account@example.test", token_valid=False)
        healthy = {"user": "ACCOUNT@example.test", "token_valid": True, "scopes": [SCOPE, *IDENTITY_SCOPES], "storage": "encrypted", "keyring_backend": "file", "encrypted_credentials_exists": True, "encryption_valid": True}
        self.env["FAKE_GWS_POST_LOGIN_STATUS"] = json.dumps(healthy)
        result = self.run("--reauth-account", "account")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.accounts_root / "account" / "profile.json").read_text())["expected_email"], "account@example.test")

    def test_reauth_swap_failure_keeps_live_profile_and_never_claims_restoration(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.env["FAKE_GWS_LOGIN_VALUE"] = "original"
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        original = {name: (profile / name).read_bytes() for name in ("profile.json", "credentials.enc", ".encryption_key", "token-cache.json")}
        self.env["FAKE_GWS_LOGIN_VALUE"] = "candidate"
        self.env["FAKE_GWS_POST_LOGIN_STATUS"] = self.env["FAKE_GWS_STATUS"]
        self.env["FAKE_GWS_SWAP_BLOCK_ROOT"] = str(self.accounts_root)
        result = self.run("--reauth-account", "account")
        os.chmod(self.accounts_root, 0o700)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("reauthenticated", result.stdout)
        self.assertTrue(profile.is_dir())
        self.assertEqual({name: (profile / name).read_bytes() for name in original}, original)

    def test_check_account_rejects_profile_permissions_that_expose_oauth_state(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        for path in (profile, profile / ".encryption_key", profile / "credentials.enc", profile / "token-cache.json"):
            os.chmod(path, 0o755 if path == profile else 0o644)
            result = self.run("--check-account", "account")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("private permissions", result.stderr)
            os.chmod(path, 0o700 if path == profile else 0o600)

    def test_check_account_rejects_descendant_symlinks(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        nested = profile / "token-cache"
        nested.mkdir()
        os.chmod(nested, 0o700)
        (nested / "linked-state").symlink_to(profile / "credentials.enc")
        result = self.run("--check-account", "account")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("private permissions", result.stderr)

    def test_pythonpath_hook_cannot_hide_exposed_state_or_wrong_status(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        exposed = profile / "credentials.enc"
        os.chmod(exposed, 0o644)
        self.status("wrong@example.test")
        self.env["FAKE_PYTHON_VALIDATION_BYPASS"] = "1"
        exposed_result = self.run("--check-account", "account")
        self.assertEqual(exposed_result.returncode, 1, exposed_result.stdout + exposed_result.stderr)
        self.assertIn("private permissions", exposed_result.stderr)
        os.chmod(exposed, 0o600)
        wrong_status = self.run("--check-account", "account")
        self.assertEqual(wrong_status.returncode, 1, wrong_status.stdout + wrong_status.stderr)
        self.assertIn("identity", wrong_status.stderr)

    def test_extracted_profile_traversal_body_propagates_walk_errors(self) -> None:
        source = SCRIPT.read_text()
        function_start = source.index("profile_state_is_private() {")
        command_start = source.index('PROFILE_DIR="$1" ', function_start)
        body_start = source.index("\n", command_start) + 1
        body_end = source.index("\nPY\n", body_start)
        traversal_body = source[body_start:body_end]
        profile = self.home / "source-profile"
        profile.mkdir()
        os.chmod(profile, 0o700)

        def execute(body: str) -> int:
            def failing_walk(*args: object, **kwargs: object) -> object:
                callback = kwargs.get("onerror")
                if callback is not None:
                    callback(PermissionError("simulated traversal failure"))
                return iter(())

            with mock.patch.dict(os.environ, {"PROFILE_DIR": str(profile)}), mock.patch("os.walk", new=failing_walk):
                try:
                    exec(compile(body, "profile-state-validator", "exec"), {})
                except SystemExit as error:
                    return int(error.code)
            return 0

        self.assertEqual(execute(traversal_body), 1)
        callback_removed = traversal_body.replace(", onerror=rethrow", "")
        self.assertNotEqual(callback_removed, traversal_body)
        self.assertEqual(execute(callback_removed), 0, "removing onerror must reproduce false health")

    def test_reauth_restores_replaced_credential_state_after_login_failure_or_wrong_account(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.env["FAKE_GWS_LOGIN_VALUE"] = "original"
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        original = {name: (profile / name).read_text() for name in ("credentials.enc", ".encryption_key", "token-cache.json")}
        self.env.update({"FAKE_GWS_LOGIN_VALUE": "failed-replacement", "FAKE_GWS_LOGIN_MODE": "fail"})
        failed = self.run("--reauth-account", "account")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertEqual({name: (profile / name).read_text() for name in original}, original)
        self.env.update({"FAKE_GWS_LOGIN_VALUE": "wrong-replacement", "FAKE_GWS_LOGIN_MODE": "ok"})
        self.status("wrong@example.test")
        wrong = self.run("--reauth-account", "account")
        self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
        self.assertEqual({name: (profile / name).read_text() for name in original}, original)


if __name__ == "__main__":
    unittest.main()
