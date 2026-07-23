import importlib.util
import copy
import hashlib
import http.client
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError


MODULE = Path(__file__).parents[1] / "plugins/web-data-tools/skills/wechat-digest/scripts/wechat_digest.py"
SKILL_DIR = MODULE.parents[1]
SKILL_FILE = SKILL_DIR / "SKILL.md"
METADATA_FILE = SKILL_DIR / "agents/openai.yaml"
WRAPPER_FILE = SKILL_DIR / "scripts/run_wechat_digest.sh"
PLUGIN_FILE = MODULE.parents[3] / ".codex-plugin/plugin.json"
SPEC = importlib.util.spec_from_file_location("wechat_digest", MODULE)
wechat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wechat)
VALID_API_KEY = "bb_" + "1" * 32
CLAIM_ID = "a" * 32


def add_claim(entry, claim_id=CLAIM_ID, expires_at="2099-01-01T00:00:00Z"):
    entry["claim_id"] = claim_id
    entry["claim_expires_at"] = expires_at
    return entry


class FakeClient:
    def __init__(self, pages=None, markdown="# body"):
        self.pages = list(pages or [])
        self.markdown_body = markdown
        self.calls = {}

    def subscription_page(self, page, page_size, before_attempt=None):
        if before_attempt is not None:
            before_attempt()
        self.calls["subscription"] = self.calls.get("subscription", 0) + 1
        return self.pages[page - 1] if page <= len(self.pages) else {"dataList": []}

    def markdown(self, resource_id, before_attempt=None):
        if before_attempt is not None:
            before_attempt()
        self.calls["markdown"] = self.calls.get("markdown", 0) + 1
        return self.markdown_body

    def me(self, before_attempt=None):
        if before_attempt is not None:
            before_attempt()
        self.calls["me"] = self.calls.get("me", 0) + 1
        return {"userTier": "pro", "id": "private-user", "email": "secret@example.com"}


class FakeResponse:
    def __init__(self, payload, url, status=200):
        self.payload, self.url, self.status = payload, url, status

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


def record(resource_id="r1", source_id="s1", when=1710000000000, url=None):
    if url is None:
        token = hashlib.sha256(str(resource_id).encode("utf-8")).hexdigest()[:16]
        url = "https://mp.weixin.qq.com/s/%s?utm_source=x" % token
    return {
        "id": resource_id,
        "sourceId": source_id,
        "sourceName": "Source One",
        "resourceType": "article",
        "url": url,
        "publishTime": when,
        "title": "An article",
    }


class WechatDigestTests(unittest.TestCase):
    def state_file(self):
        path = Path(tempfile.mkdtemp()) / "nested" / "digest.json"
        self.addCleanup(lambda: path.parent.parent.exists() and __import__("shutil").rmtree(path.parent.parent))
        return path

    def test_client_rejects_bad_envelopes_auth_errors_and_redirects(self):
        self.assertRaises(wechat.APIError, wechat.validate_envelope, {"success": True})
        self.assertRaises(wechat.APIError, wechat.validate_envelope,
                          {"success": False, "code": 401, "message": "bad", "requestId": "r", "data": {}})
        self.assertRaises(ValueError, wechat.BestBlogsClient, "short")
        self.assertRaises(ValueError, wechat.BestBlogsClient, "k", "https://elsewhere.invalid")

    def test_client_accepts_only_official_api_key_format_without_echoing_input(self):
        self.assertIsInstance(wechat.BestBlogsClient(VALID_API_KEY), wechat.BestBlogsClient)
        for invalid in (
            "valid-key", "bb_" + "1" * 31, "bb_" + "1" * 33,
            "bb_" + "g" * 32, "bb_" + "1" * 31 + "\nprivate-tail",
        ):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError) as caught:
                    wechat.BestBlogsClient(invalid)
                self.assertNotIn(invalid, str(caught.exception))

    def test_cli_rejects_newline_api_key_before_request_without_leaking_it(self):
        path = self.state_file()
        bad_key = "bb_" + "1" * 31 + "\nprivate-tail"
        old_key = os.environ.get("BESTBLOGS_API_KEY")
        original_request = wechat.Request
        requests = []
        os.environ["BESTBLOGS_API_KEY"] = bad_key
        wechat.Request = lambda *args, **kwargs: requests.append((args, kwargs))
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "doctor"])
        finally:
            wechat.Request = original_request
            if old_key is None:
                os.environ.pop("BESTBLOGS_API_KEY", None)
            else:
                os.environ["BESTBLOGS_API_KEY"] = old_key
        self.assertEqual(result, 2)
        self.assertEqual(requests, [])
        self.assertNotIn("private-tail", output.getvalue())
        self.assertIn("invalid BestBlogs API key", output.getvalue())

    def test_client_uses_documented_v2_get_contract_and_null_success_envelope(self):
        self.assertEqual(wechat.API_ORIGIN, "https://api.bestblogs.dev/openapi/v2")
        client = wechat.BestBlogsClient(VALID_API_KEY)
        body = json.dumps({"success": True, "code": None, "message": None, "requestId": "r", "data": {"ok": True}}).encode()
        opener = FakeOpener([FakeResponse(body, wechat.API_ORIGIN + "/me/feeds/subscriptions?page=2&pageSize=25&timeFilter=week")])
        client._opener = opener
        self.assertEqual(client.subscription_page(2, 25), {"ok": True})
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, wechat.API_ORIGIN + "/me/feeds/subscriptions?page=2&pageSize=25&timeFilter=week")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-api-key"), VALID_API_KEY)

    def test_default_subscription_page_size_stays_within_the_live_api_ceiling(self):
        self.assertEqual(wechat.DEFAULT_PAGE_SIZE, 50)

    def test_client_filters_incremental_feed_pages_by_one_safe_source_id(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "r",
            "data": {"dataList": []},
        }).encode()
        expected_url = (
            wechat.API_ORIGIN
            + "/me/feeds/subscriptions?page=2&pageSize=50&sourceId=SOURCE_e24314"
        )
        opener = FakeOpener([FakeResponse(body, expected_url)])
        client._opener = opener

        self.assertEqual(client.subscription_source_page(2, 50, "SOURCE_e24314"), {"dataList": []})

        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, expected_url)
        self.assertEqual(request.get_method(), "GET")
        for source_id in ("", "bad\nsource"):
            with self.subTest(source_id=repr(source_id)):
                with self.assertRaises(ValueError):
                    client.subscription_source_page(1, 50, source_id)
        self.assertEqual(len(opener.requests), 1)

    def test_client_searches_sources_with_the_documented_bounded_get_contract(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "r",
            "data": {"dataList": [], "totalCount": 0},
        }).encode()
        expected_url = (
            wechat.API_ORIGIN
            + "/search?q=%E6%96%B0%E6%99%BA%E5%85%83&language=zh_CN&page=1&pageSize=50"
        )
        opener = FakeOpener([FakeResponse(body, expected_url)])
        client._opener = opener

        self.assertEqual(client.source_search("新智元"), {"dataList": [], "totalCount": 0})

        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, expected_url)
        self.assertEqual(request.get_method(), "GET")

    def test_client_reads_resource_metadata_with_a_fixed_origin_get(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        expected_url = wechat.API_ORIGIN + "/resources/article-1/meta"
        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "r", "data": record("article-1"),
        }).encode()
        opener = FakeOpener([FakeResponse(body, expected_url)])
        client._opener = opener

        self.assertEqual(client.resource_metadata("article-1")["id"], "article-1")
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, expected_url)
        self.assertEqual(request.get_method(), "GET")
        with self.assertRaises(ValueError):
            client.resource_metadata("unsafe\nresource")
        self.assertEqual(len(opener.requests), 1)

    def test_client_follow_is_bounded_and_fixed_to_the_documented_endpoint(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "r",
            "data": {"followedCount": 3, "skippedCount": 0},
        }).encode()
        url = wechat.API_ORIGIN + "/me/onboarding/follow"
        opener = FakeOpener([FakeResponse(body, url)])
        client._opener = opener
        reservations = []

        result = client.follow_sources(
            ["SOURCE_one", "SOURCE_two", "SOURCE_three"],
            before_attempt=lambda: reservations.append(True),
        )

        self.assertEqual(result, {"followedCount": 3, "skippedCount": 0})
        self.assertEqual(reservations, [True])
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"sourceIds": ["SOURCE_one", "SOURCE_two", "SOURCE_three"]},
        )
        for invalid in ([], ["same", "same"], ["bad\nsource"], ["s%d" % i for i in range(11)]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    client.follow_sources(invalid)
        self.assertEqual(len(opener.requests), 1)

    def test_client_follow_rejects_redirect_retries_one_429_and_does_not_retry_network_failure(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        url = wechat.API_ORIGIN + "/me/onboarding/follow"
        envelope = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "r",
            "data": {
                "requestedCount": 1,
                "successCount": 1,
                "alreadySubscribedCount": 0,
                "failedCount": 0,
            },
        }).encode()

        reservations = []
        redirected = FakeOpener([FakeResponse(envelope, "https://elsewhere.invalid/follow")])
        client._opener = redirected
        with self.assertRaises(wechat.APIError):
            client.follow_sources(["SOURCE_one"], before_attempt=lambda: reservations.append(True))
        self.assertEqual(len(redirected.requests), 1)
        self.assertEqual(reservations, [True])

        rate_limited = HTTPError(url, 429, "slow", {"Retry-After": "0"}, None)
        retried = FakeOpener([rate_limited, FakeResponse(envelope, url)])
        client._opener = retried
        reservations = []
        original_sleep = wechat.time.sleep
        wechat.time.sleep = lambda delay: None
        try:
            self.assertEqual(
                client.follow_sources(
                    ["SOURCE_one"], before_attempt=lambda: reservations.append(True),
                )["successCount"],
                1,
            )
        finally:
            wechat.time.sleep = original_sleep
        self.assertEqual(len(retried.requests), 2)
        self.assertEqual(reservations, [True, True])

        failed = FakeOpener([URLError("offline")])
        client._opener = failed
        reservations = []
        with self.assertRaises(wechat.APIError):
            client.follow_sources(["SOURCE_one"], before_attempt=lambda: reservations.append(True))
        self.assertEqual(len(failed.requests), 1)
        self.assertEqual(reservations, [True])

    def test_client_rejects_redirect_and_oversized_response_and_retries_one_429(self):
        client = wechat.BestBlogsClient(VALID_API_KEY)
        envelope = json.dumps({"success": True, "code": None, "message": None, "requestId": "r", "data": {}}).encode()
        client._opener = FakeOpener([FakeResponse(envelope, "https://elsewhere.invalid/me")])
        with self.assertRaises(wechat.APIError):
            client.me()
        client._opener = FakeOpener([FakeResponse(b"x" * (wechat.MAX_BODY_BYTES + 1), wechat.API_ORIGIN + "/me")])
        with self.assertRaises(wechat.APIError):
            client.me()
        rate_limited = HTTPError(wechat.API_ORIGIN + "/me", 429, "slow", {"Retry-After": "0"}, None)
        opener = FakeOpener([rate_limited, FakeResponse(envelope, wechat.API_ORIGIN + "/me")])
        client._opener = opener
        original_sleep = wechat.time.sleep
        wechat.time.sleep = lambda delay: None
        try:
            self.assertEqual(client.me(), {})
        finally:
            wechat.time.sleep = original_sleep
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(client.calls["/me"], 4)

    def test_normalizes_safe_wechat_identity_and_schema_drift(self):
        article = wechat.parse_article(record(
            resource_id=None, when="2024-03-09T12:00:00Z",
            url="https://mp.weixin.qq.com/s/a?utm_source=x",
        ))
        self.assertIsNotNone(article)
        self.assertTrue(article["identity"].startswith("url:"))
        self.assertEqual(article["url"], "https://mp.weixin.qq.com/s/a")
        with_id = wechat.parse_article(record(
            resource_id="r1", url="https://mp.weixin.qq.com/s/stable-url",
        ))
        self.assertEqual(with_id["identity"], "url:" + hashlib.sha256(
            b"https://mp.weixin.qq.com/s/stable-url",
        ).hexdigest())
        self.assertEqual(with_id["resource_id"], "r1")
        self.assertIsNone(wechat.parse_article(record(url="https://example.com/a")))
        self.assertIsNone(wechat.parse_article({"resourceId": "x", "resourceType": "video"}))
        drifted = record(resource_id=None)
        drifted["resourceId"] = "r2"
        drifted.pop("id")
        drifted.pop("publishTime")
        drifted["publishDateStr"] = "2024-03-09"
        self.assertEqual(wechat.parse_article(drifted)["resource_id"], "r2")
        stamped = record(when=None)
        stamped.pop("publishTime")
        stamped["publishTimeStamp"] = 1710000000000
        self.assertTrue(wechat.parse_article(stamped)["published_at"])
        for unsafe in ("http://mp.weixin.qq.com/s/a", "https://user@mp.weixin.qq.com/s/a", "https://mp.weixin.qq.com:444/s/a", "https://foo.weixin.qq.com/s/a"):
            self.assertIsNone(wechat.canonical_wechat_url(unsafe))
        self.assertIsNone(wechat.parse_article({"source": [], "url": "https://mp.weixin.qq.com/s/a"}))

    def test_hostile_time_and_url_values_fail_closed_without_escaping_scan(self):
        hostile_records = []
        huge_integer = record("huge-integer")
        huge_integer["publishTime"] = 10 ** 1000
        hostile_records.append(huge_integer)
        huge_string = record("huge-string")
        huge_string["publishTime"] = "9" * 5000
        hostile_records.append(huge_string)
        invalid_url = record("invalid-url")
        invalid_url["url"] = "https://[::1"
        hostile_records.append(invalid_url)
        for raw in hostile_records:
            with self.subTest(raw_id=raw["id"]):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                try:
                    result = wechat.scan(state, FakeClient([{"dataList": [raw]}]))
                except (OverflowError, ValueError) as error:
                    self.fail("hostile remote value escaped fail-closed handling: %s" % error)
                self.assertFalse(result["complete"])
                self.assertIn("skipped_malformed_records:1", result["warnings"])
                self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_canonical_wechat_url_accepts_only_article_paths(self):
        self.assertEqual(
            wechat.canonical_wechat_url(
                "https://mp.weixin.qq.com/s?sn=deadbeef&idx=1&scene=1&mid=123&__biz=MzA123"
            ),
            "https://mp.weixin.qq.com/s?__biz=MzA123&idx=1&mid=123&sn=deadbeef",
        )
        self.assertEqual(
            wechat.canonical_wechat_url("https://mp.weixin.qq.com/s/Article_token-123"),
            "https://mp.weixin.qq.com/s/Article_token-123",
        )
        self.assertEqual(
            wechat.canonical_wechat_url(
                "https://mp.weixin.qq.com/s/Article_token-123?srcid=private&sharer_shareinfo=x&sessionid=y"
            ),
            "https://mp.weixin.qq.com/s/Article_token-123",
        )
        self.assertEqual(
            wechat.canonical_wechat_url(
                "https://mp.weixin.qq.com/s?__biz=MzA123&mid=123&idx=1&sn=deadbeef"
                "&srcid=private&sharer_shareinfo=x&sessionid=y"
            ),
            "https://mp.weixin.qq.com/s?__biz=MzA123&idx=1&mid=123&sn=deadbeef",
        )
        for non_article in (
            "https://mp.weixin.qq.com/",
            "https://mp.weixin.qq.com/mp/profile_ext?action=home",
            "https://mp.weixin.qq.com/s/",
            "https://mp.weixin.qq.com/something",
        ):
            self.assertIsNone(wechat.canonical_wechat_url(non_article), non_article)

    def test_canonical_wechat_url_rejects_ambiguous_and_encoded_article_paths(self):
        for unsafe in (
            "https://mp.weixin.qq.com/s",
            "https://mp.weixin.qq.com/s?__biz=MzA123&mid=123&idx=1",
            "https://mp.weixin.qq.com/s?__biz=MzA123&mid=123&idx=1&sn=",
            "https://mp.weixin.qq.com/s/..",
            "https://mp.weixin.qq.com/s/../",
            "https://mp.weixin.qq.com/s//",
            "https://mp.weixin.qq.com/s/a/b",
            "https://mp.weixin.qq.com/s/a.b",
            "https://mp.weixin.qq.com/s;ignored?__biz=MzA123&mid=123&idx=1&sn=deadbeef",
            "https://mp.weixin.qq.com/s/token;ignored",
            "https://mp.weixin.qq.com/s/%2e%2e",
            "https://mp.weixin.qq.com/s/%252e%252e",
            "https://mp.weixin.qq.com/s/%2F",
            "https://mp.weixin.qq.com/s/a%2Fb",
        ):
            self.assertIsNone(wechat.canonical_wechat_url(unsafe), unsafe)

    def test_article_urls_allow_only_wechat_and_two_exact_official_mirror_shapes(self):
        allowed = {
            "https://www.qbitai.com/2025/08/324282.html":
                "https://www.qbitai.com/2025/08/324282.html",
            "https://www.jiqizhixin.com/articles/2025-09-18-5":
                "https://www.jiqizhixin.com/articles/2025-09-18-5",
            "https://mp.weixin.qq.com/s/token": "https://mp.weixin.qq.com/s/token",
        }
        for raw, expected in allowed.items():
            with self.subTest(raw=raw):
                self.assertEqual(wechat.canonical_article_url(raw), expected)
                parsed = wechat.parse_article(record(url=raw))
                self.assertEqual(parsed["url"], expected)
        for unsafe in (
            "https://qbitai.com/2025/08/324282.html",
            "https://www.qbitai.com/",
            "https://www.qbitai.com/2025/08/324282.html?next=evil",
            "https://www.qbitai.com/2025/08/%2e%2e.html",
            "https://www.jiqizhixin.com/articles/",
            "https://www.jiqizhixin.com/articles/2025-09-18-5?next=evil",
            "https://user@www.jiqizhixin.com/articles/2025-09-18-5",
            "https://example.com/articles/2025-09-18-5",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(wechat.canonical_article_url(unsafe))

    def test_paginate_terminates_and_reports_unique_sources(self):
        client = FakeClient([
            {"dataList": [record("r1"), record("r2", "s2")], "total": 3},
            {"dataList": [record("r3")], "total": 3},
        ])
        result = wechat.list_sources(client, page_size=2)
        self.assertEqual([s["id"] for s in result["sources"]], ["s1", "s2"])
        self.assertEqual(client.calls["subscription"], 2)
        self.assertEqual(result["skipped"], {"invalid_or_non_wechat": 0})

    def test_source_search_returns_only_exact_unique_safe_source_matches(self):
        class SearchClient:
            def source_search(self, name, before_attempt=None):
                self.name = name
                if before_attempt is not None:
                    before_attempt()
                return {"dataList": [
                    {"sourceId": "SOURCE_one", "sourceName": "新智元", "url": "https://mp.weixin.qq.com/s/one"},
                    {"sourceId": "SOURCE_one", "sourceName": "新智元", "url": "https://mp.weixin.qq.com/s/two"},
                    {"sourceId": "SOURCE_other", "sourceName": "新智元研究院"},
                    {"sourceId": "bad\nsource", "sourceName": "新智元"},
                ]}

        client = SearchClient()
        reservations = []
        result = wechat.search_sources(client, "新智元", before_attempt=lambda: reservations.append(True))

        self.assertEqual(client.name, "新智元")
        self.assertEqual(reservations, [True])
        self.assertEqual(result, {"sources": [{"id": "SOURCE_one", "name": "新智元"}]})

    def test_source_search_rejects_ambiguous_exact_name_matches(self):
        class SearchClient:
            def source_search(self, name, before_attempt=None):
                return {"dataList": [
                    {"sourceId": "SOURCE_one", "sourceName": name},
                    {"sourceId": "SOURCE_two", "sourceName": name},
                ]}

        with self.assertRaisesRegex(wechat.APIError, "ambiguous"):
            wechat.search_sources(SearchClient(), "新智元")

    def test_source_search_rejects_missing_exact_name_match(self):
        class SearchClient:
            def source_search(self, name, before_attempt=None):
                return {"dataList": [
                    {"sourceId": "SOURCE_other", "sourceName": name + "研究院"},
                ]}

        with self.assertRaisesRegex(wechat.APIError, "no exact"):
            wechat.search_sources(SearchClient(), "新智元")

    def test_follow_receipt_is_sanitized_and_rejects_impossible_counters(self):
        class FollowClient:
            def __init__(self, receipt):
                self.receipt = receipt

            def follow_sources(self, source_ids, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return self.receipt

        reservations = []
        self.assertEqual(
            wechat.follow_selected_sources(
                FollowClient({"followedCount": 3, "skippedCount": 0, "remote": "untrusted"}),
                ["s1", "s2", "s3"],
                before_attempt=lambda: reservations.append(True),
            ),
            {"followedCount": 3, "skippedCount": 0},
        )
        self.assertEqual(reservations, [True])
        self.assertEqual(
            wechat.follow_selected_sources(
                FollowClient({
                    "requestedCount": 3,
                    "successCount": 0,
                    "alreadySubscribedCount": 3,
                    "failedCount": 0,
                    "remote": "untrusted",
                }),
                ["s1", "s2", "s3"],
            ),
            {
                "requestedCount": 3,
                "successCount": 0,
                "alreadySubscribedCount": 3,
                "failedCount": 0,
            },
        )
        for receipt in (
            None,
            {"followedCount": True, "skippedCount": 0},
            {"followedCount": 4, "skippedCount": 0},
            {"followedCount": 1, "skippedCount": 1},
            {"followedCount": 2, "skippedCount": 1},
            {
                "requestedCount": 3,
                "successCount": 2,
                "alreadySubscribedCount": 0,
                "failedCount": 1,
            },
            {
                "followedCount": 3,
                "skippedCount": 0,
                "requestedCount": 3,
                "successCount": 2,
                "alreadySubscribedCount": 0,
                "failedCount": 1,
            },
        ):
            with self.subTest(receipt=receipt):
                with self.assertRaises(wechat.APIError):
                    wechat.follow_selected_sources(FollowClient(receipt), ["s1", "s2", "s3"])

    def test_sources_keep_safe_feed_source_when_an_article_is_skipped(self):
        skipped = record("video")
        skipped["resourceType"] = "video"
        result = wechat.list_sources(FakeClient([{ "dataList": [skipped] }]))
        self.assertEqual(result["sources"], [{"id": "s1", "name": "Source One"}])
        self.assertEqual(result["skipped"], {"invalid_or_non_wechat": 1})

    def test_first_scan_baselines_then_later_scan_enqueues_and_deduplicates(self):
        path = self.state_file()
        state = wechat.load_state(path)
        wechat.configure_sources(state, ["s1"])
        first = wechat.scan(state, FakeClient([{"dataList": [record("r1")]}]))
        self.assertTrue(first["complete"])
        self.assertEqual(state["pending"], {})
        self.assertTrue(state["sources"]["s1"]["initialized"])
        later = wechat.scan(state, FakeClient([{"dataList": [record("r1"), record("r2")]}]))
        self.assertEqual(later["enqueued"], 1)
        self.assertEqual(list(state["pending"]), [wechat.parse_article(record("r2"))["identity"]])
        self.assertEqual(state["api_calls"]["subscription"], 2)

    def test_scan_without_configured_sources_fails_before_network(self):
        state = wechat.new_state()
        client = FakeClient([{"dataList": [record("r1")]}])

        with self.assertRaisesRegex(wechat.StateError, "configure at least one source"):
            wechat.scan(state, client)

        self.assertEqual(client.calls, {})
        self.assertFalse(state["scan_health"]["complete"])

    def test_cli_scan_without_configured_sources_does_not_build_client_or_advance_sequence(self):
        path = self.state_file()
        wechat.save_state(path, wechat.new_state())
        original_client = wechat._client_from_env
        built = []
        wechat._client_from_env = lambda: built.append(True)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(
                    wechat.main(["--state-file", str(path), "scan"]),
                    2,
                )
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(built, [])
        self.assertIn("configure at least one source", json.loads(output.getvalue())["error"])
        self.assertEqual(wechat.load_state(path)["next_scan_seq"], 0)

    def test_first_scan_establishes_one_page_frontier_for_each_source(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1", "s2"])

        class PerSourceClient:
            def __init__(self):
                self.calls = {}
                self.source_calls = []

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                self.source_calls.append((source_id, page, page_size))
                return {
                    "dataList": [record("%s-%d" % (source_id, index), source_id) for index in range(50)],
                    "totalCount": 1996,
                    "pageCount": 40,
                }

        client = PerSourceClient()
        result = wechat.scan(state, client)

        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(state["scan_health"]["pages"], 2)
        self.assertEqual(client.source_calls, [("s1", 1, 50), ("s2", 1, 50)])
        self.assertTrue(all(source["initialized"] for source in state["sources"].values()))
        self.assertTrue(all(len(source["recent"]) == 50 for source in state["sources"].values()))
        self.assertEqual(state["pending"], {})

    def test_baseline_full_page_without_target_fails_closed_after_one_page(self):
        non_targets = [record("video-%d" % index, "s1") for index in range(2)]
        for item in non_targets:
            item["resourceType"] = "video"
        target_page = [record("article-%d" % index, "s1") for index in range(2)]
        pages = [
            {"dataList": non_targets, "totalCount": 4},
            {"dataList": target_page, "totalCount": 4},
        ]

        class SourceClient:
            def __init__(self):
                self.calls = {}
                self.source_calls = []

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                self.source_calls.append((source_id, page, page_size))
                return pages[page - 1]

        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        baseline_client = SourceClient()

        baseline = wechat.scan(state, baseline_client, page_size=2)

        self.assertFalse(baseline["complete"])
        self.assertEqual(baseline["enqueued"], 0)
        self.assertIn("baseline_frontier_not_found", baseline["warnings"])
        self.assertEqual(baseline_client.source_calls, [("s1", 1, 2)])
        self.assertFalse(state["sources"]["s1"]["initialized"])
        self.assertEqual(state["sources"]["s1"]["recent"], {})
        self.assertEqual(state["pending"], {})

    def test_incremental_source_scan_stops_at_known_frontier_without_queueing_older_history(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        known = wechat.parse_article(record("known", "s1"))
        known_other = wechat.parse_article(record("known-other", "s1"))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                known["identity"]: sorted(wechat._entry_aliases(known, known["identity"])),
                known_other["identity"]: sorted(
                    wechat._entry_aliases(known_other, known_other["identity"]),
                ),
            },
        })
        first_page = [record("new-%d" % index, "s1") for index in range(50)]
        frontier_page = [record("new-50", "s1"), record("known", "s1"), record("old-history", "s1")]

        class FrontierClient:
            def __init__(self):
                self.calls = {}
                self.source_calls = []

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                self.source_calls.append((source_id, page, page_size))
                items = first_page if page == 1 else frontier_page
                return {"dataList": items, "totalCount": 1996, "pageCount": 40}

        client = FrontierClient()
        result = wechat.scan(state, client)

        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 51)
        self.assertEqual(client.source_calls, [("s1", 1, 50), ("s1", 2, 50)])
        pending_ids = {entry["resource_id"] for entry in state["pending"].values()}
        self.assertIn("new-50", pending_ids)
        self.assertNotIn("known", pending_ids)
        self.assertNotIn("old-history", pending_ids)
        self.assertIn(known_other["identity"], state["sources"]["s1"]["recent"])

    def test_incremental_source_scan_rejects_short_or_empty_page_before_advertised_total(self):
        class EarlyEndClient:
            def __init__(self, items):
                self.items = items
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": self.items, "totalCount": 100}

        for items, warning in (
            ([record("new", "s1")], "feed_shorter_than_total"),
            ([], "feed_ended_before_total"),
        ):
            with self.subTest(warning=warning):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                known = wechat.parse_article(record("known", "s1"))
                state["sources"]["s1"].update({
                    "initialized": True,
                    "recent": {
                        known["identity"]: sorted(
                            wechat._entry_aliases(known, known["identity"]),
                        ),
                    },
                })
                before = copy.deepcopy(state)

                result = wechat.scan(state, EarlyEndClient(items))

                self.assertFalse(result["complete"])
                self.assertEqual(result["enqueued"], 0)
                self.assertIn(warning, result["warnings"])
                self.assertEqual(state["pending"], before["pending"])
                self.assertEqual(
                    state["sources"]["s1"]["recent"],
                    before["sources"]["s1"]["recent"],
                )

    def test_incremental_source_scan_fails_closed_when_prior_frontier_disappears(self):
        class SourceClient:
            def __init__(self, items):
                self.items = items
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": self.items, "totalCount": len(self.items)}

        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        known = [wechat.parse_article(record("known-%d" % index, "s1")) for index in range(2)]
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                article["identity"]: sorted(
                    wechat._entry_aliases(article, article["identity"]),
                )
                for article in known
            },
        })
        before = copy.deepcopy(state)

        result = wechat.scan(
            state,
            SourceClient([record("older-1", "s1"), record("older-2", "s1")]),
            page_size=2,
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertIn("feed_frontier_not_found", result["warnings"])
        self.assertEqual(state["pending"], before["pending"])
        self.assertEqual(
            state["sources"]["s1"]["recent"],
            before["sources"]["s1"]["recent"],
        )

    def test_partial_first_scan_never_initializes_or_queues_history(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        client = FakeClient([{ "dataList": [record("r1")], "total": 2 }])
        result = wechat.scan(state, client, page_size=1)
        self.assertFalse(result["complete"])
        self.assertFalse(state["sources"]["s1"]["initialized"])
        self.assertFalse(state["pending"])

    def test_feed_pagination_cap_marks_health_partial_after_fourteen_calls(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        client = FakeClient([{"dataList": [record(str(index))], "total": 20} for index in range(20)])
        result = wechat.scan(state, client, page_size=1)
        self.assertFalse(result["complete"])
        self.assertEqual(client.calls["subscription"], 14)
        self.assertEqual(state["scan_health"]["pages"], 14)
        self.assertEqual(state["scan_health"]["complete"], False)

    def test_feed_schema_failures_are_partial_and_do_not_mutate_digest_state(self):
        invalid_pages = (
            {},
            [],
            {"dataList": {}},
            {"dataList": [], "total": False},
            {"dataList": [], "totalCount": "0"},
        )
        for page in invalid_pages:
            with self.subTest(page=page):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                source = state["sources"]["s1"]
                source["initialized"] = True
                source["recent"] = {"resource:old": True}
                old = wechat.parse_article(record("pending"))
                state["pending"][old["identity"]] = old
                before = copy.deepcopy(state)
                result = wechat.scan(state, FakeClient([page]))
                self.assertFalse(result["complete"])
                self.assertEqual(state["pending"], before["pending"])
                self.assertEqual(state["sources"]["s1"]["recent"], before["sources"]["s1"]["recent"])
                self.assertTrue(state["sources"]["s1"]["initialized"])
                self.assertFalse(state["scan_health"]["complete"])
                self.assertTrue(state["warnings"])

    def test_explicit_empty_feed_is_complete_and_can_establish_baseline(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([{"dataList": []}]))
        self.assertTrue(result["complete"])
        self.assertTrue(state["sources"]["s1"]["initialized"])

    def test_changing_or_contradictory_feed_totals_never_truncate_or_apply(self):
        cases = (
            ([{"dataList": [record("r1")], "total": 2},
              {"dataList": [record("r2")], "total": 3}], 2),
            ([{"dataList": [record("r1")], "total": 0}], 1),
            ([{"dataList": [record("r1"), record("r2")], "total": 1}], 2),
        )
        for pages, observed in cases:
            with self.subTest(pages=pages):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                state["sources"]["s1"]["initialized"] = True
                result = wechat.scan(state, FakeClient(pages), page_size=1)
                self.assertFalse(result["complete"])
                self.assertEqual(state["scan_health"]["records"], observed)
                self.assertEqual(state["pending"], {})
                self.assertEqual(state["sources"]["s1"]["recent"], {})

    def test_nonadjacent_repeated_full_feed_page_is_incomplete(self):
        page_a = [record("r1"), record("r2")]
        page_b = [record("r3"), record("r4")]
        pages = [
            {"dataList": page_a, "total": 6},
            {"dataList": page_b, "total": 6},
            {"dataList": copy.deepcopy(page_a), "total": 6},
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient(pages), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_repeated_full_page", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])
        self.assertEqual(state["sources"]["s1"]["recent"], {})

    def test_cross_page_duplicate_raw_record_is_incomplete(self):
        duplicate = record("r2")
        pages = [
            {"dataList": [record("r1"), duplicate], "total": 4},
            {"dataList": [copy.deepcopy(duplicate), record("r3")], "total": 4},
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient(pages), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_record", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_same_page_duplicate_raw_record_cannot_fill_advertised_total(self):
        duplicate = record("same")
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([{
            "dataList": [duplicate, copy.deepcopy(duplicate)], "total": 2,
        }]), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_record", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_same_page_duplicate_identity_with_changed_metadata_is_incomplete(self):
        first = record("same")
        second = record("same")
        second["title"] = "changed metadata"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([{
            "dataList": [first, second], "total": 2,
        }]), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_identity", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_same_page_url_and_resource_alias_collisions_are_incomplete(self):
        stable_url = "https://mp.weixin.qq.com/s/stable"
        with_id = record("r1", url=stable_url)
        without_id = record(None, url=stable_url + "?srcid=tracking")
        drifted_id = record("r2", url=stable_url)
        reused_id = record("r1", url="https://mp.weixin.qq.com/s/different")
        cases = (
            [with_id, without_id],
            [with_id, drifted_id],
            [with_id, reused_id],
        )
        for records in cases:
            with self.subTest(records=records):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([{
                    "dataList": records, "total": 2,
                }]), page_size=2)
                self.assertFalse(result["complete"])
                self.assertIn("feed_duplicate_identity", result["warnings"])
                self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_selected_article_conflicting_alias_fields_fail_closed_but_equal_values_fold(self):
        stable = record("r1", url="https://mp.weixin.qq.com/s/stable")
        stable.update({
            "resourceId": "r1",
            "source": {"id": "s1", "name": "Source One"},
            "type": "ARTICLE",
            "link": "https://mp.weixin.qq.com/s/stable?srcid=tracking",
            "originalUrl": "https://mp.weixin.qq.com/s/stable?sessionid=private",
        })
        self.assertIsNotNone(wechat.parse_article(stable))

        conflicts = []
        resource_conflict = copy.deepcopy(stable)
        resource_conflict["resourceId"] = "r2"
        conflicts.append(resource_conflict)
        source_conflict = copy.deepcopy(stable)
        source_conflict["source"]["id"] = "s2"
        conflicts.append(source_conflict)
        url_conflict = copy.deepcopy(stable)
        url_conflict["link"] = "https://mp.weixin.qq.com/s/different"
        conflicts.append(url_conflict)
        type_conflict = copy.deepcopy(stable)
        type_conflict["type"] = "wechat"
        conflicts.append(type_conflict)

        for raw in conflicts:
            with self.subTest(raw=raw):
                self.assertIsNone(wechat.parse_article(raw))
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([{"dataList": [raw]}]))
                self.assertFalse(result["complete"])
                self.assertIn("skipped_malformed_records:1", result["warnings"])
                self.assertFalse(state["sources"]["s1"]["initialized"])
        self.assertEqual(
            wechat.list_sources(FakeClient([{"dataList": [source_conflict]}]))["sources"],
            [],
        )

    def test_feed_duplicate_detection_collects_every_safe_resource_and_url_alias(self):
        resource_multi = record("r1", url="https://mp.weixin.qq.com/s/first")
        resource_multi["resourceId"] = "r2"
        resource_duplicate = record("r2", url="https://mp.weixin.qq.com/s/second")
        url_multi = record("r3", url="https://mp.weixin.qq.com/s/third")
        url_multi["link"] = "https://mp.weixin.qq.com/s/shared"
        url_duplicate = record("r4", url="https://mp.weixin.qq.com/s/shared?srcid=changed")
        for first, second in (
            (resource_multi, resource_duplicate),
            (url_multi, url_duplicate),
        ):
            with self.subTest(first=first, second=second):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([
                    {"dataList": [first], "total": 2},
                    {"dataList": [second], "total": 2},
                ]), page_size=1)
                self.assertFalse(result["complete"])
                self.assertIn("feed_duplicate_identity", result["warnings"])
                self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_cross_page_url_and_resource_alias_collisions_are_incomplete(self):
        stable_url = "https://mp.weixin.qq.com/s/stable"
        cases = (
            (record("r1", url=stable_url), record(None, url=stable_url + "?srcid=tracking")),
            (record("r1", url=stable_url), record("r2", url=stable_url)),
            (record("r1", url=stable_url), record("r1", url="https://mp.weixin.qq.com/s/different")),
        )
        for first, second in cases:
            with self.subTest(first=first, second=second):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([
                    {"dataList": [first], "total": 2},
                    {"dataList": [second], "total": 2},
                ]), page_size=1)
                self.assertFalse(result["complete"])
                self.assertIn("feed_duplicate_identity", result["warnings"])

    def test_cross_page_opaque_non_target_url_alias_is_stable_across_metadata_drift(self):
        first = {
            "sourceId": "s2", "resourceType": "video",
            "title": "first", "url": "https://example.com/post",
        }
        second = copy.deepcopy(first)
        second["title"] = "changed metadata"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([
            {"dataList": [first], "total": 2},
            {"dataList": [second], "total": 2},
        ]), page_size=1)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_identity", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_cross_page_opaque_url_alias_does_not_require_a_resource_type(self):
        first = {
            "sourceId": "s2", "title": "first", "url": "https://example.com/post",
        }
        second = copy.deepcopy(first)
        second.update({"title": "changed metadata", "resourceType": "video"})
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([
            {"dataList": [first], "total": 2},
            {"dataList": [second], "total": 2},
        ]), page_size=1)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_identity", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_cross_page_duplicate_article_identity_is_incomplete(self):
        first_r2 = record("r2")
        second_r2 = record("r2")
        second_r2["title"] = "same identity, changed metadata"
        pages = [
            {"dataList": [record("r1"), first_r2], "total": 4},
            {"dataList": [second_r2, record("r3")], "total": 4},
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient(pages), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_identity", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_cross_page_duplicate_safe_resource_id_is_global_even_for_non_targets(self):
        first = {
            "id": "shared", "sourceId": "s2", "resourceType": "video",
            "title": "first", "url": "https://example.com/first",
        }
        second = copy.deepcopy(first)
        second["title"] = "changed metadata"
        pages = [
            {"dataList": [record("r1"), first], "total": 4},
            {"dataList": [record("r2"), second], "total": 4},
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient(pages), page_size=2)
        self.assertFalse(result["complete"])
        self.assertIn("feed_duplicate_identity", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_deep_feed_records_fail_closed_without_recursion_escape(self):
        deep_a = "a"
        deep_b = "b"
        for _ in range(1100):
            deep_a = [deep_a]
            deep_b = [deep_b]
        first = record("r1")
        second = record("r1")
        first["extra"] = deep_a
        second["extra"] = deep_b
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        try:
            result = wechat.scan(state, FakeClient([
                {"dataList": [first], "total": 2},
                {"dataList": [second], "total": 2},
            ]), page_size=1)
        except RecursionError as error:
            self.fail("deep feed JSON escaped fail-safe handling: %s" % error)
        self.assertFalse(result["complete"])
        self.assertIn("feed_json_too_deep", result["warnings"])
        self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_malformed_article_makes_complete_transport_partial_without_state_advance(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"].update({"initialized": True, "recent": {"resource:old": True}})
        result = wechat.scan(state, FakeClient([{
            "dataList": [record("new"), {"not": "an article"}], "total": 2,
        }]))
        self.assertFalse(result["complete"])
        self.assertEqual(state["pending"], {})
        self.assertEqual(state["sources"]["s1"]["recent"], {"resource:old": True})
        self.assertIn("skipped_malformed_records:1", state["warnings"])

    def test_known_unselected_non_wechat_record_does_not_poison_selected_scan(self):
        ordinary_blog = {
            "id": "blog1", "sourceId": "s2", "resourceType": "blog",
            "title": "ordinary blog", "url": "https://example.com/post",
        }
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        result = wechat.scan(state, FakeClient([{
            "dataList": [record("selected"), ordinary_blog],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["skipped"], {"invalid_or_non_wechat": 0})
        self.assertTrue(state["sources"]["s1"]["initialized"])
        selected = wechat.parse_article(record("selected"))
        self.assertEqual(state["sources"]["s1"]["recent"], {
            selected["identity"]: sorted((selected["identity"], "resource:selected")),
        })

    def test_selected_explicit_non_target_resource_types_are_diagnostic_not_partial(self):
        for resource_type in ("video", "podcast", "tweet", "newsletter"):
            with self.subTest(resource_type=resource_type):
                non_target = {
                    "id": "other", "sourceId": "s1", "resourceType": resource_type,
                    "title": "non-target", "url": "https://example.com/non-target",
                }
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([{
                    "dataList": [record("selected"), non_target],
                }]))
                self.assertTrue(result["complete"])
                self.assertEqual(result["skipped"], {"invalid_or_non_wechat": 1})
                self.assertTrue(state["sources"]["s1"]["initialized"])
                selected = wechat.parse_article(record("selected"))
                self.assertEqual(state["sources"]["s1"]["recent"], {
                    selected["identity"]: sorted((selected["identity"], "resource:selected")),
                })

    def test_selected_claimed_articles_with_invalid_identity_url_or_time_are_partial(self):
        invalid_url = record("bad-url")
        invalid_url["url"] = "https://example.com/not-wechat"
        invalid_id = record("bad-id")
        invalid_id["id"] = "unsafe id"
        invalid_time = record("bad-time")
        invalid_time["publishTime"] = "not-a-time"
        for malformed in (invalid_url, invalid_id, invalid_time):
            with self.subTest(malformed=malformed):
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                result = wechat.scan(state, FakeClient([{"dataList": [malformed]}]))
                self.assertFalse(result["complete"])
                self.assertIn("skipped_malformed_records:1", result["warnings"])
                self.assertFalse(state["sources"]["s1"]["initialized"])

    def test_six_page_501_record_snapshot_fails_closed_without_cache_cascade(self):
        records = [record("r%d" % index) for index in range(501)]
        pages = [
            {"dataList": records[index:index + 100], "total": 501}
            for index in range(0, 501, 100)
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        first = wechat.scan(state, FakeClient(copy.deepcopy(pages)), page_size=100)
        self.assertFalse(first["complete"])
        self.assertFalse(state["sources"]["s1"]["initialized"])
        self.assertEqual(state["sources"]["s1"]["recent"], {})
        self.assertIn("source_snapshot_limit_exceeded:s1:501", first["warnings"])
        second = wechat.scan(state, FakeClient(copy.deepcopy(pages)), page_size=100)
        self.assertFalse(second["complete"])
        self.assertEqual(second["enqueued"], 0)
        self.assertEqual(state["pending"], {})

    def test_complete_500_record_snapshot_baseline_is_stable_on_repeat(self):
        records = [record("r%d" % index) for index in range(500)]
        pages = [
            {"dataList": records[index:index + 100], "total": 500}
            for index in range(0, 500, 100)
        ]
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        self.assertTrue(wechat.scan(state, FakeClient(copy.deepcopy(pages)), page_size=100)["complete"])
        self.assertEqual(len(state["sources"]["s1"]["recent"]), 500)
        second = wechat.scan(state, FakeClient(copy.deepcopy(pages)), page_size=100)
        self.assertTrue(second["complete"])
        self.assertEqual(second["enqueued"], 0)
        self.assertEqual(len(state["sources"]["s1"]["recent"]), 500)

    def test_url_aliases_prevent_requeue_when_resource_id_appears_or_drifts_across_scans(self):
        stable_url = "https://mp.weixin.qq.com/s/stable-across-scans"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        baseline = wechat.scan(state, FakeClient([{
            "dataList": [record(None, url=stable_url)],
        }]))
        self.assertTrue(baseline["complete"])
        self.assertEqual(state["pending"], {})
        for resource_id in ("appeared", "drifted"):
            with self.subTest(resource_id=resource_id):
                result = wechat.scan(state, FakeClient([{
                    "dataList": [record(resource_id, url=stable_url)],
                }]))
                self.assertTrue(result["complete"])
                self.assertEqual(result["enqueued"], 0)
                self.assertEqual(state["pending"], {})

    def test_recent_aliases_prevent_requeue_when_canonical_url_changes_but_resource_id_is_stable(self):
        old_url = "https://mp.weixin.qq.com/s/old-canonical"
        new_url = "https://mp.weixin.qq.com/s/new-canonical"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        self.assertTrue(wechat.scan(state, FakeClient([{
            "dataList": [record("r1", url=old_url)],
        }]))["complete"])
        result = wechat.scan(state, FakeClient([{
            "dataList": [record("r1", url=new_url)],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(state["pending"], {})
        current = wechat.parse_article(record("r1", url=new_url))
        self.assertEqual(state["sources"]["s1"]["recent"], {
            current["identity"]: sorted((current["identity"], "resource:r1")),
        })

    def test_incremental_recent_frontier_keeps_old_url_alias_across_url_drift_and_reversion(self):
        class SourceClient:
            def __init__(self, items):
                self.items = items
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": self.items}

        old_url = "https://mp.weixin.qq.com/s/old-frontier-url"
        new_url = "https://mp.weixin.qq.com/s/new-frontier-url"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        old = wechat.parse_article(record("r1", url=old_url))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                old["identity"]: sorted(wechat._entry_aliases(old, old["identity"])),
            },
        })

        drift = wechat.scan(state, SourceClient([record("r1", url=new_url)]))
        self.assertTrue(drift["complete"])
        self.assertEqual(drift["enqueued"], 0)
        self.assertIn(old["identity"], wechat._recent_aliases(state["sources"]["s1"]["recent"]))

        reverted = wechat.scan(state, SourceClient([record(None, url=old_url)]))
        self.assertTrue(reverted["complete"])
        self.assertEqual(reverted["enqueued"], 0)
        self.assertEqual(state["pending"], {})

    def test_incremental_recent_alias_overflow_fails_closed_without_advancing_state(self):
        class SourceClient:
            def __init__(self, items):
                self.items = items
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": self.items}

        old_url = "https://mp.weixin.qq.com/s/alias-cap-old"
        new_url = "https://mp.weixin.qq.com/s/alias-cap-new"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        old = wechat.parse_article(record("r1", url=old_url))
        aliases = [old["identity"], "resource:r1"] + [
            "resource:old-%d" % index
            for index in range(wechat.MAX_TOMBSTONE_ALIASES - 2)
        ]
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {old["identity"]: sorted(aliases)},
        })
        before = copy.deepcopy(state)

        result = wechat.scan(state, SourceClient([record("r1", url=new_url)]))

        self.assertFalse(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertIn("source_alias_limit_exceeded:s1", result["warnings"])
        self.assertEqual(state["pending"], before["pending"])
        self.assertEqual(
            state["sources"]["s1"]["recent"],
            before["sources"]["s1"]["recent"],
        )

    def test_pending_aliases_suppress_url_and_resource_id_drift(self):
        stable_url = "https://mp.weixin.qq.com/s/pending-stable"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        state["sources"]["s1"]["recent"] = {
            wechat.parse_article(record("other"))["identity"]: True,
        }
        legacy_entry = wechat.parse_article(record("r1", url=stable_url))
        legacy_entry["identity"] = "resource:r1"
        state["pending"]["resource:r1"] = legacy_entry
        result = wechat.scan(state, FakeClient([{
            "dataList": [record("r2", url=stable_url)],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(list(state["pending"]), ["resource:r1"])

        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        pending_entry = wechat.parse_article(record("r1", url=stable_url))
        state["pending"][pending_entry["identity"]] = pending_entry
        result = wechat.scan(state, FakeClient([{
            "dataList": [record("r2", url=stable_url)],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(list(state["pending"]), [pending_entry["identity"]])

    def test_ack_uses_tombstone_without_mutating_recent_snapshot(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        state["sources"]["s1"]["recent"] = {"resource:current": True}
        entry = add_claim(
            wechat.parse_article(record("acked")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        before = copy.deepcopy(state["sources"]["s1"]["recent"])
        wechat.ack(state, "acked", claim_id=CLAIM_ID)
        self.assertNotIn(entry["identity"], state["pending"])
        self.assertEqual(state["sources"]["s1"]["recent"], before)
        self.assertIn(entry["identity"], state["ack_tombstones"])

    def test_ack_persists_canonical_url_and_resource_aliases_and_prunes_by_alias_absence(self):
        stable_url = "https://mp.weixin.qq.com/s/acked-stable"
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        state["next_scan_seq"] = 4
        entry = add_claim(wechat.parse_article(record("r1", url=stable_url)))
        state["pending"][entry["identity"]] = entry
        receipt = wechat.ack(state, "r1", claim_id=CLAIM_ID)
        url_identity = entry["identity"]
        self.assertEqual(receipt["acknowledged"], url_identity)
        self.assertEqual(set(state["ack_tombstones"][url_identity]["aliases"]), {
            url_identity, "resource:r1",
        })

        state["next_scan_seq"] = 5
        same_url = wechat._apply_scan_observation(
            state,
            {"records": [record("r2", url=stable_url)], "complete": True,
             "warnings": [], "pages": 1},
            generation=5,
        )
        self.assertEqual(same_url["enqueued"], 0)
        self.assertIn(url_identity, state["ack_tombstones"])

        state["next_scan_seq"] = 6
        same_resource = wechat._apply_scan_observation(
            state,
            {"records": [record("r1", url="https://mp.weixin.qq.com/s/moved")],
             "complete": True, "warnings": [], "pages": 1},
            generation=6,
        )
        self.assertEqual(same_resource["enqueued"], 0)
        self.assertIn(url_identity, state["ack_tombstones"])

        state["next_scan_seq"] = 7
        absent = wechat._apply_scan_observation(
            state,
            {"records": [], "complete": True, "warnings": [], "pages": 1},
            generation=7,
        )
        self.assertTrue(absent["complete"])
        self.assertNotIn(url_identity, state["ack_tombstones"])

    def test_ack_does_not_evict_any_identity_from_a_full_current_snapshot(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        recent = {"resource:r%d" % index: True for index in range(wechat.MAX_RECENT)}
        state["sources"]["s1"]["recent"] = copy.deepcopy(recent)
        entry = add_claim(
            wechat.parse_article(record("acked")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        wechat.ack(state, "acked", claim_id=CLAIM_ID)
        self.assertEqual(state["sources"]["s1"]["recent"], recent)
        self.assertIn(entry["identity"], state["ack_tombstones"])

    def test_ack_tombstone_prunes_only_after_newer_complete_scan_observes_absence(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        entry = add_claim(
            wechat.parse_article(record("acked")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        wechat.ack(state, "acked", claim_id=CLAIM_ID)
        self.assertIn(entry["identity"], state["ack_tombstones"])
        wechat.save_state(path, state)
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: FakeClient([{"dataList": []}])
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
        finally:
            wechat._client_from_env = original_client
        self.assertNotIn(entry["identity"], wechat.load_state(path)["ack_tombstones"])

    def test_incremental_frontier_does_not_prune_older_unobserved_tombstone(self):
        class SourceClient:
            def __init__(self, items):
                self.items = items
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": self.items, "totalCount": 2}

        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        known = wechat.parse_article(record("known", "s1"))
        acked = wechat.parse_article(record("acked", "s1"))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                known["identity"]: sorted(
                    wechat._entry_aliases(known, known["identity"]),
                ),
            },
        })
        state["next_scan_seq"] = 2
        state["ack_tombstones"][acked["identity"]] = {
            "source_id": "s1",
            "ack_after_scan_seq": 1,
            "aliases": sorted(wechat._entry_aliases(acked, acked["identity"])),
        }

        observation = wechat._scan_observation(
            SourceClient([record("known", "s1"), record("acked", "s1")]),
            sources=state["sources"],
        )
        result = wechat._apply_scan_observation(state, observation, generation=2)

        self.assertTrue(result["complete"])
        self.assertIn(acked["identity"], state["ack_tombstones"])

    def test_complete_scan_never_prunes_tombstones_for_unselected_sources(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["next_scan_seq"] = 3
        state["ack_tombstones"]["resource:unselected"] = {
            "source_id": "s2", "ack_after_scan_seq": 1,
            "aliases": ["resource:unselected"],
        }
        result = wechat._apply_scan_observation(
            state,
            {"records": [], "complete": True, "warnings": [], "pages": 1},
            generation=3,
        )
        self.assertTrue(result["complete"])
        self.assertIn("resource:unselected", state["ack_tombstones"])

    def test_ack_fails_closed_when_tombstone_capacity_is_full(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["ack_tombstones"]["resource:older"] = {
            "source_id": "s1", "ack_after_scan_seq": 0,
            "aliases": ["resource:older"],
        }
        entry = add_claim(
            wechat.parse_article(record("newer")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        original_limit = wechat.MAX_TOMBSTONES
        wechat.MAX_TOMBSTONES = 1
        try:
            with self.assertRaisesRegex(wechat.StateError, "capacity"):
                wechat.ack(state, "newer", claim_id=CLAIM_ID)
        finally:
            wechat.MAX_TOMBSTONES = original_limit
        self.assertIn(entry["identity"], state["pending"])
        self.assertNotIn(entry["identity"], state["ack_tombstones"])

    def test_pending_persists_and_ack_fail_and_exhaustion(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        wechat.scan(state, FakeClient([{ "dataList": [record("old")]}]))
        wechat.scan(state, FakeClient([{ "dataList": [record("new")]}]))
        wechat.save_state(path, state)
        loaded = wechat.load_state(path)
        pending_identity = wechat.parse_article(record("new"))["identity"]
        self.assertEqual(wechat.pending(loaded)["retryable"][0]["identity"], pending_identity)
        for _ in range(3):
            issued = wechat.claim(loaded, "new")
            wechat.fail(loaded, "new", "FETCH_FAILED", claim_id=issued["claim_id"])
        self.assertEqual(len(wechat.pending(loaded)["exhausted"]), 1)
        self.assertIn(pending_identity, loaded["pending"])

    def test_pending_orders_oldest_by_instant_across_timezone_offsets(self):
        state = wechat.new_state()
        state["pending"] = {
            "resource:older": {
                "identity": "resource:older", "resource_id": "older", "source_id": "s1",
                "source_name": "Source", "title": "Older", "url": "https://mp.weixin.qq.com/s/older",
                "published_at": "2024-01-01T00:30:00+01:00", "attempts": 0,
            },
            "resource:newer": {
                "identity": "resource:newer", "resource_id": "newer", "source_id": "s1",
                "source_name": "Source", "title": "Newer", "url": "https://mp.weixin.qq.com/s/newer",
                "published_at": "2023-12-31T23:45:00+00:00", "attempts": 0,
            },
        }
        self.assertEqual(
            [entry["identity"] for entry in wechat.pending(state)["retryable"]],
            ["resource:older", "resource:newer"],
        )

    def test_pending_separates_active_claims_and_expired_claims_are_retryable(self):
        state = wechat.new_state()
        active = add_claim(wechat.parse_article(record("active")), expires_at="2026-07-18T12:10:00Z")
        expired = add_claim(wechat.parse_article(record("expired")), claim_id="b" * 32,
                            expires_at="2026-07-18T11:59:59Z")
        state["pending"] = {active["identity"]: active, expired["identity"]: expired}
        result = wechat.pending(state, now=datetime(2026, 7, 18, 12, tzinfo=timezone.utc))
        self.assertEqual([item["identity"] for item in result["claimed"]], [active["identity"]])
        self.assertEqual([item["identity"] for item in result["retryable"]], [expired["identity"]])
        self.assertEqual(result["exhausted"], [])

    def test_claim_is_atomic_and_active_conflict_is_not_a_fetch_fallback(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = wechat.parse_article(record("r1"))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        first_output = io.StringIO()
        with redirect_stdout(first_output):
            self.assertEqual(wechat.main(["--state-file", str(path), "claim", "r1"]), 0)
        first = json.loads(first_output.getvalue())
        self.assertRegex(first["claim_id"], r"^[0-9a-f]{32}$")
        self.assertIn("claim_expires_at", first)

        second_output = io.StringIO()
        with redirect_stdout(second_output):
            self.assertEqual(wechat.main(["--state-file", str(path), "claim", "r1"]), 0)
        second = json.loads(second_output.getvalue())
        self.assertEqual(second, {"claim_status": "already_claimed"})
        self.assertNotIn("fallback_reason", second)

    def test_fail_clears_matching_claim_and_ack_creates_scan_tombstone(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        state["next_scan_seq"] = 7
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.fail(state, "r1", "FETCH_FAILED", claim_id=CLAIM_ID)
        self.assertNotIn("claim_id", state["pending"][entry["identity"]])
        self.assertNotIn("claim_expires_at", state["pending"][entry["identity"]])

        add_claim(state["pending"][entry["identity"]])
        wechat.ack(state, "r1", claim_id=CLAIM_ID)
        self.assertNotIn(entry["identity"], state["pending"])
        self.assertEqual(state["ack_tombstones"][entry["identity"]], {
            "source_id": "s1", "ack_after_scan_seq": 7,
            "aliases": sorted((entry["identity"], "resource:r1")),
        })

    def test_expired_claim_can_be_replaced_but_stale_token_cannot_mutate(self):
        state = wechat.new_state()
        entry = add_claim(wechat.parse_article(record("r1")), expires_at="2020-01-01T00:00:00Z")
        state["pending"][entry["identity"]] = entry
        replacement = wechat.claim(state, "r1", now=datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.assertNotEqual(replacement["claim_id"], CLAIM_ID)
        with self.assertRaises(wechat.ClaimUnavailable):
            wechat.ack(state, "r1", claim_id=CLAIM_ID)
        self.assertIn(entry["identity"], state["pending"])

    def test_ack_and_fail_require_a_current_active_claim_in_functions_and_cli(self):
        state = wechat.new_state()
        expired = add_claim(
            wechat.parse_article(record("r1")),
            expires_at="2020-01-01T00:00:00Z",
        )
        state["pending"][expired["identity"]] = expired
        before = copy.deepcopy(state)
        with self.assertRaises(wechat.ClaimUnavailable):
            wechat.ack(state, "r1", claim_id=CLAIM_ID)
        with self.assertRaises(wechat.ClaimUnavailable):
            wechat.fail(state, "r1", "FETCH_FAILED", claim_id=CLAIM_ID)
        self.assertEqual(state, before)

        for argv in (
            ["renew", "r1"], ["ack", "r1"],
            ["fail", "r1", "--reason", "FETCH_FAILED"],
        ):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    wechat.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_renew_extends_only_the_matching_active_claim_and_persists_atomically(self):
        self.assertTrue(hasattr(wechat, "renew"), "renew helper is required")
        now = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
        state = wechat.new_state()
        entry = add_claim(
            wechat.parse_article(record("r1")),
            expires_at="2026-07-18T12:05:00Z",
        )
        entry["claim_fetch_started"] = True
        state["pending"][entry["identity"]] = entry
        renewed = wechat.renew(state, "r1", CLAIM_ID, now=now)
        self.assertEqual(renewed, {
            "claim_id": CLAIM_ID,
            "claim_expires_at": "2026-07-18T12:15:00Z",
        })
        self.assertTrue(state["pending"][entry["identity"]]["claim_fetch_started"])
        before = copy.deepcopy(state)
        with self.assertRaises(wechat.ClaimUnavailable):
            wechat.renew(state, "r1", "b" * 32, now=now)
        self.assertEqual(state, before)
        expired_state = wechat.new_state()
        expired_entry = add_claim(
            wechat.parse_article(record("expired")),
            expires_at="2026-07-18T11:59:59Z",
        )
        expired_state["pending"][expired_entry["identity"]] = expired_entry
        with self.assertRaises(wechat.ClaimUnavailable):
            wechat.renew(expired_state, "expired", CLAIM_ID, now=now)

        path = self.state_file()
        live = wechat.new_state()
        wechat.configure_sources(live, ["s1"])
        live_entry = wechat.parse_article(record("live"))
        live["pending"][live_entry["identity"]] = live_entry
        issued = wechat.claim(live, "live")
        wechat.save_state(path, live)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(wechat.main([
                "--state-file", str(path), "renew", "live", "--claim-id", issued["claim_id"],
            ]), 0)
        receipt = json.loads(output.getvalue())
        persisted = wechat.load_state(path)["pending"][live_entry["identity"]]
        self.assertEqual(persisted["claim_id"], issued["claim_id"])
        self.assertEqual(persisted["claim_expires_at"], receipt["claim_expires_at"])

    def test_markdown_budget_beijing_reset_and_never_persists_body(self):
        state = wechat.new_state()
        state["pending"]["resource:r1"] = {"identity": "resource:r1", "resource_id": "r1", "published_at": "2024-01-01T00:00:00+00:00"}
        client = FakeClient(markdown="# private body")
        first = wechat.markdown(state, client, "resource:r1", now=__import__("datetime").datetime(2024, 1, 1, 16, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(first["markdown"], "# private body")
        self.assertNotIn("markdown", state["pending"]["resource:r1"])
        self.assertEqual(wechat.BODY_DAILY_LIMIT, 35)
        state["body_budget"]["count"] = 35
        denied = wechat.markdown(state, client, "resource:r1", now=__import__("datetime").datetime(2024, 1, 1, 16, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(denied["fallback_reason"], "daily_body_budget_exhausted")
        reset = wechat.markdown(state, client, "resource:r1", now=__import__("datetime").datetime(2024, 1, 2, 16, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(reset["markdown"], "# private body")

    def test_markdown_failed_fetch_consumes_budget_and_zoneinfo_unavailable_is_safe(self):
        state = wechat.new_state()
        state["pending"]["resource:r1"] = {"identity": "resource:r1", "resource_id": "r1", "source_id": "s1", "url": "https://mp.weixin.qq.com/s/a", "attempts": 0}
        client = FakeClient()
        def failed_markdown(resource_id, before_attempt=None):
            before_attempt()
            raise wechat.APIError("safe")

        client.markdown = failed_markdown
        result = wechat.markdown(state, client, "r1")
        self.assertEqual(result["fallback_reason"], "bestblogs_markdown_unavailable")
        self.assertEqual(state["body_budget"]["count"], 1)
        original = wechat.ZoneInfo
        wechat.ZoneInfo = None
        try:
            self.assertEqual(wechat.markdown(state, FakeClient(), "r1")["fallback_reason"], "beijing_timezone_unavailable")
        finally:
            wechat.ZoneInfo = original

    def test_empty_or_whitespace_bestblogs_markdown_uses_fallback(self):
        for body in ("", "   \n\t"):
            with self.subTest(body=repr(body)):
                state = wechat.new_state()
                entry = wechat.parse_article(record("r1"))
                state["pending"][entry["identity"]] = entry
                result = wechat.markdown(state, FakeClient(markdown=body), "r1")
                self.assertEqual(result, {
                    "fallback_reason": "bestblogs_markdown_unavailable",
                })

    def test_cli_markdown_durably_reserves_each_429_attempt_before_network(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request-1", "data": "# body",
        }).encode()
        rate_limited = HTTPError(
            wechat.API_ORIGIN + "/resources/r1/markdown", 429, "slow", {"Retry-After": "0"}, None,
        )

        class PersistedBudgetOpener(FakeOpener):
            def __init__(self, responses):
                super().__init__(responses)
                self.persisted_counts = []

            def open(self, request, timeout):
                self.persisted_counts.append(wechat.load_state(path)["body_budget"]["count"])
                return super().open(request, timeout)

        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = PersistedBudgetOpener([
            rate_limited,
            FakeResponse(body, wechat.API_ORIGIN + "/resources/r1/markdown"),
        ])
        client._opener = opener
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda delay: None
        try:
            with redirect_stdout(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep
        self.assertEqual(result, 0)
        self.assertEqual(opener.persisted_counts, [1, 2])
        self.assertEqual(wechat.load_state(path)["body_budget"]["count"], 2)
        self.assertEqual(client.calls["/resources/r1/markdown"], 2)

    def test_preserve_reserve_allows_one_attempt_at_34_total_29_body_then_falls_back(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        for resource_id in ("r1", "r2"):
            entry = add_claim(wechat.parse_article(record(resource_id)))
            state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 34}
        state["body_budget"] = {"day": day, "count": 29}
        wechat.save_state(path, state)
        client = FakeClient(markdown="# reserved body")
        client_builds = []
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client_builds.append(True) or client
        try:
            first_output = io.StringIO()
            with redirect_stdout(first_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
            first_state = wechat.load_state(path)
            self.assertEqual(json.loads(first_output.getvalue()), {
                "markdown": "# reserved body", "source": "bestblogs",
            })
            self.assertEqual(first_state["total_budget"], {"day": day, "count": 35})
            self.assertEqual(first_state["body_budget"], {"day": day, "count": 30})

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r2",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(second_output.getvalue()), {
            "fallback_reason": "bestblogs_quota_reserve_preserved",
        })
        self.assertEqual(client_builds, [True])
        self.assertEqual(client.calls.get("markdown"), 1)
        after = wechat.load_state(path)
        self.assertEqual(after["total_budget"], {"day": day, "count": 35})
        self.assertEqual(after["body_budget"], {"day": day, "count": 30})
        self.assertEqual(after["api_calls"].get("markdown"), 1)

    def test_preserve_reserve_validates_pending_claim_and_state_before_rejection(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 35}
        state["body_budget"] = {"day": day, "count": 30}
        wechat.save_state(path, state)
        client_builds = []
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client_builds.append(True)
        try:
            wrong_claim = io.StringIO()
            with redirect_stdout(wrong_claim):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", "b" * 32, "--preserve-reserve",
                ]), 0)
            self.assertEqual(json.loads(wrong_claim.getvalue()), {"claim_status": "claim_lost"})

            drifted = wechat.load_state(path)
            drifted["sources"] = {}
            wechat.save_state(path, drifted)
            source_drift = io.StringIO()
            with redirect_stdout(source_drift):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 2)
            self.assertIn("not configured", json.loads(source_drift.getvalue())["error"])

            path.write_text('{"version": 999}', encoding="utf-8")
            malformed = io.StringIO()
            with redirect_stdout(malformed):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 2)
            self.assertEqual(json.loads(malformed.getvalue()), {
                "error": "unsupported or malformed state schema",
            })
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(client_builds, [])

    def test_preserve_reserve_rolls_old_beijing_day_before_evaluating_ceiling(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        state["total_budget"] = {"day": "2000-01-01", "count": 50}
        state["body_budget"] = {"day": "2000-01-01", "count": 35}
        wechat.save_state(path, state)
        client = FakeClient(markdown="# new day")
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(json.loads(output.getvalue())["markdown"], "# new day")
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["total_budget"], {"day": wechat._beijing_day(), "count": 1})
        self.assertEqual(persisted["body_budget"], {"day": wechat._beijing_day(), "count": 1})

    def test_preserve_reserve_keeps_hard_limits_and_non_reserve_commands_unchanged(self):
        for total_count, body_count, reason in (
            (50, 30, "daily_total_budget_exhausted"),
            (35, 35, "daily_body_budget_exhausted"),
        ):
            with self.subTest(reason=reason):
                path = self.state_file()
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                entry = add_claim(wechat.parse_article(record("r1")))
                state["pending"][entry["identity"]] = entry
                day = wechat._beijing_day()
                state["total_budget"] = {"day": day, "count": total_count}
                state["body_budget"] = {"day": day, "count": body_count}
                wechat.save_state(path, state)
                client = FakeClient()
                original_client = wechat._client_from_env
                wechat._client_from_env = lambda: client
                output = io.StringIO()
                try:
                    with redirect_stdout(output):
                        self.assertEqual(wechat.main([
                            "--state-file", str(path), "markdown", "r1",
                            "--claim-id", CLAIM_ID, "--preserve-reserve",
                        ]), 0)
                finally:
                    wechat._client_from_env = original_client
                self.assertEqual(json.loads(output.getvalue()), {"fallback_reason": reason})

        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("legacy")))
        state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 35}
        state["body_budget"] = {"day": day, "count": 30}
        wechat.save_state(path, state)
        client = FakeClient(markdown="# legacy behavior")
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "legacy", "--claim-id", CLAIM_ID,
                ]), 0)
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(json.loads(output.getvalue())["markdown"], "# legacy behavior")
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["total_budget"]["count"], 36)
        self.assertEqual(persisted["body_budget"]["count"], 31)

    def test_preserve_reserve_rejects_429_retry_after_the_first_attempt_reaches_ceiling(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 34}
        state["body_budget"] = {"day": day, "count": 29}
        wechat.save_state(path, state)
        rate_limited = HTTPError(
            wechat.API_ORIGIN + "/resources/r1/markdown", 429, "slow", {"Retry-After": "0"}, None,
        )
        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = FakeOpener([rate_limited])
        client._opener = opener
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda unused: None
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep

        self.assertEqual(json.loads(output.getvalue()), {
            "fallback_reason": "bestblogs_quota_reserve_preserved",
        })
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(client.calls, {"/resources/r1/markdown": 1})
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["total_budget"], {"day": day, "count": 35})
        self.assertEqual(persisted["body_budget"], {"day": day, "count": 30})
        self.assertEqual(persisted["api_calls"], {"markdown": 1})

    def test_preserve_reserve_rechecks_quota_changed_after_preflight_before_http(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 34}
        state["body_budget"] = {"day": day, "count": 29}
        wechat.save_state(path, state)
        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = FakeOpener([])
        client._opener = opener

        def reserve_concurrently_before_client_returns():
            with wechat.state_lock(path):
                current = wechat.load_state(path)
                wechat._reserve_api_attempt(current, body=True)
                current["api_calls"]["markdown"] = 1
                wechat.save_state(path, current)
            return client

        original_client = wechat._client_from_env
        wechat._client_from_env = reserve_concurrently_before_client_returns
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(output.getvalue()), {
            "fallback_reason": "bestblogs_quota_reserve_preserved",
        })
        self.assertEqual(opener.requests, [])
        self.assertEqual(client.calls, {})
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["total_budget"], {"day": day, "count": 35})
        self.assertEqual(persisted["body_budget"], {"day": day, "count": 30})
        self.assertEqual(persisted["api_calls"], {"markdown": 1})

    def test_preserve_reserve_fallback_atomically_prevents_duplicate_same_claim_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 35}
        state["body_budget"] = {"day": day, "count": 30}
        wechat.save_state(path, state)
        client_builds = []
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client_builds.append(True)
        try:
            first_output = io.StringIO()
            with redirect_stdout(first_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
            self.assertEqual(json.loads(first_output.getvalue()), {
                "fallback_reason": "bestblogs_quota_reserve_preserved",
            })
            after_first = wechat.load_state(path)
            self.assertTrue(after_first["pending"][entry["identity"]]["claim_fetch_started"])
            self.assertEqual(after_first["total_budget"], {"day": day, "count": 35})
            self.assertEqual(after_first["body_budget"], {"day": day, "count": 30})
            self.assertEqual(after_first["api_calls"], {})

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "markdown", "r1",
                    "--claim-id", CLAIM_ID, "--preserve-reserve",
                ]), 0)
            self.assertEqual(json.loads(second_output.getvalue()), {
                "claim_status": "already_fetching",
            })
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(client_builds, [])
        after_second = wechat.load_state(path)
        self.assertEqual(after_second["total_budget"], {"day": day, "count": 35})
        self.assertEqual(after_second["body_budget"], {"day": day, "count": 30})
        self.assertEqual(after_second["api_calls"], {})

    def test_state_lock_excludes_a_second_writer_with_a_bounded_safe_error(self):
        path = self.state_file()
        self.assertTrue(hasattr(wechat, "state_lock"), "state_lock is required")
        with wechat.state_lock(path, timeout=0.05):
            with self.assertRaisesRegex(wechat.StateError, "state is busy"):
                with wechat.state_lock(path, timeout=0.01):
                    self.fail("a second writer acquired the state lock")

    def test_cli_markdown_releases_state_lock_before_fetching(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)

        body = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request-1", "data": "# body",
        }).encode()

        class LockCheckingOpener(FakeOpener):
            def __init__(self):
                super().__init__([FakeResponse(body, wechat.API_ORIGIN + "/resources/r1/markdown")])
                self.lock_was_available = False

            def open(self, request, timeout):
                with wechat.state_lock(path, timeout=0):
                    self.lock_was_available = True
                    self.status_during_fetch = wechat.status(wechat.load_state(path))
                return super().open(request, timeout)

        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = LockCheckingOpener()
        client._opener = opener
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        try:
            with redirect_stdout(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        self.assertTrue(opener.lock_was_available)
        self.assertEqual(opener.status_during_fetch["total_budget"]["used"], 1)

    def test_concurrent_ack_before_markdown_reservation_prevents_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)

        class AckBeforeReservationClient(FakeClient):
            def markdown(self, resource_id, before_attempt=None):
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.ack(current, "r1", claim_id=CLAIM_ID)
                    wechat.save_state(path, current)
                before_attempt()
                self.calls["markdown"] = self.calls.get("markdown", 0) + 1
                return self.markdown_body

        client = AckBeforeReservationClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = wechat.main([
                    "--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID,
                ])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), {"claim_status": "claim_lost"})
        self.assertEqual(client.calls.get("markdown", 0), 0)

    def test_overlapping_markdown_with_wrong_claim_never_builds_client_or_fallbacks(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        original_client = wechat._client_from_env
        client_builds = []
        wechat._client_from_env = lambda: client_builds.append(True)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = wechat.main([
                    "--state-file", str(path), "markdown", "r1", "--claim-id", "b" * 32,
                ])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        self.assertEqual(client_builds, [])
        self.assertEqual(json.loads(output.getvalue()), {"claim_status": "claim_lost"})
        self.assertNotIn("fallback_reason", output.getvalue())

    def test_overlapping_markdown_with_same_claim_cannot_double_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        entry["claim_fetch_started"] = True
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        original_client = wechat._client_from_env
        client_builds = []
        wechat._client_from_env = lambda: client_builds.append(True)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = wechat.main([
                    "--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID,
                ])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        self.assertEqual(client_builds, [])
        self.assertEqual(json.loads(output.getvalue()), {"claim_status": "already_fetching"})

    def test_each_429_retry_revalidates_claim_before_second_network_attempt(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        rate_limited = HTTPError(
            wechat.API_ORIGIN + "/resources/r1/markdown", 429, "slow", {"Retry-After": "0"}, None,
        )

        class AckOnFirstOpen(FakeOpener):
            def open(self, request, timeout):
                self.requests.append((request, timeout))
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.ack(current, "r1", claim_id=CLAIM_ID)
                    wechat.save_state(path, current)
                raise rate_limited

        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = AckOnFirstOpen([])
        client._opener = opener
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda unused: None
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = wechat.main([
                    "--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID,
                ])
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep
        self.assertEqual(result, 0)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(json.loads(output.getvalue()), {"claim_status": "claim_lost"})

    def test_every_non_markdown_attempt_is_durably_reserved_before_network(self):
        path = self.state_file()
        wechat.save_state(path, wechat.new_state())
        envelope = json.dumps({
            "success": True, "code": None, "message": None, "requestId": "request-1",
            "data": {"userTier": "free"},
        }).encode()
        rate_limited = HTTPError(wechat.API_ORIGIN + "/me", 429, "slow", {"Retry-After": "0"}, None)

        class PersistedTotalOpener(FakeOpener):
            def __init__(self, responses):
                super().__init__(responses)
                self.persisted = []

            def open(self, request, timeout):
                state = wechat.load_state(path)
                self.persisted.append((state["total_budget"]["count"], state["api_calls"].get("me")))
                return super().open(request, timeout)

        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = PersistedTotalOpener([rate_limited, FakeResponse(envelope, wechat.API_ORIGIN + "/me")])
        client._opener = opener
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda delay: None
        try:
            with redirect_stdout(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "doctor"])
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep
        self.assertEqual(result, 0)
        self.assertEqual(opener.persisted, [(1, 1), (2, 2)])
        self.assertEqual(wechat.load_state(path)["total_budget"]["count"], 2)

    def test_fourteen_rate_limited_feed_pages_cannot_exceed_total_budget(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        known = wechat.parse_article(record("known-frontier"))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {known["identity"]: sorted(wechat._entry_aliases(known, known["identity"]))},
        })
        day = wechat._beijing_day()
        state["total_budget"] = {"day": day, "count": 22}
        state["body_budget"] = {"day": day, "count": 10}
        wechat.save_state(path, state)

        class RateLimitedPagesOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                if len(self.requests) % 2:
                    raise HTTPError(request.full_url, 429, "slow", {"Retry-After": "0"}, None)
                page = len(self.requests) // 2
                records = [record("p%d-%d" % (page, index)) for index in range(50)]
                payload = json.dumps({
                    "success": True, "code": None, "message": None, "requestId": "r%d" % page,
                    "data": {"dataList": records, "total": 1500},
                }).encode()
                return FakeResponse(payload, request.full_url)

        client = wechat.BestBlogsClient(VALID_API_KEY)
        opener = RateLimitedPagesOpener()
        client._opener = opener
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda delay: None
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                result = wechat.main(["--state-file", str(path), "scan"])
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(output.getvalue())["complete"])
        self.assertEqual(len(opener.requests), 28)
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["total_budget"], {"day": day, "count": 50})
        self.assertEqual(persisted["api_calls"]["subscription"], 28)

    def test_markdown_budget_boundaries_block_before_network_atomically(self):
        for total_count, body_count, reason in (
            (50, 34, "daily_total_budget_exhausted"),
            (49, 35, "daily_body_budget_exhausted"),
        ):
            with self.subTest(total_count=total_count, body_count=body_count):
                path = self.state_file()
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                entry = add_claim(wechat.parse_article(record("r1")))
                state["pending"][entry["identity"]] = entry
                day = wechat._beijing_day()
                state["total_budget"] = {"day": day, "count": total_count}
                state["body_budget"] = {"day": day, "count": body_count}
                wechat.save_state(path, state)
                client = wechat.BestBlogsClient(VALID_API_KEY)
                opener = FakeOpener([])
                client._opener = opener
                original_client = wechat._client_from_env
                wechat._client_from_env = lambda: client
                try:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
                finally:
                    wechat._client_from_env = original_client
                self.assertEqual(result, 0)
                self.assertEqual(json.loads(output.getvalue()), {"fallback_reason": reason})
                self.assertEqual(opener.requests, [])
                persisted = wechat.load_state(path)
                self.assertEqual(persisted["total_budget"]["count"], total_count)
                self.assertEqual(persisted["body_budget"]["count"], body_count)

    def test_protocol_read_errors_are_safe_json_and_markdown_fallback(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)

        class BrokenResponse(FakeResponse):
            def read(self, unused_limit):
                raise http.client.IncompleteRead(b"partial-secret", 100)

        original_client = wechat._client_from_env
        try:
            doctor_client = wechat.BestBlogsClient(VALID_API_KEY)
            doctor_client._opener = FakeOpener([BrokenResponse(b"", wechat.API_ORIGIN + "/me")])
            wechat._client_from_env = lambda: doctor_client
            doctor_output = io.StringIO()
            with redirect_stdout(doctor_output), redirect_stderr(io.StringIO()):
                doctor_result = wechat.main(["--state-file", str(path), "doctor"])
            self.assertEqual(doctor_result, 2)
            self.assertEqual(json.loads(doctor_output.getvalue()), {"error": "BestBlogs network request failed"})
            self.assertNotIn("partial-secret", doctor_output.getvalue())

            markdown_client = wechat.BestBlogsClient(VALID_API_KEY)
            markdown_client._opener = FakeOpener([
                BrokenResponse(b"", wechat.API_ORIGIN + "/resources/r1/markdown"),
            ])
            wechat._client_from_env = lambda: markdown_client
            markdown_output = io.StringIO()
            with redirect_stdout(markdown_output), redirect_stderr(io.StringIO()):
                markdown_result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
            self.assertEqual(markdown_result, 0)
            self.assertEqual(json.loads(markdown_output.getvalue()), {
                "fallback_reason": "bestblogs_markdown_unavailable",
            })
        finally:
            wechat._client_from_env = original_client

    def test_recursive_api_and_state_json_are_normalized_to_safe_errors(self):
        body = b'{"success":true}'
        client = wechat.BestBlogsClient(VALID_API_KEY)
        client._opener = FakeOpener([FakeResponse(body, wechat.API_ORIGIN + "/me")])
        original_loads = wechat.json.loads
        wechat.json.loads = lambda unused: (_ for _ in ()).throw(RecursionError("private recursive payload"))
        try:
            with self.assertRaisesRegex(wechat.APIError, "invalid JSON"):
                client.me()
        finally:
            wechat.json.loads = original_loads

        path = self.state_file()
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
        wechat.json.loads = lambda unused: (_ for _ in ()).throw(RecursionError("private recursive state"))
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "status"])
        finally:
            wechat.json.loads = original_loads
        self.assertEqual(result, 2)
        self.assertEqual(original_loads(output.getvalue()), {"error": "state cannot be read safely"})

    def test_deep_unexpected_state_and_output_fail_without_traceback(self):
        state = wechat.new_state()
        deep = "leaf"
        for _ in range(1100):
            deep = [deep]
        state["unexpected"] = deep
        with self.assertRaises(wechat.StateError):
            wechat.save_state(self.state_file(), state)

        path = self.state_file()
        wechat.save_state(path, wechat.new_state())
        original_status = wechat.status
        wechat.status = lambda unused: {"deep": deep}
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "status"])
        finally:
            wechat.status = original_status
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue()), {"error": "output serialization failed safely"})

    def test_scan_result_merge_preserves_concurrent_ack_and_configure(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        old = add_claim(
            wechat.parse_article(record("old")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][old["identity"]] = old
        wechat.save_state(path, state)

        class ConcurrentMutationClient(FakeClient):
            def subscription_page(self, page, page_size, before_attempt=None):
                before_attempt()
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.ack(current, "old", claim_id=CLAIM_ID)
                    wechat.configure_sources(current, ["s2"])
                    wechat.save_state(path, current)
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": [record("new", "s1")]}

        client = ConcurrentMutationClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        try:
            with redirect_stdout(io.StringIO()):
                result = wechat.main(["--state-file", str(path), "scan"])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        persisted = wechat.load_state(path)
        self.assertEqual(list(persisted["sources"]), ["s2"])
        self.assertNotIn("resource:old", persisted["pending"])
        self.assertNotIn("resource:new", persisted["pending"])

    def test_scan_rejects_aba_source_reconfiguration_during_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        old = wechat.parse_article(record("r1", url="https://mp.weixin.qq.com/s/aba-old"))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                old["identity"]: sorted(wechat._entry_aliases(old, old["identity"])),
            },
        })
        wechat.save_state(path, state)

        class AbaClient:
            def __init__(self):
                self.calls = {}

            def subscription_source_page(self, page, page_size, source_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.configure_sources(current, ["s2"])
                    wechat.configure_sources(current, ["s1"])
                    wechat.save_state(path, current)
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": [
                    record("r1", "s1", url="https://mp.weixin.qq.com/s/aba-new"),
                ]}

        original_client = wechat._client_from_env
        wechat._client_from_env = AbaClient
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
        finally:
            wechat._client_from_env = original_client

        result = json.loads(output.getvalue())
        self.assertTrue(result["superseded"])
        self.assertIn("superseded_configuration", result["warnings"])
        persisted = wechat.load_state(path)
        self.assertEqual(list(persisted["sources"]), ["s1"])
        self.assertFalse(persisted["sources"]["s1"]["initialized"])
        self.assertEqual(persisted["sources"]["s1"]["recent"], {})

    def test_scan_merge_does_not_requeue_an_article_acked_during_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        entry = add_claim(
            wechat.parse_article(record("acked")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)

        class AckDuringFetchClient(FakeClient):
            def subscription_page(self, page, page_size, before_attempt=None):
                before_attempt()
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.ack(current, "acked", claim_id=CLAIM_ID)
                    wechat.save_state(path, current)
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": [record("acked", "s1")]}

        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: AckDuringFetchClient()
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
        finally:
            wechat._client_from_env = original_client
        persisted = wechat.load_state(path)
        self.assertNotIn(entry["identity"], persisted["pending"])
        self.assertIn(entry["identity"], persisted["sources"]["s1"]["recent"])

    def test_older_scan_result_does_not_overwrite_newer_scan_state(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        wechat.save_state(path, state)

        class SupersededScanClient(FakeClient):
            def subscription_page(self, page, page_size, before_attempt=None):
                before_attempt()
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    current["next_scan_seq"] += 1
                    current["last_applied_scan_generation"] = current["next_scan_seq"]
                    current["scan_health"] = {
                        "pages": 9, "records": 9, "complete": True,
                        "skipped": {"invalid_or_non_wechat": 0},
                    }
                    current["warnings"] = ["newer_scan_won"]
                    wechat.save_state(path, current)
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": [record("stale", "s1")]}

        client = SupersededScanClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = wechat.main(["--state-file", str(path), "scan"])
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())["superseded"])
        persisted = wechat.load_state(path)
        self.assertEqual(persisted["scan_health"]["records"], 9)
        self.assertEqual(persisted["warnings"], ["newer_scan_won"])
        self.assertNotIn("resource:stale", persisted["pending"])

    def test_later_started_failed_scan_supersedes_older_success(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["initialized"] = True
        wechat.save_state(path, state)

        class LaterFailedScanClient(FakeClient):
            def subscription_page(self, page, page_size, before_attempt=None):
                before_attempt()
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    current["next_scan_seq"] += 1
                    wechat.save_state(path, current)
                self.calls["subscription"] = self.calls.get("subscription", 0) + 1
                return {"dataList": [record("older-success", "s1")]}

        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: LaterFailedScanClient()
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
        finally:
            wechat._client_from_env = original_client
        result = json.loads(output.getvalue())
        self.assertTrue(result["superseded"])
        persisted = wechat.load_state(path)
        self.assertFalse(any(
            entry["resource_id"] == "older-success"
            for entry in persisted["pending"].values()
        ))
        self.assertEqual(persisted["last_applied_scan_generation"], 0)

    def test_newer_partial_observation_settles_generation_before_older_complete(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        known = wechat.parse_article(record("known", "s1"))
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {
                known["identity"]: sorted(
                    wechat._entry_aliases(known, known["identity"]),
                ),
            },
        })
        state["next_scan_seq"] = 2
        fingerprint = wechat._source_configuration_fingerprint(state["sources"])
        newer = {
            "records": [],
            "complete": False,
            "warnings": ["feed_ended_before_total"],
            "pages": 1,
            "source_ids": ["s1"],
            "source_configuration_fingerprint": fingerprint,
        }
        older = {
            "records": [record("stale-new", "s1")],
            "complete": True,
            "warnings": [],
            "pages": 1,
            "source_ids": ["s1"],
            "source_configuration_fingerprint": fingerprint,
        }

        partial = wechat._apply_scan_observation(state, newer, generation=2)
        stale = wechat._apply_scan_observation(state, older, generation=1)

        self.assertFalse(partial["complete"])
        self.assertEqual(state["last_applied_scan_generation"], 2)
        self.assertTrue(stale["superseded"])
        self.assertEqual(state["pending"], {})

    def test_cli_markdown_reservation_write_failure_prevents_outbound_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        wechat.save_state(path, state)
        client = FakeClient()
        original_client = wechat._client_from_env
        original_save = wechat.save_state

        def fail_write(unused_path, unused_state):
            raise OSError("cannot write /private/secret-owner/reservation.json")

        wechat._client_from_env = lambda: client
        wechat.save_state = fail_write
        stream = io.StringIO()
        try:
            with redirect_stdout(stream):
                result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
        finally:
            wechat._client_from_env = original_client
            wechat.save_state = original_save
        self.assertEqual(result, 2)
        self.assertEqual(client.calls.get("markdown", 0), 0)
        self.assertEqual(json.loads(stream.getvalue()), {"error": "state operation failed safely"})
        self.assertNotIn("secret-owner", stream.getvalue())

    def test_429_retry_never_exceeds_daily_markdown_attempt_limit(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        entry = add_claim(wechat.parse_article(record("r1")))
        state["pending"][entry["identity"]] = entry
        state["body_budget"] = {"day": wechat._beijing_day(), "count": wechat.BODY_DAILY_LIMIT - 1}
        state["total_budget"] = {"day": wechat._beijing_day(), "count": wechat.BODY_DAILY_LIMIT - 1}
        wechat.save_state(path, state)
        rate_limited = HTTPError(
            wechat.API_ORIGIN + "/resources/r1/markdown", 429, "slow", {"Retry-After": "0"}, None,
        )
        client = wechat.BestBlogsClient(VALID_API_KEY)
        client._opener = FakeOpener([rate_limited])
        original_client = wechat._client_from_env
        original_sleep = wechat.time.sleep
        wechat._client_from_env = lambda: client
        wechat.time.sleep = lambda delay: None
        stream = io.StringIO()
        try:
            with redirect_stdout(stream):
                result = wechat.main(["--state-file", str(path), "markdown", "r1", "--claim-id", CLAIM_ID])
        finally:
            wechat._client_from_env = original_client
            wechat.time.sleep = original_sleep
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stream.getvalue()), {"fallback_reason": "daily_body_budget_exhausted"})
        self.assertEqual(client.calls["/resources/r1/markdown"], 1)
        self.assertEqual(wechat.load_state(path)["body_budget"]["count"], wechat.BODY_DAILY_LIMIT)

    def test_source_cap_corrupt_state_and_secret_redaction(self):
        state = wechat.new_state()
        with self.assertRaises(ValueError):
            wechat.configure_sources(state, [f"s{i}" for i in range(11)])
        path = self.state_file()
        path.parent.mkdir(parents=True)
        path.write_text('{"version": 999}')
        with self.assertRaises(wechat.StateError):
            wechat.load_state(path)
        self.assertEqual(path.read_text(), '{"version": 999}')
        malformed = wechat.new_state()
        malformed["sources"]["s1"] = {"id": "s1", "initialized": True, "recent": [], "health": {}}
        path.write_text(json.dumps(malformed))
        with self.assertRaises(wechat.StateError):
            wechat.load_state(path)
        self.assertEqual(path.read_text(), json.dumps(malformed))
        malformed = wechat.new_state()
        entry = wechat.parse_article(record("r1"))
        entry["identity"] = "resource:other"
        malformed["pending"]["resource:other"] = entry
        path.write_text(json.dumps(malformed))
        with self.assertRaises(wechat.StateError):
            wechat.load_state(path)
        path.write_text(json.dumps({"version": 1, "sources": [], "pending": {}, "body_budget": {}, "api_calls": {}, "warnings": []}))
        with self.assertRaises(wechat.StateError):
            wechat.load_state(path)
        output = wechat.doctor(FakeClient(), api_key="dummy")
        self.assertNotIn("dummy", json.dumps(output))
        self.assertNotIn("secret@example.com", json.dumps(output))
        self.assertEqual(output["tier"], "pro")

    def test_configure_discards_pending_and_tombstones_for_deselected_sources(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1", "s2"])
        removed = wechat.parse_article(record("removed", "s1"))
        retained = wechat.parse_article(record("retained", "s2"))
        state["pending"] = {
            removed["identity"]: removed,
            retained["identity"]: retained,
        }
        removed_ack = wechat.parse_article(record("removed-ack", "s1"))
        retained_ack = wechat.parse_article(record("retained-ack", "s2"))
        state["ack_tombstones"] = {
            removed_ack["identity"]: {
                "source_id": "s1",
                "ack_after_scan_seq": 0,
                "aliases": sorted(
                    wechat._entry_aliases(removed_ack, removed_ack["identity"]),
                ),
            },
            retained_ack["identity"]: {
                "source_id": "s2",
                "ack_after_scan_seq": 0,
                "aliases": sorted(
                    wechat._entry_aliases(retained_ack, retained_ack["identity"]),
                ),
            },
        }

        receipt = wechat.configure_sources(state, ["s2"])

        self.assertEqual(receipt, {
            "configured_sources": ["s2"],
            "discarded_pending": 1,
            "discarded_tombstones": 1,
        })
        self.assertEqual(list(state["pending"]), [retained["identity"]])
        self.assertEqual(list(state["ack_tombstones"]), [retained_ack["identity"]])

    def test_cli_quarantines_preexisting_pending_for_deselected_source(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s2"])
        stale = wechat.parse_article(record("stale", "s1"))
        state["pending"][stale["identity"]] = stale
        wechat.save_state(path, state)

        pending_output = io.StringIO()
        with redirect_stdout(pending_output):
            self.assertEqual(wechat.main(["--state-file", str(path), "pending"]), 0)
        pending_receipt = json.loads(pending_output.getvalue())
        self.assertEqual(pending_receipt["retryable"], [])
        self.assertEqual(pending_receipt["claimed"], [])
        self.assertEqual(pending_receipt["exhausted"], [])
        self.assertEqual(pending_receipt["deselected_count"], 1)

        claim_output = io.StringIO()
        with redirect_stdout(claim_output):
            self.assertEqual(
                wechat.main(["--state-file", str(path), "claim", "stale"]),
                2,
            )
        self.assertIn("not configured", json.loads(claim_output.getvalue())["error"])

        current_status = wechat.status(wechat.load_state(path))
        self.assertEqual(current_status["pending"], 0)
        self.assertEqual(current_status["deselected_pending"], 1)

    def test_budget_days_and_cross_budget_counts_are_canonical_and_consistent(self):
        day = "2026-07-18"
        invalid_states = []
        for bad_day in ("2026-07-18T00:00:00", "2026-7-18", "2026-02-30"):
            state = wechat.new_state()
            state["total_budget"] = {"day": bad_day, "count": 1}
            invalid_states.append(state)
        state = wechat.new_state()
        state["total_budget"] = {"day": day, "count": True}
        invalid_states.append(state)
        state = wechat.new_state()
        state["body_budget"] = {"day": day, "count": 35}
        state["total_budget"] = {"day": day, "count": 0}
        invalid_states.append(state)
        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(wechat.StateError):
                    wechat.save_state(self.state_file(), state)

    def test_budget_clock_rollback_and_naive_injected_time_fail_closed(self):
        state = wechat.new_state()
        state["total_budget"] = {"day": "2026-07-19", "count": 4}
        state["body_budget"] = {"day": "2026-07-19", "count": 2}
        before = copy.deepcopy(state)
        with self.assertRaises(wechat.StateError):
            wechat._reserve_api_attempt(
                state, now=datetime(2026, 7, 18, 12, tzinfo=timezone.utc), body=True,
            )
        self.assertEqual(state, before)
        with self.assertRaises(wechat.StateError):
            wechat._beijing_day(datetime(2026, 7, 18, 12))

    def test_budget_reservation_rejects_cross_day_body_total_inconsistency_atomically(self):
        state = wechat.new_state()
        state["body_budget"] = {"day": "2026-07-18", "count": 5}
        state["total_budget"] = {"day": "2026-07-17", "count": 12}
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(wechat.StateError, "inconsistent"):
            wechat._reserve_api_attempt(
                state, now=datetime(2026, 7, 18, 12, tzinfo=timezone.utc), body=True,
            )
        self.assertEqual(state, before)

    def test_well_formed_v1_state_migrates_to_v4_with_fail_closed_total_budget(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 1
        legacy.pop("total_budget", None)
        legacy.pop("next_scan_seq", None)
        legacy.pop("last_applied_scan_generation", None)
        legacy.pop("ack_tombstones", None)
        legacy["body_budget"] = {"day": wechat._beijing_day(), "count": 7}
        wechat.configure_sources(legacy, ["s1"])
        old_url = "https://mp.weixin.qq.com/s/v1-recent?sessionid=private"
        old_identity = "url:" + hashlib.sha256(old_url.encode("utf-8")).hexdigest()
        legacy["sources"]["s1"].update({
            "initialized": True, "recent": {old_identity: True},
        })
        legacy_entry = wechat.parse_article(record("r1"))
        legacy_entry["identity"] = "resource:r1"
        legacy["pending"]["resource:r1"] = legacy_entry
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 4)
        self.assertEqual(migrated["total_budget"], {
            "day": wechat._beijing_day(), "count": wechat.TOTAL_DAILY_LIMIT,
        })
        self.assertEqual(migrated["body_budget"]["count"], 7)
        self.assertEqual(migrated["pending"], {})
        self.assertIn("legacy_pending_discarded:1", migrated["warnings"])
        self.assertFalse(migrated["sources"]["s1"]["initialized"])
        self.assertEqual(migrated["sources"]["s1"]["recent"], {})
        self.assertIn("identity_rebaseline:s1", migrated["warnings"])

        with redirect_stdout(io.StringIO()):
            self.assertEqual(wechat.main(["--state-file", str(path), "status"]), 0)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["version"], 4)
        self.assertEqual(persisted["total_budget"]["count"], 50)

    def test_earliest_exact_v1_state_without_scan_health_migrates(self):
        path = self.state_file()
        earliest = {
            "version": 1,
            "sources": {},
            "pending": {},
            "body_budget": {"day": "", "count": 0},
            "last_successful_scan": None,
            "api_calls": {},
            "warnings": [],
        }
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(earliest), encoding="utf-8")
        try:
            migrated = wechat.load_state(path)
        except wechat.StateError as error:
            self.fail("exact earliest v1 state did not migrate: %s" % error)
        self.assertEqual(migrated["version"], 4)
        self.assertEqual(migrated["scan_health"], {
            "pages": 0, "records": 0, "complete": False,
            "skipped": {"invalid_or_non_wechat": 0},
        })
        self.assertEqual(migrated["total_budget"]["count"], wechat.TOTAL_DAILY_LIMIT)

    def test_early_v1_pending_with_obsolete_url_shape_is_discarded_safely(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 1
        legacy.pop("total_budget")
        legacy.pop("next_scan_seq")
        legacy.pop("last_applied_scan_generation")
        legacy.pop("ack_tombstones")
        old_url = "https://legacy.weixin.qq.com/obsolete/path?x=1"
        old_identity = "url:" + hashlib.sha256(old_url.encode("utf-8")).hexdigest()
        legacy["pending"][old_identity] = {
            "identity": old_identity,
            "resource_id": None,
            "source_id": "s1",
            "source_name": "Legacy Source",
            "title": "Legacy article",
            "url": old_url,
            "published_at": "",
            "attempts": 0,
        }
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["pending"], {})
        self.assertIn("legacy_pending_discarded:1", migrated["warnings"])

    def test_well_formed_v2_state_migrates_sequences_without_claim_or_tombstone_data(self):
        path = self.state_file()
        previous = wechat.new_state()
        previous["version"] = 2
        previous["scan_generation"] = 4
        previous.pop("next_scan_seq")
        previous.pop("last_applied_scan_generation")
        previous.pop("ack_tombstones")
        wechat.configure_sources(previous, ["s1"])
        old_url = "https://mp.weixin.qq.com/s/v2-recent?srcid=legacy"
        old_identity = "url:" + hashlib.sha256(old_url.encode("utf-8")).hexdigest()
        previous["sources"]["s1"].update({
            "initialized": True, "recent": {old_identity: True},
        })
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(previous), encoding="utf-8")
        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 4)
        self.assertEqual(migrated["next_scan_seq"], 4)
        self.assertEqual(migrated["last_applied_scan_generation"], 0)
        self.assertEqual(migrated["ack_tombstones"], {})
        self.assertFalse(migrated["sources"]["s1"]["initialized"])
        self.assertEqual(migrated["sources"]["s1"]["recent"], {})
        self.assertIn("identity_rebaseline:s1", migrated["warnings"])

    def test_v3_resource_recent_migrates_to_rebaseline_before_id_drift_can_enqueue(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 3
        wechat.configure_sources(legacy, ["s1"])
        legacy["sources"]["s1"].update({
            "initialized": True,
            "recent": {"resource:r1": True},
        })
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 4)
        self.assertFalse(migrated["sources"]["s1"]["initialized"])
        self.assertEqual(migrated["sources"]["s1"]["recent"], {})
        self.assertIn("identity_rebaseline:s1", migrated["warnings"])
        result = wechat.scan(migrated, FakeClient([{
            "dataList": [record("r2", url="https://mp.weixin.qq.com/s/same-historical-page")],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(migrated["pending"], {})
        self.assertTrue(migrated["sources"]["s1"]["initialized"])

    def test_v3_url_recent_migrates_to_rebaseline_after_canonicalizer_tightening(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 3
        wechat.configure_sources(legacy, ["s1"])
        old_url = "https://mp.weixin.qq.com/s/stable?sessionid=private"
        old_identity = "url:" + hashlib.sha256(old_url.encode("utf-8")).hexdigest()
        legacy["sources"]["s1"].update({
            "initialized": True,
            "recent": {old_identity: True},
        })
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertFalse(migrated["sources"]["s1"]["initialized"])
        self.assertEqual(migrated["sources"]["s1"]["recent"], {})
        self.assertIn("identity_rebaseline:s1", migrated["warnings"])
        result = wechat.scan(migrated, FakeClient([{
            "dataList": [record(None, url=old_url)],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(migrated["pending"], {})

    def test_v3_pending_is_discarded_when_identity_rules_change(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 3
        wechat.configure_sources(legacy, ["s1"])
        legacy["sources"]["s1"]["initialized"] = True
        old_url = "https://mp.weixin.qq.com/s/pending?sessionid=private"
        old_identity = "url:" + hashlib.sha256(old_url.encode("utf-8")).hexdigest()
        entry = wechat.parse_article(record(None, url=old_url))
        entry.update({"identity": old_identity, "url": old_url})
        legacy["pending"][old_identity] = entry
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["pending"], {})
        self.assertIn("legacy_pending_discarded:1", migrated["warnings"])
        self.assertFalse(migrated["sources"]["s1"]["initialized"])

    def test_v3_overlapping_pending_and_tombstone_state_cannot_redeliver(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 3
        wechat.configure_sources(legacy, ["s1"])
        legacy["sources"]["s1"]["initialized"] = True
        shared_url = "https://mp.weixin.qq.com/s/shared"
        resource_entry = wechat.parse_article(record("r1", url=shared_url))
        resource_entry["identity"] = "resource:r1"
        url_entry = wechat.parse_article(record(None, url=shared_url))
        legacy["pending"] = {
            resource_entry["identity"]: resource_entry,
            url_entry["identity"]: url_entry,
        }
        legacy["ack_tombstones"] = {
            "resource:r1": {"source_id": "s1", "ack_after_scan_seq": 0},
        }
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["pending"], {})
        self.assertEqual(wechat.pending(migrated)["retryable"], [])
        self.assertIn("legacy_pending_discarded:2", migrated["warnings"])

    def test_v3_tombstones_and_pending_are_discarded_before_safe_rebaseline(self):
        path = self.state_file()
        stable_url = "https://mp.weixin.qq.com/s/legacy-pending"
        legacy = wechat.new_state()
        legacy["version"] = 3
        legacy["next_scan_seq"] = 8
        wechat.configure_sources(legacy, ["s1"])
        legacy["sources"]["s1"]["initialized"] = True
        pending_entry = wechat.parse_article(record("pending-id", url=stable_url))
        pending_entry["identity"] = "resource:pending-id"
        legacy["pending"]["resource:pending-id"] = pending_entry
        legacy["ack_tombstones"] = {
            "resource:acked-id": {"source_id": "s1", "ack_after_scan_seq": 7},
        }
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 4)
        self.assertEqual(migrated["ack_tombstones"], {})
        self.assertEqual(migrated["pending"], {})
        self.assertIn("legacy_pending_discarded:1", migrated["warnings"])
        self.assertIn("legacy_tombstones_discarded:1", migrated["warnings"])
        self.assertFalse(migrated["sources"]["s1"]["initialized"])
        result = wechat.scan(migrated, FakeClient([{
            "dataList": [
                record("drifted-id", url=stable_url),
                record("acked-id", url="https://mp.weixin.qq.com/s/legacy-acked-moved"),
            ],
        }]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(migrated["pending"], {})

    def test_first_cli_rebaseline_scan_surfaces_migration_receipts_once(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 3
        wechat.configure_sources(legacy, ["s1"])
        legacy["sources"]["s1"]["initialized"] = True
        pending_entry = wechat.parse_article(record("pending-id"))
        pending_entry["identity"] = "resource:pending-id"
        legacy["pending"][pending_entry["identity"]] = pending_entry
        legacy["ack_tombstones"] = {
            "resource:acked-id": {"source_id": "s1", "ack_after_scan_seq": 0},
        }
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: FakeClient([{"dataList": []}])
        try:
            first_output = io.StringIO()
            with redirect_stdout(first_output):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
            first = json.loads(first_output.getvalue())
            self.assertIn("identity_rebaseline:s1", first["warnings"])
            self.assertIn("legacy_pending_discarded:1", first["warnings"])
            self.assertIn("legacy_tombstones_discarded:1", first["warnings"])
            self.assertEqual(wechat.load_state(path)["warnings"], first["warnings"])

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                self.assertEqual(wechat.main(["--state-file", str(path), "scan"]), 0)
            self.assertEqual(json.loads(second_output.getvalue())["warnings"], [])
            self.assertEqual(wechat.load_state(path)["warnings"], [])
        finally:
            wechat._client_from_env = original_client

    def test_malformed_v3_container_types_fail_as_state_errors_during_migration(self):
        base = wechat.new_state()
        base["version"] = 3
        cases = (
            ("ack_tombstones", []),
            ("sources", []),
        )
        for field, bad_value in cases:
            with self.subTest(field=field):
                path = self.state_file()
                malformed = copy.deepcopy(base)
                malformed[field] = bad_value
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.assertRaises(wechat.StateError):
                    wechat.load_state(path)

    def test_malformed_nested_v3_state_fails_safely_without_rewriting(self):
        base = wechat.new_state()
        base["version"] = 3
        wechat.configure_sources(base, ["s1"])
        cases = []
        bad_tombstone = copy.deepcopy(base)
        bad_tombstone["ack_tombstones"] = {
            "resource:r1": {"source_id": [], "ack_after_scan_seq": 0},
        }
        cases.append(bad_tombstone)
        for recent in (123, [1]):
            malformed = copy.deepcopy(base)
            malformed["sources"]["s1"]["recent"] = recent
            cases.append(malformed)
        for index, malformed in enumerate(cases):
            with self.subTest(index=index):
                path = self.state_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                encoded = json.dumps(malformed)
                path.write_text(encoded, encoding="utf-8")
                with self.assertRaises(wechat.StateError):
                    wechat.load_state(path)
                self.assertEqual(path.read_text(encoding="utf-8"), encoded)

    def test_v4_alias_lists_reject_non_string_values_as_state_errors(self):
        url = "https://mp.weixin.qq.com/s/valid"
        identity = "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
        cases = []
        recent = wechat.new_state()
        wechat.configure_sources(recent, ["s1"])
        recent["sources"]["s1"].update({
            "initialized": True,
            "recent": {identity: [identity, {}]},
        })
        cases.append(recent)
        tombstone = wechat.new_state()
        tombstone["ack_tombstones"][identity] = {
            "source_id": "s1", "ack_after_scan_seq": 0,
            "aliases": [identity, 1],
        }
        cases.append(tombstone)
        for malformed in cases:
            with self.subTest(malformed=malformed):
                with self.assertRaises(wechat.StateError):
                    wechat.save_state(self.state_file(), malformed)

    def test_v4_state_rejects_overlapping_pending_and_tombstone_aliases(self):
        shared = wechat.parse_article(record("r1", url="https://mp.weixin.qq.com/s/shared"))
        resource_copy = wechat.parse_article(record(
            "r1", url="https://mp.weixin.qq.com/s/shared-by-resource",
        ))
        tombstone_one = wechat.parse_article(record(
            "t1", url="https://mp.weixin.qq.com/s/tombstone-one",
        ))["identity"]
        tombstone_two = wechat.parse_article(record(
            "t2", url="https://mp.weixin.qq.com/s/tombstone-two",
        ))["identity"]
        cases = []
        duplicate_pending = wechat.new_state()
        duplicate_pending["pending"] = {
            shared["identity"]: shared,
            resource_copy["identity"]: resource_copy,
        }
        cases.append(duplicate_pending)
        pending_tombstone = wechat.new_state()
        pending_tombstone["pending"][shared["identity"]] = shared
        pending_tombstone["ack_tombstones"][tombstone_one] = {
            "source_id": "s1", "ack_after_scan_seq": 0,
            "aliases": sorted([tombstone_one, "resource:r1"]),
        }
        cases.append(pending_tombstone)
        duplicate_tombstones = wechat.new_state()
        duplicate_tombstones["ack_tombstones"] = {
            tombstone_one: {
                "source_id": "s1", "ack_after_scan_seq": 0,
                "aliases": sorted([tombstone_one, "resource:r1"]),
            },
            tombstone_two: {
                "source_id": "s1", "ack_after_scan_seq": 0,
                "aliases": sorted([tombstone_two, "resource:r1"]),
            },
        }
        cases.append(duplicate_tombstones)
        for malformed in cases:
            with self.subTest(malformed=malformed):
                with self.assertRaises(wechat.StateError):
                    wechat.save_state(self.state_file(), malformed)

    def test_v4_pending_and_tombstones_require_url_primary_identities(self):
        pending = wechat.new_state()
        entry = wechat.parse_article(record("r1", url="https://mp.weixin.qq.com/s/primary"))
        entry["identity"] = "resource:r1"
        pending["pending"][entry["identity"]] = entry
        tombstone = wechat.new_state()
        tombstone["ack_tombstones"]["resource:r1"] = {
            "source_id": "s1", "ack_after_scan_seq": 0,
            "aliases": ["resource:r1"],
        }
        for malformed in (pending, tombstone):
            with self.subTest(malformed=malformed):
                with self.assertRaises(wechat.StateError):
                    wechat.save_state(self.state_file(), malformed)

    def test_pending_state_rejects_unexpected_content_fields_without_rewriting(self):
        path = self.state_file()
        path.parent.mkdir(parents=True)
        for field in ("markdown", "body", "content", "summary", "unrecognized"):
            state = wechat.new_state()
            entry = wechat.parse_article(record("r1"))
            entry[field] = "forbidden persisted content"
            state["pending"][entry["identity"]] = entry
            serialized = json.dumps(state)
            path.write_text(serialized)
            with self.assertRaises(wechat.StateError):
                wechat.load_state(path)
            self.assertEqual(path.read_text(), serialized)

    def test_v4_recent_entries_require_a_primary_canonical_url_identity(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"].update({
            "initialized": True,
            "recent": {"resource:r1": ["resource:r1"]},
        })
        with self.assertRaises(wechat.StateError):
            wechat.save_state(self.state_file(), state)

    def test_successful_doctor_and_sources_cli_persist_call_counters(self):
        path = self.state_file()
        client = FakeClient([{"dataList": [record("r1")]}])
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wechat.main(["--state-file", str(path), "doctor"]), 0)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wechat.main(["--state-file", str(path), "sources"]), 0)
        finally:
            wechat._client_from_env = original_client
        self.assertEqual(wechat.status(wechat.load_state(path))["api_calls"], {"me": 1, "subscription": 1})

    def test_source_search_and_follow_cli_persist_each_durable_api_attempt(self):
        path = self.state_file()

        class IntakeClient:
            def source_search(self, name, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return {"dataList": [{"sourceId": "SOURCE_one", "sourceName": name}]}

            def follow_sources(self, source_ids, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return {"followedCount": len(source_ids), "skippedCount": 0}

        original_client = wechat._client_from_env
        wechat._client_from_env = IntakeClient
        search_output = io.StringIO()
        follow_output = io.StringIO()
        try:
            with redirect_stdout(search_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "search-sources", "--name", "新智元",
                ]), 0)
            with redirect_stdout(follow_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "follow", "--source-id", "SOURCE_one",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(search_output.getvalue()), {
            "sources": [{"id": "SOURCE_one", "name": "新智元"}],
        })
        self.assertEqual(json.loads(follow_output.getvalue()), {
            "followedCount": 1, "skippedCount": 0,
        })
        persisted = wechat.status(wechat.load_state(path))
        self.assertEqual(persisted["api_calls"], {"source_search": 1, "onboarding_follow": 1})
        self.assertEqual(persisted["total_budget"]["used"], 2)

    def test_cli_reports_corrupt_state_as_json_error_without_traceback(self):
        path = self.state_file()
        path.parent.mkdir(parents=True)
        path.write_text("not json")
        stream = io.StringIO()
        with redirect_stdout(stream):
            result = wechat.main(["--state-file", str(path), "status"])
        self.assertEqual(result, 2)
        self.assertIn("state cannot be read safely", stream.getvalue())

    def test_state_reader_enforces_a_bounded_byte_limit_before_json_decode(self):
        self.assertTrue(hasattr(wechat, "MAX_STATE_BYTES"), "state read byte cap is required")
        path = self.state_file()
        path.parent.mkdir(parents=True)
        path.write_bytes(b" " * 65)
        original_limit = wechat.MAX_STATE_BYTES
        wechat.MAX_STATE_BYTES = 64
        try:
            with self.assertRaisesRegex(wechat.StateError, "size limit"):
                wechat.load_state(path)
        finally:
            wechat.MAX_STATE_BYTES = original_limit
        self.assertEqual(path.stat().st_size, 65)

    def test_state_writer_never_persists_a_file_larger_than_the_read_cap(self):
        path = self.state_file()
        original_limit = wechat.MAX_STATE_BYTES
        wechat.MAX_STATE_BYTES = 64
        try:
            with self.assertRaisesRegex(wechat.StateError, "size limit"):
                wechat.save_state(path, wechat.new_state())
        finally:
            wechat.MAX_STATE_BYTES = original_limit
        self.assertFalse(path.exists())

    def test_cli_reports_state_write_oserror_as_redacted_json(self):
        path = self.state_file()
        original_save = wechat.save_state

        def fail_write(unused_path, unused_state):
            raise OSError("cannot write /private/secret-owner/state.json")

        wechat.save_state = fail_write
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    result = wechat.main(["--state-file", str(path), "configure", "--source-id", "s1"])
                except OSError:
                    result = None
        finally:
            wechat.save_state = original_save
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(stdout.getvalue()), {"error": "state operation failed safely"})
        self.assertNotIn("secret-owner", stdout.getvalue() + stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_article_resource_id_aliases_work_for_pending_actions(self):
        state = wechat.new_state()
        entry = add_claim(
            wechat.parse_article(record("r1")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        self.assertEqual(
            wechat.fail(state, "r1", "FETCH_FAILED", claim_id=CLAIM_ID)["attempts"], 1,
        )
        add_claim(entry, expires_at="2999-01-01T00:00:00Z")
        self.assertEqual(
            wechat.ack(state, "r1", claim_id=CLAIM_ID)["acknowledged"], entry["identity"],
        )

    def test_url_key_pending_resolves_unique_raw_resource_id_for_every_action(self):
        def url_entry(resource_id="r1", token="one"):
            entry = wechat.parse_article(record(
                resource_id, url="https://mp.weixin.qq.com/s/%s" % token,
            ))
            self.assertTrue(entry["identity"].startswith("url:"))
            return entry

        state = wechat.new_state()
        entry = url_entry()
        state["pending"][entry["identity"]] = entry
        issued = wechat.claim(state, "r1")
        self.assertIn("claim_id", issued)

        for action in ("renew", "markdown", "fail", "ack"):
            with self.subTest(action=action):
                state = wechat.new_state()
                entry = add_claim(url_entry())
                state["pending"][entry["identity"]] = entry
                if action == "renew":
                    receipt = wechat.renew(state, "r1", CLAIM_ID)
                    self.assertEqual(receipt["claim_id"], CLAIM_ID)
                elif action == "markdown":
                    receipt = wechat.markdown(state, FakeClient(markdown="# body"), "r1")
                    self.assertEqual(receipt["source"], "bestblogs")
                elif action == "fail":
                    receipt = wechat.fail(state, "r1", "FETCH_FAILED", claim_id=CLAIM_ID)
                    self.assertEqual(receipt["attempts"], 1)
                else:
                    receipt = wechat.ack(state, "r1", claim_id=CLAIM_ID)
                    self.assertEqual(receipt["acknowledged"], entry["identity"])

    def test_raw_resource_id_resolution_is_ambiguous_when_multiple_pending_entries_match(self):
        state = wechat.new_state()
        for token in ("one", "two"):
            entry = wechat.parse_article(record(
                "shared", url="https://mp.weixin.qq.com/s/%s" % token,
            ))
            state["pending"][entry["identity"]] = entry
        with self.assertRaisesRegex(KeyError, "ambiguous"):
            wechat.claim(state, "shared")

    def test_direct_pending_identity_cannot_shadow_another_raw_resource_id(self):
        state = wechat.new_state()
        direct = wechat.parse_article(record("direct", url="https://mp.weixin.qq.com/s/direct"))
        shadow = wechat.parse_article(record(
            direct["identity"], url="https://mp.weixin.qq.com/s/shadow",
        ))
        state["pending"] = {direct["identity"]: direct, shadow["identity"]: shadow}
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(KeyError, "ambiguous"):
            wechat.claim(state, direct["identity"])
        self.assertEqual(state, before)

    def test_identity_resource_collision_is_ambiguous_for_every_pending_action(self):
        for action in ("renew", "markdown", "fail", "ack"):
            with self.subTest(action=action):
                state = wechat.new_state()
                direct = wechat.parse_article(record(
                    "direct", url="https://mp.weixin.qq.com/s/direct-action",
                ))
                shadow = wechat.parse_article(record(
                    direct["identity"], url="https://mp.weixin.qq.com/s/shadow-action",
                ))
                add_claim(direct)
                add_claim(shadow)
                state["pending"] = {
                    direct["identity"]: direct,
                    shadow["identity"]: shadow,
                }
                before = copy.deepcopy(state)
                with self.assertRaisesRegex(KeyError, "ambiguous"):
                    if action == "renew":
                        wechat.renew(state, direct["identity"], CLAIM_ID)
                    elif action == "markdown":
                        wechat.markdown(state, FakeClient(markdown="# body"), direct["identity"])
                    elif action == "fail":
                        wechat.fail(state, direct["identity"], "FETCH_FAILED", claim_id=CLAIM_ID)
                    else:
                        wechat.ack(state, direct["identity"], claim_id=CLAIM_ID)
                self.assertEqual(state, before)

    def test_status_exposes_safe_body_budget_details(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["body_budget"] = {"day": "2026-07-18", "count": 17}
        state["total_budget"] = {"day": "2026-07-18", "count": 21}
        entry = add_claim(
            wechat.parse_article(record("claimed")),
            expires_at="2999-01-01T00:00:00Z",
        )
        state["pending"][entry["identity"]] = entry
        self.assertEqual(wechat.status(state)["body_budget"], {
            "day": "2026-07-18", "used": 17, "limit": 35,
        })
        self.assertEqual(wechat.status(state)["total_budget"], {
            "day": "2026-07-18", "used": 21, "limit": 50,
        })
        self.assertEqual(wechat.status(state)["claimed"], 1)

        self.assertFalse(wechat.status(state)["baseline_established"])
        state["scan_health"]["complete"] = True
        self.assertFalse(wechat.status(state)["baseline_established"])
        state["sources"]["s1"]["initialized"] = True
        self.assertTrue(wechat.status(state)["baseline_established"])


class WechatDigestSkillContractTests(unittest.TestCase):
    def markdown_section(self, text, heading, next_heading):
        start_marker = "## %s" % heading
        end_marker = "## %s" % next_heading
        self.assertIn(start_marker, text)
        self.assertIn(end_marker, text)
        return text.split(start_marker, 1)[1].split(end_marker, 1)[0]

    def paragraph_containing(self, text, needle):
        matches = [paragraph for paragraph in text.split("\n\n") if needle in paragraph]
        self.assertEqual(len(matches), 1, "expected one paragraph containing %r" % needle)
        return matches[0]

    def sentence_containing(self, text, needle):
        matches = [sentence for sentence in text.split(". ") if needle in sentence]
        self.assertEqual(len(matches), 1, "expected one sentence containing %r" % needle)
        return matches[0]

    def test_skill_routes_interactive_reading_without_the_digest_lifecycle(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        for heading in (
            "Setup", "Intent Routing", "Interactive Reading", "Incremental Digest",
            "Safety and Quotas", "Automation",
        ):
            self.assertIn("## %s" % heading, text, heading)
        intent = self.markdown_section(text, "Intent Routing", "Interactive Reading")
        exact_name = self.paragraph_containing(intent, "search-sources --name <exact-name>")
        for relationship in (
            "requested exact source name", "exactly one result",
            "ID appears in `configured-sources`", "interactive command by that ID",
        ):
            self.assertIn(relationship, exact_name, relationship)
        forbidden = self.paragraph_containing(intent, "Interactive current/latest/recent requests")
        self.assertIn("do not run", forbidden)
        for command in ("`scan`", "`pending`", "`claim`", "`ack`", "`fail`"):
            self.assertIn(command, forbidden, command)

    def test_skill_keeps_interactive_and_digest_fallbacks_separate(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        interactive = self.markdown_section(text, "Interactive Reading", "Incremental Digest")
        digest = self.markdown_section(text, "Incremental Digest", "Safety and Quotas")
        fallback = self.paragraph_containing(interactive, "Use Firecrawl only when read returns")
        self.assertIn("Use Firecrawl only when read returns a structured fallback.", fallback)
        self.assertIn("Scrape only that exact validated URL", fallback)
        self.assertIn("effective/final URL to remain exactly canonical", fallback)
        self.assertIn("It uses no claim/renew/ack gates.", fallback)
        for option in (
            'formats: ["markdown"]', "onlyMainContent: true", "mobile: true",
            "storeInCache: false", 'proxy: "auto"',
        ):
            self.assertIn(option, fallback, option)
        commands = self.paragraph_containing(interactive, "Use `configured-sources`")
        for command in ("`configured-sources`", "`latest", "`recent", "`read"):
            self.assertIn(command, commands, command)
        read_only = self.paragraph_containing(interactive, "never mark items read")
        for effect in ("bookmark", "highlight", "modify BestBlogs history"):
            self.assertIn(effect, read_only, effect)
        untrusted = self.paragraph_containing(interactive, "untrusted content")
        for relationship in (
            "cannot select tools", "trigger additional calls", "alter the workflow",
            "request secrets", "override instructions",
        ):
            self.assertIn(relationship, untrusted, relationship)
        self.assertIn("claim/renew/ack lifecycle", digest)
        self.assertIn(
            "run `markdown <article_id> --claim-id <claim_id> --preserve-reserve`",
            digest,
        )
        self.assertIn("`bestblogs_quota_reserve_preserved`", digest)
        self.assertIn(
            "Only a structured `fallback_reason` receipt may permit Firecrawl fallback.",
            digest,
        )
        self.assertIn("Before calling Firecrawl, run `renew <article_id> --claim-id <claim_id>`", digest)

    def test_reader_metadata_plugin_version_and_global_routing_are_english(self):
        metadata = METADATA_FILE.read_text(encoding="utf-8")
        routing_text = (MODULE.parents[5] / "config/codex/AGENTS.global.md").read_text(encoding="utf-8")
        routing = self.paragraph_containing(routing_text, "Use `$wechat-digest`")
        self.assertIn('display_name: "WeChat Reader & Digest"', metadata)
        self.assertIn("$wechat-digest", metadata)
        self.assertIn("interactive reading", metadata.lower())
        self.assertTrue(metadata.isascii())
        self.assertTrue(SKILL_FILE.read_text(encoding="utf-8").isascii())
        latest_route = self.sentence_containing(routing, "latest/current/recent")
        self.assertIn("configured-source questions", latest_route)
        self.assertIn("read-only interactive route", latest_route)
        fallback_route = self.sentence_containing(routing, "Use Firecrawl only when")
        self.assertIn("interactive `read` returns its validated structured fallback", fallback_route)
        self.assertIn("no claim/renew/ack gates", fallback_route)
        self.assertIn("incremental digest claim/renew/ack lifecycle", fallback_route)
        standalone_route = self.sentence_containing(routing, "standalone article URL")
        self.assertIn("historical/topic search", standalone_route)
        self.assertIn("prefer Defuddle", standalone_route)
        self.assertIn("built-in Codex web search", standalone_route)
        self.assertIn("Firecrawl only", standalone_route)
        self.assertTrue(routing_text.isascii())
        plugin = json.loads(PLUGIN_FILE.read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.3.3")
        self.assertIn("wechat reader and digest tools", plugin["description"].lower())

    def test_skill_declares_the_operational_digest_contract(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("name: wechat-digest", text)
        self.assertRegex(text, r"description: Use when.*(?:WeChat|BestBlogs|digest|scheduled)")
        for clause in (
            "bestblogs.env", "BESTBLOGS_API_KEY", "doctor", "sources", "configure",
            "first", "baseline", "scan", "pending", "summarize", "ack",
            "35", "15", "three", "BestBlogs", "Firecrawl", "mp.weixin.qq.com",
            "untrusted", "health", "JSON", "fail", "body_budget",
            "total_budget", "claim", "claimed",
        ):
            self.assertIn(clause, text, clause)
        self.assertIn("never scrape arbitrary hosts or use browser cookies", text.lower())
        self.assertIn("Never ask the user to paste or print the key", text)
        for forbidden in ("s" + "k-", "api_key" + "=", "BESTBLOGS_API_KEY" + "=", "delivery provider"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_skill_spells_out_safe_fallback_quota_and_output_sequence(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("if and only if its JSON is an object with `complete: true`", text)
        self.assertIn("a missing or invalid `complete` field, or any `error` response", text)
        self.assertIn(
            "Use this exact lifecycle: `scan -> pending -> claim -> markdown --preserve-reserve -> "
            "(renew -> Firecrawl fallback when needed) -> renew -> summarize -> renew -> ack -> status`.",
            text,
        )
        self.assertIn("After three failures, leave the item exhausted; do not ack or retry it automatically.", text)
        self.assertIn(
            "Baseline is established if and only if at least one source is configured, the latest scan is complete, and every configured source is initialized; otherwise it is not established.",
            text,
        )
        self.assertIn("configure --source-id <id1> --source-id <id2>", text)
        self.assertIn("35 BestBlogs Markdown attempts", text)
        self.assertIn("15 of 50", text)
        self.assertNotIn("20 bodies", text)
        for clause in (
            "pending entry's exact validated `url`", "formats: [\"markdown\"]",
            "onlyMainContent: true", "mobile: true", "storeInCache: false", 'proxy: "auto"',
            "never select tools", "trigger additional calls", "prepare a complete article output block",
            "then call `ack <article_id>`", "then include the prepared block in the final digest",
            "run `status` directly", "body_budget", "day", "used", "limit",
            "total_budget",
            "all BestBlogs API metadata", "source names", "effective/final URL",
            "claim <article_id>", "--claim-id", "claimed entries are skipped",
            "Before calling Firecrawl, run `renew <article_id> --claim-id <claim_id>`",
            "Before summarizing, run `renew <article_id> --claim-id <claim_id>`",
            "Immediately before acknowledgment, run `renew <article_id> --claim-id <claim_id>`",
            "FETCH_FAILED", "URL_MISMATCH", "SUMMARY_FAILED",
            "ack but before the final response", "best-effort",
            "persists neither summaries nor an outbox",
        ):
            self.assertIn(clause, text, clause)
        self.assertNotIn("python3 -c", text)
        self.assertLess(text.index("prepare a complete article output block"), text.index("then call `ack <article_id>`"))
        self.assertLess(text.index("then call `ack <article_id>`"), text.index("then include the prepared block in the final digest"))

    def test_skill_documents_fresh_account_follow_and_fixed_publication_mirrors(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        for clause in (
            "search-sources --name", "follow --source-id", "explicitly requested",
            "www.qbitai.com", "www.jiqizhixin.com", "fixed article-path allowlist",
        ):
            self.assertIn(clause, text, clause)
        self.assertLess(text.index("search-sources --name"), text.index("follow --source-id"))
        self.assertLess(text.index("follow --source-id"), text.index("configure --source-id"))

    def test_skill_records_the_approved_scheduler_guardrails(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        for clause in (
            "08:30", "America/New_York", "automation", "scheduler",
            "complete baseline", "configured", "initialized", "not deployed",
        ):
            self.assertIn(clause, text, clause)

    def test_wrapper_loads_only_the_standard_secret_file_and_executes_helper(self):
        text = WRAPPER_FILE.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertIn('"${BASH_SOURCE[0]}"', text)
        self.assertIn("bestblogs.env", text)
        self.assertIn("set -a", text)
        self.assertIn("set +a", text)
        self.assertIn("BESTBLOGS_API_KEY", text)
        self.assertIn("exec python3", text)
        self.assertIn('"$@"', text)
        self.assertNotIn("echo \"$BESTBLOGS_API_KEY", text)
        self.assertNotIn("printenv", text)

    def test_wrapper_rejects_keyless_secret_file_even_with_inherited_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets_dir = root / "secrets"
            fake_bin = root / "bin"
            secrets_dir.mkdir()
            fake_bin.mkdir()
            (secrets_dir / "bestblogs.env").write_text("# key intentionally absent\n", encoding="utf-8")
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            fake_python.chmod(0o700)
            env = os.environ.copy()
            env.update({
                "BESTBLOGS_API_KEY": VALID_API_KEY,
                "CODEX_SECRETS_DIR": str(secrets_dir),
                "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            })

            result = subprocess.run(
                [str(WRAPPER_FILE), "doctor"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("BESTBLOGS_API_KEY is required", result.stderr)
        self.assertNotIn(VALID_API_KEY, result.stderr)

    def test_wrapper_disables_shell_trace_and_verbose_before_sourcing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets_dir = root / "secrets"
            fake_bin = root / "bin"
            secrets_dir.mkdir()
            fake_bin.mkdir()
            (secrets_dir / "bestblogs.env").write_text(
                "BESTBLOGS_API_KEY=%s\n" % VALID_API_KEY,
                encoding="utf-8",
            )
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o700)
            env = os.environ.copy()
            env.update({
                "CODEX_SECRETS_DIR": str(secrets_dir),
                "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            })
            for trace_flag in ("-x", "-v", "-xv"):
                with self.subTest(trace_flag=trace_flag):
                    result = subprocess.run(
                        ["bash", trace_flag, str(WRAPPER_FILE), "doctor"],
                        env=env,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertNotIn(VALID_API_KEY, result.stdout + result.stderr)

    def test_skill_metadata_and_plugin_keep_web_capabilities_consistent(self):
        metadata = METADATA_FILE.read_text(encoding="utf-8")
        self.assertIn('display_name: "WeChat Reader & Digest"', metadata)
        short = next(line for line in metadata.splitlines() if "short_description:" in line).split('"')[1]
        self.assertGreaterEqual(len(short), 25)
        self.assertLessEqual(len(short), 64)
        self.assertIn("$wechat-digest", metadata)
        self.assertNotIn("dependencies:", metadata)
        plugin = json.loads(PLUGIN_FILE.read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.3.3")
        joined = json.dumps(plugin).lower()
        for capability in ("wechat", "firecrawl", "playwright"):
            self.assertIn(capability, joined)



class WechatInteractiveListingTests(unittest.TestCase):
    def state_file(self):
        path = Path(tempfile.mkdtemp()) / "nested" / "digest.json"
        self.addCleanup(lambda: path.parent.parent.exists() and __import__("shutil").rmtree(path.parent.parent))
        return path

    def test_configured_sources_lists_only_local_config_without_a_network_client(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1", "s2"])
        state["sources"]["s1"].update({"name": "Source One", "initialized": True})
        wechat.save_state(path, state)
        original_client = wechat._client_from_env
        built = []
        wechat._client_from_env = lambda: built.append(True)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main(["--state-file", str(path), "configured-sources"]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(output.getvalue()), {"sources": [
            {"id": "s1", "name": "Source One", "initialized": True},
            {"id": "s2", "name": "s2", "initialized": False},
        ]})
        self.assertEqual(built, [])

    def test_interactive_latest_and_recent_are_safe_source_filtered_and_only_mutate_permitted_state(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"].update({"name": "Configured Name", "initialized": True})
        pending = add_claim(wechat.parse_article(record("pending", "s1")))
        state["pending"][pending["identity"]] = pending
        wechat.save_state(path, state)
        before = path.read_bytes()

        class InteractiveClient:
            def __init__(self):
                self.calls = []

            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                self.calls.append((page, page_size, source_id, time_filter))
                return {"dataList": [
                    dict(record("older", "s1", 1710000000000), sourceName="Configured Name"),
                    dict(record("newer", "s1", 1720000000000), sourceName="Configured Name"),
                ]}

        client = InteractiveClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        latest_output = io.StringIO()
        recent_output = io.StringIO()
        try:
            with redirect_stdout(latest_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "latest", "--source", "s1",
                ]), 0)
            with redirect_stdout(recent_output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "recent", "--source", "Configured Name", "--limit", "2",
                    "--time-filter", "week",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        latest = json.loads(latest_output.getvalue())
        self.assertEqual(latest["source"], {"id": "s1", "name": "Configured Name", "initialized": True})
        self.assertEqual(latest["article"]["resource_id"], "newer")
        self.assertEqual(set(latest["article"]), {
            "resource_id", "source_id", "source_name", "title", "url", "published_at",
        })
        self.assertEqual(latest["warnings"], [])
        recent = json.loads(recent_output.getvalue())
        self.assertEqual([article["resource_id"] for article in recent["articles"]], ["newer", "older"])
        self.assertEqual(recent["requested_limit"], 2)
        self.assertEqual(recent["warnings"], [])
        self.assertEqual(client.calls, [(1, 50, "s1", None), (1, 50, "s1", "week")])

        after = wechat.load_state(path)
        before_state = json.loads(before)
        protected_before = {
            key: value for key, value in before_state.items()
            if key not in ("api_calls", "body_budget", "total_budget")
        }
        protected_after = {
            key: value for key, value in after.items()
            if key not in ("api_calls", "body_budget", "total_budget")
        }
        self.assertEqual(
            json.dumps(protected_after, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            json.dumps(protected_before, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertEqual(after["body_budget"], before_state["body_budget"])
        self.assertEqual(after["total_budget"]["count"], before_state["total_budget"]["count"] + 2)
        self.assertEqual(after["api_calls"], {"subscription": 2})

    def test_interactive_listing_fails_closed_for_bad_selector_or_response_and_preserves_delivery_state(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1", "s2"])
        state["sources"]["s1"]["name"] = "Same Name"
        state["sources"]["s2"]["name"] = "Same Name"
        pending = wechat.parse_article(record("pending", "s1"))
        state["pending"][pending["identity"]] = pending
        wechat.save_state(path, state)
        before = wechat.load_state(path)

        class BadClient:
            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return {"dataList": [record("one", "s2")]}

        original_client = wechat._client_from_env
        wechat._client_from_env = BadClient
        try:
            for argv, expected in (
                (["latest", "--source", "missing"], "unknown configured source"),
                (["latest", "--source", " s1"], "unknown configured source"),
                (["latest", "--source", "Same Name"], "ambiguous configured source name"),
                (["recent", "--source", "s1", "--limit", "21"], "limit must be between 1 and 20"),
                (["recent", "--source", "s1", "--limit", "1", "--time-filter", "year"], "invalid time filter"),
                (["latest", "--source", "s1"], "feed source filter mismatch"),
            ):
                with self.subTest(argv=argv):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(wechat.main(["--state-file", str(path)] + argv), 2)
                    self.assertIn(expected, json.loads(output.getvalue())["error"])
        finally:
            wechat._client_from_env = original_client

        after = wechat.load_state(path)
        for protected in ("pending", "ack_tombstones", "next_scan_seq", "last_applied_scan_generation", "scan_health", "warnings"):
            self.assertEqual(after[protected], before[protected])
        self.assertEqual(after["sources"], before["sources"])

    def test_interactive_listing_rejects_duplicates_and_unsafe_text_uses_provider_order_and_caches_only_consistent_names(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])

        class SourceClient:
            def __init__(self, pages):
                self.pages = pages

            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return self.pages[page - 1]

        duplicate = record("duplicate", "s1")
        with self.assertRaisesRegex(wechat.APIError, "duplicate identity"):
            wechat.interactive_articles(
                state, SourceClient([{ "dataList": [duplicate, duplicate] }]), "s1", 1,
            )

        unsafe = record("unsafe", "s1")
        unsafe["title"] = "Unsafe\x00title"
        with self.assertRaisesRegex(wechat.APIError, "no safe article"):
            wechat.interactive_articles(
                state, SourceClient([{ "dataList": [unsafe] }]), "s1", 1,
            )

        first = record("first", "s1", None)
        second = record("second", "s1", 1720000000000)
        first["sourceName"] = "Cached Source"
        second["sourceName"] = "Cached Source"
        result = wechat.interactive_articles(
            state, SourceClient([{ "dataList": [first, second] }]), "s1", 2,
        )
        self.assertEqual([article["resource_id"] for article in result["articles"]], ["first", "second"])
        self.assertEqual(result["warnings"], ["provider_order_used"])
        self.assertEqual(state["sources"]["s1"]["name"], "Cached Source")

        before_conflict = copy.deepcopy(state["sources"])
        conflict = record("conflict", "s1")
        conflict["sourceName"] = "Different Source"
        result = wechat.interactive_articles(
            state, SourceClient([{ "dataList": [conflict, dict(record("other", "s1"), sourceName="Other Source")] }]), "s1", 1,
        )
        self.assertIn("source_name_conflict", result["warnings"])
        self.assertEqual(state["sources"], before_conflict)

    def test_missing_provider_names_do_not_change_or_conflict_with_the_cached_alias(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["name"] = "Existing Alias"

        class SourceClient:
            def __init__(self, records):
                self.records = records

            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                return {"dataList": self.records}

        missing = record("missing", "s1")
        missing.pop("sourceName")
        all_missing = wechat.interactive_articles(state, SourceClient([missing]), "s1", 1)
        self.assertEqual(all_missing["warnings"], [])
        self.assertEqual(all_missing["articles"][0]["source_name"], "s1")
        self.assertEqual(state["sources"]["s1"]["name"], "Existing Alias")

        present = record("present", "s1")
        present["sourceName"] = "Provider Alias"
        mixed = wechat.interactive_articles(state, SourceClient([missing, present]), "s1", 2)
        self.assertEqual(mixed["warnings"], [])
        self.assertEqual(state["sources"]["s1"]["name"], "Existing Alias")

    def test_interactive_listing_fails_closed_when_the_only_candidate_has_no_resource_id(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        missing_id = record(None, "s1")

        class SourceClient:
            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                return {"dataList": [missing_id]}

        with self.assertRaisesRegex(wechat.APIError, "no safe article"):
            wechat.interactive_articles(state, SourceClient(), "s1", 1)

    def test_interactive_listing_skips_idless_candidates_and_returns_only_readable_articles(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        missing_id = record(None, "s1")
        valid = record("readable", "s1")

        class SourceClient:
            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                return {"dataList": [missing_id, valid]}

        result = wechat.interactive_articles(state, SourceClient(), "s1", 2)

        self.assertEqual([article["resource_id"] for article in result["articles"]], ["readable"])

    def test_interactive_cache_compare_and_swap_preserves_a_newer_concurrent_alias(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"]["name"] = "Before Request"
        wechat.save_state(path, state)

        class RacingClient:
            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                before_attempt()
                with wechat.state_lock(path):
                    newer = wechat.load_state(path)
                    newer["sources"]["s1"]["name"] = "Newer Alias"
                    wechat.save_state(path, newer)
                return {"dataList": [dict(record("latest", "s1"), sourceName="Stale Provider Alias")]}

        original_client = wechat._client_from_env
        wechat._client_from_env = RacingClient
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wechat.main(["--state-file", str(path), "latest", "--source", "s1"]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(wechat.load_state(path)["sources"]["s1"]["name"], "Newer Alias")

    def test_display_sanitization_rejects_unicode_control_characters(self):
        self.assertIsNone(wechat._bounded_display_text("Unsafe\u0080name", 200))
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        unsafe = record("unsafe-unicode", "s1")
        unsafe["title"] = "Unsafe\u0080title"

        class SourceClient:
            def subscription_source_page(self, page, page_size, source_id, time_filter=None, before_attempt=None):
                return {"dataList": [unsafe]}

        with self.assertRaisesRegex(wechat.APIError, "no safe article"):
            wechat.interactive_articles(state, SourceClient(), "s1", 1)

    def test_source_name_is_excluded_from_scan_configuration_fingerprint(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        before = wechat._source_configuration_fingerprint(state["sources"])
        state["sources"]["s1"]["name"] = "Updated Display Name"
        self.assertEqual(wechat._source_configuration_fingerprint(state["sources"]), before)

    def test_read_verifies_selected_source_metadata_before_markdown_and_only_mutates_budgets(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["sources"]["s1"].update({"name": "Source One", "initialized": True})
        pending = add_claim(wechat.parse_article(record("pending", "s1")))
        state["pending"][pending["identity"]] = pending
        wechat.save_state(path, state)
        before = wechat.load_state(path)

        class ReadClient:
            def __init__(self):
                self.calls = []

            def resource_metadata(self, resource_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                self.calls.append(("metadata", resource_id))
                return record("article-1", "s1")

            def markdown(self, resource_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                self.calls.append(("markdown", resource_id))
                return "# verified body"

        client = ReadClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "read", "article-1", "--source", "s1",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(output.getvalue()), {
            "article": {
                "resource_id": "article-1", "source_id": "s1", "source_name": "Source One",
                "title": "An article", "url": record("article-1", "s1")["url"].split("?")[0],
                "published_at": "2024-03-09T16:00:00+00:00",
            },
            "content": {"source": "bestblogs", "markdown": "# verified body"},
        })
        self.assertEqual(client.calls, [("metadata", "article-1"), ("markdown", "article-1")])
        after = wechat.load_state(path)
        self.assertEqual(after["total_budget"]["count"], before["total_budget"]["count"] + 2)
        self.assertEqual(after["body_budget"]["count"], before["body_budget"]["count"] + 1)
        self.assertEqual(after["api_calls"], {"resource_metadata": 1, "markdown": 1})
        for protected in (
            "sources", "pending", "ack_tombstones", "last_successful_scan", "warnings",
            "next_scan_seq", "last_applied_scan_generation", "scan_health",
        ):
            self.assertEqual(after[protected], before[protected])

    def test_read_fails_closed_before_markdown_for_unverified_metadata(self):
        for label, metadata, expected in (
            ("mismatch", record("other", "s1"), "resource metadata mismatch"),
            ("wrong_source", record("article-1", "s2"), "feed source filter mismatch"),
            ("unsafe_url", dict(record("article-1", "s1"), url="https://example.invalid/a"), "unsafe resource metadata"),
        ):
            with self.subTest(label=label):
                path = self.state_file()
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                wechat.save_state(path, state)

                class ReadClient:
                    def __init__(self):
                        self.calls = []

                    def resource_metadata(self, resource_id, before_attempt=None):
                        if before_attempt is not None:
                            before_attempt()
                        self.calls.append("metadata")
                        return metadata

                    def markdown(self, resource_id, before_attempt=None):
                        self.calls.append("markdown")
                        return "unexpected"

                client = ReadClient()
                original_client = wechat._client_from_env
                wechat._client_from_env = lambda: client
                output = io.StringIO()
                try:
                    with redirect_stdout(output):
                        self.assertEqual(wechat.main([
                            "--state-file", str(path), "read", "article-1", "--source", "s1",
                        ]), 2)
                finally:
                    wechat._client_from_env = original_client

                result = json.loads(output.getvalue())
                self.assertEqual(result, {"error": expected})
                self.assertEqual(client.calls, ["metadata"])

    def test_read_returns_a_safe_fallback_only_after_verified_metadata(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        wechat.save_state(path, state)

        class ReadClient:
            def resource_metadata(self, resource_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return record("article-1", "s1")

            def markdown(self, resource_id, before_attempt=None):
                if before_attempt is not None:
                    before_attempt()
                return ""

        original_client = wechat._client_from_env
        wechat._client_from_env = ReadClient
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "read", "article-1", "--source", "s1",
                ]), 0)
        finally:
            wechat._client_from_env = original_client

        result = json.loads(output.getvalue())
        self.assertEqual(result["fallback"], {
            "reason": "bestblogs_markdown_unavailable",
            "url": record("article-1", "s1")["url"].split("?")[0],
        })
        self.assertEqual(result["article"]["resource_id"], "article-1")

    def test_read_configuration_loss_after_metadata_prevents_the_markdown_request(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        wechat.save_state(path, state)

        class RacingReadClient:
            def __init__(self):
                self.calls = []

            def resource_metadata(self, resource_id, before_attempt=None):
                before_attempt()
                self.calls.append("metadata")
                with wechat.state_lock(path):
                    current = wechat.load_state(path)
                    wechat.configure_sources(current, ["s2"])
                    wechat.save_state(path, current)
                return record("article-1", "s1")

            def markdown(self, resource_id, before_attempt=None):
                before_attempt()
                self.calls.append("markdown")
                return "# stale content"

        client = RacingReadClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "read", "article-1", "--source", "s1",
                ]), 2)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(output.getvalue()), {
            "error": "configured source changed during read request",
        })
        self.assertEqual(client.calls, ["metadata"])

    def test_read_configuration_loss_during_markdown_suppresses_content_and_fallback(self):
        for body in ("# stale content", ""):
            with self.subTest(body=body):
                path = self.state_file()
                state = wechat.new_state()
                wechat.configure_sources(state, ["s1"])
                wechat.save_state(path, state)

                class RacingReadClient:
                    def __init__(self):
                        self.calls = []

                    def resource_metadata(self, resource_id, before_attempt=None):
                        before_attempt()
                        self.calls.append("metadata")
                        return record("article-1", "s1")

                    def markdown(self, resource_id, before_attempt=None):
                        before_attempt()
                        self.calls.append("markdown")
                        with wechat.state_lock(path):
                            current = wechat.load_state(path)
                            wechat.configure_sources(current, ["s2"])
                            wechat.save_state(path, current)
                        return body

                client = RacingReadClient()
                original_client = wechat._client_from_env
                wechat._client_from_env = lambda: client
                output = io.StringIO()
                try:
                    with redirect_stdout(output):
                        self.assertEqual(wechat.main([
                            "--state-file", str(path), "read", "article-1", "--source", "s1",
                        ]), 2)
                finally:
                    wechat._client_from_env = original_client

                self.assertEqual(json.loads(output.getvalue()), {
                    "error": "configured source changed during read request",
                })
                self.assertEqual(client.calls, ["metadata", "markdown"])

    def test_read_reports_total_budget_exhaustion_without_a_fallback_url_before_metadata(self):
        path = self.state_file()
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["total_budget"] = {"day": wechat._beijing_day(), "count": wechat.TOTAL_DAILY_LIMIT}
        wechat.save_state(path, state)

        class ReadClient:
            def __init__(self):
                self.calls = []

            def resource_metadata(self, resource_id, before_attempt=None):
                before_attempt()
                self.calls.append("metadata")
                return record("article-1", "s1")

            def markdown(self, resource_id, before_attempt=None):
                self.calls.append("markdown")
                return "unexpected"

        client = ReadClient()
        original_client = wechat._client_from_env
        wechat._client_from_env = lambda: client
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                self.assertEqual(wechat.main([
                    "--state-file", str(path), "read", "article-1", "--source", "s1",
                ]), 2)
        finally:
            wechat._client_from_env = original_client

        self.assertEqual(json.loads(output.getvalue()), {"error": "daily total budget exhausted"})
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
