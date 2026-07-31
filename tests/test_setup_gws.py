#!/usr/bin/env python3
"""Behavioral tests for the opt-in isolated gws bootstrap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-gws.sh"
VERSION = "0.22.5"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"


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
        return subprocess.run(["bash", str(SCRIPT), result, *args], cwd=ROOT, env=self.env, text=True, capture_output=True, check=False)

    def install_fake_runtime(self) -> None:
        self.runtime_gws.parent.mkdir(parents=True)
        self.runtime_gws.write_text("""#!/bin/sh
printf '%s|%s|%s|%s|%s|%s\\n' "$*" "$PWD" "${GOOGLE_WORKSPACE_CLI_CONFIG_DIR:-}" "${GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND:-}" "${GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE:-}" "${GOOGLE_APPLICATION_CREDENTIALS:-}" >> "$FAKE_GWS_LOG"
if [ "$1" = "--version" ]; then printf '0.22.5\\n'; exit 0; fi
if [ "$1" = "auth" ] && [ "$2" = "login" ]; then mkdir -p "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR"; printf login > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/login-artifact"; exit 0; fi
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then printf '%s\\n' "$FAKE_GWS_STATUS"; exit 0; fi
exit 3
""")
        self.runtime_gws.chmod(0o755)
        self.local_bin.mkdir(exist_ok=True)
        (self.local_bin / "gws").symlink_to(self.runtime_gws)

    def write_client(self, payload: object | None = None) -> Path:
        source = self.home / "desktop-client.json"
        source.write_text(json.dumps(payload if payload is not None else {"installed": {"client_id": "desktop-id.apps.googleusercontent.com", "client_secret": "desktop-secret", "project_id": "project-id"}}))
        return source

    def register_client(self) -> None:
        result = self.run("--register-client", str(self.write_client()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def status(self, address: str, **changes: object) -> None:
        value: dict[str, object] = {"email": address, "valid": True, "scopes": [SCOPE], "keyring_backend": "file", "credentials_encrypted": True, "credentials_decryptable": True}
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
        result = self.run("--install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already installed", result.stdout)
        self.assertEqual((self.local_bin / "gws").resolve(), self.runtime_gws.resolve())

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
        log = self.gws_log.read_text()
        self.assertIn(f"auth login --scopes {SCOPE}|/|{profile}|file", log)
        self.assertIn(str(profile / "missing-adc.json"), log)
        self.status("second@example.test")
        second = self.run("--add-account", "second@example.test")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn(f"auth login --scopes {SCOPE}|/|{self.accounts_root / 'second'}|file", self.gws_log.read_text())

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

    def test_wrong_login_rolls_back_new_profile_without_touching_existing_profiles(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("wrong@example.test")
        result = self.run("--add-account", "right@example.test", "--alias", "right")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("identity", result.stderr)
        self.assertFalse((self.accounts_root / "right").exists())

    def test_health_checks_reject_bad_status_and_clear_ambient_credentials(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        self.env["GOOGLE_WORKSPACE_CLI_TOKEN"] = "ambient-token"
        for changes in ({"email": "wrong@example.test"}, {"scopes": []}, {"valid": False}, {"credentials_decryptable": False}):
            self.status("account@example.test", **changes)
            self.assertEqual(self.run("--check-account", "account").returncode, 1)
        self.status("ACCOUNT@example.test")
        result = self.run("--check-account", "account")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("account: ready", result.stdout)
        self.assertIn("||", self.gws_log.read_text())

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

    def test_reauth_refuses_an_unhealthy_existing_profile_before_login(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        artifact = self.accounts_root / "account" / "login-artifact"
        artifact.unlink()
        self.status("account@example.test", valid=False)
        result = self.run("--reauth-account", "account")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(artifact.exists(), "an unhealthy profile must not start a new OAuth login")
        self.assertEqual(json.loads((self.accounts_root / "account" / "profile.json").read_text())["expected_email"], "account@example.test")

    def test_check_account_rejects_profile_permissions_that_expose_oauth_state(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        os.chmod(self.accounts_root / "account", 0o755)
        result = self.run("--check-account", "account")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("private permissions", result.stderr)


if __name__ == "__main__":
    unittest.main()
