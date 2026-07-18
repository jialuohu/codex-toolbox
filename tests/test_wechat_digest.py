import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / "plugins/web-data-tools/skills/wechat-digest/scripts/wechat_digest.py"
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
        return {"tier": "pro", "id": "private-user", "email": "secret@example.com"}


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
        state["body_budget"]["count"] = wechat.BODY_DAILY_LIMIT
        denied = wechat.markdown(state, client, "resource:r1", now=__import__("datetime").datetime(2024, 1, 1, 16, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(denied["fallback_reason"], "daily_body_budget_exhausted")
        reset = wechat.markdown(state, client, "resource:r1", now=__import__("datetime").datetime(2024, 1, 2, 16, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(reset["markdown"], "# private body")

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
        path.write_text(json.dumps({"version": 1, "sources": [], "pending": {}, "body_budget": {}, "api_calls": {}, "warnings": []}))
        with self.assertRaises(wechat.StateError):
            wechat.load_state(path)
        output = wechat.doctor(FakeClient(), api_key="fixture")
        self.assertNotIn("fixture", json.dumps(output))
        self.assertNotIn("secret@example.com", json.dumps(output))

    def test_article_resource_id_aliases_work_for_pending_actions(self):
        state = wechat.new_state()
        state["pending"]["resource:r1"] = {"identity": "resource:r1", "resource_id": "r1", "attempts": 0}
        self.assertEqual(wechat.fail(state, "r1", "FETCH_FAILED")["attempts"], 1)
        self.assertEqual(wechat.ack(state, "r1")["acknowledged"], "resource:r1")


if __name__ == "__main__":
    unittest.main()
