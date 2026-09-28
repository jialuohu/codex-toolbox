import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
AUDIT_SCRIPT = REPO_ROOT / "scripts/privacy-audit.sh"
PRIVATE_PATH = "/" + "Users" + "/fixture/private-project"
HOME_SECRET_REFERENCE = "$HOME/" + ".codex" + "/secrets"
BRACED_HOME_SECRET_REFERENCE = "${HOME}/" + ".codex" + "/secrets"


class PrivacyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(AUDIT_SCRIPT, self.root / "scripts/privacy-audit.sh")
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.root,
            check=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative_path, content):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self):
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Privacy Test", "-c",
             "user.email=privacy@example.invalid", "commit", "-qm", "fixture"],
            cwd=self.root, check=True,
        )

    def run_audit(self, *, mode="current", path=None):
        env = None
        if path is not None:
            env = os.environ.copy()
            env["PATH"] = path
        return subprocess.run(
            [shutil.which("bash"), "scripts/privacy-audit.sh", mode],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_current_ignores_git_metadata_and_gitignored_local_artifacts(self):
        self.write(
            ".gitignore",
            ".worktrees/\n.superpowers/\n.env\n",
        )
        self.write("safe.txt", "safe public content\n")
        subprocess.run(
            ["git", "add", ".gitignore", "safe.txt", "scripts/privacy-audit.sh"],
            cwd=self.root,
            check=True,
        )

        self.write(".git/worktrees/fixture/gitdir", PRIVATE_PATH + "\n")
        self.write(".worktrees/feature/private.md", PRIVATE_PATH + "\n")
        self.write(".superpowers/sdd/private.md", PRIVATE_PATH + "\n")
        self.write(".env", "PRIVATE_PATH=" + PRIVATE_PATH + "\n")

        result = self.run_audit()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Privacy audit found no matches", result.stdout)

    def test_current_scans_tracked_files(self):
        self.write("tracked.txt", PRIVATE_PATH + "\n")
        subprocess.run(
            ["git", "add", "tracked.txt", "scripts/privacy-audit.sh"],
            cwd=self.root,
            check=True,
        )

        result = self.run_audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("tracked.txt", result.stdout)
        self.assertIn("Privacy audit found matches", result.stderr)

    def test_current_scans_nonignored_untracked_files(self):
        self.write("untracked.txt", PRIVATE_PATH + "\n")
        subprocess.run(
            ["git", "add", "scripts/privacy-audit.sh"],
            cwd=self.root,
            check=True,
        )

        result = self.run_audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("untracked.txt", result.stdout)
        self.assertIn("Privacy audit found matches", result.stderr)

    def test_current_scans_untracked_files_without_ripgrep(self):
        self.write("untracked.txt", PRIVATE_PATH + "\n")
        subprocess.run(
            ["git", "add", "scripts/privacy-audit.sh"],
            cwd=self.root,
            check=True,
        )
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(shutil.which("git"))

        result = self.run_audit(path=str(bin_dir))

        self.assertEqual(result.returncode, 1)
        self.assertIn("untracked.txt", result.stdout)
        self.assertIn("Privacy audit found matches", result.stderr)

    def test_current_fails_closed_when_untracked_scan_errors(self):
        self.write("untracked.txt", "safe public content\n")
        subprocess.run(
            ["git", "add", "scripts/privacy-audit.sh"],
            cwd=self.root,
            check=True,
        )
        git_path = shutil.which("git")
        git_wrapper = self.write(
            "bin/git",
            "#!/bin/sh\n"
            'if [ "$1" = "grep" ] && [ "$2" = "--no-index" ]; then\n'
            "  exit 2\n"
            "fi\n"
            f'exec "{git_path}" "$@"\n',
        )
        git_wrapper.chmod(0o755)
        subprocess.run(
            [git_path, "add", "bin/git"],
            cwd=self.root,
            check=True,
        )

        result = self.run_audit(path=str(git_wrapper.parent))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Privacy audit could not scan untracked file: untracked.txt",
            result.stderr,
        )

    def test_home_relative_configuration_references_pass_all_modes(self):
        self.write(
            "tracked.sh",
            'secrets_dir="${CODEX_SECRETS_DIR:-' + HOME_SECRET_REFERENCE + '}"\n'
            'source "' + BRACED_HOME_SECRET_REFERENCE + '/example.env"\n'
            + HOME_SECRET_REFERENCE + "\n",
        )
        self.commit()
        self.write("untracked.md", HOME_SECRET_REFERENCE + "\n"
                   + "Use `" + HOME_SECRET_REFERENCE + "`.\n")

        for mode in ("current", "history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_configuration_reference_does_not_hide_adjacent_leaks(self):
        leaks = (
            PRIVATE_PATH,
            "/" + "home" + "/fixture/private-project",
            ".codex" + "/secrets/example.env",
            "api_key=" + "a" * 24,
            "ghp_" + "a" * 24,
        )
        for leak in leaks:
            with self.subTest(leak=leak):
                self.write("untracked.txt", HOME_SECRET_REFERENCE + " " + leak + "\n")
                result = self.run_audit()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("untracked.txt", result.stdout)
                self.assertIn(leak, result.stdout)

    def test_similar_names_and_malformed_configuration_references_still_fail(self):
        references = (
            HOME_SECRET_REFERENCE + "-backup",
            HOME_SECRET_REFERENCE + "_private",
            HOME_SECRET_REFERENCE + "suffix",
            "token" + HOME_SECRET_REFERENCE,
            "token:" + HOME_SECRET_REFERENCE,
            "x:1:" + HOME_SECRET_REFERENCE,
            '"token' + HOME_SECRET_REFERENCE + '"',
        )
        for reference in references:
            with self.subTest(reference=reference):
                self.write("untracked.txt", reference + "\n")
                result = self.run_audit()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(reference, result.stdout)

    def test_forged_location_prefix_is_rejected_in_tracked_and_history_content(self):
        content = "x:1:" + HOME_SECRET_REFERENCE
        self.write("tracked.txt", content + "\n")
        self.commit()
        for mode in ("current", "history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(content, result.stdout)

    def test_ambiguous_colon_filename_does_not_exempt_candidate(self):
        content = HOME_SECRET_REFERENCE
        self.write("ambiguous:1:filename.txt", content + "\n")
        self.commit()
        for mode in ("current", "history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("ambiguous:1:filename.txt", result.stdout)

    def test_literal_home_path_remains_private(self):
        literal_path = PRIVATE_PATH + "/" + ".codex" + "/secrets"
        self.write("tracked.txt", literal_path + "\n")
        self.commit()
        for mode in ("current", "history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(literal_path, result.stdout)

    def test_history_still_detects_removed_leak_beside_configuration_reference(self):
        self.write("tracked.txt", HOME_SECRET_REFERENCE + " " + PRIVATE_PATH + "\n")
        self.commit()
        self.write("tracked.txt", HOME_SECRET_REFERENCE + "\n")
        self.commit()

        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for mode in ("history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(PRIVATE_PATH, result.stdout)

    def test_tracked_and_history_scan_errors_fail_closed(self):
        self.write("safe.txt", HOME_SECRET_REFERENCE + "\n")
        self.commit()
        git_path = shutil.which("git")
        wrapper = self.write(
            "bin/git",
            '#!/bin/sh\nif [ "$1" = "grep" ]; then exit 2; fi\n'
            f'exec "{git_path}" "$@"\n',
        )
        wrapper.chmod(0o755)
        for mode in ("current", "history", "all"):
            with self.subTest(mode=mode):
                result = self.run_audit(mode=mode, path=str(wrapper.parent))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Privacy audit could not scan", result.stderr)

    def test_enumeration_errors_fail_closed(self):
        self.write("safe.txt", HOME_SECRET_REFERENCE + "\n")
        self.commit()
        git_path = shutil.which("git")
        for operation, modes in (
            ("ls-files", ("current", "all")),
            ("rev-list", ("history", "all")),
        ):
            wrapper = self.write(
                "bin/git",
                f'#!/bin/sh\nif [ "$1" = "{operation}" ]; then exit 2; fi\n'
                f'exec "{git_path}" "$@"\n',
            )
            wrapper.chmod(0o755)
            for mode in modes:
                with self.subTest(operation=operation, mode=mode):
                    result = self.run_audit(mode=mode, path=str(wrapper.parent))
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("Privacy audit could not enumerate", result.stderr)


if __name__ == "__main__":
    unittest.main()
