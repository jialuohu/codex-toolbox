import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
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


class FakeClient:
    def __init__(self, pages=None, markdown="# body"):
        self.pages = list(pages or [])
        self.markdown_body = markdown
        self.calls = {}

    def subscription_page(self, page, page_size):
        self.calls["subscription"] = self.calls.get("subscription", 0) + 1
        return self.pages[page - 1] if page <= len(self.pages) else {"dataList": []}

    def markdown(self, resource_id):
        self.calls["markdown"] = self.calls.get("markdown", 0) + 1
        return self.markdown_body

    def me(self):
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

    def test_client_uses_documented_v2_get_contract_and_null_success_envelope(self):
        self.assertEqual(wechat.API_ORIGIN, "https://api.bestblogs.dev/openapi/v2")
        client = wechat.BestBlogsClient("valid-key")
        body = json.dumps({"success": True, "code": None, "message": None, "requestId": "r", "data": {"ok": True}}).encode()
        opener = FakeOpener([FakeResponse(body, wechat.API_ORIGIN + "/me/feeds/subscriptions?page=2&pageSize=25&timeFilter=week")])
        client._opener = opener
        self.assertEqual(client.subscription_page(2, 25), {"ok": True})
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, wechat.API_ORIGIN + "/me/feeds/subscriptions?page=2&pageSize=25&timeFilter=week")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-api-key"), "valid-key")

    def test_client_rejects_redirect_and_oversized_response_and_retries_one_429(self):
        client = wechat.BestBlogsClient("valid-key")
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
            wechat.fail(loaded, "resource:new", "FETCH_FAILED")
        self.assertEqual(len(wechat.pending(loaded)["exhausted"]), 1)
        wechat.ack(loaded, "resource:new")
        self.assertFalse(loaded["pending"])

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
        client.markdown = lambda resource_id: (_ for _ in ()).throw(wechat.APIError("safe"))
        result = wechat.markdown(state, client, "r1")
        self.assertEqual(result["fallback_reason"], "bestblogs_markdown_unavailable")
        self.assertEqual(state["body_budget"]["count"], 1)
        original = wechat.ZoneInfo
        wechat.ZoneInfo = None
        try:
            self.assertEqual(wechat.markdown(state, FakeClient(), "r1")["fallback_reason"], "beijing_timezone_unavailable")
        finally:
            wechat.ZoneInfo = original

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

    def test_article_resource_id_aliases_work_for_pending_actions(self):
        state = wechat.new_state()
        state["pending"]["resource:r1"] = {"identity": "resource:r1", "resource_id": "r1", "attempts": 0}
        self.assertEqual(wechat.fail(state, "r1", "FETCH_FAILED")["attempts"], 1)
        self.assertEqual(wechat.ack(state, "r1")["acknowledged"], "resource:r1")

    def test_status_exposes_safe_body_budget_details(self):
        state = wechat.new_state()
        state["body_budget"] = {"day": "2026-07-18", "count": 17}
        self.assertEqual(wechat.status(state)["body_budget"], {
            "day": "2026-07-18", "used": 17, "limit": 35,
        })


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
