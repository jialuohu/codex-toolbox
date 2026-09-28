"""Exact tab-ownership and same-task cleanup receipts for v2 trials."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic.tab_lease import (
    TabLeaseObserver,
    close_script,
    create_script,
    owner_script,
    trial_url,
)

NONCE = "b" * 32
CASE = "browser-filter-0"
TAB = "fixture-tab-42"


def event(code: str, text: str, *, status: str = "completed") -> dict:
    return {"type": "item.completed", "item": {"type": "mcp_tool_call",
            "server": "cua_repl", "tool": "js", "status": status,
            "arguments": {"code": code}, "result": {"content": [{"type": "text", "text": text}]}}}


class TabLeaseTests(unittest.TestCase):
    def owner(self, *, url: str | None = None, tab_id: str = TAB) -> dict:
        value = {"id": tab_id, "url": url or trial_url(CASE, NONCE),
                 "browserId": "1", "present": True, "existingFixtureCount": 60}
        return event(owner_script(trial_url(CASE, NONCE)),
                     "CU_TAB_OWNER " + json.dumps(value))

    def closed(self, *, tab_id: str = TAB, absent: bool = True) -> dict:
        return event(close_script(),
                     "CU_TAB_CLOSED " + json.dumps({"id": tab_id, "absent": absent}))

    def created(self) -> dict:
        return event(create_script(trial_url(CASE, NONCE)),
                     "0 AXWebArea Computer Use Browser Fixture")

    def test_owner_then_close_requires_same_tab_and_absence_before_process_exit(self) -> None:
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        lease.on_event(self.owner(), 100)
        lease.on_event(self.closed(), 150)
        self.assertTrue(lease.verified)
        self.assertTrue(lease.metadata(200)["close_verified"])
        self.assertEqual(lease.metadata(200)["existing_fixture_count"], 60)
        self.assertFalse(lease.metadata(140)["close_verified"])
        self.assertNotIn(TAB, str(lease.metadata(200)))
        self.assertNotIn(trial_url(CASE, NONCE), str(lease.metadata(200)))

    def test_foreign_or_missing_owner_cannot_authorize_close(self) -> None:
        for owner in (self.owner(url=trial_url(CASE, "c" * 32)),
                      self.owner(tab_id="bad tab id"),
                      event("nodeRepl.write('owner');", self.owner()["item"]["result"]["content"][0]["text"])):
            with self.subTest(owner=owner):
                lease = TabLeaseObserver(CASE, NONCE)
                lease.on_event(self.created(), 50)
                lease.on_event(owner, 100)
                lease.on_event(self.closed(), 150)
                self.assertFalse(lease.verified)
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        lease.on_event(self.closed(), 150)
        self.assertFalse(lease.verified)

    def test_failed_close_and_cross_tab_receipts_stop_cleanup(self) -> None:
        for close in (self.closed(absent=False), self.closed(tab_id="other"),
                      event("await cua.listTabs({browser:'1'});",
                            "CU_TAB_CLOSED " + json.dumps({"id": TAB, "absent": True}))):
            with self.subTest(close=close):
                lease = TabLeaseObserver(CASE, NONCE)
                lease.on_event(self.created(), 50)
                lease.on_event(self.owner(), 100)
                lease.on_event(close, 150)
                self.assertFalse(lease.verified)
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        lease.on_event(self.owner(), 100)
        lease.on_event(self.closed(), 150)
        lease.on_event(self.closed(), 160)
        self.assertFalse(lease.verified)

    def test_timeout_or_incomplete_result_never_claims_cleanup(self) -> None:
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        lease.on_event(self.owner(), 100)
        lease.on_event(self.closed(), 150)
        self.assertFalse(lease.metadata(None)["close_verified"])
        skipped = TabLeaseObserver(CASE, NONCE)
        skipped.on_event(self.created(), 50)
        skipped.on_event(event("cuFixtureTab.id; await cua.listTabs({});",
                               self.owner()["item"]["result"]["content"][0]["text"],
                               status="failed"), 100)
        self.assertFalse(skipped.verified)
        failed_creation = self.created()
        failed_creation["item"]["result"]["isError"] = True
        rejected = TabLeaseObserver(CASE, NONCE)
        rejected.on_event(failed_creation, 50)
        rejected.on_event(self.owner(), 100)
        rejected.on_event(self.closed(), 150)
        self.assertFalse(rejected.verified)

    def test_forged_marker_without_exact_inventory_code_is_rejected(self) -> None:
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        owner_text = self.owner()["item"]["result"]["content"][0]["text"]
        lease.on_event(event("nodeRepl.write('" + owner_text + "');", owner_text), 100)
        lease.on_event(self.closed(), 150)
        self.assertFalse(lease.verified)

    def test_documented_unified_computer_use_server_alias(self) -> None:
        lease = TabLeaseObserver(CASE, NONCE)
        for ms, item in ((50, self.created()), (100, self.owner()), (150, self.closed())):
            item["item"]["server"] = "unified-computer-use"
            lease.on_event(item, ms)
        self.assertTrue(lease.verified)

    def test_concatenated_probe_and_owner_output_is_recognized(self) -> None:
        lease = TabLeaseObserver(CASE, NONCE)
        lease.on_event(self.created(), 50)
        owner = self.owner()
        owner["item"]["result"]["content"][0]["text"] = (
            "CU_REPL_PROBE fresh" + owner["item"]["result"]["content"][0]["text"])
        lease.on_event(owner, 100)
        lease.on_event(self.closed(), 150)
        self.assertTrue(lease.verified)
        self.assertIn("+ '\\n'", owner_script(trial_url(CASE, NONCE)))

    def test_only_pinned_browser_cases_and_hex_nonce_are_accepted(self) -> None:
        self.assertEqual(trial_url(CASE, NONCE),
                         f"http://127.0.0.1:8765/?case_id={CASE}&trial={NONCE}")
        for case, nonce in (("browser-dialog-0", NONCE), (CASE, "bad"),
                            ("native-duplicate_label-0", NONCE)):
            with self.subTest(case=case, nonce=nonce), self.assertRaises(ValueError):
                trial_url(case, nonce)


if __name__ == "__main__":
    unittest.main()
