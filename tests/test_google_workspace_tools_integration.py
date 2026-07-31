from __future__ import annotations

import json
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
                '[ -f "$gws_bin" ] && [ ! -L "$gws_bin" ] && [ -x "$gws_bin" ] || exit 1\n',
                "gws shared runtime must require a regular non-symlink executable",
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
                "gws shared runtime must clear ambient GOOGLE_WORKSPACE_PROJECT_ID",
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
                "gws shared runtime must reject duplicate or extra scopes",
            ),
            (
                "and set(scopes) == required_scopes\n",
                "gws shared runtime must require the exact scope set",
            ),
            (
                "There is no same-request Gmail connector fallback. Fail closed.\n",
                "gws shared runtime must forbid same-request connector fallback",
            ),
        )

        for removed_line, expected_message in mutations:
            def mutate(root: Path, line: str = removed_line) -> None:
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
                '  if ! run_isolated "$candidate" auth login --scopes "$GMAIL_SCOPE"; then\n'
                '    die "OAuth login failed; candidate profile will be removed"\n',
                '  if ! "$GWS_BIN" auth login --scopes "$GMAIL_SCOPE"; then\n'
                '    die "OAuth login failed; candidate profile will be removed"\n',
            )

        def make_post_login_health_check_dead(root: Path) -> None:
            self.replace_once(
                root,
                setup_script,
                '  if ! check_profile_health "$candidate" "$email" "$alias"; then\n'
                '    die "OAuth login identity check failed; candidate profile will be removed"\n',
                '  if false && ! check_profile_health "$candidate" "$email" "$alias"; then\n'
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
                "setup-gws profile manager must match the canonical reviewed text",
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
            self.replace_once(
                root,
                gws_setup,
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
            self.replace_once(
                root,
                gws_setup,
                '    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
                "",
            )

        def remove_singular_credential_override_scrub(root: Path) -> None:
            self.replace_once(
                root,
                shared_skill,
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
                lambda manifest: manifest.update({"version": "0.2.0"}),
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
                "Reauthenticate an existing profile, including one with an expired or revoked\n"
                "token, without changing its expected identity",
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
                "gws-shared security contract must match the canonical reviewed text",
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
                manage_gws_mcp,
                "gws must not be a managed MCP server",
            ),
            (
                change_manifest_version,
                "google-workspace-tools manifest version must be 0.1.0",
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
