"""Exact same-thread browser cleanup is bounded and evidence based."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import tab_lease, timeout_cleanup
from computer_use_diagnostic.stream_capture import CaptureResult

THREAD = "01a0d41c-0c36-7293-ac9a-c0df74912eee"
TAB = "2124389806"
URL = tab_lease.trial_url("browser-duplicate_label-0", "a" * 32)


def cua_event(code: str, output: str) -> dict:
    return {"type": "item.completed", "item": {"type": "mcp_tool_call",
            "server": "cua_repl", "tool": "js", "status": "completed",
            "arguments": {"code": code},
            "result": {"content": [{"type": "text", "text": output}]}}}


class TimeoutCleanupTests(unittest.TestCase):
    def _run(self, *, marker: str | None = None, extra: bool = False,
             timed_out: bool = False, thread: str = THREAD):
        expected = hashlib.sha256(THREAD.encode()).hexdigest()
        bind = timeout_cleanup.bind_script(TAB)
        close = timeout_cleanup.close_script(TAB, URL)
        if marker is None:
            marker = 'CU_TAB_RECOVERED {"id":"2124389806","urlMatched":true,"absent":true}'

        def capture(command, *, prepare_stdin, timeout_ms, cwd, on_event):
            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertEqual(command[-2:], [THREAD, "-"])
            self.assertEqual(timeout_ms, 100_000)
            self.assertEqual(cwd, ROOT)
            prompt = prepare_stdin()
            self.assertIn(bind, prompt)
            self.assertIn(close, prompt)
            self.assertLess(close.index("url !=="), close.index(".close()"))
            on_event(cua_event(bind, "bound"), 20)
            on_event(cua_event(close, marker), 30)
            if extra:
                on_event(cua_event("await cua.listTabs();", "[]"), 35)
            result = CaptureResult(10, 40, 0, timed_out,
                                   hashlib.sha256(thread.encode()).hexdigest())
            result.process_exited_ms = 41
            result.process_group_quiescent = True
            result.turn_completed_ms = 39
            result.tool_calls = [{"kind": "cua"}, {"kind": "cua"}]
            if extra:
                result.tool_calls.append({"kind": "cua"})
            return result

        return timeout_cleanup.recover(
            thread_id=THREAD, expected_thread_sha256=expected,
            tab_id=TAB, url=URL, browser_id="1", cwd=ROOT,
            model="gpt-6-astra", reasoning="medium", isolated_config_args=[],
            capture=capture,
        )

    def test_verified_close_uses_exact_id_url_and_same_thread(self) -> None:
        result = self._run()
        self.assertTrue(result.verified)
        self.assertEqual(result.tool_calls, 2)
        self.assertNotIn(TAB, json.dumps(result.metadata()))
        self.assertNotIn(URL, json.dumps(result.metadata()))

    def test_missing_or_contradictory_evidence_stops(self) -> None:
        self.assertFalse(self._run(marker='CU_TAB_RECOVERED {"id":"wrong","urlMatched":true,"absent":true}').verified)
        self.assertFalse(self._run(extra=True).verified)
        self.assertFalse(self._run(timed_out=True).verified)
        self.assertFalse(self._run(thread="ffffffff-ffff-ffff-ffff-ffffffffffff").verified)
        self.assertFalse(self._run(marker="CU_TAB_RECOVERED invalid").verified)

    def test_invalid_original_identity_never_starts_recovery(self) -> None:
        for digest, url in (("wrong", URL),
                            (hashlib.sha256(THREAD.encode()).hexdigest(), URL + "&extra=1")):
            with self.subTest(digest=digest, url=url):
                result = timeout_cleanup.recover(
                    thread_id=THREAD, expected_thread_sha256=digest, tab_id=TAB,
                    url=url, browser_id="1", cwd=ROOT, model="gpt-6-astra",
                    reasoning="medium", isolated_config_args=[],
                    capture=lambda *_args, **_kwargs: self.fail("unexpected recovery process"),
                )
                self.assertFalse(result.attempted)
                self.assertEqual(result.error_kind, "invalid_owned_identity")


if __name__ == "__main__":
    unittest.main()
