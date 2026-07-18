import importlib.util
import copy
import http.client
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError


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


def record(resource_id="r1", source_id="s1", when=1710000000000, url="https://mp.weixin.qq.com/s/a?utm_source=x"):
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
        article = wechat.parse_article(record(resource_id=None, when="2024-03-09T12:00:00Z"))
        self.assertIsNotNone(article)
        self.assertTrue(article["identity"].startswith("url:"))
        self.assertEqual(article["url"], "https://mp.weixin.qq.com/s/a")
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

    def test_paginate_terminates_and_reports_unique_sources(self):
        client = FakeClient([
            {"dataList": [record("r1"), record("r2", "s2")], "total": 3},
            {"dataList": [record("r3")], "total": 3},
        ])
        result = wechat.list_sources(client, page_size=2)
        self.assertEqual([s["id"] for s in result["sources"]], ["s1", "s2"])
        self.assertEqual(client.calls["subscription"], 2)
        self.assertEqual(result["skipped"], {"invalid_or_non_wechat": 0})

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
        self.assertEqual(list(state["pending"]), ["resource:r2"])
        self.assertEqual(state["api_calls"]["subscription"], 2)

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
        self.assertEqual(state["sources"]["s1"]["recent"], {"resource:selected": True})

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
                self.assertEqual(state["sources"]["s1"]["recent"], {"resource:selected": True})

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

    def test_complete_scan_never_prunes_tombstones_for_unselected_sources(self):
        state = wechat.new_state()
        wechat.configure_sources(state, ["s1"])
        state["next_scan_seq"] = 3
        state["ack_tombstones"]["resource:unselected"] = {
            "source_id": "s2", "ack_after_scan_seq": 1,
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
        self.assertEqual(wechat.pending(loaded)["retryable"][0]["identity"], "resource:new")
        for _ in range(3):
            issued = wechat.claim(loaded, "resource:new")
            wechat.fail(loaded, "resource:new", "FETCH_FAILED", claim_id=issued["claim_id"])
        self.assertEqual(len(wechat.pending(loaded)["exhausted"]), 1)
        self.assertIn("resource:new", loaded["pending"])

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
        self.assertEqual([item["identity"] for item in result["claimed"]], ["resource:active"])
        self.assertEqual([item["identity"] for item in result["retryable"]], ["resource:expired"])
        self.assertEqual(result["exhausted"], [])

    def test_claim_is_atomic_and_active_conflict_is_not_a_fetch_fallback(self):
        path = self.state_file()
        state = wechat.new_state()
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
        state["pending"]["resource:r1"] = add_claim(wechat.parse_article(record("r1")))
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
        state["pending"]["resource:r1"] = add_claim(wechat.parse_article(record("r1")))
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
                records = [record("p%d-%d" % (page, index)) for index in range(100)]
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

    def test_later_started_failed_scan_does_not_suppress_older_success(self):
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
        self.assertFalse(result.get("superseded", False))
        persisted = wechat.load_state(path)
        self.assertIn("resource:older-success", persisted["pending"])
        self.assertEqual(persisted["last_applied_scan_generation"], 1)

    def test_cli_markdown_reservation_write_failure_prevents_outbound_fetch(self):
        path = self.state_file()
        state = wechat.new_state()
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

    def test_well_formed_v1_state_migrates_to_v3_with_fail_closed_total_budget(self):
        path = self.state_file()
        legacy = wechat.new_state()
        legacy["version"] = 1
        legacy.pop("total_budget", None)
        legacy.pop("next_scan_seq", None)
        legacy.pop("last_applied_scan_generation", None)
        legacy.pop("ack_tombstones", None)
        legacy["body_budget"] = {"day": wechat._beijing_day(), "count": 7}
        legacy["pending"]["resource:r1"] = wechat.parse_article(record("r1"))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["total_budget"], {
            "day": wechat._beijing_day(), "count": wechat.TOTAL_DAILY_LIMIT,
        })
        self.assertEqual(migrated["body_budget"]["count"], 7)
        self.assertIn("resource:r1", migrated["pending"])

        with redirect_stdout(io.StringIO()):
            self.assertEqual(wechat.main(["--state-file", str(path), "status"]), 0)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["version"], 3)
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
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["scan_health"], {
            "pages": 0, "records": 0, "complete": False,
            "skipped": {"invalid_or_non_wechat": 0},
        })
        self.assertEqual(migrated["total_budget"]["count"], wechat.TOTAL_DAILY_LIMIT)

    def test_well_formed_v2_state_migrates_sequences_without_claim_or_tombstone_data(self):
        path = self.state_file()
        previous = wechat.new_state()
        previous["version"] = 2
        previous["scan_generation"] = 4
        previous.pop("next_scan_seq")
        previous.pop("last_applied_scan_generation")
        previous.pop("ack_tombstones")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(previous), encoding="utf-8")
        migrated = wechat.load_state(path)
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["next_scan_seq"], 4)
        self.assertEqual(migrated["last_applied_scan_generation"], 0)
        self.assertEqual(migrated["ack_tombstones"], {})

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
            wechat.ack(state, "r1", claim_id=CLAIM_ID)["acknowledged"], "resource:r1",
        )

    def test_status_exposes_safe_body_budget_details(self):
        state = wechat.new_state()
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


class WechatDigestSkillContractTests(unittest.TestCase):
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
        self.assertIn("Use this exact lifecycle: `scan -> pending -> summarize -> ack`.", text)
        self.assertIn("After three failures, leave the item exhausted; do not ack or retry it automatically.", text)
        self.assertIn(
            "Baseline is established if and only if the latest scan is complete and every configured source is initialized; otherwise it is not established.",
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
        ):
            self.assertIn(clause, text, clause)
        self.assertNotIn("python3 -c", text)
        self.assertLess(text.index("prepare a complete article output block"), text.index("then call `ack <article_id>`"))
        self.assertLess(text.index("then call `ack <article_id>`"), text.index("then include the prepared block in the final digest"))

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

    def test_skill_metadata_and_plugin_keep_web_capabilities_consistent(self):
        metadata = METADATA_FILE.read_text(encoding="utf-8")
        self.assertIn('display_name: "WeChat Digest"', metadata)
        short = next(line for line in metadata.splitlines() if "short_description:" in line).split('"')[1]
        self.assertGreaterEqual(len(short), 25)
        self.assertLessEqual(len(short), 64)
        self.assertIn("$wechat-digest", metadata)
        self.assertNotIn("dependencies:", metadata)
        plugin = json.loads(PLUGIN_FILE.read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.2.0")
        joined = json.dumps(plugin).lower()
        for capability in ("wechat", "firecrawl", "playwright"):
            self.assertIn(capability, joined)


if __name__ == "__main__":
    unittest.main()
