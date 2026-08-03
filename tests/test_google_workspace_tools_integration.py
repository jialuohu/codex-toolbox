from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GoogleWorkspaceToolsIntegrationTests(unittest.TestCase):
    """Exercise the installed gws contract through the repository setup checker."""

    def run_checker(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, root / "scripts" / "check-codex-toolbox-setup.py"],
            check=False,
            cwd=root,
            text=True,
            capture_output=True,
        )

    def copy_toolbox(self, destination: Path) -> None:
        shutil.copytree(
            ROOT,
            destination,
            ignore=shutil.ignore_patterns(
                ".git",
                ".superpowers",
                ".worktrees",
                ".venv",
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
            ),
        )

    def replace_once(
        self,
        root: Path,
        relative_path: str,
        before: str,
        after: str,
    ) -> None:
        path = root / relative_path
        original = path.read_text(encoding="utf-8")
        self.assertEqual(
            original.count(before),
            1,
            f"mutation precondition changed for {relative_path}: {before!r}",
        )
        changed = original.replace(before, after, 1)
        self.assertNotEqual(original, changed)
        path.write_text(changed, encoding="utf-8")

    def rewrite_json(
        self,
        root: Path,
        relative_path: str,
        change: Callable[[dict], None],
    ) -> None:
        path = root / relative_path
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def replace_once_in_region(
        self,
        root: Path,
        relative_path: str,
        region_start: str,
        region_end: str,
        before: str,
        after: str,
    ) -> None:
        path = root / relative_path
        original = path.read_text(encoding="utf-8")
        start = original.index(region_start)
        end = original.index(region_end, start)
        region = original[start:end]
        self.assertEqual(
            region.count(before),
            1,
            f"scoped mutation precondition changed for {relative_path}: {before!r}",
        )
        changed_region = region.replace(before, after, 1)
        path.write_text(original[:start] + changed_region + original[end:], encoding="utf-8")

    def refresh_checker_hash(
        self,
        root: Path,
        relative_path: str,
        constant_name: str,
    ) -> None:
        digest = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
        checker = root / "scripts" / "check-codex-toolbox-setup.py"
        original = checker.read_text(encoding="utf-8")
        pattern = re.compile(
            rf'(?P<prefix>^{re.escape(constant_name)} = \(\n    ")[0-9a-f]{{64}}'
            rf'(?P<suffix>"\n\))',
            re.MULTILINE,
        )
        changed, replacements = pattern.subn(
            rf"\g<prefix>{digest}\g<suffix>",
            original,
        )
        self.assertEqual(replacements, 1, f"checker hash constant missing: {constant_name}")
        checker.write_text(changed, encoding="utf-8")

    def assert_checker_rejects(
        self,
        mutate: Callable[[Path], None],
        expected_message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_root = Path(temporary_directory) / "toolbox"
            self.copy_toolbox(copied_root)
            mutate(copied_root)

            result = self.run_checker(copied_root)

        self.assertNotEqual(
            result.returncode,
            0,
            "setup checker accepted a broken google-workspace-tools contract",
        )
        self.assertIn(expected_message, result.stdout + result.stderr)

    def test_setup_checker_accepts_the_complete_google_workspace_contract(self) -> None:
        result = self.run_checker(ROOT)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_setup_checker_rejects_shared_runtime_isolation_regressions(self) -> None:
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        mutations = (
            (
                "  cd / || exit 1\n",
                "gws shared runtime must run from the filesystem root",
            ),
            (
                'gws_runtime_path="${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws"\n',
                "gws shared runtime must use the pinned absolute managed binary",
            ),
            (
                "        metadata = os.lstat(component)\n",
                "gws shared runtime must validate every managed runtime path component",
            ),
            (
                "            or not stat.S_ISDIR(metadata.st_mode)\n"
                "            or metadata.st_uid not in trusted_owners\n"
                "            or mode & (stat.S_IWGRP | stat.S_IWOTH)\n",
                "gws shared runtime must reject untrusted or writable runtime directories",
            ),
            (
                "        or not stat.S_ISREG(metadata.st_mode)\n"
                "        or metadata.st_uid not in trusted_owners\n"
                "        or mode & (stat.S_IWGRP | stat.S_IWOTH)\n",
                "gws shared runtime must reject an untrusted or writable runtime binary",
            ),
            (
                'gws_sha_output="$(/usr/bin/shasum -a 256 "$gws_bin" 2>/dev/null)" || exit 1\n',
                "gws shared runtime must hash the managed binary with /usr/bin/shasum",
            ),
            (
                '[ "$gws_sha256" = "0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e" ] || exit 1\n',
                "gws shared runtime must verify the pinned binary checksum",
            ),
            (
                '[ "$first_line" = "gws 0.22.5" ] || exit 1\n',
                "gws shared runtime must verify the pinned binary version",
            ),
            (
                "  /usr/bin/env -u GOOGLE_WORKSPACE_CLI_TOKEN \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_TOKEN",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_CLIENT_ID \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CLIENT_ID",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_CLIENT_SECRET \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CLIENT_SECRET",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_LOG \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_LOG",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_LOG_FILE \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_LOG_FILE",
            ),
            (
                "    -u GOOGLE_WORKSPACE_PROJECT_ID \\\n",
                "gws shared preflight must prevent an ambient quota-project header",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE",
            ),
            (
                "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_MODE \\\n",
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_SANITIZE_MODE",
            ),
            (
                "    -u GOOGLE_APPLICATION_CREDENTIALS \\\n",
                "gws shared runtime must unset ambient GOOGLE_APPLICATION_CREDENTIALS",
            ),
            (
                '    GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile" \\\n',
                "gws shared runtime must select the isolated profile directory",
            ),
            (
                "    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n",
                "gws shared runtime must force the file keyring backend",
            ),
            (
                '    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
                "gws shared runtime must set the missing profile-local ADC sentinel",
            ),
            (
                'and status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()\n',
                "gws shared runtime must verify the exact live identity",
            ),
            (
                'and status.get("token_valid") is True\n',
                "gws shared runtime must require a valid token",
            ),
            (
                'and status.get("storage") == "encrypted"\n',
                "gws shared runtime must require encrypted credential storage",
            ),
            (
                'and status.get("keyring_backend") == "file"\n',
                "gws shared runtime must verify the file keyring backend",
            ),
            (
                'and status.get("encrypted_credentials_exists") is True\n',
                "gws shared runtime must require encrypted credentials",
            ),
            (
                'and status.get("encryption_valid") is True\n',
                "gws shared runtime must require decryptable credentials",
            ),
            (
                "and isinstance(scopes, list)\n",
                "gws shared runtime must validate the scope collection",
            ),
            (
                '        "openid",\n',
                "gws shared runtime must require the openid identity scope",
            ),
            (
                '        "https://www.googleapis.com/auth/gmail.modify",\n',
                "gws shared runtime must require gmail.modify",
            ),
            (
                '        "https://www.googleapis.com/auth/userinfo.email",\n',
                "gws shared runtime must require the userinfo.email identity scope",
            ),
            (
                '        "https://www.googleapis.com/auth/userinfo.profile",\n',
                "gws shared runtime must require the userinfo.profile identity scope",
            ),
            (
                "and len(scopes) == len(required_scopes)\n",
                "gws shared encrypted mode must require the exact four scopes",
            ),
            (
                "and set(scopes) == required_scopes\n",
                "gws shared encrypted mode must require the exact four scopes",
            ),
            (
                "There is no same-request Gmail connector fallback. Fail closed.\n",
                "gws shared runtime must forbid same-request connector fallback",
            ),
        )

        duplicated_imported_branch_lines = {
            "  cd / || exit 1\n",
            "  /usr/bin/env -u GOOGLE_WORKSPACE_CLI_TOKEN \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_CLIENT_ID \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_CLIENT_SECRET \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_LOG \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_LOG_FILE \\\n",
            "    -u GOOGLE_WORKSPACE_PROJECT_ID \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE \\\n",
            "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_MODE \\\n",
            "    -u GOOGLE_APPLICATION_CREDENTIALS \\\n",
            '    GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile" \\\n',
            "    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n",
            '    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
        }

        for removed_line, expected_message in mutations:
            def mutate(root: Path, line: str = removed_line) -> None:
                if line in duplicated_imported_branch_lines:
                    self.replace_once_in_region(
                        root,
                        shared_skill,
                        'if [ "$credential_mode" = "imported_authorized_user" ]; then\n',
                        'elif [ "$credential_mode" = "encrypted_oauth" ]; then\n',
                        line,
                        "",
                    )
                else:
                    self.replace_once(root, shared_skill, line, "")

            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_additive_security_contradictions(self) -> None:
        mutations = (
            (
                "plugins/google-workspace-tools/skills/gws-shared/SKILL.md",
                "\nUse `account-one` as the default account when no alias is supplied.\n",
                "gws-shared security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail/SKILL.md",
                "\nPermanent deletion is available through `users.messages.delete`.\n",
                "gws-gmail security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-send/SKILL.md",
                "\nSend immediately without creating or rereading a draft.\n",
                "gws-gmail-send security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-reply/SKILL.md",
                "\nSend immediately without creating or rereading a draft.\n",
                "gws-gmail-reply security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-reply-all/SKILL.md",
                "\nSend immediately without creating or rereading a draft.\n",
                "gws-gmail-reply-all security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-forward/SKILL.md",
                "\nSend immediately without creating or rereading a draft.\n",
                "gws-gmail-forward security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-read/SKILL.md",
                "\nUse `account-one` by default and send immediately when a message is urgent.\n",
                "gws-gmail-read security contract must match the canonical reviewed text",
            ),
            (
                "plugins/google-workspace-tools/skills/gws-gmail-triage/SKILL.md",
                "\nUse `account-one` by default and send immediately when a message is urgent.\n",
                "gws-gmail-triage security contract must match the canonical reviewed text",
            ),
            (
                "config/codex/AGENTS.global.md",
                "\nUse the official Gmail connector and direct gws together in the same request.\n",
                "global AGENTS Gmail routing policy must match the canonical reviewed paragraph",
            ),
            (
                "config/codex/AGENTS.global.md",
                "\nFor urgent Gmail work, use the official connector and direct `gws` together.\n",
                "global AGENTS Gmail routing policy must match the canonical reviewed paragraph",
            ),
        )

        for relative_path, addition, expected_message in mutations:
            def mutate(
                root: Path,
                path_value: str = relative_path,
                appended_text: str = addition,
            ) -> None:
                path = root / path_value
                original = path.read_text(encoding="utf-8")
                path.write_text(original + appended_text, encoding="utf-8")
                self.assertTrue(path.read_text(encoding="utf-8").endswith(appended_text))

            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_pin_and_inventory_bypasses(self) -> None:
        setup_script = "scripts/setup-gws.sh"

        def append_version_override(root: Path) -> None:
            path = root / setup_script
            path.write_text(
                path.read_text(encoding="utf-8") + '\nVERSION="0.22.4"\n',
                encoding="utf-8",
            )

        def append_checksum_override(root: Path) -> None:
            path = root / setup_script
            path.write_text(
                path.read_text(encoding="utf-8") + f'\nSHA256="{"0" * 64}"\n',
                encoding="utf-8",
            )

        def remove_binary_checksum_pin(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                'BINARY_SHA256="0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e"\n',
                "",
            )

        def change_release_url(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                'RELEASE_URL="https://github.com/googleworkspace/cli/releases/download/v${VERSION}/${ASSET}"',
                'RELEASE_URL="https://example.invalid/gws.tar.gz"',
            )

        def disable_checksum_comparison(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  [ "$actual" = "$SHA256" ] || die "checksum mismatch for pinned gws release"\n',
                '  # [ "$actual" = "$SHA256" ] || die "checksum mismatch for pinned gws release"\n',
            )

        def change_curl_operand(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  curl -fsSL "$RELEASE_URL" -o "$archive" || die "download failed"\n',
                '  curl -fsSL "https://example.invalid/gws.tar.gz" -o "$archive" || die "download failed"\n',
            )

        def replace_digest_with_expected_checksum(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  actual="$(file_sha256 "$archive")" || die "unable to hash downloaded gws release"\n',
                '  actual="$SHA256"\n',
            )

        def make_checksum_comparison_unreachable(root: Path) -> None:
            comparison = (
                '  [ "$actual" = "$SHA256" ] || '
                'die "checksum mismatch for pinned gws release"\n'
            )
            self.replace_once(
                root,
                setup_script,
                comparison,
                f"  if false; then\n{comparison}  fi\n",
            )

        def bypass_isolated_login(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  if ! run_isolated "$candidate" encrypted_oauth auth login --scopes "$GMAIL_SCOPE"; then\n'
                '    die "OAuth login failed; candidate profile will be removed"\n',
                '  if ! "$GWS_BIN" auth login --scopes "$GMAIL_SCOPE"; then\n'
                '    die "OAuth login failed; candidate profile will be removed"\n',
            )

        def make_post_login_health_check_dead(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  if ! check_profile_health "$candidate" "$email" "$alias" encrypted_oauth; then\n'
                '    die "OAuth login identity check failed; candidate profile will be removed"\n',
                '  if false && ! check_profile_health "$candidate" "$email" "$alias" encrypted_oauth; then\n'
                '    die "OAuth login identity check failed; candidate profile will be removed"\n',
            )

        def add_extra_setup_scope(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '        "https://www.googleapis.com/auth/userinfo.profile",\n',
                '        "https://www.googleapis.com/auth/userinfo.profile",\n'
                '        "https://www.googleapis.com/auth/calendar.readonly",\n',
            )

        def truncate_license(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/LICENSE"
            original = path.read_bytes()
            self.assertGreater(len(original), 64)
            path.write_bytes(original[:-64])

        def add_provenance_import(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/PROVENANCE.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n- `skills/gws-drive/SKILL.md`\n",
                encoding="utf-8",
            )

        def append_provenance_runtime_vendoring_claim(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/PROVENANCE.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nAdditional upstream runtime code is vendored alongside these skills.\n",
                encoding="utf-8",
            )

        def add_empty_skill_directory(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/skills/unexpected-empty"
            self.assertFalse(path.exists())
            path.mkdir()

        cases: tuple[tuple[Callable[[Path], None], str], ...] = (
            (
                append_version_override,
                "setup-gws must pin gws version 0.22.5 exactly once",
            ),
            (
                append_checksum_override,
                "setup-gws must pin the expected release checksum exactly once",
            ),
            (
                remove_binary_checksum_pin,
                "setup-gws must pin the expected binary checksum exactly once",
            ),
            (
                change_release_url,
                "setup-gws must pin the exact upstream release URL",
            ),
            (
                disable_checksum_comparison,
                "setup-gws must actively compare the downloaded archive checksum",
            ),
            (
                change_curl_operand,
                "setup-gws install_gws function must match the canonical reviewed text",
            ),
            (
                replace_digest_with_expected_checksum,
                "setup-gws install_gws function must match the canonical reviewed text",
            ),
            (
                make_checksum_comparison_unreachable,
                "setup-gws install_gws function must match the canonical reviewed text",
            ),
            (
                bypass_isolated_login,
                "setup-gws profile manager must match the canonical reviewed text",
            ),
            (
                make_post_login_health_check_dead,
                "setup-gws profile manager must match the canonical reviewed text",
            ),
            (
                add_extra_setup_scope,
                "setup-gws required Gmail scope set must remain exactly four",
            ),
            (
                truncate_license,
                "google-workspace-tools license must match the canonical Apache-2.0 text",
            ),
            (
                add_provenance_import,
                "google-workspace-tools provenance imported skill inventory must be exact",
            ),
            (
                append_provenance_runtime_vendoring_claim,
                "google-workspace-tools provenance must match the canonical reviewed text",
            ),
            (
                add_empty_skill_directory,
                "google-workspace-tools skills inventory must be exactly the eight Gmail skills",
            ),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_imported_profile_contract_bypasses(self) -> None:
        setup_script = "scripts/setup-gws.sh"
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        credential_assignment = (
            '      GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json" \\\n'
        )
        mutations = (
            (
                shared_skill,
                "    if not mode_keys.intersection(metadata):\n",
                "    if True:\n",
                "gws shared contract must distinguish legacy encrypted and exact imported metadata",
            ),
            (
                shared_skill,
                '            or re.fullmatch(r"[0-9a-f]{64}", metadata["source_sha256"]) is None\n',
                "",
                "gws shared imported marker must require a lowercase SHA-256 digest",
            ),
            (
                shared_skill,
                '            or credentials["client_id"] != installed.get("client_id")\n'
                '            or credentials["client_secret"] != installed.get("client_secret")\n',
                "",
                "gws shared imported credentials must match the profile client",
            ),
            (
                shared_skill,
                '            or hashlib.sha256(credential_bytes).hexdigest() != metadata["source_sha256"]\n',
                "",
                "gws shared imported credentials must match the recorded source hash",
            ),
            (
                shared_skill,
                "        credentials = json.loads(\n"
                "            credential_bytes.decode(\"utf-8\"), object_pairs_hook=reject_duplicates\n"
                "        )\n",
                "        credentials = json.loads(credential_bytes.decode(\"utf-8\"))\n",
                "gws shared imported credentials must reject duplicate keys",
            ),
            (
                shared_skill,
                '        credential_keys = {"type", "client_id", "client_secret", "refresh_token"}\n'
                "        if (\n"
                "            not isinstance(credentials, dict)\n"
                "            or set(credentials) != credential_keys\n",
                "        if (\n"
                "            not isinstance(credentials, dict)\n",
                "gws shared imported credentials must use the exact four-key schema",
            ),
            (
                shared_skill,
                '            or credentials.get("type") != "authorized_user"\n',
                "",
                "gws shared imported credentials must be authorized_user",
            ),
            (
                shared_skill,
                "            or not all(\n"
                "                isinstance(credentials.get(key), str) and credentials[key]\n"
                '                for key in ("client_id", "client_secret", "refresh_token")\n'
                "            )\n",
                "",
                "gws shared imported credential fields must be nonempty strings",
            ),
            (
                shared_skill,
                "    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != mode:\n",
                "    if stat.S_IMODE(metadata.st_mode) != mode:\n",
                "gws shared profile objects must be owned by the current user",
            ),
            (
                shared_skill,
                '            if name == "credentials.json" and file_metadata.st_nlink != 1:\n'
                '                raise ValueError("unsafe imported credential link count")\n',
                "",
                "gws shared imported credentials must be single-link",
            ),
            (
                shared_skill,
                '        if os.path.lexists(os.path.join(profile, "credentials.enc")):\n'
                '            raise ValueError("mixed credential state")\n',
                "",
                "gws shared imported mode must reject mixed encrypted state",
            ),
            (
                shared_skill,
                '      GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json" \\\n',
                "",
                "gws shared imported mode must select credentials only in the imported branch",
            ),
            (
                shared_skill,
                "        and all(isinstance(scope, str) for scope in scopes)\n"
                "        and len(scopes) == len(set(scopes))\n",
                "",
                "gws shared status must require unique string scopes",
            ),
            (
                shared_skill,
                "            and required_scopes.issubset(set(scopes))\n",
                "            and bool(scopes)\n",
                "gws shared imported mode must require every required scope",
            ),
            (
                shared_skill,
                "            and required_scopes.issubset(set(scopes))\n"
                '            and "https://mail.google.com/" not in scopes\n',
                "            and required_scopes.issubset(set(scopes))\n",
                "gws shared imported mode must reject the broad Gmail scope",
            ),
            (
                setup_script,
                '  SOURCE_PATH="$source" DESTINATION_PATH="$destination" IMPORT_ROOT="$SECRETS_BASE/gws-import" CLIENT_FILE="$CLIENT_PATH" /usr/bin/python3 -I - <<\'PY\'\n',
                '  SOURCE_PATH="$source" DESTINATION_PATH="$destination" IMPORT_ROOT="${TMPDIR:-/tmp}" CLIENT_FILE="$CLIENT_PATH" /usr/bin/python3 -I - <<\'PY\'\n',
                "setup-gws imported credentials must come from the private staging root",
            ),
            (
                setup_script,
                "        and os.path.realpath(path) == path\n"
                "        and stat.S_ISDIR(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and metadata.st_uid == os.getuid()\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o700\n",
                "        and os.path.realpath(path) == path\n"
                "        and stat.S_ISDIR(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o700\n",
                "setup-gws import root must be current-user-owned and mode 700",
            ),
            (
                setup_script,
                "        or os.path.dirname(source_path) != root\n",
                "",
                "setup-gws import source must be a canonical direct child",
            ),
            (
                setup_script,
                "def safe_source(metadata):\n"
                "    return (\n"
                "        stat.S_ISREG(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and metadata.st_uid == os.getuid()\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                "        and metadata.st_nlink == 1\n"
                "    )\n",
                "def safe_source(metadata):\n"
                "    return (\n"
                "        stat.S_ISREG(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                "    )\n",
                "setup-gws import source must be current-user-owned mode 600 and single-link",
            ),
            (
                setup_script,
                '    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)\n',
                "    flags = os.O_RDONLY\n",
                "setup-gws import copy must resist source races and verify both copies",
            ),
            (
                setup_script,
                "    destination_fd = os.open(destination_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)\n",
                "    destination_fd = os.open(destination_path, os.O_WRONLY | os.O_CREAT, 0o644)\n",
                "setup-gws import copy must resist source races and verify both copies",
            ),
            (
                setup_script,
                '        if hashlib.sha256(copied.read()).hexdigest() != digest:\n'
                '            raise ValueError("candidate digest mismatch")\n',
                "",
                "setup-gws import copy must resist source races and verify both copies",
            ),
            (
                setup_script,
                "        identity(after_fd) != identity(opened)\n"
                "        or identity(after_path) != identity(before)\n"
                "        or hashlib.sha256(reread).hexdigest() != digest\n",
                "        False\n",
                "setup-gws import copy must resist source races and verify both copies",
            ),
            (
                setup_script,
                '        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()\n',
                "",
                "setup-gws imported profile must verify exact credentials, client, and source hash",
            ),
            (
                setup_script,
                '    credentials = json.loads(credential_bytes.decode("utf-8"), object_pairs_hook=reject_duplicates)\n'
                '    with open(os.path.join(root, "client_secret.json"), encoding="utf-8") as source:\n',
                '    credentials = json.loads(credential_bytes.decode("utf-8"))\n'
                '    with open(os.path.join(root, "client_secret.json"), encoding="utf-8") as source:\n',
                "setup-gws imported profile must reject duplicate credential keys",
            ),
            (
                setup_script,
                '    expected_keys = {"type", "client_id", "client_secret", "refresh_token"}\n'
                "    valid = (\n"
                "        isinstance(credentials, dict)\n"
                "        and set(credentials) == expected_keys\n",
                "    valid = (\n"
                "        isinstance(credentials, dict)\n",
                "setup-gws imported profile must use the exact four-key credential schema",
            ),
            (
                setup_script,
                '        and credentials.get("type") == "authorized_user"\n'
                '        and all(isinstance(credentials.get(key), str) and credentials[key] for key in ("client_id", "client_secret", "refresh_token"))\n'
                '        and credentials["client_id"] == client.get("client_id")\n'
                '        and credentials["client_secret"] == client.get("client_secret")\n'
                '        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()\n',
                '        and all(isinstance(credentials.get(key), str) and credentials[key] for key in ("client_id", "client_secret", "refresh_token"))\n'
                '        and credentials["client_id"] == client.get("client_id")\n'
                '        and credentials["client_secret"] == client.get("client_secret")\n'
                '        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()\n',
                "setup-gws imported profile must require authorized_user credentials",
            ),
            (
                setup_script,
                '        and all(isinstance(credentials.get(key), str) and credentials[key] for key in ("client_id", "client_secret", "refresh_token"))\n'
                '        and credentials["client_id"] == client.get("client_id")\n'
                '        and credentials["client_secret"] == client.get("client_secret")\n'
                '        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()\n',
                '        and credentials["client_id"] == client.get("client_id")\n'
                '        and credentials["client_secret"] == client.get("client_secret")\n'
                '        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()\n',
                "setup-gws imported credential fields must be nonempty strings",
            ),
            (
                setup_script,
                '  private_regular_file "$profile/credentials.json" || return 1\n',
                "",
                "setup-gws imported mode must require plaintext credentials",
            ),
            (
                setup_script,
                '  [ ! -e "$profile/credentials.enc" ] && [ ! -L "$profile/credentials.enc" ] || return 1\n',
                "",
                "setup-gws imported mode must reject mixed encrypted state",
            ),
            (
                setup_script,
                '  validate_imported_profile_state "$profile"\n',
                "  true\n",
                "setup-gws imported static state must validate credentials, client, and hash",
            ),
            (
                setup_script,
                '      GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json" \\\n',
                "",
                "setup-gws imported mode must select credentials only in the imported branch",
            ),
            (
                setup_script,
                "            and required_scopes.issubset(set(scopes))\n",
                "            and bool(scopes)\n",
                "setup-gws imported grants must contain every required scope",
            ),
            (
                setup_script,
                '            and "https://mail.google.com/" not in scopes\n',
                "",
                "setup-gws imported grants must reject the broad Gmail scope",
            ),
            (
                setup_script,
                "            and len(scopes) == len(required_scopes)\n"
                "            and set(scopes) == required_scopes\n",
                "            and required_scopes.issubset(set(scopes))\n",
                "setup-gws encrypted mode must require the exact four scopes",
            ),
            (
                setup_script,
                '  [ "$mode" = "encrypted_oauth" ] || die "imported profiles cannot be reauthenticated; use --import-account FILE --email EMAIL --alias $alias --replace"\n',
                '  if ! run_isolated "$candidate" encrypted_oauth auth login --scopes "$GMAIL_SCOPE"; then\n'
                '    die "OAuth login failed; live profile remains unchanged"\n'
                "  fi\n"
                '  [ "$mode" = "encrypted_oauth" ] || die "imported profiles cannot be reauthenticated; use --import-account FILE --email EMAIL --alias $alias --replace"\n',
                "setup-gws reauthentication must reject imported profiles before login",
            ),
            (
                setup_script,
                '    emails_match "$expected" "$email" || die "account alias belongs to another expected email"\n',
                "",
                "setup-gws replacement must preserve the alias identity",
            ),
            (
                setup_script,
                '    [ "$existing_mode" = "imported_authorized_user" ] || die "--replace is only supported for imported account profiles"\n',
                "",
                "setup-gws replacement must accept only an existing imported profile",
            ),
            (
                setup_script,
                '  if ! check_profile_health "$candidate" "$email" "$alias" imported_authorized_user >/dev/null; then\n'
                '    die "imported credential identity or health check failed; live profile remains unchanged"\n'
                "  fi\n",
                "",
                "setup-gws must validate an imported candidate before activation",
            ),
            (
                setup_script,
                '    if ! rename_path "$profile" "$backup"; then\n'
                '      TX_BACKUP=""\n'
                '      die "unable to stage live profile; live profile remains unchanged"\n'
                "    fi\n",
                '    /bin/rm -rf -- "$profile"\n',
                "setup-gws imported replacement must be transactional and restorable",
            ),
            (
                setup_script,
                '  ensure_accounts_root\n'
                '  acquire_alias_lock "$alias"\n'
                '  profile="$ACCOUNTS_ROOT/$alias"\n'
                '  [ ! -L "$profile" ] || die "refusing symlinked account profile"\n',
                '  ensure_accounts_root\n'
                '  profile="$ACCOUNTS_ROOT/$alias"\n'
                '  [ ! -L "$profile" ] || die "refusing symlinked account profile"\n',
                "setup-gws import activation must hold the alias lock",
            ),
            (
                setup_script,
                '  accounts_root_is_private || die "invalid profile"\n'
                '  acquire_alias_lock "$alias"\n'
                '  profile="$(profile_for_alias "$alias")" || die "invalid profile"\n',
                '  accounts_root_is_private || die "invalid profile"\n'
                '  profile="$(profile_for_alias "$alias")" || die "invalid profile"\n',
                "setup-gws reauthentication must hold the alias lock",
            ),
            (
                shared_skill,
                "            and len(scopes) == len(required_scopes)\n"
                "            and set(scopes) == required_scopes\n",
                "            and required_scopes.issubset(set(scopes))\n",
                "gws shared encrypted mode must require the exact four scopes",
            ),
        )

        for relative_path, before, after, expected_message in mutations:
            def mutate(
                root: Path,
                path: str = relative_path,
                old: str = before,
                new: str = after,
            ) -> None:
                if path == shared_skill and old == credential_assignment:
                    self.replace_once_in_region(
                        root,
                        path,
                        'if [ "$credential_mode" = "imported_authorized_user" ]; then\n',
                        'elif [ "$credential_mode" = "encrypted_oauth" ]; then\n',
                        old,
                        new,
                    )
                elif path == setup_script and old.startswith(
                    '  accounts_root_is_private || die "invalid profile"\n'
                ):
                    self.replace_once_in_region(
                        root,
                        path,
                        "reauth_account() {\n",
                        "check_all() {\n",
                        old,
                        new,
                    )
                else:
                    self.replace_once(root, path, old, new)

            with self.subTest(expected_message=expected_message, mutation=before):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_hash_refreshed_imported_branch_bypasses(self) -> None:
        setup_script = "scripts/setup-gws.sh"
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        credential_assignment = (
            '      GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json" \\\n'
        )

        def relocate_setup_credentials_to_encrypted(root: Path) -> None:
            self.replace_once_in_region(
                root,
                setup_script,
                '  if [ "$mode" = "imported_authorized_user" ]; then\n',
                "    return\n  fi\n",
                credential_assignment,
                "",
            )
            self.replace_once_in_region(
                root,
                setup_script,
                "  fi\n  /usr/bin/env \\\n",
                "}\n\nstatus_is_healthy()",
                "    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n",
                "    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n"
                + credential_assignment,
            )
            self.refresh_checker_hash(root, setup_script, "GWS_SETUP_SHA256")

        def relocate_shared_credentials_to_encrypted(root: Path) -> None:
            self.replace_once_in_region(
                root,
                shared_skill,
                'if [ "$credential_mode" = "imported_authorized_user" ]; then\n',
                'elif [ "$credential_mode" = "encrypted_oauth" ]; then\n',
                credential_assignment,
                "",
            )
            self.replace_once_in_region(
                root,
                shared_skill,
                'elif [ "$credential_mode" = "encrypted_oauth" ]; then\n',
                "else\n  exit 1\nfi\n",
                "      GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n",
                "      GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n"
                + credential_assignment,
            )
            self.refresh_checker_hash(root, shared_skill, "GWS_SHARED_SKILL_SHA256")

        def mutate_and_refresh(
            relative_path: str,
            constant_name: str,
            before: str,
            after: str,
        ) -> Callable[[Path], None]:
            def mutate(root: Path) -> None:
                self.replace_once(root, relative_path, before, after)
                self.refresh_checker_hash(root, relative_path, constant_name)

            return mutate

        cases: tuple[tuple[Callable[[Path], None], str], ...] = (
            (
                relocate_setup_credentials_to_encrypted,
                "setup-gws imported mode must select credentials only in the imported branch",
            ),
            (
                relocate_shared_credentials_to_encrypted,
                "gws shared imported mode must select credentials only in the imported branch",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    '            and status.get("has_refresh_token") is True\n',
                    "",
                ),
                "setup-gws imported live status must require exact plaintext credential state",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    '            and status.get("plain_credentials") == os.path.join(profile, "credentials.json")\n',
                    "",
                ),
                "setup-gws imported live status must require exact plaintext credential state",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    '            and status.get("has_refresh_token") is True\n',
                    "",
                ),
                "gws shared imported live status must require exact plaintext credential state",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    '            and status.get("plain_credentials") == os.path.join(profile, "credentials.json")\n',
                    "",
                ),
                "gws shared imported live status must require exact plaintext credential state",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "        profile = json.load(source, object_pairs_hook=reject_duplicates)\n",
                    "        profile = json.load(source)\n",
                ),
                "setup-gws profile metadata must reject duplicate keys",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    "        return json.load(source, object_pairs_hook=reject_duplicates)\n",
                    "        return json.load(source)\n",
                ),
                "gws shared profile metadata must reject duplicate keys",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    "umask 077\n\n",
                    "",
                ),
                "gws shared executable preflight must establish private umask 077 before profile validation",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    'gws_runtime_path="${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws"\n',
                    'umask 022\n'
                    'gws_runtime_path="${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws"\n',
                ),
                "gws shared executable preflight must keep exactly one lexical umask command line, the leading umask 077",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    "umask 077\n\n",
                    "umask 077\n\n"
                    "printf '%s\\n' \"<<'true'\"\n"
                    "umask 022\n"
                    "true\n",
                ),
                "gws shared executable preflight must keep exactly one lexical umask command line, the leading umask 077",
            ),
            (
                mutate_and_refresh(
                    shared_skill,
                    "GWS_SHARED_SKILL_SHA256",
                    "umask 077\n\n",
                    "umask 077\n\n"
                    "# <<'true'\n"
                    "umask 022\n"
                    "true\n",
                ),
                "gws shared executable preflight must keep exactly one lexical umask command line, the leading umask 077",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "    valid = (\n"
                    "        stat.S_ISREG(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and metadata.st_uid == os.getuid()\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                    "    )\n",
                    "    valid = (\n"
                    "        stat.S_ISREG(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                    "    )\n",
                ),
                "setup-gws private regular files must be current-user-owned mode 600",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "    valid = (\n"
                    "        stat.S_ISDIR(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and metadata.st_uid == os.getuid()\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o700\n"
                    "    )\n",
                    "    valid = (\n"
                    "        stat.S_ISDIR(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o700\n"
                    "    )\n",
                ),
                "setup-gws private profile roots must be current-user-owned mode 700",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != expected_mode:\n",
                    "    if stat.S_IMODE(metadata.st_mode) != expected_mode:\n",
                ),
                "setup-gws profile objects must be current-user-owned with private modes",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "def safe_imported_credentials(metadata):\n"
                    "    return (\n"
                    "        stat.S_ISREG(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and metadata.st_uid == os.getuid()\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                    "        and metadata.st_nlink == 1\n"
                    "    )\n",
                    "def safe_imported_credentials(metadata):\n"
                    "    return (\n"
                    "        stat.S_ISREG(metadata.st_mode)\n"
                    "        and not stat.S_ISLNK(metadata.st_mode)\n"
                    "        and metadata.st_uid == os.getuid()\n"
                    "        and stat.S_IMODE(metadata.st_mode) == 0o600\n"
                    "    )\n",
                ),
                "setup-gws imported credentials must be current-user-owned mode 600 and single-link",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    '        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),\n',
                    "        os.O_RDONLY,\n",
                ),
                "setup-gws imported profile validation must resist credential path races",
            ),
            (
                mutate_and_refresh(
                    setup_script,
                    "GWS_SETUP_SHA256",
                    "    if identity(after_fd) != identity(opened) or identity(after_path) != identity(before):\n",
                    "    if False:\n",
                ),
                "setup-gws imported profile validation must resist credential path races",
            ),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_hash_refreshed_runtime_quota_project_bypasses(self) -> None:
        """Each mutation changes a real safety boundary, not merely pinned text."""
        setup_script = "scripts/setup-gws.sh"
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        plugin_manifest = "plugins/google-workspace-tools/.codex-plugin/plugin.json"
        readme = "README.md"
        provenance = "plugins/google-workspace-tools/PROVENANCE.md"

        def mutate_setup(
            before: str,
            after: str,
        ) -> Callable[[Path], None]:
            def mutate(root: Path) -> None:
                self.replace_once(root, setup_script, before, after)
                self.refresh_checker_hash(root, setup_script, "GWS_SETUP_SHA256")

            return mutate

        def mutate_shared(
            before: str,
            after: str,
        ) -> Callable[[Path], None]:
            def mutate(root: Path) -> None:
                self.replace_once(root, shared_skill, before, after)
                self.refresh_checker_hash(root, shared_skill, "GWS_SHARED_SKILL_SHA256")

            return mutate

        def mutate_setup_function(
            function_name: str,
            next_function_name: str,
            before: str,
            after: str,
        ) -> Callable[[Path], None]:
            def mutate(root: Path) -> None:
                self.replace_once_in_region(
                    root,
                    setup_script,
                    f"{function_name}() {{\n",
                    f"{next_function_name}() {{\n",
                    before,
                    after,
                )
                self.refresh_checker_hash(root, setup_script, "GWS_SETUP_SHA256")

            return mutate

        def remove_shared_quota_header(root: Path) -> None:
            path = root / shared_skill
            original = path.read_text(encoding="utf-8")
            before = "    -u GOOGLE_WORKSPACE_PROJECT_ID \\\n"
            self.assertEqual(original.count(before), 4)
            path.write_text(original.replace(before, ""), encoding="utf-8")
            self.refresh_checker_hash(root, shared_skill, "GWS_SHARED_SKILL_SHA256")

        def remove_shared_live_identity_readback(root: Path) -> None:
            path = root / shared_skill
            original = path.read_text(encoding="utf-8")
            before = '      "$gws_bin" gmail users getProfile --params \'{"userId":"me"}\' --format json\n'
            self.assertEqual(original.count(before), 2)
            path.write_text(
                original.replace(
                    before,
                    '      "$gws_bin" gmail users getProfile --params \'{"userId":"me"}\' --format json --removed\n',
                ),
                encoding="utf-8",
            )
            self.refresh_checker_hash(root, shared_skill, "GWS_SHARED_SKILL_SHA256")

        def mutate_manifest(root: Path) -> None:
            self.rewrite_json(
                root,
                plugin_manifest,
                lambda manifest: manifest.update({"version": "0.2.0"}),
            )

        cases: tuple[tuple[Callable[[Path], None], str], ...] = (
            (
                mutate_setup(
                    '        and installed["project_id"] == ""\n',
                    '        and isinstance(installed.get("project_id"), str)\n',
                ),
                "setup-gws runtime client validator must require an exactly empty quota project",
            ),
            (
                mutate_setup(
                    '    expected["installed"]["project_id"] = ""\n'
                    '    valid = runtime == expected\n',
                    '    valid = runtime == registered\n',
                ),
                "setup-gws runtime comparator must derive exactly the projectless registered client",
            ),
            (
                mutate_setup(
                    '    client["installed"]["project_id"] = ""\n'
                    '    encoded = (json.dumps(client, separators=(",", ":")) + "\\n").encode("utf-8")\n',
                    '    encoded = (json.dumps(client, separators=(",", ":")) + "\\n").encode("utf-8")\n',
                ),
                "setup-gws runtime writer must create a projectless client rather than copy the protected registration",
            ),
            (
                mutate_setup_function(
                    "add_account",
                    "import_account",
                    '  if ! write_runtime_client "$candidate/client_secret.json"; then\n'
                    '    die "unable to create candidate account profile"\n'
                    '  fi\n',
                    '  /bin/cp "$CLIENT_PATH" "$candidate/client_secret.json" || die "unable to create candidate account profile"\n'
                    '  chmod 600 "$candidate/client_secret.json" || die "unable to protect candidate account client"\n',
                ),
                "setup-gws account creation must write a projectless runtime client rather than copy the protected registration",
            ),
            (
                mutate_setup_function(
                    "import_account",
                    "migrate_account",
                    '  if ! write_runtime_client "$candidate/client_secret.json"; then\n'
                    '    die "unable to copy registered OAuth client"\n'
                    '  fi\n',
                    '  /bin/cp "$CLIENT_PATH" "$candidate/client_secret.json" || die "unable to copy registered OAuth client"\n'
                    '  chmod 600 "$candidate/client_secret.json" || die "unable to protect imported account client"\n',
                ),
                "setup-gws imported account creation must write a projectless runtime client rather than copy the protected registration",
            ),
            (
                mutate_setup_function(
                    "runtime_client_matches_registered",
                    "legacy_runtime_client_matches_registered",
                    'runtime_client_matches_registered() {\n',
                    'runtime_client_matches_registered_removed() {\n',
                ),
                "setup-gws must define one runtime client comparator",
            ),
            (
                mutate_setup(
                    '  identity="$(run_isolated "$profile" "$mode" gmail users getProfile --params \'{"userId":"me"}\' --format json 2>/dev/null)" || { printf \'%s: live identity check failed\\n\' "$alias" >&2; return 1; }\n'
                    '  live_identity_matches_expected "$expected" "$identity" || { printf \'%s: live identity check failed\\n\' "$alias" >&2; return 1; }\n',
                    '',
                ),
                "setup-gws health checks must prove the exact Gmail identity with users.getProfile",
            ),
            (
                mutate_setup_function(
                    "migrate_account",
                    "reauth_account",
                    '  [ "$#" -eq 1 ] || usage\n',
                    '  [ "$#" -ge 1 ] || usage\n',
                ),
                "setup-gws migration must accept exactly one explicit alias",
            ),
            (
                mutate_setup_function(
                    "migrate_account",
                    "reauth_account",
                    '  acquire_alias_lock "$alias"\n'
                    '  profile="$(profile_for_alias "$alias")" || die "invalid profile"\n',
                    '  profile="$(profile_for_alias "$alias")" || die "invalid profile"\n',
                ),
                "setup-gws migration must hold an explicit alias-scoped lock",
            ),
            (
                mutate_setup_function(
                    "migrate_account",
                    "reauth_account",
                    '  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.migrate.XXXXXX")" || die "unable to create migration candidate"\n',
                    '  candidate="$profile"\n',
                ),
                "setup-gws migration must stage an alias-scoped candidate",
            ),
            (
                mutate_setup_function(
                    "migrate_account",
                    "reauth_account",
                    '  backup="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.backup.XXXXXX")" || die "unable to reserve profile backup"\n',
                    '  backup="$profile"\n',
                ),
                "setup-gws migration must reserve an alias-scoped backup",
            ),
            (
                mutate_setup(
                    '      if ! rename_path "$TX_LIVE" "$TX_CANDIDATE"; then\n',
                    '      if ! true; then\n',
                ),
                "setup-gws EXIT cleanup must quarantine uncommitted live profiles before backup restoration and preserve failed rollback state",
            ),
            (
                mutate_setup_function(
                    "migrate_account",
                    "reauth_account",
                    '  if ! check_account "$alias" >/dev/null; then\n'
                    '    die "migrated profile failed live readback; transaction will roll back"\n'
                    '  fi\n'
                    '  commit_profile_activation\n',
                    '  commit_profile_activation\n',
                ),
                "setup-gws migration must perform final live readback before committing activation",
            ),
            (
                mutate_shared(
                    '    registered_client_path = os.path.join(gws_root, "client_secret.json")\n',
                    '    registered_client_path = os.path.join(secrets_root, "client_secret.json")\n',
                ),
                "gws shared preflight must read the protected registered client from the gws root",
            ),
            (
                mutate_shared(
                    '    transaction_prefix = f".{alias}."\n'
                    '    if any(name.startswith(transaction_prefix) for name in os.listdir(root)):\n'
                    '        raise ValueError("profile transaction is incomplete")\n',
                    '',
                ),
                "gws shared preflight must reject alias-scoped transaction siblings before invoking gws",
            ),
            (
                mutate_shared(
                    '    check(registered_client_path, stat.S_ISREG, 0o600)\n'
                    '    registered_client = load_json(registered_client_path)\n'
                    '    runtime_client = load_json(runtime_client_path)\n'
                    '    if not valid_registered_client(registered_client):\n'
                    '        raise ValueError("invalid registered OAuth client")\n'
                    '    expected_runtime_client = json.loads(json.dumps(registered_client))\n'
                    '    expected_runtime_client["installed"]["project_id"] = ""\n'
                    '    if runtime_client != expected_runtime_client:\n'
                    '        raise ValueError("invalid runtime OAuth client")\n',
                    '',
                ),
                "gws shared preflight must validate the protected registration and exact projectless runtime equality",
            ),
            (
                remove_shared_quota_header,
                "gws shared preflight must prevent an ambient quota-project header",
            ),
            (
                remove_shared_live_identity_readback,
                "gws shared preflight must retain the live Gmail users.getProfile identity readback",
            ),
            (
                mutate_manifest,
                "google-workspace-tools manifest version must be 0.2.1",
            ),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

        def stale_readme(root: Path) -> None:
            self.replace_once(
                root,
                readme,
                "A gws request that sends `x-goog-user-project` can receive a quota-project 403.",
                "Quota failures have no documented cause.",
            )

        def stale_provenance(root: Path) -> None:
            self.replace_once(
                root,
                provenance,
                "The quota-project runtime-client split is a local safety and compatibility patch.",
                "The quota-project behavior is unmodified upstream behavior.",
            )

        for mutate, expected_message in (
            (stale_readme, "README must explain the gws quota-project 403 and projectless runtime contract"),
            (stale_provenance, "google-workspace-tools provenance must identify the local quota-project runtime-client patch"),
        ):
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_imported_profile_documentation_regressions(self) -> None:
        readme = "README.md"
        provenance = "plugins/google-workspace-tools/PROVENANCE.md"
        mutations = (
            (
                readme,
                "Encrypted OAuth is the recommended credential mode.",
                "Both credential modes are equivalent.",
                "README must recommend encrypted OAuth",
            ),
            (
                readme,
                "Imported `authorized_user` JSON is a supported opt-in plaintext-at-rest alternative.",
                "Imported credentials are encrypted automatically.",
                "README must identify imported authorized_user JSON as plaintext at rest",
            ),
            (
                readme,
                "scripts/setup-gws.sh --import-account /absolute/path/to/gws-import/account-one.json --email account-one@example.com --alias account-one",
                "scripts/setup-gws.sh --add-account account-one@example.com --alias account-one",
                "README must document imported account onboarding with neutral placeholders",
            ),
            (
                readme,
                "scripts/setup-gws.sh --import-account /absolute/path/to/gws-import/account-one-rotated.json --email account-one@example.com --alias account-one --replace",
                "scripts/setup-gws.sh --import-account /absolute/path/to/gws-import/account-one-rotated.json --email account-one@example.com --alias account-two --replace",
                "README must document same-alias same-identity imported rotation",
            ),
            (
                readme,
                "The staging source is retained, and import creates another plaintext copy.",
                "The staging source is deleted after import.",
                "README must warn that import retains the source and creates another plaintext copy",
            ),
            (
                readme,
                "Imported grants may contain extra scopes, but always reject `https://mail.google.com/`.",
                "Imported grants may contain every Gmail scope.",
                "README must document imported extra-scope and broad-scope policy",
            ),
            (
                readme,
                "Imported profiles cannot use `--reauth-account`",
                "Imported profiles can use `--reauth-account`",
                "README must document that imported profiles cannot be reauthenticated",
            ),
            (
                readme,
                "The candidate must\npass its live identity and scope checks before the transactional replacement",
                "The candidate replaces the live profile before validation",
                "README must document pre-activation imported candidate validation",
            ),
            (
                readme,
                "the previous live profile is restored if activation or final live readback fails.",
                "replacement failures may remove the previous live profile.",
                "README must document transactional imported replacement readback and restoration",
            ),
            (
                provenance,
                "Imported authorized-user support is a local plaintext-at-rest extension",
                "Imported authorized-user support comes from upstream",
                "google-workspace-tools provenance must identify the local imported-profile extension",
            ),
        )

        for relative_path, before, after, expected_message in mutations:
            def mutate(
                root: Path,
                path: str = relative_path,
                old: str = before,
                new: str = after,
            ) -> None:
                self.replace_once(root, path, old, new)

            with self.subTest(expected_message=expected_message, mutation=before):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_profile_manager_state_bypasses(self) -> None:
        setup_script = "scripts/setup-gws.sh"

        mutations = (
            (
                "  runtime_path_is_trusted 0 || return 1\n",
                "",
                "setup-gws must validate the complete managed runtime trust path",
            ),
            (
                "            or not stat.S_ISDIR(metadata.st_mode)\n"
                "            or metadata.st_uid not in trusted_owners\n"
                "            or mode & (stat.S_IWGRP | stat.S_IWOTH)\n",
                "            or not stat.S_ISDIR(metadata.st_mode)\n",
                "setup-gws must reject untrusted or writable runtime directories",
            ),
            (
                "  ensure_runtime_dir\n",
                '  ensure_executable_dir "$RUNTIME_DIR"\n',
                "setup-gws installer must reject unsafe preexisting runtime paths",
            ),
            (
                '  profile_state_is_private_shallow "$SECRETS_BASE" || return 1\n',
                "",
                "setup-gws must enforce the canonical private secrets hierarchy",
            ),
            (
                "    valid = (\n"
                "        stat.S_ISDIR(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and metadata.st_uid == os.getuid()\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o700\n"
                "    )\n",
                "    valid = (\n"
                "        stat.S_ISDIR(metadata.st_mode)\n"
                "        and not stat.S_ISLNK(metadata.st_mode)\n"
                "        and metadata.st_uid == os.getuid()\n"
                "        and stat.S_IMODE(metadata.st_mode) == 0o755\n"
                "    )\n",
                "setup-gws private profile roots must be current-user-owned mode 700",
            ),
            (
                '    required = ("client_id", "client_secret", "project_id", "auth_uri", "token_uri")\n',
                '    required = ("client_id", "client_secret", "project_id", "auth_uri")\n',
                "setup-gws registered client validator must require the complete protected Desktop client",
            ),
            (
                '        and installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"\n',
                '        and installed["auth_uri"] == "https://example.invalid/oauth"\n',
                "setup-gws registered client validator must require the complete protected Desktop client",
            ),
            (
                '        and installed["token_uri"] == "https://oauth2.googleapis.com/token"\n',
                '        and installed["token_uri"] == "https://example.invalid/token"\n',
                "setup-gws registered client validator must require the complete protected Desktop client",
            ),
            (
                '  TX_CLIENT_CANDIDATE="$candidate"\n',
                "",
                "setup-gws must register the OAuth client transactionally without clobbering",
            ),
            (
                '  /bin/ln "$candidate" "$CLIENT_PATH" || die "OAuth client already registered; refusing replacement"\n',
                '  /bin/cp "$candidate" "$CLIENT_PATH" || die "unable to store OAuth client"\n',
                "setup-gws must register the OAuth client transactionally without clobbering",
            ),
            (
                '  /bin/rm -- "$candidate" || die "unable to clean OAuth client candidate"\n',
                "",
                "setup-gws must register the OAuth client transactionally without clobbering",
            ),
            (
                '  ensure_accounts_root\n'
                '  acquire_alias_lock "$alias"\n'
                '  profile="$ACCOUNTS_ROOT/$alias"\n'
                '  if [ -L "$profile" ]; then\n',
                '  ensure_accounts_root\n'
                '  profile="$ACCOUNTS_ROOT/$alias"\n'
                '  if [ -L "$profile" ]; then\n',
                "setup-gws must serialize and reserve account activation",
            ),
            (
                '  /bin/mkdir "$profile" || die "unable to reserve account profile path"\n'
                '  TX_RESERVATION="$profile"\n',
                '  /bin/mkdir -p "$profile" || die "unable to reserve account profile path"\n'
                '  TX_RESERVATION="$profile"\n',
                "setup-gws must serialize and reserve account activation",
            ),
            (
                '  rename_path "$candidate" "$profile" || die "unable to activate candidate account profile"\n',
                '  /bin/mv -- "$candidate" "$profile" || die "unable to activate candidate account profile"\n',
                "setup-gws must serialize and reserve account activation",
            ),
            (
                '  if ! check_account "$alias"; then\n'
                '    die "activated account profile failed live readback; transaction will roll back"\n'
                '  fi\n',
                '  if false && ! check_account "$alias"; then\n'
                '    die "activated account profile failed live readback; transaction will roll back"\n'
                '  fi\n',
                "setup-gws must serialize and reserve account activation",
            ),
            (
                '  PROFILE_ENTRIES=("$ACCOUNTS_ROOT"/*)\n',
                '  PROFILE_ENTRIES=("$ACCOUNTS_ROOT"/[a-z0-9]*)\n',
                "setup-gws must inspect hidden and broken profile entries fail closed",
            ),
            (
                '    elif ! secrets_root_inventory_is_clean; then\n'
                "      printf 'OAuth client: unsafe\\n'\n"
                "      printf 'Profiles: unsafe\\n'\n"
                "      failed=1\n",
                "",
                "setup-gws must inspect hidden and broken profile entries fail closed",
            ),
            (
                '  if ! secrets_root_inventory_is_clean; then\n'
                "    printf 'Profiles: unsafe\\n'\n"
                "    return 1\n"
                "  fi\n",
                "",
                "setup-gws must inspect hidden and broken profile entries fail closed",
            ),
            (
                '  private_regular_file "$profile/credentials.enc" || return 1\n',
                "",
                "setup-gws must require encrypted credential files before auth status",
            ),
            (
                '  private_regular_file "$profile/.encryption_key" || return 1\n',
                "",
                "setup-gws must require encrypted credential files before auth status",
            ),
            (
                '  [ ! -e "$profile/credentials.json" ] && [ ! -L "$profile/credentials.json" ]\n',
                "  true\n",
                "setup-gws must reject plaintext credential state",
            ),
            (
                '        and status.get("plain_credentials_exists") is False\n',
                '        and status.get("plain_credentials_exists") is not None\n',
                "setup-gws must reject plaintext credential state",
            ),
        )

        for before, after, expected_message in mutations:
            def mutate(
                root: Path,
                old: str = before,
                new: str = after,
                message: str = expected_message,
            ) -> None:
                if message == "setup-gws registered client validator must require the complete protected Desktop client":
                    self.replace_once_in_region(
                        root,
                        setup_script,
                        "validate_registered_client_json() {\n",
                        "validate_runtime_client_json() {\n",
                        old,
                        new,
                    )
                else:
                    self.replace_once(root, setup_script, old, new)

            with self.subTest(expected_message=expected_message, mutation=before):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_shared_profile_and_attachment_bypasses(self) -> None:
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        mutations = (
            (
                'secrets_root_path="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"\n',
                'secrets_root_path="${CODEX_SECRETS_DIR:-/tmp/gws-secrets}"\n',
                "gws shared contract must enforce the full canonical private secrets hierarchy",
            ),
            (
                "    check(secrets_root, stat.S_ISDIR, 0o700)\n",
                "    check(secrets_root, stat.S_ISDIR, 0o755)\n",
                "gws shared contract must enforce the full canonical private secrets hierarchy",
            ),
            (
                '        "credentials.enc",\n',
                "",
                "gws shared contract must require encrypted credential files before status",
            ),
            (
                '        ".encryption_key",\n',
                "",
                "gws shared contract must require encrypted credential files before status",
            ),
            (
                '        if os.path.lexists(os.path.join(profile, "credentials.json")):\n'
                '            raise ValueError("plaintext profile credentials are forbidden")\n',
                "",
                "gws shared contract must reject plaintext credential state",
            ),
            (
                '        and status.get("plain_credentials_exists") is False\n',
                '        and status.get("plain_credentials_exists") is not None\n',
                "gws shared contract must reject plaintext credential state",
            ),
            (
                "2. Create a private temporary directory with mode `700`, register cleanup for\n",
                "2. Use a temporary directory and register cleanup for\n",
                "gws shared contract must stage attachments as private immutable copies",
            ),
            (
                "3. After the copy, perform a post-copy original restat and rehash. Require the\n",
                "3. After the copy, continue without restating the original. Require the\n",
                "gws shared contract must restat and rehash the original after staging",
            ),
            (
                "   digest and size to match the original record.\n",
                "   digest to be recorded without comparing it to the original.\n",
                "gws shared contract must verify staged size and digest",
            ),
            (
                "   the staged file. Require the final staged digest and identity to match the\n"
                "   staged record. Invoke gws with only the staged copy; never pass the mutable\n"
                "   original path.\n",
                "   the staged file. Invoke gws with the original path.\n",
                "gws shared contract must verify the final staged copy and never pass the original path",
            ),
        )

        for before, after, expected_message in mutations:
            def mutate(
                root: Path,
                old: str = before,
                new: str = after,
            ) -> None:
                self.replace_once(root, shared_skill, old, new)

            with self.subTest(expected_message=expected_message, mutation=before):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_compose_draft_boundary_bypasses(self) -> None:
        compose_skills = (
            "gws-gmail-send",
            "gws-gmail-reply",
            "gws-gmail-reply-all",
            "gws-gmail-forward",
        )

        for skill in compose_skills:
            relative_path = f"plugins/google-workspace-tools/skills/{skill}/SKILL.md"

            def remove_from(root: Path, path: str = relative_path) -> None:
                self.replace_once(root, path, ' --from "$expected_email"', "")

            def remove_full_get(root: Path, path: str = relative_path) -> None:
                self.replace_once(
                    root,
                    path,
                    'draft_json="$(isolated_gws gmail users drafts get --params "$draft_get_params")" || exit 1\n',
                    "",
                )

            def remove_unchanged_reread(root: Path, path: str = relative_path) -> None:
                self.replace_once(
                    root,
                    path,
                    'draft_json_again="$(isolated_gws gmail users drafts get --params "$draft_get_params")" || exit 1\n',
                    "",
                )

            with self.subTest(skill=skill, boundary="from"):
                self.assert_checker_rejects(
                    remove_from,
                    f"{skill} must bind the helper draft to the verified From identity",
                )
            with self.subTest(skill=skill, boundary="full-get"):
                self.assert_checker_rejects(
                    remove_full_get,
                    f"{skill} must fetch the exact new draft in full",
                )
            with self.subTest(skill=skill, boundary="unchanged-reread"):
                self.assert_checker_rejects(
                    remove_unchanged_reread,
                    f"{skill} must immediately reread the exact new draft before send",
                )

        representative_mutations = (
            (
                "gws-gmail-send",
                "--subject <subject> --body <body> --draft",
                "--subject <subject> --body <body>",
                "gws-gmail-send must always create a server-side draft first",
            ),
            (
                "gws-gmail-reply",
                "Validate the actual From\ncase-insensitively against `$expected_email`; validate actual To/CC/BCC,\n"
                "subject, reply thread context, and attachment names and count",
                "Validate the subject only",
                "gws-gmail-reply must validate authoritative draft envelope and attachment fields",
            ),
            (
                "gws-gmail-reply-all",
                "Validate decoded body content against\n"
                "the requested body and the expected helper-generated quotation of the source\n"
                "message.",
                "Trust the helper-generated body without decoding it.",
                "gws-gmail-reply-all must validate decoded draft body content",
            ),
            (
                "gws-gmail-forward",
                "canonical MIME content digest from each part path, lowercase MIME\n"
                "type, decoded byte length, and SHA-256 of its decoded bytes.",
                "a MIME summary without hashing decoded bytes.",
                "gws-gmail-forward must validate the canonical MIME content digest",
            ),
            (
                "gws-gmail-send",
                'print(json.dumps({"id": os.environ["DRAFT_ID"]}, separators=(",", ":")))\n',
                'print(json.dumps({"id": os.environ["DRAFT_ID"], "message": {}}, separators=(",", ":")))\n',
                "gws-gmail-send must send only the exact newly created draft ID",
            ),
            (
                "gws-gmail-reply",
                'isolated_gws gmail users drafts send --params \'{"userId":"me"}\' --json "$draft_send_body" || exit 1\n',
                'isolated_gws gmail users drafts send --params \'{"userId":"me","id":"guessed"}\' --json "$draft_send_body" || exit 1\n',
                "gws-gmail-reply must use the narrow exact raw drafts.send command",
            ),
            (
                "gws-gmail-forward",
                'isolated_gws gmail users drafts send --params \'{"userId":"me"}\' --json "$draft_send_body" || exit 1\n',
                'isolated_gws gmail users messages send --params \'{"userId":"me"}\' --json "$draft_send_body" || exit 1\n',
                "gws-gmail-forward must use the narrow exact raw drafts.send command",
            ),
            (
                "gws-gmail-reply-all",
                "Perform the final staged digest check,\n"
                "pass only the staged copy to gws, and cleanup on every exit. Never pass the\n"
                "mutable user-supplied path.\n",
                "Pass the mutable user-supplied path to gws.\n",
                "gws-gmail-reply-all must enforce staged attachment integrity",
            ),
        )

        for skill, before, after, expected_message in representative_mutations:
            relative_path = f"plugins/google-workspace-tools/skills/{skill}/SKILL.md"

            def mutate(
                root: Path,
                path: str = relative_path,
                old: str = before,
                new: str = after,
            ) -> None:
                self.replace_once(root, path, old, new)

            with self.subTest(skill=skill, expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)

    def test_setup_checker_rejects_google_workspace_contract_regressions(self) -> None:
        plugin_manifest = (
            "plugins/google-workspace-tools/.codex-plugin/plugin.json"
        )
        setup_script = "scripts/setup-codex-toolbox.sh"
        gws_setup = "scripts/setup-gws.sh"
        shared_skill = "plugins/google-workspace-tools/skills/gws-shared/SKILL.md"
        gmail_skill = "plugins/google-workspace-tools/skills/gws-gmail/SKILL.md"
        global_agents = "config/codex/AGENTS.global.md"

        def comment_out_default_install(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  "google-workspace-tools"\n',
                '  # "google-workspace-tools"\n',
            )

        def change_installer_version(root: Path) -> None:
            self.replace_once(root, gws_setup, 'VERSION="0.22.5"', 'VERSION="0.22.4"')

        def change_installer_asset(root: Path) -> None:
            self.replace_once(
                root,
                gws_setup,
                'ASSET="google-workspace-cli-aarch64-apple-darwin.tar.gz"',
                'ASSET="google-workspace-cli-x86_64-apple-darwin.tar.gz"',
            )

        def change_installer_checksum(root: Path) -> None:
            self.replace_once(
                root,
                gws_setup,
                'SHA256="1d2a9ffd5bc9b2c2c4b48630daf082fad13d9e57d741988a2c248eed562f7dac"',
                f'SHA256="{"0" * 64}"',
            )

        def remove_installer_sanitizer_scrub(root: Path) -> None:
            self.replace_once_in_region(
                root,
                gws_setup,
                '  if [ "$mode" = "imported_authorized_user" ]; then\n',
                "    return\n  fi\n",
                "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE \\\n",
                "",
            )

        def remove_provenance(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/PROVENANCE.md"
            self.assertTrue(path.is_file())
            path.unlink()

        def remove_license(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/LICENSE"
            self.assertTrue(path.is_file())
            path.unlink()

        def remove_explicit_alias_rule(root: Path) -> None:
            self.replace_once(
                root,
                shared_skill,
                "Require an **explicit alias**",
                "Choose an account alias",
            )

        def introduce_unsafe_default_account(root: Path) -> None:
            self.replace_once(
                root,
                shared_skill,
                "never infer one from a likely\ninbox, directory name, current login, or deadline",
                "use `account-one` by default when no alias is supplied",
            )

        def remove_adc_sentinel(root: Path) -> None:
            self.replace_once_in_region(
                root,
                gws_setup,
                '  if [ "$mode" = "imported_authorized_user" ]; then\n',
                "    return\n  fi\n",
                '    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
                "",
            )

        def remove_singular_credential_override_scrub(root: Path) -> None:
            self.replace_once_in_region(
                root,
                shared_skill,
                'if [ "$credential_mode" = "imported_authorized_user" ]; then\n',
                'elif [ "$credential_mode" = "encrypted_oauth" ]; then\n',
                "    -u GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE \\\n",
                "",
            )

        def add_extra_shared_scope(root: Path) -> None:
            self.replace_once(
                root,
                shared_skill,
                '        "https://www.googleapis.com/auth/userinfo.profile",\n',
                '        "https://www.googleapis.com/auth/userinfo.profile",\n'
                '        "https://www.googleapis.com/auth/calendar.readonly",\n',
            )

        def allow_permanent_delete(root: Path) -> None:
            self.replace_once(
                root,
                gmail_skill,
                "Do not invoke `users.messages.delete`,\n"
                "`users.messages.batchDelete`",
                "Invoke `users.messages.delete` or\n"
                "`users.messages.batchDelete` for permanent deletion",
            )

        def add_plugin_mcp_file(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/.mcp.json"
            self.assertFalse(path.exists())
            path.write_text('{"mcpServers": {"gws": {}}}\n', encoding="utf-8")

        def add_manifest_mcp_declaration(root: Path) -> None:
            self.rewrite_json(
                root,
                plugin_manifest,
                lambda manifest: manifest.update({"mcpServers": "./.mcp.json"}),
            )

        def add_manifest_app_declaration(root: Path) -> None:
            self.rewrite_json(
                root,
                plugin_manifest,
                lambda manifest: manifest.update({"apps": ["gmail"]}),
            )

        def manage_gws_mcp(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                "MANAGED_MCP_SERVERS=(\n",
                'MANAGED_MCP_SERVERS=(\n  "gws"\n',
            )

        def change_manifest_version(root: Path) -> None:
            self.rewrite_json(
                root,
                plugin_manifest,
                lambda manifest: manifest.update({"version": "0.1.0"}),
            )

        def remove_one_skill(root: Path) -> None:
            path = root / "plugins/google-workspace-tools/skills/gws-gmail-forward"
            self.assertTrue(path.is_dir())
            shutil.rmtree(path)

        def remove_marketplace_entry(root: Path) -> None:
            def change(marketplace: dict) -> None:
                marketplace["plugins"] = [
                    plugin
                    for plugin in marketplace["plugins"]
                    if plugin["name"] != "google-workspace-tools"
                ]

            self.rewrite_json(
                root,
                ".agents/plugins/marketplace.json",
                change,
            )

        def remove_direct_gws_routing(root: Path) -> None:
            self.replace_once(
                root,
                global_agents,
                "explicitly requests direct `gws` or multi-account Gmail",
                "requests Gmail access",
            )

        def remove_routing_alias_requirement(root: Path) -> None:
            self.replace_once(
                root,
                global_agents,
                "supplies an explicit account alias",
                "has a configured account",
            )

        def remove_one_surface_rule(root: Path) -> None:
            self.replace_once(
                root,
                global_agents,
                "Use exactly one Gmail surface per request",
                "Choose a Gmail surface when convenient",
            )

        def remove_official_connector_rule(root: Path) -> None:
            self.replace_once(
                root,
                global_agents,
                "Keep the official Gmail connector available",
                "Prefer direct gws for all Gmail work",
            )

        def remove_readme_status(root: Path) -> None:
            self.replace_once(
                root,
                "README.md",
                "not an officially supported Google product",
                "an officially supported Google product",
            )

        def remove_readme_oauth_scope(root: Path) -> None:
            self.replace_once(
                root,
                "README.md",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://mail.google.com/",
            )

        def remove_readme_identity_scope(root: Path) -> None:
            self.replace_once(
                root,
                "README.md",
                "`openid`, `userinfo.email`, and\n"
                "   `userinfo.profile`",
                "`openid` and `userinfo.email`",
            )

        def restore_healthy_only_reauth_wording(root: Path) -> None:
            self.replace_once(
                root,
                "README.md",
                "Reauthenticate an existing encrypted OAuth profile, including one with an\n"
                "expired or revoked token, without changing its expected identity",
                "Reauthenticate an existing healthy profile without changing its expected identity",
            )

        def make_readme_client_path_non_executable(root: Path) -> None:
            self.replace_once(
                root,
                "README.md",
                "/absolute/path/to/client_secret.json",
                "<downloaded-client.json>",
            )

        cases: tuple[tuple[Callable[[Path], None], str], ...] = (
            (
                comment_out_default_install,
                "setup script must install google-workspace-tools as an active default plugin",
            ),
            (
                change_installer_version,
                "setup-gws must pin gws version 0.22.5",
            ),
            (
                change_installer_asset,
                "setup-gws must pin the macOS arm64 release asset",
            ),
            (
                change_installer_checksum,
                "setup-gws must pin the expected release checksum",
            ),
            (
                remove_installer_sanitizer_scrub,
                "setup-gws must clear ambient GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE",
            ),
            (
                remove_provenance,
                "google-workspace-tools provenance must exist",
            ),
            (
                remove_license,
                "google-workspace-tools Apache-2.0 license must exist",
            ),
            (
                remove_explicit_alias_rule,
                "gws shared contract must require an explicit alias",
            ),
            (
                introduce_unsafe_default_account,
                "gws shared contract must reject default account inference",
            ),
            (
                remove_adc_sentinel,
                "setup-gws must block ambient ADC with a missing profile-local sentinel",
            ),
            (
                remove_singular_credential_override_scrub,
                "gws shared contract must clear ambient GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE",
            ),
            (
                add_extra_shared_scope,
                "gws shared required Gmail scope set must remain exactly four",
            ),
            (
                allow_permanent_delete,
                "gws Gmail contract must keep permanent deletion unavailable",
            ),
            (
                add_plugin_mcp_file,
                "google-workspace-tools must not define an MCP config file",
            ),
            (
                add_manifest_mcp_declaration,
                "google-workspace-tools manifest must not declare MCP servers",
            ),
            (
                add_manifest_app_declaration,
                "google-workspace-tools manifest must not declare apps",
            ),
            (
                manage_gws_mcp,
                "gws must not be a managed MCP server",
            ),
            (
                change_manifest_version,
                "google-workspace-tools manifest version must be 0.2.1",
            ),
            (
                remove_one_skill,
                "google-workspace-tools skills inventory must be exactly the eight Gmail skills",
            ),
            (
                remove_marketplace_entry,
                "marketplace must include google-workspace-tools",
            ),
            (
                remove_direct_gws_routing,
                "global AGENTS must route direct or multi-account Gmail to google-workspace-tools",
            ),
            (
                remove_routing_alias_requirement,
                "global AGENTS direct gws routing must require an explicit account alias",
            ),
            (
                remove_one_surface_rule,
                "global AGENTS Gmail routing must select exactly one surface per request",
            ),
            (
                remove_official_connector_rule,
                "global AGENTS must retain the official Gmail connector",
            ),
            (
                remove_readme_status,
                "README must state that gws is not an officially supported Google product",
            ),
            (
                remove_readme_oauth_scope,
                "README must require only the gmail.modify OAuth scope",
            ),
            (
                remove_readme_identity_scope,
                "README must document the three identity scopes added by gws v0.22.5",
            ),
            (
                restore_healthy_only_reauth_wording,
                "README must document repair reauthentication for unhealthy tokens",
            ),
            (
                make_readme_client_path_non_executable,
                "README must use an executable neutral OAuth client path",
            ),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)


if __name__ == "__main__":
    unittest.main()
