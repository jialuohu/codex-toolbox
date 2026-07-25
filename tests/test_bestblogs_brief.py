import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path


MODULE = Path(__file__).parents[1] / "plugins/web-data-tools/skills/bestblogs-brief/scripts/bestblogs_brief.py"
SPEC = importlib.util.spec_from_file_location("bestblogs_brief", MODULE)
brief = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(brief)
VALID_API_KEY = "bb_" + "1" * 32


def item(resource_id, **changes):
    value = {
        "resourceId": resource_id,
        "score": 0.9,
        "tags": ["AI"],
        "oneSentenceSummary": "A concise finding.",
        "summary": "A longer explanation.",
        "mainPoints": ["First point"],
        "deepRead": False,
        "featured": True,
        "personalized": True,
    }
    value.update(changes)
    return value


def metadata(resource_id, content_type="ARTICLE", **changes):
    value = {
        "resourceId": resource_id,
        "sourceId": "source-" + resource_id,
        "sourceName": "A source",
        "title": "Title " + resource_id,
        "contentType": content_type,
        "url": "https://example.com/" + resource_id,
        "coverUrl": "https://images.example.com/" + resource_id + ".jpg",
        "publishedAt": "2026-07-24T01:02:03Z",
        "readTime": 5,
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
        return self.responses.pop(0)


class BestBlogsBriefTests(unittest.TestCase):
    def stable_brief(self, status="PUBLISHED", items=None, brief_date="2026-07-24"):
        return {
            "briefDate": brief_date,
            "status": status,
            "generatedAt": "2026-07-24T08:00:00Z",
            "editorIntro": "Today\'s picks",
            "keywords": ["models", "systems"],
            "items": list(items or [item("one"), item("two")]),
        }

    def pro_client(self, today, batches):
        return FakeClient({"userTier": "PRO"}, today, batches)

    def test_normalizes_mixed_content_in_personal_brief_order(self):
        today = self.stable_brief(items=[item("video"), item("article"), item("tweet")])
        client = self.pro_client(today, [[
            metadata("article", "ARTICLE"),
            metadata("tweet", "TWITTER", coverUrl=None, publishedAt=None),
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

    def test_client_posts_bounded_batch_to_fixed_endpoint_and_rejects_malformed_envelopes(self):
        client = brief.BestBlogsClient(VALID_API_KEY)
        url = brief.API_ORIGIN + "/resources/batch-meta"
        valid = json.dumps({"success": True, "code": None, "message": None, "requestId": "request", "data": []}).encode()
        client._opener = FakeOpener([FakeResponse(valid, url)])

        self.assertEqual(client.batch_meta(["one"]), [])
        request, _ = client._opener.requests[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"resourceIds": ["one"]})
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
            self.stable_brief(items=[item("one", summary="First line.\nSecond line.", oneSentenceSummary=None), item("two", summary=None)]),
            [[metadata("one"), metadata("two")]],
        )

        result = brief.read_today(client, "2026-07-24")

        self.assertEqual(result["items"][0]["summary"], "First line.\nSecond line.")
        self.assertNotIn("oneSentenceSummary", result["items"][0])
        self.assertNotIn("summary", result["items"][1])

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
        for field, unsafe in (("url", "http://example.com/item"), ("url", "https://user@example.com/item"),
                              ("coverUrl", "https://user@example.com/image")):
            with self.subTest(field=field, unsafe=unsafe):
                values = {field: unsafe}
                client = self.pro_client(self.stable_brief(), [[metadata("one", **values), metadata("two")]])
                with self.assertRaisesRegex(brief.BriefError, "HTTPS"):
                    brief.read_today(client, "2026-07-24")
        client = self.pro_client(self.stable_brief(), [[metadata("one", "PODCAST"), metadata("two")]])
        with self.assertRaisesRegex(brief.BriefError, "content type"):
            brief.read_today(client, "2026-07-24")

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
