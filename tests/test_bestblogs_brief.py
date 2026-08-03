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
from unittest.mock import ANY


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
    def __init__(self, account, today, batches, history=None):
        self.account = account
        self.today = today
        self.batches = list(batches)
        self.batch_calls = []
        self.history = history
        self.history_calls = []

    def me(self):
        return self.account

    def today_brief(self):
        return self.today

    def brief_history(self, page=1, page_size=30):
        self.history_calls.append((page, page_size))
        return self.history

    def batch_meta(self, resource_ids):
        self.batch_calls.append(list(resource_ids))
        return self.batches.pop(0)


class PublicOnlyClient:
    """A public endpoint double that fails if a personal route is touched."""

    def __init__(self, public, batches):
        self.public = public
        self.batches = list(batches)
        self.public_calls = []
        self.batch_calls = []

    def me(self):
        raise AssertionError("public reads must not call /me")

    def public_brief(self, date, language):
        self.public_calls.append((date, language))
        return self.public

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
        content_items = [item("one"), item("two")] if items is None else list(items)
        return {
            "briefDate": brief_date,
            "status": status,
            "editorIntro": "Today\'s picks",
            "keywords": ["models", "systems"],
            "contentItems": content_items,
        }

    def pro_client(self, today, batches):
        return FakeClient({"userTier": "PRO"}, today, batches)

    def public_client(self, public, batches):
        return PublicOnlyClient(public, batches)

    def assert_unsafe_item_url_and_omitted_cover(self, unsafe):
        item_client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", url=unsafe, cover=None),
        ]])
        with self.assertRaisesRegex(brief.BriefError, "resource HTTPS URL"):
            brief.read_today(item_client, "2026-07-24")

        cover_client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", url="https://publisher.example.com/one", cover=unsafe),
        ]])
        result = brief.read_today(cover_client, "2026-07-24")
        self.assertNotIn("coverUrl", result["items"][0])

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
                url="https://example.com/first", cover="https://image.jido.dev/first.jpg",
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
            "coverUrl": "https://image.jido.dev/first.jpg",
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

    def test_rejects_timezone_less_publication_text(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", publishDateTimeStr="2026-07-24 08:30:00", publishTimeStamp=None),
                metadata("two", publishDateTimeStr=None, publishTimeStamp=None),
            ]],
        )

        with self.assertRaisesRegex(brief.BriefError, "publication time"):
            brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

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

    def test_client_gets_bounded_history_from_fixed_endpoint_and_rejects_malformed_envelopes(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/me/briefs/history?page=1&pageSize=30"
        valid = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request", "data": [],
        }).encode()
        client._opener = FakeOpener([FakeResponse(valid, url)])

        self.assertEqual(client.brief_history(), [])
        request, _ = client._opener.requests[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("X-api-key"), VALID_API_KEY)

        client._opener = FakeOpener([FakeResponse(b'{"success":true}', url)])
        with self.assertRaisesRegex(brief.BriefError, "envelope"):
            client.brief_history()

    def test_public_client_uses_exact_fixed_date_and_language_endpoint(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/brief?date=2026-07-24&language=zh"
        valid = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request", "data": {},
        }).encode()
        client._opener = FakeOpener([FakeResponse(valid, url)])

        self.assertEqual(client.public_brief("2026-07-24", "zh"), {})
        request, _ = client._opener.requests[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("X-api-key"), VALID_API_KEY)

    def test_public_client_falls_back_in_order_only_for_unauthorized_or_missing_primary(self):
        primary_url = brief.API_ORIGIN + "/brief?date=2026-07-24&language=zh"
        fallback_url = brief.API_ORIGIN + "/briefs/public/today?locale=zh"
        valid = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request", "data": {"route": "fallback"},
        }).encode()
        for status in (401, 404):
            with self.subTest(status=status):
                client = brief.BestBlogsClient(VALID_API_KEY)
                client._opener = FakeOpener([
                    HTTPError(primary_url, status, "sensitive upstream detail", {}, io.BytesIO(b"sensitive payload")),
                    FakeResponse(valid, fallback_url),
                ])

                self.assertEqual(client.public_brief("2026-07-24", "zh"), {"route": "fallback"})
                requests = [request for request, _ in client._opener.requests]
                self.assertEqual([request.full_url for request in requests], [primary_url, fallback_url])
                self.assertEqual([request.get_method() for request in requests], ["GET", "GET"])
                self.assertTrue(all(request.data is None for request in requests))
                self.assertTrue(all("/me" not in request.full_url for request in requests))

    def test_public_client_preserves_other_http_status_without_fallback_or_sensitive_details(self):
        primary_url = brief.API_ORIGIN + "/brief?date=2026-07-24&language=en"
        for status in (400, 403, 429, 500):
            with self.subTest(status=status):
                client = brief.BestBlogsClient(VALID_API_KEY)
                client._opener = FakeOpener([
                    HTTPError(
                        primary_url, status, "sensitive upstream detail", {},
                        io.BytesIO(("sensitive payload " + VALID_API_KEY).encode()),
                    ),
                ])

                with self.assertRaisesRegex(brief.BriefError, r"^BestBlogs HTTP request failed$") as raised:
                    client.public_brief("2026-07-24", "en")

                self.assertEqual(raised.exception.status, status)
                self.assertEqual([request.full_url for request, _ in client._opener.requests], [primary_url])
                self.assertNotIn("sensitive", str(raised.exception))
                self.assertNotIn(VALID_API_KEY, str(raised.exception))

    def test_public_today_fallback_still_rejects_a_returned_date_mismatch_before_metadata(self):
        primary_url = brief.API_ORIGIN + "/brief?date=2026-07-23&language=zh"
        fallback_url = brief.API_ORIGIN + "/briefs/public/today?locale=zh"
        fallback = json.dumps({
            "success": True,
            "code": None,
            "message": None,
            "requestId": "request",
            "data": self.stable_brief(brief_date="2026-07-24"),
        }).encode()
        client = brief.BestBlogsClient(VALID_API_KEY)
        client._opener = FakeOpener([
            HTTPError(primary_url, 404, "not found", {}, io.BytesIO(b"sensitive payload")),
            FakeResponse(fallback, fallback_url),
        ])

        with self.assertRaisesRegex(brief.BriefError, "brief date"):
            brief.read_public(client, "2026-07-23", "zh")

        self.assertEqual(
            [request.full_url for request, _ in client._opener.requests],
            [primary_url, fallback_url],
        )

    def test_public_normalizes_every_item_in_order_without_personal_routes(self):
        newsletter = item("newsletter", contentType="NEWSLETTER")
        for field in ("deepRead", "featured", "personalized"):
            del newsletter[field]
        source = self.stable_brief(items=[newsletter, item(
            "article", contentType="ARTICLE", deepRead=True, featured=False, personalized=False,
        )])
        client = self.public_client(source, [[
            metadata("article", "ARTICLE"),
            metadata("newsletter", "NEWSLETTER"),
        ]])

        result = brief.read_public(client, "2026-07-24", "zh", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(client.public_calls, [("2026-07-24", "zh")])
        self.assertEqual(client.batch_calls, [["newsletter", "article"]])
        self.assertEqual([entry["resourceId"] for entry in result["items"]], ["newsletter", "article"])
        self.assertEqual([entry["contentType"] for entry in result["items"]], ["NEWSLETTER", "ARTICLE"])
        self.assertEqual(
            [(entry["deepRead"], entry["featured"], entry["personalized"]) for entry in result["items"]],
            [(False, True, False), (True, False, False)],
        )

    def test_public_rejects_invalid_request_and_incomplete_or_mismatched_editions_before_metadata(self):
        for name, requested_date, language, source, expected_error in (
            ("malformed date", "2026-7-24", "zh", self.stable_brief(), "public date"),
            ("unsupported language", "2026-07-24", "fr", self.stable_brief(), "public language"),
            ("wrong date", "2026-07-24", "zh", self.stable_brief(brief_date="2026-07-23"), "date"),
            ("unstable", "2026-07-24", "zh", self.stable_brief(status="GENERATING"), "status"),
            ("empty", "2026-07-24", "zh", self.stable_brief(items=[]), "items are empty"),
        ):
            with self.subTest(name=name):
                client = self.public_client(source, [])
                with self.assertRaisesRegex(brief.BriefError, expected_error):
                    brief.read_public(client, requested_date, language)
                self.assertEqual(client.batch_calls, [])

    def test_public_rejects_invalid_explicit_selection_flags(self):
        for field, value in (("deepRead", "false"), ("featured", 1), ("personalized", 0.0), ("personalized", True)):
            with self.subTest(field=field):
                public_item = item("one")
                public_item[field] = value
                client = self.public_client(self.stable_brief(items=[public_item]), [[metadata("one")]])
                with self.assertRaisesRegex(brief.BriefError, field):
                    brief.read_public(client, "2026-07-24", "en")

    def test_public_cli_emits_one_normalized_object_without_personal_access(self):
        public_client = self.public_client(
            self.stable_brief(items=[item("newsletter", contentType="NEWSLETTER", personalized=False)]),
            [[metadata("newsletter", "NEWSLETTER")]],
        )
        original_factory = brief.BestBlogsClient
        original_key = os.environ.get("BESTBLOGS_API_KEY")
        output, errors = io.StringIO(), io.StringIO()
        brief.BestBlogsClient = lambda unused_key: public_client
        os.environ["BESTBLOGS_API_KEY"] = VALID_API_KEY
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                result = brief.main(["public", "--date", "2026-07-24", "--language", "en"])
        finally:
            brief.BestBlogsClient = original_factory
            if original_key is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = original_key

        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(public_client.public_calls, [("2026-07-24", "en")])
        self.assertEqual(json.loads(output.getvalue())["items"][0]["personalized"], False)

    def test_history_selects_one_complete_mixed_type_edition_before_normalizing(self):
        requested = self.stable_brief(
            status="COMPLETED",
            brief_date="2026-07-23",
            items=[
                item("podcast", contentType="PODCAST"),
                item("video", contentType="VIDEO"),
                item("tweet", contentType="TWITTER"),
                item("article", contentType="ARTICLE"),
            ],
        )
        client = FakeClient(
            {"userTier": "PRO"},
            self.stable_brief(),
            [[
                metadata("article", "ARTICLE"),
                metadata("podcast", "PODCAST"),
                metadata("tweet", "TWITTER"),
                metadata("video", "VIDEO"),
            ]],
            history=[self.stable_brief(brief_date="2026-07-24"), requested],
        )

        result = brief.read_history(client, "2026-07-23", clock=lambda: "2026-07-24T09:10:11Z")

        self.assertEqual(client.history_calls, [(1, 30)])
        self.assertEqual(client.batch_calls, [["podcast", "video", "tweet", "article"]])
        self.assertEqual(result["briefDate"], "2026-07-23")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(
            [(entry["resourceId"], entry["contentType"]) for entry in result["items"]],
            [("podcast", "PODCAST"), ("video", "VIDEO"), ("tweet", "TWITTER"), ("article", "ARTICLE")],
        )

    def test_history_rejects_absent_duplicate_incomplete_and_empty_matching_editions_before_metadata(self):
        requested_date = "2026-07-23"
        cases = (
            ("absent", [self.stable_brief(brief_date="2026-07-24")], "not available"),
            (
                "duplicate",
                [self.stable_brief(brief_date=requested_date), self.stable_brief(brief_date=requested_date)],
                "ambiguous",
            ),
            ("incomplete", [self.stable_brief(status="GENERATING", brief_date=requested_date)], "not complete"),
            ("empty", [self.stable_brief(brief_date=requested_date, items=[])], "items are empty"),
        )
        for name, history, expected_error in cases:
            with self.subTest(name=name):
                client = FakeClient({"userTier": "PRO"}, self.stable_brief(), [], history=history)

                with self.assertRaisesRegex(brief.BriefError, expected_error):
                    brief.read_history(client, requested_date)

                self.assertEqual(client.history_calls, [(1, 30)])
                self.assertEqual(client.batch_calls, [])

    def test_history_cli_emits_one_normalized_object(self):
        history_client = FakeClient(
            {"userTier": "PRO"},
            self.stable_brief(),
            [[metadata("podcast", "PODCAST")]],
            history=[self.stable_brief(status="COMPLETED", brief_date="2026-07-23", items=[item("podcast", contentType="PODCAST")])],
        )
        original_factory = brief.BestBlogsClient
        original_key = os.environ.get("BESTBLOGS_API_KEY")
        output, errors = io.StringIO(), io.StringIO()
        brief.BestBlogsClient = lambda unused_key: history_client
        os.environ["BESTBLOGS_API_KEY"] = VALID_API_KEY
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                result = brief.main(["history", "--date", "2026-07-23"])
        finally:
            brief.BestBlogsClient = original_factory
            if original_key is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = original_key
        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(json.loads(output.getvalue()), {
            "schemaVersion": 1,
            "briefDate": "2026-07-23",
            "status": "COMPLETED",
            "generatedAt": ANY,
            "editorIntro": "Today's picks",
            "keywords": ["models", "systems"],
            "items": [{
                "resourceId": "podcast",
                "sourceId": "brief-source-podcast",
                "sourceName": "Brief source podcast",
                "title": "Brief title podcast",
                "contentType": "PODCAST",
                "url": "https://example.com/podcast",
                "publishedAt": "2026-07-24T01:02:03Z",
                "readTime": 5,
                "score": 0.9,
                "tags": ["AI"],
                "oneSentenceSummary": "A concise finding.",
                "summary": "A longer explanation.",
                "mainPoints": ["First point"],
                "deepRead": False,
                "featured": True,
                "personalized": True,
            }],
        })

    def test_history_cli_redacts_http_failure(self):
        original_factory = brief.BestBlogsClient
        original_key = os.environ.get("BESTBLOGS_API_KEY")
        client = brief.BestBlogsClient(VALID_API_KEY)
        me_url = brief.API_ORIGIN + "/me"
        history_url = brief.API_ORIGIN + "/me/briefs/history?page=1&pageSize=30"
        account = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request", "data": {"userTier": "PRO"},
        }).encode()
        client._opener = FakeOpener([
            FakeResponse(account, me_url),
            HTTPError(history_url, 500, "error", {}, io.BytesIO(("sensitive " + VALID_API_KEY).encode("utf-8"))),
        ])
        output, errors = io.StringIO(), io.StringIO()
        brief.BestBlogsClient = lambda unused_key: client
        os.environ["BESTBLOGS_API_KEY"] = VALID_API_KEY
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                result = brief.main(["history", "--date", "2026-07-23"])
        finally:
            brief.BestBlogsClient = original_factory
            if original_key is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = original_key
        self.assertEqual(result, 2)
        self.assertIn("HTTP request failed", errors.getvalue())
        self.assertNotIn(VALID_API_KEY, output.getvalue() + errors.getvalue())

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

    def test_requires_exact_calendar_brief_date_grammar(self):
        for malformed in (
            "2026-7-24",
            "2026-07-4",
            "2026-02-29",
            "2026-13-01",
            "2026-00-01",
            "2026-07-24T00:00:00Z",
        ):
            with self.subTest(malformed=malformed):
                client = self.pro_client(
                    self.stable_brief(items=[item("one")], brief_date=malformed),
                    [[metadata("one")]],
                )
                with self.assertRaisesRegex(brief.BriefError, "date"):
                    brief.read_today(client, malformed)

    def test_rejects_empty_stable_editions(self):
        for status in ("COMPLETED", "PUBLISHED"):
            with self.subTest(status=status):
                client = self.pro_client(self.stable_brief(status=status, items=[]), [])

                with self.assertRaisesRegex(brief.BriefError, "brief items"):
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

    def test_rejects_unsafe_urls(self):
        for field, unsafe in (
            ("url", "https://user@example.com/item"),
            ("url", "https://bad host.example/item"),
            ("url", "https://example.com:443/item"),
            ("url", "https://example.com:/item"),
            ("url", "https://example.com/item#fragment"),
        ):
            with self.subTest(field=field, unsafe=unsafe):
                values = {field: unsafe}
                if field == "url":
                    values["readUrl"] = None
                client = self.pro_client(self.stable_brief(), [[metadata("one", **values), metadata("two")]])
                with self.assertRaisesRegex(brief.BriefError, "HTTPS"):
                    brief.read_today(client, "2026-07-24")

    def test_normalizes_documented_podcasts_from_brief_and_metadata(self):
        client = self.pro_client(
            self.stable_brief(items=[
                item("brief-podcast", contentType="PODCAST"),
                item("metadata-podcast", contentType=None),
            ]),
            [[
                metadata("brief-podcast", "ARTICLE"),
                metadata("metadata-podcast", "PODCAST"),
            ]],
        )

        result = brief.read_today(client, "2026-07-24")

        self.assertEqual(
            [(entry["resourceId"], entry["contentType"]) for entry in result["items"]],
            [("brief-podcast", "PODCAST"), ("metadata-podcast", "PODCAST")],
        )

    def test_rejects_undocumented_content_types(self):
        client = self.pro_client(
            self.stable_brief(items=[item("one", contentType="AUDIOBOOK"), item("two")]),
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

    def test_does_not_use_read_page_as_original_publisher_url(self):
        client = self.pro_client(
            self.stable_brief(),
            [[
                metadata("one", url="https://bad host.example/item", readUrl="https://reader.example.com/one"),
                metadata("two"),
            ]],
        )

        with self.assertRaisesRegex(brief.BriefError, "resource HTTPS URL"):
            brief.read_today(client, "2026-07-24", clock=lambda: "2026-07-24T09:10:11Z")

    def test_requires_explicit_boolean_selection_flags(self):
        for field, value in (
            ("deepRead", None),
            ("deepRead", "false"),
            ("featured", 1),
            ("personalized", 0.0),
            ("missing-deepRead", None),
            ("missing-featured", None),
            ("missing-personalized", None),
        ):
            with self.subTest(field=field, value=value):
                brief_item = item("one")
                if field.startswith("missing-"):
                    del brief_item[field.removeprefix("missing-")]
                else:
                    brief_item[field] = value
                client = self.pro_client(self.stable_brief(items=[brief_item]), [[metadata("one")]])

                with self.assertRaisesRegex(brief.BriefError, "deepRead|featured|personalized"):
                    brief.read_today(client, "2026-07-24")

    def test_requires_finite_conservative_read_time_and_score_ranges(self):
        for field, value, message in (
            ("readTime", -1, "read time"),
            ("readTime", 1441, "read time"),
            ("readTime", float("inf"), "read time"),
            ("totalScore", -1_000_001, "score"),
            ("totalScore", 1_000_001, "score"),
            ("totalScore", float("nan"), "score"),
        ):
            with self.subTest(field=field, value=value):
                brief_changes = {field: value} if field == "totalScore" else {}
                metadata_changes = {field: value} if field == "readTime" else {}
                client = self.pro_client(
                    self.stable_brief(items=[item("one", **brief_changes)]),
                    [[metadata("one", **metadata_changes)]],
                )

                with self.assertRaisesRegex(brief.BriefError, message):
                    brief.read_today(client, "2026-07-24")

        client = self.pro_client(
            self.stable_brief(items=[item("one", totalScore=-1_000_000)]),
            [[metadata("one", readTime=1440)]],
        )
        result = brief.read_today(client, "2026-07-24")
        self.assertEqual(result["items"][0]["readTime"], 1440)
        self.assertEqual(result["items"][0]["score"], -1_000_000)
        self.assertIsNone(brief._number_or_none(None, "score", -1_000_000, 1_000_000))
        self.assertEqual(brief._number_or_none(1.5, "score", -1_000_000, 1_000_000), 1.5)

    def test_rejects_non_standard_json_numbers_and_never_serializes_them(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/resources/batch-meta"
        client._opener = FakeOpener([
            FakeResponse(b'{"success":true,"code":null,"message":null,"requestId":"request","data":NaN}', url),
        ])
        with self.assertRaisesRegex(brief.BriefError, "invalid JSON"):
            client.batch_meta(["one"])

        valid = json.dumps({"success": True, "code": None, "message": None, "requestId": "request", "data": []}).encode()
        client._opener = FakeOpener([FakeResponse(valid, url)])
        with self.assertRaises(ValueError):
            client._request("POST", "/resources/batch-meta", {"ids": [float("nan")]})

    def test_emits_a_golden_trimmed_canonical_utc_envelope(self):
        today = self.stable_brief(items=[item(
            "one", sourceId=" brief-source ", sourceName=" Brief source ", title=" Brief title ",
            contentType="article", totalScore=1.25, deepRead=True, featured=False, personalized=True,
        )])
        today.update({
            "generatedAt": "2026-07-24T09:10:11.120+08:00",
            "editorIntro": "  Today\'s picks  ",
            "keywords": [" models ", " systems "],
        })
        client = self.pro_client(today, [[metadata(
            "one", originalUrl="https://publisher.example.com/original", url="https://bestblogs.dev/reader/one",
            cover="https://image.jido.dev/one.jpg", publishDateTimeStr="2026-07-24T01:02:03.004+00:00",
            readTime=5, tags=[" AI "], oneSentenceSummary=" concise ", summary=" summary ", mainPoints=[" point "],
        )]])

        self.assertEqual(brief.read_today(client, "2026-07-24"), {
            "schemaVersion": 1,
            "briefDate": "2026-07-24",
            "status": "PUBLISHED",
            "generatedAt": "2026-07-24T01:10:11.120000Z",
            "editorIntro": "Today\'s picks",
            "keywords": ["models", "systems"],
            "items": [{
                "resourceId": "one",
                "sourceId": "brief-source",
                "sourceName": "Brief source",
                "title": "Brief title",
                "contentType": "ARTICLE",
                "url": "https://publisher.example.com/original",
                "coverUrl": "https://image.jido.dev/one.jpg",
                "publishedAt": "2026-07-24T01:02:03.004000Z",
                "readTime": 5,
                "score": 1.25,
                "tags": ["AI"],
                "oneSentenceSummary": "concise",
                "summary": "summary",
                "mainPoints": ["point"],
                "deepRead": True,
                "featured": False,
                "personalized": True,
            }],
        })

    def test_rejects_blank_or_nul_text_and_non_zoned_timestamps(self):
        for target, value, message in (
            ("title", " \t ", "title"),
            ("title", "bad\x00title", "title"),
            ("summary", " \n ", "summary"),
            ("summary", "bad\x00summary", "summary"),
            ("generatedAt", "2026-07-24", "generatedAt"),
            ("generatedAt", "2026-07-24T01:02:03", "generatedAt"),
            ("generatedAt", "2026-02-30T01:02:03Z", "generatedAt"),
            ("publishDateTimeStr", "2026-07-24", "publication time"),
            ("publishDateTimeStr", "2026-07-24T01:02:03", "publication time"),
            ("publishDateTimeStr", "2026-02-30T01:02:03Z", "publication time"),
        ):
            with self.subTest(target=target, value=value):
                today = self.stable_brief(items=[item("one")])
                metadata_changes = {}
                if target in ("title", "summary"):
                    if target == "title":
                        today["contentItems"] = [item("one", title=value)]
                    else:
                        metadata_changes[target] = value
                elif target == "generatedAt":
                    today[target] = value
                else:
                    metadata_changes[target] = value
                client = self.pro_client(today, [[metadata("one", **metadata_changes)]])

                with self.assertRaisesRegex(brief.BriefError, message):
                    brief.read_today(client, "2026-07-24")

    def test_rejects_non_public_and_bestblogs_item_urls_but_omits_unsafe_covers(self):
        for unsafe in (
            "https://bestblogs.dev/reader/one",
            "https://api.bestblogs.dev/reader/one",
            "https://localhost/one",
            "https://service.localhost/one",
            "https://service.local/one",
            "https://service.internal/one",
            "https://127.0.0.1/one",
            "https://10.0.0.1/one",
            "https://169.254.1.1/one",
            "https://192.0.2.1/one",
            "https://224.0.0.1/one",
            "https://0.0.0.0/one",
            "https://[::1]/one",
        ):
            with self.subTest(unsafe=unsafe):
                client = self.pro_client(self.stable_brief(items=[item("one")]), [[
                    metadata("one", url=unsafe, readUrl="https://publisher.example.com/one"),
                ]])
                with self.assertRaisesRegex(brief.BriefError, "resource HTTPS URL"):
                    brief.read_today(client, "2026-07-24")

        client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", cover="https://127.0.0.1/image.jpg"),
        ]])
        result = brief.read_today(client, "2026-07-24")
        self.assertNotIn("coverUrl", result["items"][0])

    def test_rejects_url_controls_del_and_backslash_in_items_and_covers(self):
        for unsafe in (
            "https://publisher.example.com/\x00item",
            "https://publisher.example.com/\x01item",
            "https://publisher.example.com/\x1fitem",
            "https://publisher.example.com/\x7fitem",
            "https://publisher.example.com/path\\item",
        ):
            with self.subTest(unsafe=repr(unsafe)):
                self.assert_unsafe_item_url_and_omitted_cover(unsafe)

    def test_rejects_empty_fragments_and_bracketed_non_ip_authorities(self):
        for unsafe in (
            "https://x.com/item#",
            "https://[x.com]/item",
            "https://[v1.foo]/item",
        ):
            with self.subTest(unsafe=unsafe):
                self.assert_unsafe_item_url_and_omitted_cover(unsafe)

    def test_rejects_legacy_numeric_and_noncanonical_ip_authorities(self):
        for unsafe in (
            "https://127.1/item",
            "https://2130706433/item",
            "https://0x7f000001/item",
            "https://0177.0.0.1/item",
            "https://[8.8.8.8]/item",
            "https://[2606:4700:4700:0000:0000:0000:0000:1111]/item",
        ):
            with self.subTest(unsafe=unsafe):
                self.assert_unsafe_item_url_and_omitted_cover(unsafe)

    def test_rejects_special_transition_and_scoped_ip_authorities(self):
        for unsafe in (
            "https://192.88.99.1/item",
            "https://[2002:808:808::]/item",
            "https://[2002:7f00:1::]/item",
            "https://[2606:4700:4700::1111%25eth0]/item",
            "https://[::ffff:7f00:1]/item",
            "https://[64:ff9b::7f00:1]/item",
            "https://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/item",
        ):
            with self.subTest(unsafe=unsafe):
                self.assert_unsafe_item_url_and_omitted_cover(unsafe)

    def test_rejects_single_label_internal_and_wildcard_alias_hosts(self):
        for unsafe in (
            "https://printer/item",
            "https://service.bestblogs.dev/item",
            "https://service.localhost/item",
            "https://service.local/item",
            "https://service.internal/item",
            "https://service.intranet/item",
            "https://service.private/item",
            "https://service.invalid/item",
            "https://service.localdomain/item",
            "https://service.lan/item",
            "https://service.home/item",
            "https://service.corp/item",
            "https://home.arpa/item",
            "https://service.svc/item",
            "https://service.onion/item",
            "https://service.test/item",
            "https://service.example/item",
            "https://nip.io/item",
            "https://127.0.0.1.nip.io/item",
            "https://sslip.io/item",
            "https://127-0-0-1.sslip.io/item",
            "https://xip.io/item",
            "https://127.0.0.1.xip.io/item",
            "https://localtest.me/item",
            "https://app.localtest.me/item",
            "https://lvh.me/item",
            "https://app.lvh.me/item",
            "https://localhost.direct/item",
            "https://app.localhost.direct/item",
            "https://local.gd/item",
            "https://app.local.gd/item",
            "https://vcap.me/item",
            "https://app.vcap.me/item",
            "https://traefik.me/item",
            "https://app.traefik.me/item",
            "https://my.local-ip.co/item",
            "https://app.my.local-ip.co/item",
            "https://local-ip.sh/item",
            "https://app.local-ip.sh/item",
            "https://nar0.com/item",
            "https://app.nar0.com/item",
        ):
            with self.subTest(unsafe=unsafe):
                self.assert_unsafe_item_url_and_omitted_cover(unsafe)

    def test_accepts_known_public_web_and_canonical_ip_destinations(self):
        for safe in (
            "https://x.com/example/status/1",
            "https://www.youtube.com/watch?v=example",
            "https://pbs.twimg.com/media/example.jpg",
            "https://video.twimg.com/ext_tw_video/example.mp4",
            "https://8.8.8.8/item",
            "https://[2606:4700:4700::1111]/item",
        ):
            with self.subTest(safe=safe):
                client = self.pro_client(self.stable_brief(items=[item("one")]), [[
                    metadata("one", url=safe, cover=None),
                ]])

                result = brief.read_today(client, "2026-07-24")
                self.assertEqual(result["items"][0]["url"], safe)

    def test_accepts_case_insensitive_https_scheme(self):
        client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", url="HTTPS://X.COM/example/status/1", cover=None),
        ]])

        result = brief.read_today(client, "2026-07-24")
        self.assertEqual(result["items"][0]["url"], "HTTPS://X.COM/example/status/1")

    def test_upgrades_safe_authoritative_http_publisher_url_to_https(self):
        client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata(
                "one",
                url="http://www.ruanyifeng.com/blog/2026/07/weekly-issue-405.html",
                readUrl="https://www.bestblogs.dev/article/example",
                cover=None,
            ),
        ]])

        result = brief.read_today(client, "2026-07-24")
        self.assertEqual(
            result["items"][0]["url"],
            "https://www.ruanyifeng.com/blog/2026/07/weekly-issue-405.html",
        )

    def test_rejects_unsafe_authoritative_http_urls_and_never_upgrades_covers(self):
        for unsafe in (
            "http://user@publisher.example.com/item",
            "http://publisher.example.com:80/item",
            "http://publisher.example.com/item#",
            "http://publisher.example.com/\x00item",
            "http://localhost/item",
        ):
            with self.subTest(unsafe=repr(unsafe)):
                client = self.pro_client(self.stable_brief(items=[item("one")]), [[
                    metadata("one", url=unsafe, cover=None),
                ]])
                with self.assertRaisesRegex(brief.BriefError, "resource HTTPS URL"):
                    brief.read_today(client, "2026-07-24")

        client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", cover="http://image.jido.dev/image.jpg"),
        ]])
        result = brief.read_today(client, "2026-07-24")
        self.assertNotIn("coverUrl", result["items"][0])

    def test_only_emits_allowlisted_public_cover_hosts(self):
        for cover in (
            "https://image.jido.dev/image.jpg",
            "https://i1.ytimg.com/image.jpg",
            "https://i4.ytimg.com/image.jpg",
            "https://storage.googleapis.com/bucket/image.jpg",
            "https://res.infoq.com/image.jpg",
            "https://pbs.twimg.com/media/image.jpg",
            "https://mmbiz.qpic.cn/image.jpg",
        ):
            with self.subTest(cover=cover):
                client = self.pro_client(self.stable_brief(items=[item("one")]), [[
                    metadata("one", cover=cover),
                ]])

                result = brief.read_today(client, "2026-07-24")
                self.assertEqual(result["items"][0]["coverUrl"], cover)

    def test_omits_unlisted_cover_hosts_even_when_public(self):
        for cover in (
            "https://media.bestblogs.dev/image.jpg",
            "https://ytimg.com/image.jpg",
            "https://x.com/image.jpg",
            "https://video.twimg.com/image.jpg",
            "https://images.example.com/image.jpg",
            "https://sub.image.jido.dev/image.jpg",
            "https://evilstorage.googleapis.com/image.jpg",
            "https://8.8.8.8/image.jpg",
            "https://[2606:4700:4700::1111]/image.jpg",
        ):
            with self.subTest(cover=cover):
                client = self.pro_client(self.stable_brief(items=[item("one")]), [[
                    metadata("one", cover=cover),
                ]])

                result = brief.read_today(client, "2026-07-24")
                self.assertNotIn("coverUrl", result["items"][0])

    def test_rejects_read_only_metadata_without_an_authoritative_publisher_url(self):
        client = self.pro_client(self.stable_brief(items=[item("one")]), [[
            metadata("one", url=None, readUrl="https://publisher.example.com/one"),
        ]])

        with self.assertRaisesRegex(brief.BriefError, "resource HTTPS URL"):
            brief.read_today(client, "2026-07-24")

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
