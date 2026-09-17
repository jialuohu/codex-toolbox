import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/omnigraffle/compile_latexit_probe.py"
SPEC = importlib.util.spec_from_file_location("latexit_compile_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class CompileProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "source.zip"
        self.output = self.root / "output"
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, extra=None, licenses=True):
        with zipfile.ZipFile(self.archive, "w") as zipped:
            for name in ("LatexitEquation.m", "LaTeXProcessor.m", "LaTeXiT_Prefix.pch"):
                zipped.writestr("LaTeXiT-mainline/" + name, "/* compilation fixture */\n")
            if licenses:
                for name in probe.LICENSE_PATHS.values():
                    zipped.writestr(name, "upstream license fixture\n")
            if extra:
                zipped.writestr(*extra)
        return patch.object(probe, "SOURCE_SHA256", hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def runner(self, command, **kwargs):
        self.assertEqual(kwargs["timeout"], 60)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertTrue(set(kwargs["env"]) <= {"PATH", "HOME", "TMPDIR", "DEVELOPER_DIR", "LANG", "LC_ALL"})
        if command == ["/usr/bin/xcrun", "--show-sdk-path"]:
            return subprocess.CompletedProcess(command, 0, str(self.sdk) + "\n", "")
        self.assertEqual(command[:3], ["/usr/bin/xcrun", "clang", "-c"])
        self.assertIn("-isysroot", command)
        Path(command[-1]).write_bytes(b"object fixture")
        return subprocess.CompletedProcess(command, 0, "", "warning fixture")

    def test_hash_rejection_creates_nothing(self):
        self.fixture()
        report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("SHA-256", report["error"])
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_touched(self):
        self.output.mkdir()
        sentinel = self.output / "preserve"
        sentinel.write_text("original")
        with self.fixture():
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "original")

    def test_app_and_repository_outputs_rejected(self):
        app = self.root / "Example.app"
        app.mkdir()
        with self.fixture():
            for output in (app / "output", probe.REPO_ROOT / "probe-output"):
                report = probe.probe(self.archive, output, self.runner)
                self.assertEqual(report["status"], "blocked")
                self.assertFalse(output.exists())

    def test_output_symlink_is_not_followed(self):
        destination = self.root / "preserved"
        destination.mkdir()
        self.output.symlink_to(destination, target_is_directory=True)
        with self.fixture():
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(list(destination.iterdir()), [])

    def test_zip_traversal_rejected_before_output_creation(self):
        with self.fixture(("../outside", "bad")):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_escaping_archive_links_are_rejected(self):
        link = zipfile.ZipInfo("LaTeXiT-mainline/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.fixture((link, "../../elsewhere")):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(self.output.exists())

    def test_contained_framework_links_are_retained(self):
        link = zipfile.ZipInfo("LaTeXiT-mainline/source-alias")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.fixture((link, "LatexitEquation.m")):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "compiled_translation_units")
        alias = self.output / "upstream/LaTeXiT-mainline/source-alias"
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.read_text(), "/* compilation fixture */\n")

    def test_archive_cannot_write_through_link_ancestor(self):
        link = zipfile.ZipInfo("LaTeXiT-mainline/alias")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.fixture((link, "target"))
        with zipfile.ZipFile(self.archive, "a") as zipped:
            zipped.writestr("LaTeXiT-mainline/alias/unexpected", "bad")
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with patch.object(probe, "SOURCE_SHA256", digest):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("write through", report["error"])
        self.assertFalse(self.output.exists())

    def test_compile_evidence_never_claims_native_acceptance(self):
        with self.fixture():
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "compiled_translation_units")
        self.assertTrue(report["compiler_only"])
        for key in ("rendering_verified", "linkback_verified", "native_acceptance_passed"):
            self.assertFalse(report[key])
        self.assertEqual(len(report["compilations"]), 2)
        self.assertEqual(json.loads((self.output / "evidence.json").read_text()), report)

    def test_compiler_failure_and_timeout_remain_failures(self):
        def failure(command, **kwargs):
            if command == ["/usr/bin/xcrun", "--show-sdk-path"]:
                return self.runner(command, **kwargs)
            if "LatexitEquation.m" in command:
                return subprocess.CompletedProcess(command, 1, "", "compile failed")
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with self.fixture():
            report = probe.probe(self.archive, self.output, failure)
        self.assertEqual(report["status"], "compiler_failed")
        self.assertEqual([item["exit_code"] for item in report["compilations"]], [1, None])
        self.assertFalse(report["native_acceptance_passed"])

    def test_decompression_limit_rejected_before_output_creation(self):
        with self.fixture(), patch.object(probe, "MAX_EXPANDED_BYTES", 1):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(self.output.exists())

    def test_compiler_environment_is_restricted(self):
        with self.fixture(), patch.dict(os.environ, {"CPATH": "unexpected", "DYLD_INSERT_LIBRARIES": "unexpected", "CCC_OVERRIDE_OPTIONS": "unexpected"}):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "compiled_translation_units")

    def test_disallowed_compression_rejected_before_creation(self):
        entry = zipfile.ZipInfo("LaTeXiT-mainline/compressed")
        entry.compress_type = zipfile.ZIP_BZIP2
        with self.fixture((entry, "compressed fixture")):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("compression", report["error"])
        self.assertFalse(self.output.exists())

    def test_missing_license_rejected_before_creation(self):
        with self.fixture(licenses=False):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("license", report["error"])
        self.assertFalse(self.output.exists())

    def test_failed_extraction_is_preserved_and_reported(self):
        original_open = Path.open

        def fail_second_source(path, *args, **kwargs):
            if path.name == "LaTeXProcessor.m" and args == ("xb",):
                raise OSError("fixture extraction write failure")
            return original_open(path, *args, **kwargs)

        with self.fixture(), patch.object(Path, "open", fail_second_source):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["partial_extraction"])
        self.assertTrue((self.output / "upstream/LaTeXiT-mainline/LatexitEquation.m").is_file())
        self.assertTrue((self.output / "evidence.json").is_file())

    def test_evidence_write_failure_returns_blocked_report(self):
        original_write = Path.write_text

        def fail_evidence(path, *args, **kwargs):
            if path.name == "evidence.json":
                raise OSError("fixture evidence write failure")
            return original_write(path, *args, **kwargs)

        with self.fixture(), patch.object(Path, "write_text", fail_evidence):
            report = probe.probe(self.archive, self.output, self.runner)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("evidence_write_error", report)
        self.assertFalse(report["partial_extraction"])
        self.assertFalse(report["native_acceptance_passed"])
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
