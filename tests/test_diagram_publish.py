"""Publication lifecycle tests with an in-memory Cloudflare transport.

No test invokes Wrangler, reads real credentials, or contacts the network.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit


SOURCE = (Path(__file__).resolve().parents[1] / "plugins/diagram-tools/skills/"
          "diagram-publish/scripts/diagram_publish.py")
SPEC = importlib.util.spec_from_file_location("diagram_publish_lifecycle", SOURCE)
publisher_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher_module)


class FakeCloudflare:
    def __init__(self, config):
        self.config = config
        self.project = {
            "id": config["project_id"],
            "name": config["project_name"],
            "production_branch": "main",
        }
        self.deployments = {}
        self.pages = {}
        self.calls = []
        self.deleted = []
        self.delete_takes_effect = True
        self.path = publisher_module.Publisher.project_path(config)

    def create_deployment(self, branch, data):
        index = len(self.pages) + 1
        deployment_id = f"deployment-{index}"
        url = f"https://{index:08x}.{self.config['project_name']}.pages.dev"
        self.deployments[deployment_id] = {
            "id": deployment_id,
            "project_id": self.config["project_id"],
            "project_name": self.config["project_name"],
            "environment": "preview",
            "deployment_trigger": {"metadata": {"branch": branch}},
            "latest_stage": {"name": "deploy", "status": "success"},
            "url": url,
        }
        self.pages[url] = (200, {
            "content-type": "text/html; charset=utf-8",
            "x-robots-tag": "noindex, nofollow",
        }, data)
        return self.deployments[deployment_id]

    @staticmethod
    def response(result, status=200):
        return status, {"content-type": "application/json"}, json.dumps({
            "success": status == 200, "result": result,
        }).encode()

    def transport(self, method, url, headers, body=None, limit=None):
        self.calls.append((method, url, dict(headers)))
        if not url.startswith(publisher_module.API):
            if method != "GET" or "Authorization" in headers:
                raise AssertionError("Public verification must be an unauthenticated GET")
            return self.pages.get(url, (404, {}, b""))
        path = urlsplit(url[len(publisher_module.API):]).path
        if not headers.get("Authorization", "").startswith("Bearer "):
            raise AssertionError("Provider API request requires isolated authentication")
        if method == "GET" and path == self.path:
            return self.response(self.project)
        if method == "GET" and path == self.path + "/deployments":
            return self.response(list(self.deployments.values()))
        prefix = self.path + "/deployments/"
        if path.startswith(prefix):
            deployment_id = path[len(prefix):]
            if method == "GET":
                return self.response(self.deployments.get(deployment_id),
                                     200 if deployment_id in self.deployments else 404)
            if method == "DELETE":
                self.deleted.append(deployment_id)
                if self.delete_takes_effect:
                    deployment = self.deployments.pop(deployment_id, None)
                    if deployment:
                        self.pages.pop(deployment["url"], None)
                return self.response({})
        raise AssertionError(f"Unexpected provider request: {method} {path}")


class DiagramPublishLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="diagram-publish-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / "codex-home"
        self.home.mkdir(mode=0o700)
        secrets = self.home / "secrets"
        secrets.mkdir(mode=0o700)
        token = secrets / "cloudflare-token"
        token.write_text("A" * 32)
        token.chmod(0o600)
        self.config = {
            "schema_version": 1,
            "account_id": "a" * 32,
            "project_name": "codex-diagrams-" + "b" * 16,
            "project_id": "project-123",
            "production_branch": "main",
            "token_file": str(token),
            "mode": "auto",
        }
        self.server = FakeCloudflare(self.config)
        self.publisher = publisher_module.Publisher(
            env={"CODEX_HOME": str(self.home)},
            transport=self.server.transport,
            runner=self.runner,
            sleep=lambda _: None,
        )
        publisher_module.write_json(self.publisher.config_path, self.config)
        self.publisher.runtime_status = lambda: "ready"
        self.publisher.node = lambda: "/synthetic/node"
        self.upload_count = 0
        self.create_on_upload = True
        self.upload_times_out = False
        self.last_upload = None
        self.html = self.home / "diagram.html"
        self.data = b"<!doctype html><html><body>First accepted drawing</body></html>"
        self.html.write_bytes(self.data)

    def runner(self, args, **kwargs):
        self.assertEqual(args[2:4], ["pages", "deploy"])
        self.upload_count += 1
        data = (Path(args[4]) / "index.html").read_bytes()
        branch = args[args.index("--branch") + 1]
        self.last_upload = (branch, data)
        if self.create_on_upload:
            self.server.create_deployment(branch, data)
        if self.upload_times_out:
            raise subprocess.TimeoutExpired(args, 180)
        return subprocess.CompletedProcess(args, 0)

    def publish(self, data=None):
        if data is not None:
            self.data = data
            self.html.write_bytes(data)
        return self.publisher.publish(self.html, publisher_module.digest(self.data), reviewed=True)

    def test_publication_verifies_exact_bytes_and_records_receipt(self):
        result = self.publish()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(self.server.pages[result["url"]][2], self.data)
        self.assertEqual(self.upload_count, 1)
        record, = self.publisher.list_publications()["publications"]
        self.assertEqual(record["deployment_id"], result["deployment_id"])
        self.assertEqual(record["sha256"], publisher_module.digest(self.data))
        self.assertEqual(record["status"], "verified")
        self.assertNotIn(str(self.html), json.dumps(record))

    def test_same_artifact_reconciles_existing_deployment_without_upload(self):
        first = self.publish()
        second = self.publish()
        self.assertEqual(first["url"], second["url"])
        self.assertEqual(first["deployment_id"], second["deployment_id"])
        self.assertEqual(self.upload_count, 1)
        self.assertEqual(len(self.publisher.ledger()), 1)

    def test_public_verification_identifies_publisher_without_credentials(self):
        transport = self.publisher.transport

        def reject_default_user_agent(method, url, headers, body=None, limit=None):
            if not url.startswith(publisher_module.API):
                self.assertNotIn("Authorization", headers)
                self.assertNotIn("Cookie", headers)
                if headers.get("User-Agent") != "codex-toolbox-diagram-publish/0.5.0":
                    return 403, {"content-type": "text/plain"}, b"error code: 1010\n"
            return transport(method, url, headers, body, limit)

        self.publisher.transport = reject_default_user_agent
        self.assertTrue(self.publish()["ok"])
        self.assertEqual(self.upload_count, 1)

    def test_next_artifact_has_distinct_url_and_preserves_previous_page(self):
        first_data = self.data
        first = self.publish()
        second = self.publish(b"<!doctype html><html><body>Second drawing</body></html>")
        self.assertTrue(second["ok"])
        self.assertNotEqual(first["url"], second["url"])
        self.assertNotEqual(first["deployment_id"], second["deployment_id"])
        self.assertEqual(self.server.pages[first["url"]][2], first_data)
        self.assertEqual(self.server.pages[second["url"]][2], self.data)
        self.assertEqual(self.upload_count, 2)
        self.assertEqual(len(self.publisher.ledger()), 2)

    def test_timeout_after_creation_is_reconciled_without_reupload(self):
        self.upload_times_out = True
        result = self.publish()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(self.publish()["deployment_id"], result["deployment_id"])
        self.assertEqual(self.upload_count, 1)

    def test_unknown_timeout_does_not_duplicate_and_late_result_reconciles(self):
        self.upload_times_out = True
        self.create_on_upload = False
        first = self.publish()
        second = self.publish()
        for result in (first, second):
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "outcome_unknown")
            self.assertTrue(result["local_artifact_preserved"])
        self.assertEqual(self.upload_count, 1)
        self.assertEqual(self.html.read_bytes(), self.data)
        self.assertEqual(self.publisher.ledger()[0]["status"], "unresolved")
        self.server.create_deployment(*self.last_upload)
        recovered = self.publish()
        self.assertTrue(recovered["ok"])
        self.assertEqual(self.upload_count, 1)
        self.assertNotIn("last_error", self.publisher.ledger()[0])

    def test_structured_output_uses_verified_api_lookup_without_listing(self):
        real_runner = self.publisher.runner

        def structured(*args, **kwargs):
            result = real_runner(*args, **kwargs)
            deployment_id = next(iter(self.server.deployments))
            Path(kwargs["env"]["WRANGLER_OUTPUT_FILE_PATH"]).write_text(json.dumps({
                "type": "pages-deploy", "version": 1,
                "pages_project": self.config["project_name"], "deployment_id": deployment_id,
            }) + "\n")
            return result

        self.publisher.runner = structured
        result = self.publish()
        self.assertTrue(result["ok"])
        self.assertFalse(any("/deployments?" in url for _, url, _ in self.server.calls))
        self.assertTrue(any(url.endswith("/deployments/" + result["deployment_id"]) for _, url, _ in self.server.calls))

    def test_malformed_provider_metadata_is_recorded_unresolved(self):
        real_runner = self.publisher.runner

        def malformed(*args, **kwargs):
            result = real_runner(*args, **kwargs)
            for deployment in self.server.deployments.values():
                deployment["deployment_trigger"] = None
            return result

        self.publisher.runner = malformed
        result = self.publish()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid_deployment_response")
        self.assertEqual(self.publisher.ledger()[0]["status"], "unresolved")

    def test_nonpublic_page_stays_unresolved_without_reupload(self):
        first = self.publish()
        self.server.pages[first["url"]] = (403, {}, b"Authentication required")
        result = self.publish()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "deployment_not_public")
        self.assertEqual(self.upload_count, 1)

    def test_changed_public_bytes_are_not_reported_verified(self):
        first = self.publish()
        status, headers, _ = self.server.pages[first["url"]]
        self.server.pages[first["url"]] = (status, headers, b"changed")
        result = self.publish()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "published_content_mismatch")
        self.assertEqual(self.upload_count, 1)

    def test_initial_verification_failure_retains_identity_for_explicit_removal(self):
        real_runner = self.publisher.runner

        def inaccessible(*args, **kwargs):
            result = real_runner(*args, **kwargs)
            for url in self.server.pages:
                self.server.pages[url] = (403, {}, b"private")
            return result

        self.publisher.runner = inaccessible
        self.assertFalse(self.publish()["ok"])
        record, = self.publisher.ledger()
        self.assertEqual(record["status"], "unresolved")
        self.assertIn("deployment_id", record)
        result = self.publisher.unpublish(record["deployment_id"], confirm=True)
        self.assertEqual(result["status"], "removed")
        self.assertEqual(self.server.deployments, {})

    def test_unpublish_needs_explicit_confirmation_without_provider_calls(self):
        result = self.publish()
        before = len(self.server.calls)
        with self.assertRaisesRegex(publisher_module.PublishError,
                                    "^explicit_removal_confirmation_required$"):
            self.publisher.unpublish(result["deployment_id"])
        self.assertEqual(len(self.server.calls), before)
        self.assertEqual(self.server.deleted, [])

    def test_unpublish_removes_only_selected_record_and_is_idempotent(self):
        first = self.publish()
        second = self.publish(b"<html><body>Retain this second drawing</body></html>")
        result = self.publisher.unpublish(first["deployment_id"], confirm=True)
        self.assertEqual(result["status"], "removed")
        self.assertEqual(self.server.deleted, [first["deployment_id"]])
        self.assertNotIn(first["url"], self.server.pages)
        self.assertIn(second["url"], self.server.pages)
        self.assertTrue(self.html.is_file())
        self.assertEqual([r["status"] for r in self.publisher.ledger()],
                         ["removed", "verified"])
        self.publisher.unpublish(first["deployment_id"], confirm=True)
        self.assertEqual(self.server.deleted, [first["deployment_id"]])

    def test_unpublish_rejects_unrecorded_target(self):
        self.publish()
        with self.assertRaisesRegex(publisher_module.PublishError, "^deployment_not_recorded$"):
            self.publisher.unpublish("unrelated-deployment", confirm=True)
        self.assertEqual(self.server.deleted, [])

    def test_unpublish_rejects_recorded_target_when_remote_identity_changes(self):
        result = self.publish()
        self.server.deployments[result["deployment_id"]]["project_id"] = "other-project"
        with self.assertRaisesRegex(publisher_module.PublishError, "^removal_target_mismatch$"):
            self.publisher.unpublish(result["deployment_id"], confirm=True)
        self.assertEqual(self.server.deleted, [])

    def test_unpublish_rejects_production_target(self):
        result = self.publish()
        self.server.deployments[result["deployment_id"]]["environment"] = "production"
        with self.assertRaisesRegex(publisher_module.PublishError, "^removal_target_mismatch$"):
            self.publisher.unpublish(result["deployment_id"], confirm=True)
        self.assertEqual(self.server.deleted, [])

    def test_unpublish_requires_verified_absence_after_delete(self):
        result = self.publish()
        self.server.delete_takes_effect = False
        with self.assertRaisesRegex(publisher_module.PublishError, "^removal_outcome_unknown$"):
            self.publisher.unpublish(result["deployment_id"], confirm=True)
        self.assertEqual(self.publisher.ledger()[0]["status"], "removing")
        self.assertIn(result["url"], self.server.pages)


if __name__ == "__main__":
    unittest.main()
