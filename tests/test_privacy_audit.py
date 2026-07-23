import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
AUDIT_SCRIPT = REPO_ROOT / "scripts/privacy-audit.sh"
PRIVATE_PATH = "/" + "Users" + "/fixture/private-project"


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

    def run_audit(self):
        return subprocess.run(
            ["bash", "scripts/privacy-audit.sh", "current"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
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


if __name__ == "__main__":
    unittest.main()
