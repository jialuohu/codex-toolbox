import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.error import HTTPError


MODULE = Path(__file__).parents[1] / "plugins/web-data-tools/skills/bestblogs-brief/scripts/bestblogs_brief.py"
SKILL_FILE = MODULE.parents[1] / "SKILL.md"
WRAPPER_FILE = MODULE.parent / "run_bestblogs_brief.sh"
SPEC = importlib.util.spec_from_file_location("bestblogs_brief", MODULE)
brief = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(brief)
VALID_API_KEY = "bb_" + "1" * 32


def item(resource_id, **changes):
    value = {
        "resourceId": resource_id,
        "sourceId": "brief-source-" + resource_id,
        "sourceName": "Brief source " + resource_id,
        "title": "Brief title " + resource_id,
        "contentType": "ARTICLE",
        "totalScore": 0.9,
        "deepRead": False,
        "featured": True,
        "personalized": True,
    }
    value.update(changes)
    return value


def metadata(resource_id, resource_type="ARTICLE", **changes):
    value = {
        "id": resource_id,
        "resourceType": resource_type,
        "sourceId": "metadata-source-" + resource_id,
        "sourceName": "Metadata source " + resource_id,
        "title": "Metadata title " + resource_id,
        "url": "https://example.com/" + resource_id,
        "readUrl": "https://reader.example.com/" + resource_id,
        "cover": "https://images.example.com/" + resource_id + ".jpg",
        "publishDateTimeStr": "2026-07-24T01:02:03Z",
        "readTime": 5,
        "tags": ["AI"],
        "oneSentenceSummary": "A concise finding.",
        "summary": "A longer explanation.",
        "mainPoints": ["First point"],
    }
    value.update(changes)
    return value


class FakeClient:
    def __init__(self, account, today, batches):
        self.account = account
        self.today = today
        self.batches = list(batches)
        self.batch_calls = []

    def me(self):
        return self.account

    def today_brief(self):
        return self.today

    def batch_meta(self, resource_ids):
        self.batch_calls.append(list(resource_ids))
        return self.batches.pop(0)


class FakeResponse:
    def __init__(self, payload, url, status=200):
        self.payload = payload
        self.url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, unused_limit):
        return self.payload


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class BestBlogsBriefTests(unittest.TestCase):
    def stable_brief(self, status="PUBLISHED", items=None, brief_date="2026-07-24"):
        return {
            "briefDate": brief_date,
            "status": status,
            "editorIntro": "Today\'s picks",
            "keywords": ["models", "systems"],
            "contentItems": list(items or [item("one"), item("two")]),
        }

    def pro_client(self, today, batches):
        return FakeClient({"userTier": "PRO"}, today, batches)

    def test_normalizes_mixed_content_in_personal_brief_order(self):
        today = self.stable_brief(items=[item("video", contentType="VIDEO"), item("article"), item("tweet", contentType="TWITTER")])
        client = self.pro_client(today, [[
            metadata("article", "ARTICLE"),
            metadata("tweet", "TWITTER", cover=None, publishDateTimeStr=None),
            metadata("video", "VIDEO"),
        ]])

        result = brief.read_today(client, "2026-07-24")

        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["briefDate"], "2026-07-24")
        self.assertEqual([entry["resourceId"] for entry in result["items"]], ["video", "article", "tweet"])
        self.assertEqual([entry["contentType"] for entry in result["items"]], ["VIDEO", "ARTICLE", "TWITTER"])
        self.assertNotIn("coverUrl", result["items"][2])
        self.assertNotIn("publishedAt", result["items"][2])
        self.assertEqual(client.batch_calls, [["video", "article", "tweet"]])

    def test_normalizes_sanitized_live_contract_with_retrieval_timestamp(self):
        today = {
            "briefDate": "2026-07-24",
            "status": "PUBLISHED",
            "editorIntro": "Sanitized live intro",
            "keywords": ["systems"],
            "contentItems": [
                item("first", title="Brief wins", sourceName="Brief source", contentType="ARTICLE", totalScore=9.5),
                item("second", contentType="VIDEO", featured=False),
            ],
            "deepReadItems": [],
        }
        client = self.pro_client(today, [[
            metadata(
                "second", "video", url="https://example.com/second", readUrl="https://reader.example.com/second",
                publishDateTimeStr=None, publishTimeStamp=1_753_409_600_000,
            ),
            metadata(
                "first", "article", title="Metadata loses", sourceName="Metadata loses",
                url="https://example.com/first", cover="https://images.example.com/first.jpg",
                publishDateTimeStr="2026-07-24T01:02:03Z", readTime=7,
                summary="Metadata summary", oneSentenceSummary="Metadata one sentence",
                mainPoints=["Point one"], tags=["ML"],
            ),
        ]])

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(client.batch_calls, [["first", "second"]])
        self.assertEqual(result["generatedAt"], "2026-07-24T09:10:11Z")
        self.assertEqual([entry["resourceId"] for entry in result["items"]], ["first", "second"])
        self.assertEqual(result["items"][0], {
            "resourceId": "first",
            "sourceId": "brief-source-first",
            "sourceName": "Brief source",
            "title": "Brief wins",
            "contentType": "ARTICLE",
            "url": "https://example.com/first",
            "coverUrl": "https://images.example.com/first.jpg",
            "publishedAt": "2026-07-24T01:02:03Z",
            "readTime": 7,
            "score": 9.5,
            "tags": ["ML"],
            "oneSentenceSummary": "Metadata one sentence",
            "summary": "Metadata summary",
            "mainPoints": ["Point one"],
            "deepRead": False,
            "featured": True,
            "personalized": True,
        })
        self.assertEqual(result["items"][1]["publishedAt"], "2025-07-25T02:13:20Z")

    def test_prefers_epoch_over_live_naive_publication_text_and_emits_utc(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", publishDateTimeStr="2026-07-24 08:30:00", publishTimeStamp=1_753_409_600_000),
                metadata("two", publishDateTimeStr="2026-07-24 08:30:00", publishTimeStamp=1_753_409_600),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        for entry in result["items"]:
            self.assertEqual(entry["publishedAt"], "2025-07-25T02:13:20Z")
            self.assertRegex(entry["publishedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_interprets_naive_publication_text_as_beijing_time(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", publishDateTimeStr="2026-07-24 08:30:00", publishTimeStamp=None),
                metadata("two", publishDateTimeStr=None, publishTimeStamp=None),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["items"][0]["publishedAt"], "2026-07-24T00:30:00Z")
        self.assertNotIn("publishedAt", result["items"][1])

    def test_rejects_invalid_naive_publication_time(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", publishDateTimeStr="2026-02-30 08:30:00", publishTimeStamp=None),
                metadata("two"),
            ]],
        )

        with self.assertRaisesRegex(brief.BriefError, "publication time"):
            brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

    def test_rejects_unrepresentable_epochs_with_bounded_publication_error(self):
        for timestamp in (10 ** 1000, -(10 ** 1000), float("inf"), float("-inf"), float("nan")):
            with self.subTest(timestamp_type=type(timestamp).__name__, negative=timestamp < 0):
                client = self.pro_client(
                    self.stable_brief(),
                    [[metadata("one", publishDateTimeStr=None, publishTimeStamp=timestamp), metadata("two")]],
                )

                with self.assertRaisesRegex(brief.BriefError, r"^invalid publication time$"):
                    brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

    def test_client_posts_bounded_batch_to_fixed_endpoint_and_rejects_malformed_envelopes(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/resources/batch-meta"
        valid = json.dumps({"success": True, "code": None, "message": None, "requestId": "request", "data": []}).encode()
        client._opener = FakeOpener([FakeResponse(valid, url)])

        self.assertEqual(client.batch_meta(["one"]), [])
        request, _ = client._opener.requests[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"ids": ["one"]})
        self.assertEqual(request.get_header("X-api-key"), VALID_API_KEY)

        client._opener = FakeOpener([FakeResponse(b'{"success":true}', url)])
        with self.assertRaisesRegex(brief.BriefError, "envelope"):
            client.batch_meta(["one"])

    def test_batches_metadata_requests_at_one_hundred_ids(self):
        items = [item("resource-%03d" % index) for index in range(101)]
        client = self.pro_client(
            self.stable_brief(items=items),
            [[metadata("resource-%03d" % index) for index in range(100)], [metadata("resource-100")]],
        )

        result = brief.read_today(client, "2026-07-24")

        self.assertEqual(len(result["items"]), 101)
        self.assertEqual([len(batch) for batch in client.batch_calls], [100, 1])
        self.assertEqual(result["items"][-1]["resourceId"], "resource-100")

    def test_accepts_each_stable_status(self):
        for status in ("COMPLETED", "PUBLISHED"):
            with self.subTest(status=status):
                client = self.pro_client(self.stable_brief(status=status), [[metadata("one"), metadata("two")]])
                self.assertEqual(brief.read_today(client, "2026-07-24")["status"], status)

    def test_preserves_optional_multiline_summary_without_inventing_missing_text(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", summary="First line.\nSecond line.", oneSentenceSummary=None),
                metadata("two", summary=None, oneSentenceSummary=None),
            ]],
        )

        result = brief.read_today(client, "2026-07-24")

        self.assertEqual(result["items"][0]["summary"], "First line.\nSecond line.")
        self.assertNotIn("oneSentenceSummary", result["items"][0])
        self.assertNotIn("summary", result["items"][1])

    def test_keeps_one_sentence_summary_without_inventing_summary(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", summary=None, oneSentenceSummary="Concise only"),
                metadata("two", summary=None, oneSentenceSummary=None),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["items"][0]["oneSentenceSummary"], "Concise only")
        self.assertNotIn("summary", result["items"][0])

    def test_rejects_wrong_date_and_unstable_or_unknown_statuses(self):
        client = self.pro_client(self.stable_brief(brief_date="2026-07-23"), [])
        with self.assertRaisesRegex(brief.BriefError, "date"):
            brief.read_today(client, "2026-07-24")
        for status in ("GENERATING", "FAILED", "OTHER"):
            with self.subTest(status=status):
                client = self.pro_client(self.stable_brief(status=status), [])
                with self.assertRaisesRegex(brief.BriefError, "status"):
                    brief.read_today(client, "2026-07-24")

    def test_rejects_duplicate_brief_ids_and_missing_or_foreign_metadata(self):
        duplicate = self.pro_client(self.stable_brief(items=[item("one"), item("one")]), [])
        with self.assertRaisesRegex(brief.BriefError, "duplicate"):
            brief.read_today(duplicate, "2026-07-24")
        missing = self.pro_client(self.stable_brief(), [[metadata("one")]])
        with self.assertRaisesRegex(brief.BriefError, "missing"):
            brief.read_today(missing, "2026-07-24")
        foreign = self.pro_client(self.stable_brief(), [[metadata("one"), metadata("foreign")]])
        with self.assertRaisesRegex(brief.BriefError, "foreign"):
            brief.read_today(foreign, "2026-07-24")

    def test_rejects_unsafe_urls_and_unknown_content_types(self):
        for field, unsafe in (
            ("url", "http://example.com/item"),
            ("url", "https://user@example.com/item"),
            ("cover", "https://user@example.com/image"),
            ("url", "https://bad host.example/item"),
            ("url", "https://example.com:443/item"),
            ("url", "https://example.com/item#fragment"),
        ):
            with self.subTest(field=field, unsafe=unsafe):
                values = {field: unsafe}
                if field == "url":
                    values["readUrl"] = None
                client = self.pro_client(self.stable_brief(), [[metadata("one", **values), metadata("two")]])
                with self.assertRaisesRegex(brief.BriefError, "HTTPS"):
                    brief.read_today(client, "2026-07-24")
        client = self.pro_client(
            self.stable_brief(items=[item("one", contentType="PODCAST"), item("two")]),
            [[metadata("one"), metadata("two")]],
        )
        with self.assertRaisesRegex(brief.BriefError, "content type"):
            brief.read_today(client, "2026-07-24")

    def test_keeps_documented_legacy_items_and_metadata_shape_compatible(self):
        legacy = self.stable_brief()
        legacy["items"] = [{
            "resourceId": "legacy",
            "score": 1.5,
            "tags": ["legacy"],
            "mainPoints": ["Compatibility"],
            "deepRead": True,
            "featured": False,
            "personalized": False,
        }]
        del legacy["contentItems"]
        client = self.pro_client(legacy, [[{
            "resourceId": "legacy",
            "sourceId": "legacy-source",
            "sourceName": "Legacy source",
            "title": "Legacy title",
            "contentType": "ARTICLE",
            "url": "https://example.com/legacy",
            "coverUrl": None,
            "publishedAt": None,
            "readTime": 2,
        }]])

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["generatedAt"], "2026-07-24T09:10:11Z")
        self.assertEqual(result["items"][0]["title"], "Legacy title")

    def test_rejects_invalid_upstream_generated_timestamp(self):
        today = self.stable_brief()
        today["generatedAt"] = "not-a-timestamp"
        client = self.pro_client(today, [[metadata("one"), metadata("two")]])

        with self.assertRaisesRegex(brief.BriefError, "generatedAt"):
            brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

    def test_normalizes_structured_live_main_points_to_point_text(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", mainPoints=[{"point": "Key point", "explanation": "Sanitized rationale"}]),
                metadata("two", mainPoints=None),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["items"][0]["mainPoints"], ["Key point"])
        self.assertEqual(result["items"][1]["mainPoints"], [])

    def test_omits_structured_main_point_without_point_text(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", mainPoints=[{"explanation": "No displayable point"}]),
                metadata("two", mainPoints=[]),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["items"][0]["mainPoints"], [])

    def test_uses_safe_read_url_when_primary_url_is_invalid(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", url="https://bad host.example/item", readUrl="https://reader.example.com/one"),
                metadata("two"),
            ]],
        )

        result = brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(result["items"][0]["url"], "https://reader.example.com/one")

    def test_main_redacts_valid_key_when_http_failure_contains_sensitive_body(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/me"
        client._opener = FakeOpener([
            HTTPError(url, 500, "error", {}, io.BytesIO(("sensitive " + VALID_API_KEY).encode("utf-8"))),
        ])
        original_factory = brief.BestBlogsClient
        original_key = os.environ.get("BESTBLOGS_API_KEY")
        output, errors = io.StringIO(), io.StringIO()
        brief.BestBlogsClient = lambda unused_key: client
        os.environ["BESTBLOGS_API_KEY"] = VALID_API_KEY
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                result = brief.main(["doctor"])
        finally:
            brief.BestBlogsClient = original_factory
            if original_key is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = original_key
        self.assertEqual(result, 2)
        self.assertIn("HTTP request failed", errors.getvalue())
        self.assertNotIn(VALID_API_KEY, output.getvalue() + errors.getvalue())

    def test_launcher_uses_standard_codex_home_fallback_without_personal_path_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            secrets_dir = codex_home / "secrets"
            fake_bin = root / "bin"
            secrets_dir.mkdir(parents=True)
            fake_bin.mkdir()
            (secrets_dir / "bestblogs.env").write_text("BESTBLOGS_API_KEY=%s\n" % VALID_API_KEY, encoding="utf-8")
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o700)
            env = os.environ.copy()
            env.pop("CODEX_SECRETS_DIR", None)
            env.update({"CODEX_HOME": str(codex_home), "PATH": str(fake_bin) + os.pathsep + env.get("PATH", "")})

            result = subprocess.run([str(WRAPPER_FILE), "doctor"], env=env, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0)
        self.assertNotIn(VALID_API_KEY, result.stdout + result.stderr)
        docs = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("CODEX_SECRETS_DIR", docs)
        self.assertIn("standard Codex secrets fallback", docs)
        self.assertNotIn("$HOME" + "/.codex" + "/secrets", docs)

    def test_doctor_redacts_secret_and_rejects_non_pro_accounts(self):
        secret = VALID_API_KEY + "-never-print"
        original = os.environ.get("BESTBLOGS_API_KEY")
        os.environ["BESTBLOGS_API_KEY"] = secret
        output, errors = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                result = brief.main(["doctor"])
        finally:
            if original is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = original
        self.assertEqual(result, 2)
        self.assertNotIn(secret, output.getvalue() + errors.getvalue())

        client = FakeClient({"userTier": "FREE"}, self.stable_brief(), [])
        with self.assertRaisesRegex(brief.BriefError, "Pro"):
            brief.read_today(client, "2026-07-24")


if __name__ == "__main__":
    unittest.main()
