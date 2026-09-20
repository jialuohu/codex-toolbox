"""Offline boundary and installation tests for the optional HTML publisher."""
import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/diagram-tools/skills/diagram-publish/scripts/diagram_publish.py"
SPEC = importlib.util.spec_from_file_location("diagram_publish_security", SCRIPT)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class PublisherSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "codex"
        self.env = {"CODEX_HOME": str(self.home), "PATH": os.environ["PATH"]}
        self.network = []

        def no_network(*args, **kwargs):
            self.network.append(args)
            raise AssertionError("unexpected network")

        self.pub = publisher.Publisher(env=self.env, transport=no_network, sleep=lambda _: None)
        self.html = self.base / "accepted.html"
        self.html.write_text('<!doctype html><html><body><svg><use href="#node"/></svg></body></html>')
        self.sha = publisher.digest(self.html.read_bytes())

    def configured(self, mode="auto"):
        publisher.private_dir(self.pub.root)
        self.pub.secrets_root.mkdir(parents=True, mode=0o700)
        self.token_path = self.pub.secrets_root / "pages-token"
        self.token_path.write_text("test" * 12)
        self.token_path.chmod(0o600)
        self.config = {"schema_version": 1, "account_id": "a" * 32,
                       "project_name": "codex-diagrams-" + "b" * 16,
                       "project_id": "test-project", "production_branch": "main",
                       "mode": mode, "token_file": str(self.token_path)}
        publisher.write_json(self.pub.config_path, self.config)
        self.pub.runtime_status = lambda: "ready"
        self.pub.node = lambda: "/fake/node"

    def test_status_and_list_do_not_create_state_or_use_network(self):
        self.assertEqual(self.pub.status()["status"], "unconfigured")
        self.assertEqual(self.pub.list_publications()["publications"], [])
        self.assertFalse(self.home.exists())
        self.assertFalse(self.network)

    def test_unconfigured_local_only_and_ci_never_upload(self):
        self.assertEqual(self.pub.publish(self.html, self.sha, reviewed=True)["status"], "publishing_disabled")
        self.configured()
        self.assertEqual(self.pub.publish(self.html, self.sha, local_only=True)["status"], "local_only")
        self.pub.env["CI"] = "true"
        self.assertEqual(self.pub.publish(self.html, self.sha, reviewed=True)["status"], "local_only")
        self.pub.env.pop("CI")
        self.pub.env["CODEX_TOOLBOX_NO_PUBLISH"] = "1"
        self.assertEqual(self.pub.publish(self.html, self.sha, reviewed=True)["status"], "local_only")
        self.assertFalse(self.network)

    def test_off_and_malformed_config_do_not_upload(self):
        self.configured(mode="off")
        self.assertEqual(self.pub.publish(self.html, self.sha, reviewed=True)["status"], "publishing_disabled")
        self.pub.config_path.write_text("{broken")
        self.assertEqual(self.pub.status()["mode"], "off")
        with self.assertRaises(publisher.PublishError):
            self.pub.publish(self.html, self.sha, reviewed=True)
        self.assertFalse(self.network)

    def test_review_and_exact_hash_are_required_before_network(self):
        self.configured()
        with self.assertRaisesRegex(publisher.PublishError, "visual_review_required"):
            self.pub.publish(self.html, self.sha)
        self.html.write_text("<html>changed</html>")
        with self.assertRaisesRegex(publisher.PublishError, "artifact_hash_changed"):
            self.pub.publish(self.html, self.sha, reviewed=True)
        self.assertFalse(self.network)

    def test_disable_before_lock_acquisition_prevents_upload(self):
        self.configured()

        @contextmanager
        def concurrent_disable():
            publisher.write_json(self.pub.config_path, {**self.config, "mode": "off"})
            yield

        self.pub.lock = concurrent_disable
        self.assertEqual(self.pub.publish(self.html, self.sha, reviewed=True)["status"], "publishing_disabled")
        self.assertFalse(self.network)

    def test_symlink_input_and_private_state_refused(self):
        linked = self.base / "linked.html"
        linked.symlink_to(self.html)
        with self.assertRaises(publisher.PublishError):
            publisher.accepted_html(linked, self.sha)
        self.configured()
        self.pub.config_path.chmod(0o644)
        self.assertFalse(self.pub.status()["ok"])
        self.pub.config_path.chmod(0o600)
        original = self.pub.root.rename(self.home / "moved")
        self.pub.root.symlink_to(original)
        self.assertFalse(self.pub.status()["ok"])

    def test_missing_token_does_not_fall_back_to_ambient_auth(self):
        self.configured()
        self.token_path.unlink()
        self.pub.env.update({"CLOUDFLARE_API_TOKEN": "ambient" * 8, "CLOUDFLARE_ACCOUNT_ID": "f" * 32})
        with self.assertRaises(publisher.PublishError):
            self.pub.publish(self.html, self.sha, reviewed=True)
        self.assertFalse(self.network)

    def test_token_boundary_permissions_and_symlink(self):
        self.configured()
        self.assertEqual(self.pub.token(self.token_path), "test" * 12)
        self.token_path.chmod(0o644)
        with self.assertRaisesRegex(publisher.PublishError, "unsafe_private_file"):
            self.pub.token(self.token_path)
        self.token_path.chmod(0o600)
        outside = self.base / "outside-token"
        outside.write_text("test" * 12)
        outside.chmod(0o600)
        with self.assertRaisesRegex(publisher.PublishError, "token_outside"):
            self.pub.token(outside)
        alias = self.pub.secrets_root / "alias"
        alias.symlink_to(self.token_path)
        with self.assertRaises(publisher.PublishError):
            self.pub.token(alias)

    def test_resource_urls_and_css_are_checked(self):
        for reference in ('<img src="relative.png">', '<a href="file:///private/tmp/example">x</a>',
                          '<img src="&#102;ile:///tmp/example">', '<style>x{background:url(local.png)}</style>',
                          '<style>@import "local.css";</style>', '<iframe srcdoc="local"></iframe>',
                          '<img src="http://localhost/image">', '<img src="http://localhost./image">',
                          '<img src="http://127.0.0.2/image">', '<img src="http://127.1/image">',
                          '<img src="http://192.168.1.1/image">', '<img src="http://[::1]/image">',
                          '<img src="%68ttps://example.com/image">', '<a href="%23local">link</a>',
                          '<meta http-equiv="refresh" content="0;url=file:///tmp/example">'):
            with self.subTest(reference=reference):
                self.html.write_text("<html>" + reference + "</html>")
                with self.assertRaises(publisher.PublishError):
                    publisher.accepted_html(self.html, publisher.digest(self.html.read_bytes()))
        self.html.write_text('<html><link href="https://fonts.googleapis.com/css2?family=Mono"><style>svg{fill:url(#x)}</style></html>')
        data = self.html.read_bytes()
        self.assertEqual(publisher.accepted_html(self.html, publisher.digest(data)), data)

    def test_javascript_css_generator_is_not_parsed_as_stylesheet(self):
        self.html.write_text('<html><script>const marker = "url(${reference})";</script></html>')
        data = self.html.read_bytes()
        self.assertEqual(publisher.accepted_html(self.html, publisher.digest(data)), data)

    def test_oversized_html_rejected(self):
        with patch.object(publisher, "MAX_HTML", 8):
            with self.assertRaisesRegex(publisher.PublishError, "oversized"):
                publisher.accepted_html(self.html, self.sha)

    def test_one_process_holds_operation_lock(self):
        with self.pub.lock():
            with self.assertRaisesRegex(publisher.PublishError, "operation_in_progress"):
                with self.pub.lock():
                    self.fail("second writer acquired lock")
        with self.pub.lock():
            pass

    def test_upload_stages_only_two_files_and_scrubs_environment(self):
        self.configured()
        self.pub.env.update({"NODE_OPTIONS": "untrusted", "CLOUDFLARE_API_TOKEN": "ambient", "GIT_DIR": "untrusted"})
        (self.base / "private.json").write_text("private")
        observed = []

        def runner(argv, **kwargs):
            observed.append(kwargs["cwd"])
            stage = Path(argv[4])
            self.assertEqual({p.name for p in stage.iterdir()}, {"index.html", "_headers"})
            self.assertEqual((stage / "index.html").read_bytes(), self.html.read_bytes())
            child = kwargs["env"]
            self.assertEqual(child["CLOUDFLARE_API_TOKEN"], "test" * 12)
            self.assertNotIn("NODE_OPTIONS", child)
            self.assertNotIn("GIT_DIR", child)
            self.assertEqual(child["CI"], "true")
            self.assertNotEqual(child["HOME"], str(Path.home()))
            self.assertNotIn("test" * 12, " ".join(argv))
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            return subprocess.CompletedProcess(argv, 0)

        self.pub.runner = runner
        self.pub.run_upload(self.config, "test" * 12, {"branch": "diagram-" + "d" * 32, "sha256": self.sha}, self.html.read_bytes())
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].exists())

    def test_project_identity_and_branch_drift_refused(self):
        self.configured()
        valid = {"id": self.config["project_id"], "name": self.config["project_name"], "production_branch": "main"}
        for update in ({"id": "other"}, {"name": "other"}, {"production_branch": "other"}, {"source": {"type": "github"}}, {"uses_functions": True}):
            with self.subTest(update=update):
                self.pub.api = lambda *a, **kw: {**valid, **update}
                with self.assertRaises(publisher.PublishError):
                    self.pub.project(self.config, "test" * 12)

    def test_url_validation_prevents_arbitrary_fetch(self):
        self.configured()
        for url in ("http://example.test", "https://localhost/", "https://example.test/", "https://user:password@example.test/"):
            with self.assertRaises(publisher.PublishError):
                self.pub.deployment_url(url, self.config)
        url = "https://abc123." + self.config["project_name"] + ".pages.dev"
        self.assertEqual(self.pub.deployment_url(url, self.config), url)

    def test_launcher_preserves_existing_unowned_file(self):
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        launcher = bin_dir / "diagram-publish"
        launcher.write_text("unrelated")
        env = {**self.env, "CODEX_LOCAL_BIN_DIR": str(bin_dir)}
        result = subprocess.run(["bash", str(ROOT / "scripts/setup-diagram-publish.sh")], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(launcher.read_text(), "unrelated")

    def test_setup_recovers_definitive_rejection_without_losing_unknown_attempt(self):
        self.configured()
        self.pub.config_path.unlink()
        created = []
        reject = [True]

        def api(method, suffix, token, payload=None):
            if method == "POST":
                if reject[0]:
                    raise publisher.PublishError("provider_http_403")
                value = {"id": "created-project", **payload}
                created.append(value)
                return value
            return created[-1] if created else []

        self.pub.api = api
        with self.assertRaisesRegex(publisher.PublishError, "provider_http_403"):
            self.pub.setup(self.config["account_id"], self.token_path, auto=True)
        self.assertFalse((self.pub.root / "setup-attempt.json").exists())
        reject[0] = False
        result = self.pub.setup(self.config["account_id"], self.token_path, auto=True)
        self.assertEqual(result["status"], "configured")
        self.assertEqual(len(created), 1)

    def test_repeated_setup_reuses_same_name_after_unknown_creation(self):
        self.configured()
        self.pub.config_path.unlink()
        posts = []

        def api(method, suffix, token, payload=None):
            if method == "POST":
                posts.append(payload)
                raise publisher.PublishError("network_unavailable")
            if "?page=" in suffix:
                return []
            raise publisher.PublishError("provider_http_404")

        self.pub.api = api
        for _ in range(2):
            with self.assertRaisesRegex(publisher.PublishError, "setup_outcome_unknown"):
                self.pub.setup(self.config["account_id"], self.token_path, auto=True)
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["name"], posts[1]["name"])
        self.assertTrue((self.pub.root / "setup-attempt.json").exists())

    def test_runtime_path_binds_entire_lock_and_corrupt_metadata_is_not_ready(self):
        self.assertIn(self.pub.lock_hash[:16], self.pub.runtime.name)
        package = self.pub.runtime / "node_modules/wrangler/package.json"
        package.parent.mkdir(parents=True)
        self.pub.runtime.chmod(0o700)
        package.write_text("[]")
        publisher.write_json(self.pub.runtime / "receipt.json", {"lock_sha256": self.pub.lock_hash})
        self.assertEqual(self.pub.runtime_status(), "stale")

    def test_install_repairs_corrupt_runtime_atomically(self):
        package = self.pub.runtime / "node_modules/wrangler/package.json"
        package.parent.mkdir(parents=True)
        self.pub.runtime.chmod(0o700)
        package.write_text("[]")
        self.pub.node = lambda: "/fake/node"

        def install(argv, **kwargs):
            stage = Path(kwargs["cwd"])
            package = stage / "node_modules/wrangler/package.json"
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({"version": publisher.WRANGLER_VERSION}))
            binary = package.parent / "bin/wrangler.js"
            binary.parent.mkdir()
            binary.write_text("// synthetic runtime fixture\n")
            return subprocess.CompletedProcess(argv, 0)

        self.pub.runner = install
        with patch.object(publisher.shutil, "which", return_value="/fake/npm"):
            self.assertEqual(self.pub.install_runtime()["status"], "ready")
        self.assertEqual(self.pub.runtime_status(), "ready")
        retired, = self.pub.runtime.parent.glob(self.pub.runtime.name + ".retired-*")
        self.assertEqual((retired / "node_modules/wrangler/package.json").read_text(), "[]")

    def test_lockfile_change_selects_an_independent_runtime(self):
        source = self.base / "runtime-source"
        source.mkdir()
        lock = source / "package-lock.json"
        with patch.object(publisher, "RUNTIME_SOURCE", source):
            lock.write_text('{"generation":1}')
            before = publisher.Publisher(env=self.env).runtime
            lock.write_text('{"generation":2}')
            after = publisher.Publisher(env=self.env).runtime
        self.assertNotEqual(before, after)

    def test_node_timeout_has_actionable_code(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args, 10)
        self.pub.runner = timeout
        with patch.object(publisher.shutil, "which", return_value="/fake/node"):
            with self.assertRaisesRegex(publisher.PublishError, "node_22_required"):
                self.pub.node()

    def test_spawn_failure_records_not_uploaded_and_allows_retry(self):
        self.configured()
        self.pub.project = lambda *args: None
        calls = []

        def failed_spawn(*args, **kwargs):
            calls.append(args)
            raise FileNotFoundError("synthetic")

        self.pub.runner = failed_spawn
        for _ in range(2):
            with self.assertRaisesRegex(publisher.PublishError, "uploader_could_not_start"):
                self.pub.publish(self.html, self.sha, reviewed=True)
            self.assertEqual(self.pub.ledger()[0]["status"], "not_uploaded")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.pub.ledger()), 1)

    def test_launcher_install_does_not_install_runtime_or_configure(self):
        env = {**self.env, "CODEX_LOCAL_BIN_DIR": str(self.base / "bin")}
        result = subprocess.run(["bash", str(ROOT / "scripts/setup-diagram-publish.sh")], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "unconfigured")
        self.assertTrue((self.base / "bin/diagram-publish").is_symlink())
        self.assertFalse(self.pub.config_path.exists())
        self.assertFalse(self.pub.runtime.exists())


if __name__ == "__main__":
    unittest.main()
