from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "setup-codex-prerequisites.py"
SETUP = ROOT / "scripts" / "setup-codex-toolbox.sh"

SPEC = importlib.util.spec_from_file_location("setup_codex_prerequisites", HELPER)
assert SPEC and SPEC.loader
prerequisites = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prerequisites)


def executable(path: Path, body: str = 'printf "ok\\n"\n') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}")
    path.chmod(0o755)
    return path


def skill_environment(root: Path) -> tuple[dict[str, str], Path, Path]:
    codex_home = root / "codex-home"
    cc_switch_home = root / "cc-switch-home"
    (codex_home / "skills").mkdir(parents=True)
    (cc_switch_home / "skills").mkdir(parents=True)
    env = {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(codex_home),
        "CC_SWITCH_HOME": str(cc_switch_home),
    }
    return env, codex_home / "skills", cc_switch_home / "skills"


class SetupCodexPrerequisitesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_legacy_skill_install_is_idempotent_and_preserves_targets(self) -> None:
        env, codex_skills, cc_switch_skills = skill_environment(self.root)
        for name in prerequisites.LEGACY_SKILLS:
            target = cc_switch_skills / name
            target.mkdir()
            (target / "SKILL.md").write_text(name)
            (codex_skills / name).symlink_to(target)

        hatch_target = cc_switch_skills / "hatch-pet"
        hatch_target.mkdir()
        hatch_link = codex_skills / "hatch-pet"
        hatch_link.symlink_to(hatch_target)

        self.assertEqual(prerequisites.migrate_legacy_skills(install=True, env=env), 0)
        self.assertTrue(
            all(not (codex_skills / name).exists() for name in prerequisites.LEGACY_SKILLS)
        )
        self.assertTrue(
            all(
                (cc_switch_skills / name / "SKILL.md").read_text() == name
                for name in prerequisites.LEGACY_SKILLS
            )
        )
        self.assertTrue(hatch_link.is_symlink())
        self.assertTrue(hatch_target.is_dir())

        self.assertEqual(prerequisites.migrate_legacy_skills(install=True, env=env), 0)
        self.assertTrue(hatch_link.is_symlink())

    def test_legacy_skill_check_reports_pending_without_mutation(self) -> None:
        env, codex_skills, cc_switch_skills = skill_environment(self.root)
        target = cc_switch_skills / "chronicle"
        target.mkdir()
        link = codex_skills / "chronicle"
        link.symlink_to(target)

        self.assertEqual(prerequisites.migrate_legacy_skills(install=False, env=env), 1)
        self.assertTrue(link.is_symlink())

    def test_legacy_skill_migration_fails_closed_before_removal(self) -> None:
        for unexpected_kind in ("file", "alternate-link"):
            with self.subTest(unexpected_kind=unexpected_kind):
                case_root = self.root / unexpected_kind
                env, codex_skills, cc_switch_skills = skill_environment(case_root)
                valid_target = cc_switch_skills / "chronicle"
                valid_target.mkdir()
                valid_link = codex_skills / "chronicle"
                valid_link.symlink_to(valid_target)

                unexpected = codex_skills / "defuddle"
                if unexpected_kind == "file":
                    unexpected.write_text("user owned")
                else:
                    alternate = case_root / "alternate-defuddle"
                    alternate.mkdir()
                    unexpected.symlink_to(alternate)

                self.assertEqual(
                    prerequisites.migrate_legacy_skills(install=True, env=env), 2
                )
                self.assertTrue(valid_link.is_symlink())
                self.assertTrue(unexpected.exists() or unexpected.is_symlink())

    def test_ensure_rg_prefers_working_path_binary(self) -> None:
        path_rg = executable(self.root / "path-bin" / "rg")
        local_rg = executable(self.root / "local-bin" / "rg")
        env = {
            "HOME": str(self.root),
            "PATH": str(path_rg.parent),
            "CODEX_LOCAL_BIN_DIR": str(local_rg.parent),
        }

        self.assertEqual(prerequisites.find_working_rg(env=env), path_rg)
        self.assertEqual(prerequisites.ensure_rg(install=False, env=env), 0)

    def test_ensure_rg_uses_codex_local_bin_when_path_lacks_rg(self) -> None:
        local_rg = executable(self.root / "local-bin" / "rg")
        env = {
            "HOME": str(self.root),
            "PATH": str(self.root / "empty-bin"),
            "CODEX_LOCAL_BIN_DIR": str(local_rg.parent),
        }

        self.assertEqual(prerequisites.find_working_rg(env=env), local_rg)
        self.assertEqual(prerequisites.ensure_rg(install=False, env=env), 0)

    def test_ensure_rg_installs_with_brew_and_exposes_local_link(self) -> None:
        brew_log = self.root / "brew.log"
        formula = self.root / "formula"
        brewed_rg = executable(formula / "bin" / "rg")
        brew = executable(
            self.root / "brew-bin" / "brew",
            """case "$1" in
  --version) printf 'Homebrew test\\n' ;;
  install) printf '%s\\n' "$*" >> "$FAKE_BREW_LOG" ;;
  --prefix) printf '%s\\n' "$FAKE_RIPGREP_PREFIX" ;;
  *) exit 1 ;;
esac
""",
        )
        local_bin = self.root / "local-bin"
        env = {
            "HOME": str(self.root),
            "PATH": str(brew.parent),
            "CODEX_LOCAL_BIN_DIR": str(local_bin),
        }

        with mock.patch.dict(
            os.environ,
            {
                "FAKE_BREW_LOG": str(brew_log),
                "FAKE_RIPGREP_PREFIX": str(formula),
            },
        ):
            self.assertEqual(prerequisites.ensure_rg(install=True, env=env), 0)
            exposed = local_bin / "rg"
            self.assertTrue(exposed.is_symlink())
            self.assertEqual(exposed.resolve(), brewed_rg.resolve())
            self.assertEqual(brew_log.read_text().strip(), "install ripgrep")
            self.assertEqual(prerequisites.ensure_rg(install=True, env=env), 0)
            self.assertEqual(brew_log.read_text().splitlines(), ["install ripgrep"])

    def test_ensure_rg_fails_without_working_brew(self) -> None:
        env = {
            "HOME": str(self.root),
            "PATH": str(self.root / "empty-bin"),
            "CODEX_LOCAL_BIN_DIR": str(self.root / "local-bin"),
        }

        with mock.patch.object(prerequisites, "DEFAULT_BREW_BINARIES", ()):
            self.assertEqual(prerequisites.ensure_rg(install=True, env=env), 1)
        self.assertFalse((self.root / "local-bin" / "rg").exists())

    def test_resolve_codex_prefers_path_then_chatgpt_then_legacy(self) -> None:
        path_codex = executable(self.root / "path-bin" / "codex")
        chatgpt_codex = executable(self.root / "ChatGPT.app" / "codex")
        legacy_codex = executable(self.root / "Codex.app" / "codex")
        env = {"PATH": str(path_codex.parent), "HOME": str(self.root)}

        self.assertEqual(
            prerequisites.resolve_codex(
                env=env, chatgpt_codex=chatgpt_codex, legacy_codex=legacy_codex
            ),
            path_codex,
        )

        path_codex.write_text("#!/bin/sh\nexit 1\n")
        self.assertEqual(
            prerequisites.resolve_codex(
                env=env, chatgpt_codex=chatgpt_codex, legacy_codex=legacy_codex
            ),
            chatgpt_codex,
        )

        chatgpt_codex.write_text("#!/bin/sh\nexit 1\n")
        self.assertEqual(
            prerequisites.resolve_codex(
                env=env, chatgpt_codex=chatgpt_codex, legacy_codex=legacy_codex
            ),
            legacy_codex,
        )

    def test_resolve_codex_returns_none_when_every_candidate_is_invalid(self) -> None:
        env = {"PATH": str(self.root / "empty-bin"), "HOME": str(self.root)}
        self.assertIsNone(
            prerequisites.resolve_codex(
                env=env,
                chatgpt_codex=self.root / "missing-chatgpt",
                legacy_codex=self.root / "missing-legacy",
            )
        )

    def test_setup_inspects_migration_before_mutating_prerequisites(self) -> None:
        source = SETUP.read_text()
        legacy_call = 'python3 "$PREREQUISITES" legacy-skills --install'
        rg_call = 'python3 "$PREREQUISITES" ensure-rg --install'
        resolve_call = 'python3 "$PREREQUISITES" resolve-codex'
        migration_check = 'python3 "$ROOT/scripts/migrate_visual_communication.py" --check-setup'

        self.assertLess(source.index(resolve_call), source.index(migration_check))
        self.assertLess(source.index(migration_check), source.index(legacy_call))
        self.assertLess(source.index(legacy_call), source.index(rg_call))
        self.assertIn('"$ROOT/scripts/sync-agents.sh" --install', source)
        self.assertLess(
            source.index(rg_call),
            source.index('"$ROOT/scripts/sync-agents.sh" --install'),
        )

    def test_setup_stops_before_prerequisite_mutations_when_family_is_blocked(self) -> None:
        self.assert_migration_wrapper((), "--check-setup", 2)

    def test_explicit_family_modes_exit_without_running_normal_setup(self) -> None:
        for option, action in (("--migration-plan", "--plan"), ("--migrate", "--apply")):
            with self.subTest(option=option):
                self.assert_migration_wrapper((option, "visual-communication"), action, 0)

    def assert_migration_wrapper(self, arguments: tuple[str, ...], action: str, expected_code: int) -> None:
        command_log = self.root / "migration-wrapper.log"
        command_log.write_text("")
        fake_codex = executable(self.root / "bin/codex")
        executable(self.root / "bin/python3", '''
printf '%s\\n' "$*" >> "$MIGRATION_TEST_LOG"
case "$1:$2" in
  */setup-codex-prerequisites.py:resolve-codex) printf '%s\\n' "$MIGRATION_TEST_CODEX" ;;
  */migrate_visual_communication.py:--check-setup) exit 2 ;;
  */migrate_visual_communication.py:--plan|*/migrate_visual_communication.py:--apply) printf '{}\\n' ;;
  *) exit 99 ;;
esac
''')
        environment = {"HOME": str(self.root), "CODEX_HOME": str(self.root / "codex-home"),
                       "PATH": str(fake_codex.parent) + ":/usr/bin:/bin",
                       "MIGRATION_TEST_LOG": str(command_log), "MIGRATION_TEST_CODEX": str(fake_codex)}
        result = subprocess.run(["/bin/bash", str(SETUP), *arguments], env=environment,
                                text=True, capture_output=True, check=False, timeout=10)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        calls = command_log.read_text().splitlines()
        self.assertEqual(len(calls), 2, calls)
        self.assertIn("setup-codex-prerequisites.py resolve-codex", calls[0])
        self.assertIn("migrate_visual_communication.py " + action, calls[1])
        self.assertFalse((self.root / "codex-home").exists())

    def test_codex_app_fallback_constants_are_current_then_legacy(self) -> None:
        self.assertEqual(
            prerequisites.CHATGPT_CODEX,
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
        )
        self.assertEqual(
            prerequisites.LEGACY_CODEX,
            Path("/Applications/Codex.app/Contents/Resources/codex"),
        )


if __name__ == "__main__":
    unittest.main()
