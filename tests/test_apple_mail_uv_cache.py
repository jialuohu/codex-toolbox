"""Real, offline uv regression for refreshed immutable plugin sources."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "plugins/apple-mail-tools/server"
SPEC = importlib.util.spec_from_file_location(
    "cache_test_stamp", SERVER / "src/apple_mail_tools/runtime_stamp.py"
)
STAMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAMP)


@unittest.skipUnless(shutil.which("uv"), "real uv required for offline cache regression")
class AppleMailUvCacheTests(unittest.TestCase):
    def test_timestamp_refresh_passes_but_content_change_fails_strict_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            package = project / "src/fixture"
            package.mkdir(parents=True)
            (project / "scripts").mkdir()
            for name in ("apple-mail-mcp", "mail_bridge.applescript"):
                (project / "scripts" / name).write_text("fixture\n")
            source = package / "__init__.py"
            source.write_text("VALUE = 1\n")
            # Use the production cache-key configuration with a tiny local wheel
            # backend: no downloaded build requirements or account access.
            import tomllib
            settings = tomllib.loads((SERVER / "pyproject.toml").read_text())
            self.assertEqual(settings["tool"]["uv"]["cache-keys"],
                             [{"env": "APPLE_MAIL_RUNTIME_FINGERPRINT"}])
            pyproject = project / "pyproject.toml"
            pyproject.write_text('''[build-system]
requires = []
build-backend = "backend"
backend-path = ["."]
[project]
name = "fixture"
version = "1.0.0"
[tool.uv]
cache-keys = [{env = "APPLE_MAIL_RUNTIME_FINGERPRINT"}]
''')
            (project / "backend.py").write_text('''from pathlib import Path
from zipfile import ZipFile
def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name = "fixture-1.0.0-py3-none-any.whl"
    with ZipFile(Path(wheel_directory) / name, "w") as archive:
        archive.writestr("fixture/__init__.py", Path("src/fixture/__init__.py").read_bytes())
        archive.writestr("fixture-1.0.0.dist-info/METADATA", "Metadata-Version: 2.1\\nName: fixture\\nVersion: 1.0.0\\n")
        archive.writestr("fixture-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nGenerator: fixture\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")
        archive.writestr("fixture-1.0.0.dist-info/RECORD", "")
    return name
''')
            env = os.environ.copy()
            env.update(UV_PROJECT_ENVIRONMENT=str(root / "runtime"),
                       UV_CACHE_DIR=str(root / "cache"), UV_PYTHON_DOWNLOADS="never")
            def run(*args):
                return subprocess.run([shutil.which("uv"), *args, "--offline",
                                       "--directory", str(project)], env=env,
                                      capture_output=True, text=True, timeout=30)
            result = run("lock", "--python", sys.executable)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = STAMP.fingerprint(project)
            env["APPLE_MAIL_RUNTIME_FINGERPRINT"] = original
            result = run("sync", "--python", sys.executable, "--frozen", "--no-dev", "--no-editable")
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = next((root / "runtime").rglob("site-packages/fixture/__init__.py"))
            installed_before = installed.read_bytes()
            for path in (pyproject, source):
                timestamp = path.stat().st_mtime + 30
                contents = path.read_bytes()
                path.unlink()
                path.write_bytes(contents)
                os.utime(path, (timestamp, timestamp))
            self.assertEqual(STAMP.fingerprint(project), original)
            result = run("sync", "--frozen", "--check", "--no-dev", "--no-editable")
            self.assertEqual(result.returncode, 0, result.stderr)
            source.write_text("VALUE = 2\n")
            env["APPLE_MAIL_RUNTIME_FINGERPRINT"] = STAMP.fingerprint(project)
            self.assertNotEqual(env["APPLE_MAIL_RUNTIME_FINGERPRINT"], original)
            result = run("sync", "--frozen", "--check", "--no-dev", "--no-editable")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(installed.read_bytes(), installed_before)


if __name__ == "__main__":
    unittest.main()
