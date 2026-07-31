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
                '  GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
                "",
            )

        def remove_singular_credential_override_scrub(root: Path) -> None:
            self.replace_once(
                root,
                shared_skill,
                "    -u GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE \\\n",
                "",
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
                make_readme_client_path_non_executable,
                "README must use an executable neutral OAuth client path",
            ),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)


if __name__ == "__main__":
    unittest.main()
