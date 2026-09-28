"""Metadata-only JSONL stream capture tests with a disposable child process."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic.stream_capture import (
    _timing_consistent,
    _wrapper_overheads,
    capture_command,
)

THREAD = "12345678-1234-4123-8123-123456789abc"
TURN = "12345678-1234-4123-8123-123456789abd"
COUNTERS = {
    "input_tokens": 80, "cached_input_tokens": 20,
    "cache_write_input_tokens": 0, "output_tokens": 20,
    "reasoning_output_tokens": 5, "total_tokens": 100,
}


def _rollout(root: Path, *, six_counters: bool = True, runtime_call: bool = True) -> None:
    day = datetime.now().astimezone().strftime("%Y/%m/%d")
    folder = root / day
    folder.mkdir(parents=True)
    usage = dict(COUNTERS)
    if not six_counters:
        del usage["cache_write_input_tokens"]
    rows = [
        {"type": "session_meta", "payload": {
            "id": THREAD, "session_id": THREAD, "source": "exec", "originator": "codex_exec",
        }},
        *([{"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "McpToolCall", "server": "cua_repl", "tool": "js",
            "duration": {"secs": 0, "nanos": 15_000_000},
        }}}] if runtime_call else []),
        {"type": "token_usage_record", "payload": {
            "session_id": THREAD, "turn_id": TURN, "turn_token_usage": usage,
        }},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": TURN}},
    ]
    path = folder / f"rollout-test-{THREAD}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _child(events: list[dict], *, delay: float = 0.01) -> list[str]:
    script = (
        "import json,sys,time\n"
        f"events={events!r}\n"
        "sys.stdin.read()\n"
        "for row in events:\n"
        " print(json.dumps(row), flush=True)\n"
        f" time.sleep({delay!r})\n"
    )
    return [sys.executable, "-u", "-c", script]


def _events() -> list[dict]:
    return [
        {"type": "thread.started", "thread_id": THREAD},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "item_1", "type": "mcp_tool_call",
            "server": "unified-computer-use", "tool": "js",
            "arguments": {"code": "secret prompt content"}}},
        {"type": "item.completed", "item": {"id": "item_1", "type": "mcp_tool_call",
            "server": "unified-computer-use", "tool": "js",
            "arguments": {"code": "secret prompt content"},
            "result": "private UI output"}},
        {"type": "turn.completed", "usage": {"total_tokens": 100}},
    ]


class CaptureTests(unittest.TestCase):
    def test_monotonic_span_pairs_tool_and_keeps_payloads_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _rollout(root)
            seen = []
            capture = capture_command(
                _child(_events()), prepare_stdin=lambda: "secret recipe",
                timeout_ms=2000, cwd=root, sessions_dir=root,
                on_event=lambda event, ms: seen.append((event["type"], ms)),
            )
            self.assertEqual(capture.returncode, 0)
            self.assertFalse(capture.timed_out)
            self.assertIsNone(capture.error_kind)
            self.assertEqual(capture.event_count, 5)
            self.assertEqual(len(seen), 5)
            self.assertEqual(len(capture.tool_calls), 1)
            call = capture.tool_calls[0]
            self.assertEqual(call["kind"], "cua")
            self.assertLess(capture.start_ms, call["start_ms"])
            self.assertLess(call["start_ms"], call["end_ms"])
            self.assertLess(call["end_ms"], capture.end_ms)
            self.assertIsNotNone(capture.process_exited_ms)
            self.assertTrue(capture.process_group_quiescent)
            self.assertLessEqual(call["end_ms"], capture.process_exited_ms)
            self.assertLessEqual(capture.process_exited_ms, capture.end_ms)
            self.assertGreater(call["code_bytes"], 0)
            self.assertEqual(call["output_bytes"], len("private UI output"))
            self.assertTrue(capture.runtime_durations_covered)
            self.assertEqual(capture.runtime_tool_durations_ms, [15.0])
            self.assertTrue(capture.usage_isolated)
            self.assertEqual(capture.codex_usage["turn_token_usage"], COUNTERS)
            self.assertFalse(capture.codex_usage["task_complete"]["after_verification"])
            verified_receipt = next(ms for name, ms in seen if name == "item.completed")
            confirmed = capture.codex_usage_after_verification(verified_receipt)
            self.assertTrue(confirmed["task_complete"]["after_verification"])
            self.assertFalse(capture.codex_usage["task_complete"]["after_verification"])
            self.assertIsNone(capture.codex_usage_after_verification(verified_receipt + 1))
            capture.runtime_tool_event_indices[0] = confirmed["event_index"]
            self.assertIsNone(capture.codex_usage_after_verification(verified_receipt))
            capture.runtime_tool_event_indices[0] = confirmed["task_complete"]["event_index"]
            self.assertIsNone(capture.codex_usage_after_verification(verified_receipt))
            self.assertNotIn("secret", repr(capture))
            self.assertNotIn("private UI", repr(capture))

    def test_preparation_is_inside_span_and_errors_are_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            def prepare() -> str:
                time.sleep(0.02)
                raise RuntimeError("private recipe")

            capture = capture_command(
                [sys.executable], prepare_stdin=prepare, timeout_ms=2000, cwd=temp,
            )
            self.assertEqual(capture.error_kind, "preparation_error")
            self.assertGreaterEqual(capture.end_ms - capture.start_ms, 15)
            self.assertNotIn("private recipe", repr(capture))

    def test_timeout_and_incomplete_counters_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            timeout = capture_command(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                prepare_stdin=lambda: "", timeout_ms=30, cwd=root, sessions_dir=root,
            )
            self.assertTrue(timeout.timed_out)
            self.assertIsNotNone(timeout.process_exited_ms)
            self.assertTrue(timeout.process_group_quiescent)
            self.assertGreaterEqual(timeout.process_exited_ms, timeout.end_ms)
            self.assertIn("thread_started_missing", timeout.warnings)
            _rollout(root, six_counters=False)
            incomplete = capture_command(
                _child(_events()), prepare_stdin=lambda: "", timeout_ms=2000,
                cwd=root, sessions_dir=root,
            )
            self.assertIsNone(incomplete.codex_usage)
            self.assertIn("six_token_counters_missing", incomplete.warnings)

    def test_large_stdin_cannot_block_the_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            start = time.monotonic()
            stalled = capture_command(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                prepare_stdin=lambda: "x" * 1_000_000,
                timeout_ms=50, cwd=temp,
            )
            wall_ms = (time.monotonic() - start) * 1000
            self.assertTrue(stalled.timed_out)
            self.assertLess(stalled.end_ms - stalled.start_ms, 500)
            self.assertLess(wall_ms, 1000)
            self.assertIn("thread_started_missing", stalled.warnings)

    def test_large_stdin_is_delivered_while_stdout_is_drained(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _rollout(root)
            capture = capture_command(
                _child(_events()), prepare_stdin=lambda: "x" * 300_000,
                timeout_ms=2000, cwd=root, sessions_dir=root,
            )
            self.assertFalse(capture.timed_out)
            self.assertEqual(capture.returncode, 0)
            self.assertEqual(capture.event_count, 5)

    def test_live_process_identity_is_available_only_to_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _rollout(root)
            pids = []
            capture = capture_command(
                _child(_events()), prepare_stdin=lambda: "", timeout_ms=2000,
                cwd=root, sessions_dir=root,
                on_process_start=lambda pid: pids.append(pid),
                on_event=lambda event, _ms: self.assertTrue(pids),
            )
            self.assertEqual(len(pids), 1)
            self.assertGreater(pids[0], 0)
            self.assertNotIn(str(pids[0]), repr(capture))

    def test_unpaired_tool_completion_is_not_invented(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _rollout(root)
            events = [_events()[0], _events()[3]]
            capture = capture_command(
                _child(events), prepare_stdin=lambda: "", timeout_ms=2000,
                cwd=root, sessions_dir=root,
            )
            self.assertEqual(capture.tool_calls, [])
            self.assertIn("unpaired_tool_completion", capture.warnings)

    def test_runtime_duration_requires_one_to_one_kind_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _rollout(root, runtime_call=False)
            capture = capture_command(
                _child(_events()), prepare_stdin=lambda: "", timeout_ms=2000,
                cwd=root, sessions_dir=root,
            )
            self.assertFalse(capture.runtime_durations_covered)
            self.assertEqual(capture.runtime_tool_durations_ms, [])
            self.assertIn("runtime_tool_duration_unpaired", capture.warnings)

    def test_timing_check_rejects_buffered_or_overlapping_windows(self) -> None:
        calls = [{"start_ms": 100.0, "end_ms": 5100.0},
                 {"start_ms": 5200.0, "end_ms": 8200.0}]
        self.assertTrue(_timing_consistent(calls, [4997.0, 2998.0], 0.0, 9000.0))
        self.assertFalse(_timing_consistent(calls, [4500.0, 2998.0], 0.0, 9000.0))
        self.assertFalse(_timing_consistent(calls, [4997.0], 0.0, 9000.0))
        calls[1]["start_ms"] = 5000.0
        self.assertFalse(_timing_consistent(calls, [4997.0, 3198.0], 0.0, 9000.0))

    def test_nested_mcp_wrapper_overhead_is_separate_from_backend_duration(self) -> None:
        calls = [
            {"kind": "cua", "start_ms": 100.0, "end_ms": 5100.0},
            {"kind": "other", "start_ms": 5200.0, "end_ms": 5280.0},
            {"kind": "jev", "start_ms": 5300.0, "end_ms": 9300.0},
        ]
        durations = [4997.0, 5.0, 408.0]
        self.assertTrue(_timing_consistent(calls, durations, 0.0, 10_000.0))
        self.assertEqual(_wrapper_overheads(calls, durations), [0.0, 75.0, 3592.0])
        self.assertFalse(_timing_consistent(calls, [4500.0, 5.0, 408.0], 0.0, 10_000.0))
        self.assertFalse(_timing_consistent(calls, [4997.0, 5.0, 4500.0], 0.0, 10_000.0))


if __name__ == "__main__":
    unittest.main()
