#!/usr/bin/env python3
"""Behavioral tests for the opt-in isolated gws bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
from types import SimpleNamespace
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
        self.home = Path(self.tempdir.name).resolve()
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
            "scopes": [
                "openid",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "encryption_valid": True,
            "plain_credentials_exists": False,
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

    @property
    def import_root(self) -> Path:
        return self.secrets_home / "gws-import"

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
  if [ -n "${FAKE_GWS_LOGIN_READY:-}" ]; then
    printf ready > "$FAKE_GWS_LOGIN_READY"
    while [ ! -e "$FAKE_GWS_LOGIN_RELEASE" ]; do /bin/sleep 0.01; done
  fi
  mkdir -p "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/credentials.enc"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key"
  printf '%s' "${FAKE_GWS_LOGIN_VALUE:-fresh}" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/token_cache.json"
  if [ -n "${FAKE_GWS_POST_LOGIN_STATUS:-}" ]; then printf '%s' "$FAKE_GWS_POST_LOGIN_STATUS" > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json"; fi
  if [ -n "${FAKE_GWS_SWAP_BLOCK_ROOT:-}" ]; then chmod 500 "$FAKE_GWS_SWAP_BLOCK_ROOT"; fi
  [ "${FAKE_GWS_LOGIN_MODE:-ok}" = "fail" ] && exit 1
  exit 0
fi
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  if [ "${FAKE_GWS_STATUS_REPAIRS_KEY:-0}" = 1 ] && [ ! -e "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key" ]; then
    printf repaired > "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.encryption_key"
  fi
  profile_name="${GOOGLE_WORKSPACE_CLI_CONFIG_DIR##*/}"
  if [ "${profile_name#\.}" = "$profile_name" ] && [ -n "${FAKE_GWS_LIVE_STATUS:-}" ]; then
    printf '%s\\n' "$FAKE_GWS_LIVE_STATUS"
  elif [ -f "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json" ]; then
    cat "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/.fake-status.json"
  elif [ "${FAKE_GWS_IMPORTED_STATUS:-0}" = 1 ]; then
    STATUS_JSON="$FAKE_GWS_STATUS" PROFILE_PATH="$GOOGLE_WORKSPACE_CLI_CONFIG_DIR" /usr/bin/python3 -c 'import json, os; value=json.loads(os.environ["STATUS_JSON"]); root=os.environ["PROFILE_PATH"]; value["plain_credentials"]=value.get("plain_credentials", "").replace("__PROFILE__", root); value["client_config"]=value.get("client_config", "").replace("__PROFILE__", root); print(json.dumps(value))'
  else
    printf '%s\\n' "$FAKE_GWS_STATUS"
  fi
  exit 0
fi
if [ "$1" = "gmail" ] && [ "$2" = "users" ] && [ "$3" = "getProfile" ]; then
  profile_name="${GOOGLE_WORKSPACE_CLI_CONFIG_DIR##*/}"
  if [ "${profile_name#\.}" = "$profile_name" ] && [ -n "${FAKE_GWS_LIVE_GET_PROFILE_READY:-}" ]; then
    printf ready > "$FAKE_GWS_LIVE_GET_PROFILE_READY"
    while :; do /bin/sleep 1; done
  fi
  if [ "${profile_name#\.}" = "$profile_name" ] && [ -n "${FAKE_GWS_LIVE_GET_PROFILE:-}" ]; then
    printf '%s\n' "$FAKE_GWS_LIVE_GET_PROFILE"
  elif [ -n "${FAKE_GWS_GET_PROFILE:-}" ]; then
    printf '%s\n' "$FAKE_GWS_GET_PROFILE"
  else
    printf '%s\n' '{"emailAddress":"account@example.test"}'
  fi
  exit 0
fi
exit 3
""")
        self.runtime_gws.chmod(0o755)
        self.pin_test_script(binary_sha=hashlib.sha256(self.runtime_gws.read_bytes()).hexdigest())
        self.local_bin.mkdir(exist_ok=True)
        os.chmod(self.local_bin, 0o755)
        (self.local_bin / "gws").symlink_to(self.runtime_gws)

    def valid_client_payload(self) -> dict[str, object]:
        return {
            "installed": {
                "client_id": "desktop-id.apps.googleusercontent.com",
                "client_secret": "desktop-secret",
                "project_id": "project-id",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    def write_client(self, payload: object | None = None) -> Path:
        source = self.home / "desktop-client.json"
        source.write_text(json.dumps(payload if payload is not None else self.valid_client_payload()))
        return source

    def register_client(self) -> None:
        result = self.run("--register-client", str(self.write_client()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def write_imported_credentials(
        self,
        *,
        name: str = "authorized-user.json",
        payload: object | None = None,
    ) -> Path:
        self.import_root.mkdir(exist_ok=True)
        self.import_root.chmod(0o700)
        source = self.import_root / name
        source.write_text(json.dumps(payload if payload is not None else {
            "type": "authorized_user",
            "client_id": "desktop-id.apps.googleusercontent.com",
            "client_secret": "desktop-secret",
            "refresh_token": "refresh-token",
        }))
        source.chmod(0o600)
        return source

    def status(self, address: str, **changes: object) -> None:
        value: dict[str, object] = {
            "user": address,
            "token_valid": True,
            "scopes": [SCOPE, *IDENTITY_SCOPES],
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "encryption_valid": True,
            "plain_credentials_exists": False,
        }
        value.update(changes)
        self.env["FAKE_GWS_STATUS"] = json.dumps(value)
        self.env["FAKE_GWS_GET_PROFILE"] = json.dumps({"emailAddress": address})

    def imported_status(self, address: str, profile: Path, **changes: object) -> None:
        value: dict[str, object] = {
            "user": address,
            "token_valid": True,
            "scopes": [SCOPE, *IDENTITY_SCOPES, "https://www.googleapis.com/auth/drive.metadata.readonly"],
            "storage": "plaintext",
            "keyring_backend": "file",
            "plain_credentials_exists": True,
            "encrypted_credentials_exists": False,
            "has_refresh_token": True,
            "plain_credentials": "__PROFILE__/credentials.json",
            "client_config": "__PROFILE__/client_secret.json",
        }
        value.update(changes)
        self.env["FAKE_GWS_STATUS"] = json.dumps(value)
        self.env["FAKE_GWS_IMPORTED_STATUS"] = "1"
        self.env["FAKE_GWS_GET_PROFILE"] = json.dumps({"emailAddress": address})

    def assert_mode(self, path: Path, mode: int) -> None:
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, path)

    def snapshot_tree(self, root: Path) -> dict[str, tuple[int, str, bytes | str]]:
        snapshot: dict[str, tuple[int, str, bytes | str]] = {}
        for path in [root, *sorted(root.rglob("*"))]:
            metadata = path.lstat()
            relative = "." if path == root else str(path.relative_to(root))
            if stat.S_ISREG(metadata.st_mode):
                kind = "file"
                value: bytes | str = path.read_bytes()
            elif stat.S_ISLNK(metadata.st_mode):
                kind = "symlink"
                value = os.readlink(path)
            else:
                kind = "directory"
                value = b""
            snapshot[relative] = (stat.S_IMODE(metadata.st_mode), kind, value)
        return snapshot

    def wait_for_path(self, path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"process exited before readiness marker: {stdout}{stderr}")
            time.sleep(0.01)
        self.fail(f"timed out waiting for {path}")

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

    def test_runtime_rejects_writable_or_symlinked_release_paths(self) -> None:
        self.install_fake_runtime()
        runtime_dir = self.runtime_gws.parent

        runtime_dir.chmod(0o777)
        writable = self.run("--check")
        self.assertIn("gws runtime: missing (expected 0.22.5)", writable.stdout)

        runtime_dir.chmod(0o755)
        real_data_home = self.home / "real-data"
        self.data_home.rename(real_data_home)
        self.data_home.symlink_to(real_data_home, target_is_directory=True)
        linked_ancestor = self.run("--check")
        self.assertIn(
            "gws runtime: missing (expected 0.22.5)",
            linked_ancestor.stdout,
        )

    def test_install_refuses_an_untrusted_preexisting_runtime_path(self) -> None:
        self.install_fake_runtime()
        self.runtime_gws.parent.chmod(0o777)

        result = self.run("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unsafe gws runtime path", result.stderr)

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

    def test_register_client_requires_the_exact_desktop_oauth_shape_before_copy(self) -> None:
        valid_installed = self.valid_client_payload()["installed"]
        assert isinstance(valid_installed, dict)
        invalid_clients = (
            {
                "installed": {
                    "client_id": "desktop-id.apps.googleusercontent.com",
                    "client_secret": "desktop-secret",
                    "project_id": "project-id",
                }
            },
            {
                "installed": {
                    **valid_installed,
                    "auth_uri": "https://example.test/o/oauth2/auth",
                }
            },
            {
                "installed": {
                    **valid_installed,
                    "token_uri": "https://example.test/token",
                }
            },
            {"web": dict(valid_installed)},
        )
        for payload in invalid_clients:
            with self.subTest(payload=payload):
                bad = self.run("--register-client", str(self.write_client(payload)))
                copied = self.client_path.exists() or self.client_path.is_symlink()
                if copied:
                    self.client_path.unlink()
                self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
                self.assertIn("invalid Desktop OAuth client JSON", bad.stderr)
                self.assertFalse(copied, "invalid client must be rejected before copying")
        self.register_client()
        self.assert_mode(self.secrets_home, 0o700)
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

    def test_import_account_accepts_authorized_user_with_safe_extra_scope(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("ACCOUNT@example.test", profile)

        result = self.run(
            "--import-account",
            str(source),
            "--alias",
            "personal",
            "--email",
            "account@example.test",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "Account personal imported\n")
        self.assertNotIn("account@example.test", result.stdout + result.stderr)
        credentials = profile / "credentials.json"
        metadata = json.loads((profile / "profile.json").read_text())
        self.assertEqual(metadata, {
            "schema_version": 1,
            "expected_email": "account@example.test",
            "credential_mode": "imported_authorized_user",
            "scope_policy": "existing_grant",
            "source_sha256": hashlib.sha256(credentials.read_bytes()).hexdigest(),
        })
        self.assertEqual(credentials.read_bytes(), source.read_bytes())
        for path, mode in (
            (profile, 0o700),
            (profile / "profile.json", 0o600),
            (profile / "client_secret.json", 0o600),
            (credentials, 0o600),
        ):
            self.assert_mode(path, mode)
        status_rows = [
            line.split("|")
            for line in self.gws_log.read_text().splitlines()
            if line.startswith("auth status|")
        ]
        self.assertTrue(status_rows)
        self.assertEqual(status_rows[-1][3], f"set:{credentials}")

    def test_import_account_rejects_bad_arguments_and_authorized_user_shapes(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        valid = {
            "type": "authorized_user",
            "client_id": "desktop-id.apps.googleusercontent.com",
            "client_secret": "desktop-secret",
            "refresh_token": "refresh-token",
        }
        bad_documents: tuple[tuple[str, str], ...] = (
            ("malformed", "{"),
            ("duplicate-key", '{"type":"authorized_user","type":"authorized_user","client_id":"desktop-id.apps.googleusercontent.com","client_secret":"desktop-secret","refresh_token":"refresh-token"}'),
            ("wrong-type-value", json.dumps({**valid, "type": "service_account"})),
            ("wrong-field-type", json.dumps({**valid, "refresh_token": ["token"]})),
            ("missing-field", json.dumps({key: value for key, value in valid.items() if key != "refresh_token"})),
            ("extra-token-uri", json.dumps({**valid, "token_uri": "https://oauth2.googleapis.com/token"})),
            ("client-id-mismatch", json.dumps({**valid, "client_id": "other.apps.googleusercontent.com"})),
            ("client-secret-mismatch", json.dumps({**valid, "client_secret": "other-secret"})),
        )
        for name, body in bad_documents:
            with self.subTest(document=name):
                source = self.write_imported_credentials(name=f"{name}.json")
                source.write_text(body)
                source.chmod(0o600)
                result = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertFalse(profile.exists())

        source = self.write_imported_credentials(name="valid.json")
        invalid_commands = (
            ("missing-email", (str(source), "--alias", "personal")),
            ("missing-alias", (str(source), "--email", "account@example.test")),
            ("duplicate-email", (str(source), "--email", "account@example.test", "--email", "account@example.test", "--alias", "personal")),
            ("duplicate-alias", (str(source), "--email", "account@example.test", "--alias", "personal", "--alias", "personal")),
            ("duplicate-replace", (str(source), "--email", "account@example.test", "--alias", "personal", "--replace", "--replace")),
            ("two-positionals", (str(source), str(source), "--email", "account@example.test", "--alias", "personal")),
        )
        for name, command in invalid_commands:
            with self.subTest(arguments=name):
                result = self.run("--import-account", *command)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(profile.exists())

    def test_import_account_counts_an_empty_positional_as_the_sole_file_value(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)

        result = self.run(
            "--import-account",
            "",
            str(source),
            "--email",
            "account@example.test",
            "--alias",
            "personal",
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(profile.exists())

    def test_import_account_rejects_sources_outside_a_private_direct_staging_root(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)

        outside = self.home / "outside.json"
        outside.write_text(self.write_imported_credentials().read_text())
        outside.chmod(0o600)
        nested_dir = self.import_root / "nested"
        nested_dir.mkdir()
        nested_dir.chmod(0o700)
        nested = nested_dir / "nested.json"
        nested.write_text(outside.read_text())
        nested.chmod(0o600)
        relative = os.path.relpath(self.import_root / "authorized-user.json", ROOT)
        for name, source in (("relative", relative), ("outside", str(outside)), ("nested", str(nested))):
            with self.subTest(path=name):
                result = self.run("--import-account", source, "--email", "account@example.test", "--alias", "personal")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertFalse(profile.exists())

        source = self.import_root / "authorized-user.json"
        source.chmod(0o644)
        unsafe_mode = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(unsafe_mode.returncode, 1, unsafe_mode.stdout + unsafe_mode.stderr)
        source.chmod(0o600)

        hardlink = self.import_root / "hardlink.json"
        os.link(source, hardlink)
        linked = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(linked.returncode, 1, linked.stdout + linked.stderr)
        hardlink.unlink()

        symlink = self.import_root / "symlink.json"
        symlink.symlink_to(source)
        linked_source = self.run("--import-account", str(symlink), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(linked_source.returncode, 1, linked_source.stdout + linked_source.stderr)
        symlink.unlink()

        self.import_root.chmod(0o755)
        unsafe_root = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(unsafe_root.returncode, 1, unsafe_root.stdout + unsafe_root.stderr)
        self.assertFalse(profile.exists())

    def test_import_source_validator_rejects_wrong_owner(self) -> None:
        self.register_client()
        source_path = self.write_imported_credentials()
        destination = self.home / "candidate-credentials.json"
        script_source = SCRIPT.read_text()
        function_start = script_source.index("copy_imported_credentials() {")
        body_start = script_source.index("<<'PY'\n", function_start) + len("<<'PY'\n")
        body_end = script_source.index("\nPY\n", body_start)
        validator_body = script_source[body_start:body_end]
        real_lstat = os.lstat

        def wrong_source_owner(path: object, *args: object, **kwargs: object) -> object:
            metadata = real_lstat(path, *args, **kwargs)
            if os.fspath(path) != str(source_path):
                return metadata
            values = {
                name: getattr(metadata, name)
                for name in dir(metadata)
                if name.startswith("st_")
            }
            values["st_uid"] = metadata.st_uid + 1
            return SimpleNamespace(**values)

        environment = {
            "SOURCE_PATH": str(source_path),
            "DESTINATION_PATH": str(destination),
            "IMPORT_ROOT": str(self.import_root),
            "CLIENT_FILE": str(self.client_path),
        }
        with mock.patch.dict(os.environ, environment), mock.patch("os.lstat", side_effect=wrong_source_owner):
            with self.assertRaises(SystemExit) as rejected:
                exec(compile(validator_body, "import-source-validator", "exec"), {})
        self.assertEqual(rejected.exception.code, 1)
        self.assertFalse(destination.exists())

    def test_imported_profile_static_and_live_health_fail_closed(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        imported = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        original_metadata = (profile / "profile.json").read_bytes()
        original_credentials = (profile / "credentials.json").read_bytes()
        status_calls_before = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())

        static_mutations = (
            ("implicit-imported", lambda: (profile / "profile.json").write_text(json.dumps({"schema_version": 1, "expected_email": "account@example.test"}))),
            ("partial-mode", lambda: (profile / "profile.json").write_text(json.dumps({"schema_version": 1, "expected_email": "account@example.test", "credential_mode": "imported_authorized_user"}))),
            ("unknown-mode", lambda: (profile / "profile.json").write_text(json.dumps({"schema_version": 1, "expected_email": "account@example.test", "credential_mode": "unknown", "scope_policy": "existing_grant", "source_sha256": "0" * 64}))),
            ("checksum", lambda: (profile / "credentials.json").write_bytes(original_credentials + b"\n")),
            ("mixed-state", lambda: (profile / "credentials.enc").write_text("encrypted")),
        )
        for name, mutate in static_mutations:
            with self.subTest(static=name):
                (profile / "profile.json").write_bytes(original_metadata)
                (profile / "credentials.json").write_bytes(original_credentials)
                (profile / "credentials.enc").unlink(missing_ok=True)
                for path in (profile / "profile.json", profile / "credentials.json"):
                    path.chmod(0o600)
                mutate()
                (profile / "profile.json").chmod(0o600)
                if (profile / "credentials.enc").exists():
                    (profile / "credentials.enc").chmod(0o600)
                result = self.run("--check-account", "personal")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

        (profile / "profile.json").write_bytes(original_metadata)
        (profile / "credentials.json").write_bytes(original_credentials)
        (profile / "credentials.enc").unlink(missing_ok=True)
        (profile / "profile.json").chmod(0o600)
        (profile / "credentials.json").chmod(0o600)
        status_calls_after = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())
        self.assertEqual(status_calls_after, status_calls_before, "static failures must precede auth status")

        live_mutations: tuple[tuple[str, dict[str, object]], ...] = (
            ("identity", {"user": "wrong@example.test"}),
            ("token", {"token_valid": False}),
            ("storage", {"storage": "encrypted"}),
            ("keyring", {"keyring_backend": "keyring"}),
            ("plaintext-missing", {"plain_credentials_exists": False}),
            ("encrypted-present", {"encrypted_credentials_exists": True}),
            ("refresh-missing", {"has_refresh_token": False}),
            ("wrong-credential-path", {"plain_credentials": "/wrong/credentials.json"}),
            ("wrong-client-path", {"client_config": "/wrong/client_secret.json"}),
            ("missing-scope", {"scopes": [SCOPE, *IDENTITY_SCOPES[:-1]]}),
            ("duplicate-scope", {"scopes": [SCOPE, *IDENTITY_SCOPES, SCOPE]}),
            ("broad-scope", {"scopes": [SCOPE, *IDENTITY_SCOPES, "https://mail.google.com/"]}),
            ("non-string-scope", {"scopes": [SCOPE, *IDENTITY_SCOPES, 7]}),
        )
        for name, changes in live_mutations:
            with self.subTest(live=name):
                self.imported_status("account@example.test", profile, **changes)
                result = self.run("--check-account", "personal")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

        self.imported_status("ACCOUNT@example.test", profile)
        healthy = self.run("--check-account", "personal")
        self.assertEqual(healthy.returncode, 0, healthy.stdout + healthy.stderr)

    def test_imported_profile_rejects_hardlinked_destination_before_status(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        imported = self.run(
            "--import-account",
            str(source),
            "--email",
            "account@example.test",
            "--alias",
            "personal",
        )
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        status_calls_before = sum(
            line.startswith("auth status|")
            for line in self.gws_log.read_text().splitlines()
        )
        external_link = self.home / "linked-imported-credentials.json"
        os.link(profile / "credentials.json", external_link)

        result = self.run("--check-account", "personal")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        status_calls_after = sum(
            line.startswith("auth status|")
            for line in self.gws_log.read_text().splitlines()
        )
        self.assertEqual(
            status_calls_after,
            status_calls_before,
            "hard-linked imported credentials must fail static validation before auth status",
        )

    def test_imported_profile_rejects_boolean_schema_version_before_status(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        imported = self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        metadata = json.loads((profile / "profile.json").read_text())
        metadata["schema_version"] = True
        (profile / "profile.json").write_text(json.dumps(metadata))
        (profile / "profile.json").chmod(0o600)
        status_calls_before = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())

        result = self.run("--check-account", "personal")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        status_calls_after = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())
        self.assertEqual(status_calls_after, status_calls_before, "invalid schema type must fail before auth status")

    def test_imported_reauth_is_rejected_before_login(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        self.assertEqual(self.run("--import-account", str(source), "--email", "account@example.test", "--alias", "personal").returncode, 0)
        login_calls_before = sum(line.startswith("auth login|") for line in self.gws_log.read_text().splitlines())

        result = self.run("--reauth-account", "personal")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("--import-account", result.stderr)
        self.assertIn("--replace", result.stderr)
        login_calls_after = sum(line.startswith("auth login|") for line in self.gws_log.read_text().splitlines())
        self.assertEqual(login_calls_after, login_calls_before)

    def test_import_replacement_requires_same_imported_identity_and_is_serialized(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        first = self.write_imported_credentials(name="first.json")
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        self.assertEqual(self.run("--import-account", str(first), "--email", "account@example.test", "--alias", "personal").returncode, 0)
        original = self.snapshot_tree(profile)

        without_replace = self.run("--import-account", str(first), "--email", "account@example.test", "--alias", "personal")
        self.assertEqual(without_replace.returncode, 1, without_replace.stdout + without_replace.stderr)
        wrong_email = self.run("--import-account", str(first), "--email", "other@example.test", "--alias", "personal", "--replace")
        self.assertEqual(wrong_email.returncode, 1, wrong_email.stdout + wrong_email.stderr)
        lock = self.accounts_root / ".personal.lock"
        lock.mkdir()
        lock.chmod(0o700)
        serialized = self.run("--import-account", str(first), "--email", "account@example.test", "--alias", "personal", "--replace")
        self.assertEqual(serialized.returncode, 1, serialized.stdout + serialized.stderr)
        self.assertEqual(self.snapshot_tree(profile), original)
        lock.rmdir()

        self.status("encrypted@example.test")
        self.env.pop("FAKE_GWS_IMPORTED_STATUS")
        self.assertEqual(self.run("--add-account", "encrypted@example.test", "--alias", "encrypted").returncode, 0)
        encrypted_refusal = self.run("--import-account", str(first), "--email", "encrypted@example.test", "--alias", "encrypted", "--replace")
        self.assertEqual(encrypted_refusal.returncode, 1, encrypted_refusal.stdout + encrypted_refusal.stderr)

    def test_import_replacement_success_and_failures_are_transactional(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        first = self.write_imported_credentials(name="first.json")
        profile = self.accounts_root / "personal"
        self.imported_status("account@example.test", profile)
        self.assertEqual(self.run("--import-account", str(first), "--email", "account@example.test", "--alias", "personal").returncode, 0)
        original = self.snapshot_tree(profile)

        second_payload = {
            "type": "authorized_user",
            "client_id": "desktop-id.apps.googleusercontent.com",
            "client_secret": "desktop-secret",
            "refresh_token": "replacement-token",
        }
        second = self.write_imported_credentials(name="second.json", payload=second_payload)
        self.imported_status("wrong@example.test", profile)
        candidate_failure = self.run("--import-account", str(second), "--email", "account@example.test", "--alias", "personal", "--replace")
        self.assertEqual(candidate_failure.returncode, 1, candidate_failure.stdout + candidate_failure.stderr)
        self.assertEqual(self.snapshot_tree(profile), original)

        self.imported_status("account@example.test", profile)
        wrong_live = {
            "user": "wrong@example.test",
            "token_valid": True,
            "scopes": [SCOPE, *IDENTITY_SCOPES],
            "storage": "plaintext",
            "keyring_backend": "file",
            "plain_credentials_exists": True,
            "encrypted_credentials_exists": False,
            "has_refresh_token": True,
            "plain_credentials": str(profile / "credentials.json"),
            "client_config": str(profile / "client_secret.json"),
        }
        self.env["FAKE_GWS_LIVE_STATUS"] = json.dumps(wrong_live)
        readback_failure = self.run("--import-account", str(second), "--email", "account@example.test", "--alias", "personal", "--replace")
        self.assertEqual(readback_failure.returncode, 1, readback_failure.stdout + readback_failure.stderr)
        self.assertEqual(self.snapshot_tree(profile), original)
        self.assertEqual([path.name for path in self.accounts_root.iterdir()], ["personal"])

        self.env.pop("FAKE_GWS_LIVE_STATUS")
        replaced = self.run("--import-account", str(second), "--email", "ACCOUNT@example.test", "--alias", "personal", "--replace")
        self.assertEqual(replaced.returncode, 0, replaced.stdout + replaced.stderr)
        self.assertEqual((profile / "credentials.json").read_bytes(), second.read_bytes())
        self.assertNotEqual(self.snapshot_tree(profile), original)
        self.assertEqual([path.name for path in self.accounts_root.iterdir()], ["personal"])

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
        for changes in ({"user": "wrong@example.test"}, {"scopes": []}, {"scopes": [SCOPE, *IDENTITY_SCOPES[:-1]]}, {"scopes": [SCOPE, *IDENTITY_SCOPES, "https://www.googleapis.com/auth/calendar"]}, {"token_valid": False}, {"encrypted_credentials_exists": False}, {"encryption_valid": False}, {"plain_credentials_exists": True}, {"plain_credentials_exists": None}, {"storage": "file"}, {"keyring_backend": "keyring"}, {"scopes": [SCOPE, *IDENTITY_SCOPES, "https://mail.google.com/"]}):
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

    def test_every_health_surface_rejects_an_unsafe_or_noncanonical_secrets_root(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        commands = (
            ("--check",),
            ("--check-account", "account"),
            ("--list-accounts",),
        )
        secrets_root = self.secrets_home / "gws"
        os.chmod(secrets_root, 0o755)
        for command in commands:
            with self.subTest(parent="mode", command=command):
                result = self.run(*command)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("Overall: ready", result.stdout)
        os.chmod(secrets_root, 0o700)

        linked_base = self.home / "linked-secrets"
        linked_base.symlink_to(self.secrets_home, target_is_directory=True)
        self.env["CODEX_SECRETS_DIR"] = str(linked_base)
        for command in commands:
            with self.subTest(parent="symlink-ancestor", command=command):
                result = self.run(*command)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("Overall: ready", result.stdout)

    def test_every_health_surface_rejects_an_unsafe_secrets_base_before_status(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        commands = (
            ("--check",),
            ("--check-account", "account"),
            ("--list-accounts",),
        )
        status_calls_before = sum(
            line.startswith("auth status|")
            for line in self.gws_log.read_text().splitlines()
        )

        os.chmod(self.secrets_home, 0o777)
        for command in commands:
            with self.subTest(base="mode", command=command):
                result = self.run(*command)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("Overall: ready", result.stdout)
        os.chmod(self.secrets_home, 0o700)

        linked_base = self.home / "linked-secrets-base"
        linked_base.symlink_to(self.secrets_home, target_is_directory=True)
        self.env["CODEX_SECRETS_DIR"] = str(linked_base)
        for command in commands:
            with self.subTest(base="symlink", command=command):
                result = self.run(*command)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("Overall: ready", result.stdout)

        status_calls_after = sum(
            line.startswith("auth status|")
            for line in self.gws_log.read_text().splitlines()
        )
        self.assertEqual(
            status_calls_after,
            status_calls_before,
            "unsafe secrets bases must fail before auth status",
        )

    def test_register_client_refuses_an_existing_unsafe_secrets_base_without_repair(self) -> None:
        self.secrets_home.mkdir()
        os.chmod(self.secrets_home, 0o777)
        result = self.run("--register-client", str(self.write_client()))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_mode(self.secrets_home, 0o777)
        self.assertFalse(self.client_path.exists() or self.client_path.is_symlink())
        self.assertFalse((self.secrets_home / "gws").exists())

        os.chmod(self.secrets_home, 0o700)
        retried = self.run("--register-client", str(self.write_client()))
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assert_mode(self.client_path, 0o600)

    def test_register_client_protection_failure_leaves_no_final_or_candidate_and_can_retry(self) -> None:
        source = self.write_client()
        self.write_executable("chmod", """#!/bin/sh
if [ "${FAKE_CHMOD_CLIENT_FAILURE:-0}" = 1 ]; then
  case "${2:-}" in
    */client_secret.json|*/.client_secret.json.*) exit 1 ;;
  esac
fi
exec /bin/chmod "$@"
""")
        self.env["FAKE_CHMOD_CLIENT_FAILURE"] = "1"
        failed = self.run("--register-client", str(source))
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertFalse(self.client_path.exists() or self.client_path.is_symlink())
        gws_root = self.secrets_home / "gws"
        self.assertEqual(
            list(gws_root.glob(".client_secret.json.*")) if gws_root.exists() else [],
            [],
        )

        self.env.pop("FAKE_CHMOD_CLIENT_FAILURE")
        retried = self.run("--register-client", str(source))
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assert_mode(self.client_path, 0o600)

    def test_check_and_list_reject_hidden_or_broken_profile_entries(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)

        hidden_orphan = self.accounts_root / ".account.add.orphan"
        hidden_orphan.mkdir()
        os.chmod(hidden_orphan, 0o700)
        for command in (("--check",), ("--list-accounts",)):
            result = self.run(*command)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("Overall: ready", result.stdout)
        shutil.rmtree(hidden_orphan)

        broken = self.accounts_root / "broken"
        broken.symlink_to(self.home / "missing-profile", target_is_directory=True)
        for command in (("--check",), ("--list-accounts",)):
            result = self.run(*command)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("Overall: ready", result.stdout)

    def test_check_and_list_reject_orphaned_client_candidates_and_gws_root_entries(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        gws_root = self.secrets_home / "gws"

        orphan = gws_root / ".client_secret.json.orphan"
        os.link(self.client_path, orphan)
        for command in (("--check",), ("--list-accounts",)):
            result = self.run(*command)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("Overall: ready", result.stdout)
        orphan.unlink()

        broken = gws_root / ".client_secret.json.broken"
        broken.symlink_to(gws_root / "missing-client")
        for command in (("--check",), ("--list-accounts",)):
            result = self.run(*command)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("Overall: ready", result.stdout)

    def test_health_checks_never_repair_or_read_incomplete_static_credentials(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        credential = profile / "credentials.enc"
        encryption_key = profile / ".encryption_key"
        original_credential = credential.read_bytes()
        original_key = encryption_key.read_bytes()
        self.env["FAKE_GWS_STATUS_REPAIRS_KEY"] = "1"

        def restore_complete_state() -> None:
            for path in (credential, encryption_key, profile / "credentials.json"):
                if path.exists() or path.is_symlink():
                    path.unlink()
            credential.write_bytes(original_credential)
            encryption_key.write_bytes(original_key)
            credential.chmod(0o600)
            encryption_key.chmod(0o600)

        def remove_key() -> None:
            encryption_key.unlink()

        def remove_encrypted_credentials() -> None:
            credential.unlink()

        def add_plaintext_credentials() -> None:
            plaintext = profile / "credentials.json"
            plaintext.write_text('{"access_token":"plaintext"}')
            plaintext.chmod(0o600)

        for name, make_incomplete in (
            ("missing-encryption-key", remove_key),
            ("missing-encrypted-credentials", remove_encrypted_credentials),
            ("plaintext-credentials", add_plaintext_credentials),
        ):
            with self.subTest(state=name):
                restore_complete_state()
                make_incomplete()
                before = self.snapshot_tree(profile)
                status_calls_before = sum(
                    line.startswith("auth status|")
                    for line in self.gws_log.read_text().splitlines()
                )
                for command in (
                    ("--check",),
                    ("--check-account", "account"),
                    ("--list-accounts",),
                ):
                    result = self.run(*command)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(self.snapshot_tree(profile), before)
                status_calls_after = sum(
                    line.startswith("auth status|")
                    for line in self.gws_log.read_text().splitlines()
                )
                self.assertEqual(
                    status_calls_after,
                    status_calls_before,
                    "static rejection must occur before auth status",
                )

    def test_same_alias_add_and_reauth_are_serialized_without_nested_activation(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")

        add_ready = self.home / "add-ready"
        add_release = self.home / "add-release"
        blocking_add_env = self.env.copy()
        blocking_add_env.update({
            "FAKE_GWS_LOGIN_READY": str(add_ready),
            "FAKE_GWS_LOGIN_RELEASE": str(add_release),
        })
        first_add = subprocess.Popen(
            ["bash", str(self.script), "--add-account", "account@example.test"],
            cwd=ROOT,
            env=blocking_add_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.wait_for_path(add_ready, first_add)
            final_path_was_reserved = (self.accounts_root / "account").is_dir()
            second_add = self.run("--add-account", "account@example.test")
        finally:
            add_release.touch()
        first_add_stdout, first_add_stderr = first_add.communicate(timeout=10)

        self.assertTrue(final_path_was_reserved, "the final add path must be reserved before OAuth")
        self.assertEqual(first_add.returncode, 0, first_add_stdout + first_add_stderr)
        self.assertEqual(second_add.returncode, 1, second_add.stdout + second_add.stderr)
        self.assertNotIn("added", second_add.stdout)
        profile = self.accounts_root / "account"
        self.assertTrue(profile.is_dir())
        self.assertFalse(
            any(path.name.startswith(".account.add.") for path in profile.rglob("*")),
            "candidate activation must never nest inside a raced destination",
        )

        reauth_ready = self.home / "reauth-ready"
        reauth_release = self.home / "reauth-release"
        blocking_reauth_env = self.env.copy()
        blocking_reauth_env.update({
            "FAKE_GWS_LOGIN_READY": str(reauth_ready),
            "FAKE_GWS_LOGIN_RELEASE": str(reauth_release),
        })
        first_reauth = subprocess.Popen(
            ["bash", str(self.script), "--reauth-account", "account"],
            cwd=ROOT,
            env=blocking_reauth_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.wait_for_path(reauth_ready, first_reauth)
            second_reauth = self.run("--reauth-account", "account")
        finally:
            reauth_release.touch()
        first_reauth_stdout, first_reauth_stderr = first_reauth.communicate(timeout=10)

        self.assertEqual(first_reauth.returncode, 0, first_reauth_stdout + first_reauth_stderr)
        self.assertEqual(second_reauth.returncode, 1, second_reauth.stdout + second_reauth.stderr)
        self.assertNotIn("reauthenticated", second_reauth.stdout)
        self.assertEqual(
            [path.name for path in self.accounts_root.iterdir()],
            ["account"],
            "successful operations must remove candidates and locks",
        )

    def test_live_activation_readback_gates_success_and_restores_reauth(self) -> None:
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        wrong_live = {
            "user": "wrong@example.test",
            "token_valid": True,
            "scopes": [SCOPE, *IDENTITY_SCOPES],
            "storage": "encrypted",
            "keyring_backend": "file",
            "encrypted_credentials_exists": True,
            "encryption_valid": True,
            "plain_credentials_exists": False,
        }
        self.env["FAKE_GWS_LIVE_STATUS"] = json.dumps(wrong_live)
        added = self.run("--add-account", "account@example.test")
        self.assertEqual(added.returncode, 1, added.stdout + added.stderr)
        self.assertNotIn("Account account added", added.stdout)
        self.assertFalse((self.accounts_root / "account").exists())

        self.env.pop("FAKE_GWS_LIVE_STATUS")
        self.env["FAKE_GWS_LOGIN_VALUE"] = "original"
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        original = self.snapshot_tree(profile)
        self.env["FAKE_GWS_LOGIN_VALUE"] = "replacement"
        self.env["FAKE_GWS_LIVE_STATUS"] = json.dumps(wrong_live)
        reauthenticated = self.run("--reauth-account", "account")
        self.assertEqual(reauthenticated.returncode, 1, reauthenticated.stdout + reauthenticated.stderr)
        self.assertNotIn("Account account reauthenticated", reauthenticated.stdout)
        self.assertEqual(self.snapshot_tree(profile), original)

    def test_signal_during_final_readback_rolls_back_every_activated_profile_transaction(self) -> None:
        """Catches EXIT cleanup preserving an activated but uncommitted profile after SIGTERM."""
        self.install_fake_runtime()
        self.register_client()

        def interrupt_final_readback(*arguments: str) -> subprocess.CompletedProcess[str]:
            ready = self.home / ("final-readback-" + arguments[-1])
            child_env = self.env.copy()
            child_env["FAKE_GWS_LIVE_GET_PROFILE_READY"] = str(ready)
            process = subprocess.Popen(
                ["bash", str(self.script), *arguments],
                cwd=ROOT,
                env=child_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                self.wait_for_path(ready, process)
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=10)
            return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

        def assert_safe_interruption(result: subprocess.CompletedProcess[str]) -> None:
            self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
            diagnostic = result.stdout + result.stderr
            self.assertNotRegex(
                diagnostic,
                r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
                "signal diagnostics must never disclose an expected or observed email address",
            )
            self.assertNotIn(str(self.home), diagnostic)
            self.assertNotIn("project-id", diagnostic)

        def assert_only_profiles(*aliases: str) -> None:
            self.assertEqual(
                sorted(path.name for path in self.accounts_root.iterdir()),
                sorted(aliases),
                "signal cleanup must remove locks, candidates, reservations, backups, and quarantines",
            )

        with self.subTest(operation="add-new"):
            self.status("add-signal@example.test")
            added = interrupt_final_readback(
                "--add-account", "add-signal@example.test", "--alias", "add-signal"
            )
            assert_safe_interruption(added)
            assert_only_profiles()

        with self.subTest(operation="import-new"):
            source = self.write_imported_credentials(name="import-new.json")
            imported = self.accounts_root / "import-new"
            self.imported_status("import-new@example.test", imported)
            imported_new = interrupt_final_readback(
                "--import-account",
                str(source),
                "--email",
                "import-new@example.test",
                "--alias",
                "import-new",
            )
            assert_safe_interruption(imported_new)
            assert_only_profiles()

        with self.subTest(operation="import-replace"):
            original_source = self.write_imported_credentials(name="replace-original.json")
            replaced = self.accounts_root / "import-replace"
            self.imported_status("import-replace@example.test", replaced)
            created = self.run(
                "--import-account",
                str(original_source),
                "--email",
                "import-replace@example.test",
                "--alias",
                "import-replace",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            replaced_before = self.snapshot_tree(replaced)
            replacement_source = self.write_imported_credentials(
                name="replace-candidate.json",
                payload={
                    "type": "authorized_user",
                    "client_id": "desktop-id.apps.googleusercontent.com",
                    "client_secret": "desktop-secret",
                    "refresh_token": "replacement-refresh-token",
                },
            )
            self.imported_status("import-replace@example.test", replaced)
            replacement = interrupt_final_readback(
                "--import-account",
                str(replacement_source),
                "--email",
                "import-replace@example.test",
                "--alias",
                "import-replace",
                "--replace",
            )
            assert_safe_interruption(replacement)
            self.assertEqual(self.snapshot_tree(replaced), replaced_before)
            assert_only_profiles("import-replace")

        with self.subTest(operation="migrate"):
            self.env.pop("FAKE_GWS_IMPORTED_STATUS", None)
            self.status("migrate-signal@example.test")
            created = self.run(
                "--add-account", "migrate-signal@example.test", "--alias", "migrate-signal"
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            migrated = self.accounts_root / "migrate-signal"
            migrated.joinpath("client_secret.json").write_bytes(self.client_path.read_bytes())
            migrated.joinpath("client_secret.json").chmod(0o600)
            migrated_before = self.snapshot_tree(migrated)
            migration = interrupt_final_readback("--migrate-account", "migrate-signal")
            assert_safe_interruption(migration)
            self.assertEqual(self.snapshot_tree(migrated), migrated_before)
            assert_only_profiles("import-replace", "migrate-signal")

        with self.subTest(operation="reauth"):
            self.status("reauth-signal@example.test")
            self.env["FAKE_GWS_LOGIN_VALUE"] = "original"
            created = self.run(
                "--add-account", "reauth-signal@example.test", "--alias", "reauth-signal"
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            reauthenticated = self.accounts_root / "reauth-signal"
            reauthenticated_before = self.snapshot_tree(reauthenticated)
            self.env["FAKE_GWS_LOGIN_VALUE"] = "replacement"
            reauth = interrupt_final_readback("--reauth-account", "reauth-signal")
            assert_safe_interruption(reauth)
            self.assertEqual(self.snapshot_tree(reauthenticated), reauthenticated_before)
            assert_only_profiles("import-replace", "migrate-signal", "reauth-signal")

    def test_failed_signal_rollback_preserves_recovery_trees_and_alias_lock(self) -> None:
        """Catches exposing an uncommitted live profile after rollback itself fails."""
        self.install_fake_runtime()
        self.register_client()
        self.status("rollback-failure@example.test")
        created = self.run(
            "--add-account",
            "rollback-failure@example.test",
            "--alias",
            "rollback-failure",
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        profile = self.accounts_root / "rollback-failure"
        profile.joinpath("client_secret.json").write_bytes(self.client_path.read_bytes())
        profile.joinpath("client_secret.json").chmod(0o600)
        original = self.snapshot_tree(profile)
        ready = self.home / "rollback-failure-ready"
        child_env = self.env.copy()
        child_env["FAKE_GWS_LIVE_GET_PROFILE_READY"] = str(ready)
        process = subprocess.Popen(
            ["bash", str(self.script), "--migrate-account", "rollback-failure"],
            cwd=ROOT,
            env=child_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            self.wait_for_path(ready, process)
            candidate_rows = [
                row
                for row in (line.split("|") for line in self.gws_log.read_text().splitlines())
                if row[0] == "auth status" and "/.rollback-failure.migrate." in row[12]
            ]
            self.assertEqual(len(candidate_rows), 1)
            candidate = Path(candidate_rows[0][12].removeprefix("set:"))
            candidate.mkdir(mode=0o700)
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=10)

        self.assertEqual(process.returncode, 1, stdout + stderr)
        diagnostic = stdout + stderr
        self.assertIn("preserved profile backup requires manual review", diagnostic)
        self.assertIn("preserved candidate profile requires manual review", diagnostic)
        self.assertNotRegex(
            diagnostic,
            r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
        )
        self.assertNotIn(str(self.home), diagnostic)
        backups = list(self.accounts_root.glob(".rollback-failure.backup.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.snapshot_tree(backups[0]), original)
        self.assertNotEqual(self.snapshot_tree(profile), original)
        self.assertEqual(
            json.loads(profile.joinpath("client_secret.json").read_text())["installed"]["project_id"],
            "",
        )
        lock = self.accounts_root / ".rollback-failure.lock"
        self.assertTrue(lock.is_dir(), "failed rollback must retain the alias lock")
        blocked = self.run("--migrate-account", "rollback-failure")
        self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
        self.assertIn("already in progress or has a stale lock", blocked.stderr)

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
        healthy = {"user": "ACCOUNT@example.test", "token_valid": True, "scopes": [SCOPE, *IDENTITY_SCOPES], "storage": "encrypted", "keyring_backend": "file", "encrypted_credentials_exists": True, "encryption_valid": True, "plain_credentials_exists": False}
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
        original = {name: (profile / name).read_bytes() for name in ("profile.json", "credentials.enc", ".encryption_key", "token_cache.json")}
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
        for path in (profile, profile / ".encryption_key", profile / "credentials.enc", profile / "token_cache.json"):
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
        nested = profile / "token_cache"
        nested.mkdir()
        os.chmod(nested, 0o700)
        (nested / "linked-state").symlink_to(profile / "credentials.enc")
        result = self.run("--check-account", "account")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("private permissions", result.stderr)

    def test_extracted_profile_validator_rejects_wrong_owner_for_every_object(self) -> None:
        source = SCRIPT.read_text()
        function_start = source.index("profile_state_is_private() {")
        command_start = source.index('PROFILE_DIR="$1" ', function_start)
        body_start = source.index("\n", command_start) + 1
        body_end = source.index("\nPY\n", body_start)
        validator_body = source[body_start:body_end]
        profile = self.home / "owned-profile"
        nested = profile / "token-cache"
        nested.mkdir(parents=True)
        profile_file = profile / "profile.json"
        nested_file = nested / "state.json"
        profile_file.write_text("{}")
        nested_file.write_text("{}")
        profile.chmod(0o700)
        nested.chmod(0o700)
        profile_file.chmod(0o600)
        nested_file.chmod(0o600)
        real_lstat = os.lstat

        def execute_with_wrong_owner(target: Path) -> int:
            def wrong_owner(path: object, *args: object, **kwargs: object) -> object:
                metadata = real_lstat(path, *args, **kwargs)
                if os.fspath(path) != str(target):
                    return metadata
                values = {
                    name: getattr(metadata, name)
                    for name in dir(metadata)
                    if name.startswith("st_")
                }
                values["st_uid"] = os.getuid() + 1
                return SimpleNamespace(**values)

            with mock.patch.dict(os.environ, {"PROFILE_DIR": str(profile)}), mock.patch(
                "os.lstat", side_effect=wrong_owner
            ):
                try:
                    exec(compile(validator_body, "profile-state-validator", "exec"), {})
                except SystemExit as error:
                    return int(error.code)
            return 0

        for target in (profile, nested, profile_file, nested_file):
            with self.subTest(target=target.relative_to(profile.parent)):
                self.assertEqual(execute_with_wrong_owner(target), 1)

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
        original = {name: (profile / name).read_text() for name in ("credentials.enc", ".encryption_key", "token_cache.json")}
        self.env.update({"FAKE_GWS_LOGIN_VALUE": "failed-replacement", "FAKE_GWS_LOGIN_MODE": "fail"})
        failed = self.run("--reauth-account", "account")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertEqual({name: (profile / name).read_text() for name in original}, original)
        self.env.update({"FAKE_GWS_LOGIN_VALUE": "wrong-replacement", "FAKE_GWS_LOGIN_MODE": "ok"})
        self.status("wrong@example.test")
        wrong = self.run("--reauth-account", "account")
        self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
        self.assertEqual({name: (profile / name).read_text() for name in original}, original)

    def test_new_profiles_use_a_projectless_runtime_client_without_mutating_registration(self) -> None:
        """Catches copying the protected registered project ID into a runtime profile."""
        self.install_fake_runtime()
        self.register_client()
        registered = self.client_path.read_bytes()
        self.status("encrypted@example.test")

        added = self.run("--add-account", "encrypted@example.test", "--alias", "encrypted")

        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        self.assertEqual(
            json.loads((self.accounts_root / "encrypted" / "client_secret.json").read_text())["installed"]["project_id"],
            "",
        )
        self.assertEqual(self.client_path.read_bytes(), registered)

        source = self.write_imported_credentials()
        imported_profile = self.accounts_root / "imported"
        self.imported_status("imported@example.test", imported_profile)
        imported = self.run("--import-account", str(source), "--email", "imported@example.test", "--alias", "imported")

        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        self.assertEqual(
            json.loads((imported_profile / "client_secret.json").read_text())["installed"]["project_id"],
            "",
        )
        self.assertEqual(self.client_path.read_bytes(), registered)

    def test_check_rejects_legacy_runtime_project_before_status_and_reauth_accepts_runtime_contract(self) -> None:
        """Catches accepting a nonempty runtime project ID or treating an empty one as invalid."""
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        legacy_client = json.loads((profile / "client_secret.json").read_text())
        legacy_client["installed"]["project_id"] = "project-id"
        (profile / "client_secret.json").write_text(json.dumps(legacy_client))
        (profile / "client_secret.json").chmod(0o600)
        status_calls_before = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())

        legacy = self.run("--check-account", "account")

        self.assertEqual(legacy.returncode, 1, legacy.stdout + legacy.stderr)
        self.assertEqual(
            sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines()),
            status_calls_before,
            "legacy runtime project IDs must fail before auth status",
        )
        runtime_client = json.loads((profile / "client_secret.json").read_text())
        runtime_client["installed"]["project_id"] = ""
        (profile / "client_secret.json").write_text(json.dumps(runtime_client))
        (profile / "client_secret.json").chmod(0o600)

        reauthenticated = self.run("--reauth-account", "account")

        self.assertEqual(reauthenticated.returncode, 0, reauthenticated.stdout + reauthenticated.stderr)

    def test_health_requires_live_get_profile_identity_after_auth_status(self) -> None:
        """Catches declaring a profile ready from auth status without a live Gmail identity readback."""
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        self.env["FAKE_GWS_GET_PROFILE"] = json.dumps({"emailAddress": "other@example.test"})

        rejected = self.run("--check-account", "account")

        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertIn("identity", rejected.stderr)

    def test_health_uses_the_pinned_get_profile_me_json_contract(self) -> None:
        """Catches a live identity check that omits the explicit me target or JSON format."""
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")

        added = self.run("--add-account", "account@example.test")

        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        self.assertIn(
            'gmail users getProfile --params {"userId":"me"} --format json|',
            self.gws_log.read_text(),
        )

    def test_check_rejects_missing_or_nonstring_runtime_project_id_before_status(self) -> None:
        """Catches a runtime validator that accepts malformed project IDs or reaches gws first."""
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        original = json.loads((profile / "client_secret.json").read_text())

        for name, mutate in (
            ("missing", lambda client: client["installed"].pop("project_id")),
            ("nonstring", lambda client: client["installed"].__setitem__("project_id", None)),
        ):
            with self.subTest(project_id=name):
                client = json.loads(json.dumps(original))
                mutate(client)
                (profile / "client_secret.json").write_text(json.dumps(client))
                (profile / "client_secret.json").chmod(0o600)
                status_calls_before = sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines())
                rejected = self.run("--check-account", "account")
                self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
                self.assertEqual(
                    sum(line.startswith("auth status|") for line in self.gws_log.read_text().splitlines()),
                    status_calls_before,
                )
        (profile / "client_secret.json").write_text(json.dumps(original))
        (profile / "client_secret.json").chmod(0o600)

    def test_migrate_account_is_transactional_idempotent_and_alias_only_for_encrypted_and_imported_profiles(self) -> None:
        """Catches in-place migration, lost client fields, non-idempotence, or account-email disclosure."""
        self.install_fake_runtime()
        self.register_client()
        registered = self.client_path.read_bytes()
        self.status("encrypted@example.test")
        self.assertEqual(self.run("--add-account", "encrypted@example.test", "--alias", "encrypted").returncode, 0)
        encrypted = self.accounts_root / "encrypted"
        source = self.write_imported_credentials()
        imported = self.accounts_root / "imported"
        self.imported_status("imported@example.test", imported)
        self.assertEqual(self.run("--import-account", str(source), "--email", "imported@example.test", "--alias", "imported").returncode, 0)
        for profile in (encrypted, imported):
            (profile / "client_secret.json").write_bytes(registered)
            (profile / "client_secret.json").chmod(0o600)

        for alias, profile, email in (
            ("encrypted", encrypted, "encrypted@example.test"),
            ("imported", imported, "imported@example.test"),
        ):
            with self.subTest(alias=alias):
                if alias == "encrypted":
                    self.status(email)
                else:
                    self.imported_status(email, profile)
                legacy_snapshot = self.snapshot_tree(profile)
                migrated = self.run("--migrate-account", alias)
                self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
                self.assertIn(alias, migrated.stdout)
                self.assertNotIn(email, migrated.stdout + migrated.stderr)
                self.assertEqual(
                    json.loads((profile / "client_secret.json").read_text())["installed"]["project_id"],
                    "",
                )
                self.assertEqual(self.client_path.read_bytes(), registered)
                migrated_snapshot = self.snapshot_tree(profile)
                self.assertEqual(
                    {name: value for name, value in migrated_snapshot.items() if name != "client_secret.json"},
                    {name: value for name, value in legacy_snapshot.items() if name != "client_secret.json"},
                    "migration must only replace the runtime-client file",
                )
                first_snapshot = self.snapshot_tree(profile)
                again = self.run("--migrate-account", alias)
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                self.assertEqual(self.snapshot_tree(profile), first_snapshot)

    def test_migrate_account_rejects_bad_candidates_and_restores_the_exact_live_profile(self) -> None:
        """Catches migration that swaps an unsafe, unhealthy, or failed-readback candidate into place."""
        self.install_fake_runtime()
        self.register_client()
        self.status("account@example.test")
        self.assertEqual(self.run("--add-account", "account@example.test").returncode, 0)
        profile = self.accounts_root / "account"
        legacy_client = json.loads((profile / "client_secret.json").read_text())
        legacy_client["installed"]["project_id"] = "project-id"
        (profile / "client_secret.json").write_text(json.dumps(legacy_client))
        (profile / "client_secret.json").chmod(0o600)
        original = self.snapshot_tree(profile)

        mismatch = json.loads((profile / "client_secret.json").read_text())
        mismatch["installed"]["client_id"] = "other.apps.googleusercontent.com"
        (profile / "client_secret.json").write_text(json.dumps(mismatch))
        (profile / "client_secret.json").chmod(0o600)
        mismatched = self.run("--migrate-account", "account")
        self.assertEqual(mismatched.returncode, 1, mismatched.stdout + mismatched.stderr)
        (profile / "client_secret.json").write_bytes(original["client_secret.json"][2])
        (profile / "client_secret.json").chmod(0o600)

        profile.chmod(0o755)
        unsafe = self.run("--migrate-account", "account")
        self.assertEqual(unsafe.returncode, 1, unsafe.stdout + unsafe.stderr)
        profile.chmod(0o700)

        lock = self.accounts_root / ".account.lock"
        lock.mkdir()
        lock.chmod(0o700)
        serialized = self.run("--migrate-account", "account")
        self.assertEqual(serialized.returncode, 1, serialized.stdout + serialized.stderr)
        lock.rmdir()

        self.status("wrong@example.test")
        unhealthy = self.run("--migrate-account", "account")
        self.assertEqual(unhealthy.returncode, 1, unhealthy.stdout + unhealthy.stderr)
        self.assertEqual(self.snapshot_tree(profile), original)

        self.status("account@example.test")
        self.env["FAKE_GWS_LIVE_STATUS"] = self.env["FAKE_GWS_STATUS"]
        self.env["FAKE_GWS_LIVE_GET_PROFILE"] = json.dumps({"emailAddress": "wrong@example.test"})
        readback = self.run("--migrate-account", "account")
        self.assertEqual(readback.returncode, 1, readback.stdout + readback.stderr)
        self.assertEqual(self.snapshot_tree(profile), original)

    def test_migrate_imported_account_rejects_bad_candidates_and_rolls_back_without_artifacts(self) -> None:
        """Catches imported-mode migration failures that leak transactions or replace the live profile."""
        self.install_fake_runtime()
        self.register_client()
        registered = self.client_path.read_bytes()
        source = self.write_imported_credentials()
        profile = self.accounts_root / "imported"
        email = "imported@example.test"
        self.imported_status(email, profile)
        self.assertEqual(self.run("--import-account", str(source), "--email", email, "--alias", "imported").returncode, 0)
        (profile / "client_secret.json").write_bytes(registered)
        (profile / "client_secret.json").chmod(0o600)
        original = self.snapshot_tree(profile)

        def assert_alias_only(result: subprocess.CompletedProcess[str]) -> None:
            self.assertNotRegex(
                result.stdout + result.stderr,
                r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
                "migration diagnostics must never echo an expected or observed email address",
            )

        def assert_restored(snapshot: dict[str, tuple[int, str, bytes | str]], result: object) -> None:
            assert isinstance(result, subprocess.CompletedProcess)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            assert_alias_only(result)
            self.assertEqual(self.snapshot_tree(profile), snapshot)
            self.assertEqual([path.name for path in self.accounts_root.iterdir()], ["imported"])

        mismatch = json.loads((profile / "client_secret.json").read_text())
        mismatch["installed"]["client_id"] = "other.apps.googleusercontent.com"
        (profile / "client_secret.json").write_text(json.dumps(mismatch))
        (profile / "client_secret.json").chmod(0o600)
        mismatch_snapshot = self.snapshot_tree(profile)
        assert_restored(mismatch_snapshot, self.run("--migrate-account", "imported"))
        (profile / "client_secret.json").write_bytes(original["client_secret.json"][2])
        (profile / "client_secret.json").chmod(0o600)

        profile.chmod(0o755)
        unsafe_snapshot = self.snapshot_tree(profile)
        unsafe = self.run("--migrate-account", "imported")
        self.assertEqual(unsafe.returncode, 1, unsafe.stdout + unsafe.stderr)
        assert_alias_only(unsafe)
        self.assertEqual(self.snapshot_tree(profile), unsafe_snapshot)
        profile.chmod(0o700)

        lock = self.accounts_root / ".imported.lock"
        lock.mkdir()
        lock.chmod(0o700)
        locked = self.run("--migrate-account", "imported")
        self.assertEqual(locked.returncode, 1, locked.stdout + locked.stderr)
        assert_alias_only(locked)
        self.assertEqual(sorted(path.name for path in self.accounts_root.iterdir()), [".imported.lock", "imported"])
        lock.rmdir()
        self.assertEqual([path.name for path in self.accounts_root.iterdir()], ["imported"])

        self.imported_status("wrong@example.test", profile)
        assert_restored(original, self.run("--migrate-account", "imported"))

        self.imported_status(email, profile)
        live_status = json.loads(self.env["FAKE_GWS_STATUS"])
        live_status["plain_credentials"] = str(profile / "credentials.json")
        live_status["client_config"] = str(profile / "client_secret.json")
        self.env["FAKE_GWS_LIVE_STATUS"] = json.dumps(live_status)
        self.env["FAKE_GWS_LIVE_GET_PROFILE"] = json.dumps({"emailAddress": "wrong@example.test"})
        live_status_calls_before = sum(
            line.startswith("auth status|") and f"set:{profile}|" in line
            for line in self.gws_log.read_text().splitlines()
        )
        assert_restored(original, self.run("--migrate-account", "imported"))
        self.assertGreater(
            sum(
                line.startswith("auth status|") and f"set:{profile}|" in line
                for line in self.gws_log.read_text().splitlines()
            ),
            live_status_calls_before,
            "live readback must run after the candidate becomes active",
        )

    def test_migrate_account_requires_exactly_one_alias_without_mutation_or_gws(self) -> None:
        """Catches accepting zero or multiple migration aliases before argument validation."""
        self.install_fake_runtime()
        self.register_client()
        calls_before = self.gws_log.read_text() if self.gws_log.exists() else ""

        for arguments in ((), ("one", "two")):
            with self.subTest(arguments=arguments):
                result = self.run("--migrate-account", *arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(self.accounts_root.exists())
                self.assertEqual(self.gws_log.read_text() if self.gws_log.exists() else "", calls_before)


if __name__ == "__main__":
    unittest.main()
