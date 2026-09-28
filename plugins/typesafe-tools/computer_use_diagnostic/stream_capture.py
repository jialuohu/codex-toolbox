"""Capture one Codex JSONL run with a single monotonic clock.

This module keeps only event metadata. Raw prompts, tool input, UI output, and
stderr are consumed in memory and are never written to a file by this module.
CLI item boundaries are *stream receipt* times, not backend execution times.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

TOKEN_FIELDS = frozenset({
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
})
TOOL_TYPES = frozenset({"command_execution", "mcp_tool_call", "tool_call"})


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _signal_process_group(child: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(child.pid, sig)
    except ProcessLookupError:
        pass


def _size(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _payload_size(item: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in item:
            return _size(item[key])
    return 0


def _kind(item: dict) -> str:
    identifiers = " ".join(str(item.get(key, "")) for key in ("type", "server", "tool", "name"))
    if "cua_repl" in identifiers or "unified-computer-use" in identifiers:
        return "cua"
    if "typesafe_choose_action" in identifiers or "typesafe-judgment" in identifiers:
        return "jev"
    return "other"


def _timing_consistent(
    calls: list[dict], durations: list[float], start_ms: float, end_ms: float,
) -> bool:
    """Check direct CUA timing and containment of nested MCP execution."""
    if not calls or len(calls) != len(durations):
        return False
    previous_end = start_ms
    for call, duration in zip(calls, durations):
        call_start, call_end = call["start_ms"], call["end_ms"]
        observed = call_end - call_start
        tolerance = max(50.0, 0.02 * duration)
        if duration <= 0 or call_start < previous_end or observed <= 0 or call_end > end_ms:
            return False
        if call.get("kind", "cua") == "cua" and abs(observed - duration) > tolerance:
            return False
        if call.get("kind", "cua") != "cua" and duration > observed + tolerance:
            return False
        previous_end = call_end
    return True


def _wrapper_overheads(calls: list[dict], durations: list[float]) -> list[float]:
    """Separate preparation/transport inside non-CUA wrapper intervals."""
    return [
        max(0.0, call["end_ms"] - call["start_ms"] - duration)
        if call["kind"] != "cua" else 0.0
        for call, duration in zip(calls, durations)
    ]


@dataclass
class CaptureResult:
    """Metadata from one fresh process; milliseconds use its controller clock."""

    start_ms: float
    end_ms: float
    returncode: int | None
    timed_out: bool
    thread_id_sha256: str | None
    tool_calls: list[dict] = field(default_factory=list)
    runtime_tool_durations_ms: list[float] = field(default_factory=list)
    runtime_tool_event_indices: list[int] = field(default_factory=list)
    runtime_wrapper_overhead_ms: list[float] = field(default_factory=list)
    wrapper_preparation_ms: float = 0.0
    runtime_durations_covered: bool = False
    timing_complete: bool = False
    turn_completed_ms: float | None = None
    process_exited_ms: float | None = None
    process_group_quiescent: bool | None = None
    codex_usage: dict | None = None
    usage_isolated: bool = False
    event_count: int = 0
    stderr_bytes: int = 0
    error_kind: str | None = None
    warnings: list[str] = field(default_factory=list)
    timing_basis: str = "jsonl_stream_receipt"

    def codex_usage_after_verification(self, verified_cua_receipt_ms: float | None) -> dict | None:
        """Confirm one CUA result precedes the same turn's task completion."""
        if (self.codex_usage is None or verified_cua_receipt_ms is None
                or self.turn_completed_ms is None or self.timed_out):
            return None
        if not self.start_ms < verified_cua_receipt_ms < self.turn_completed_ms <= self.end_ms:
            return None
        matches = [index for index, call in enumerate(self.tool_calls)
                   if call["kind"] == "cua" and call["end_ms"] == verified_cua_receipt_ms]
        if len(matches) != 1 or len(self.runtime_tool_event_indices) != len(self.tool_calls):
            return None
        if not (self.runtime_tool_event_indices[matches[0]]
                < self.codex_usage["event_index"]
                < self.codex_usage["task_complete"]["event_index"]):
            return None
        usage = dict(self.codex_usage)
        usage["task_complete"] = {**usage["task_complete"], "after_verification": True}
        return usage


def _rollout_path(thread_id: str, sessions_dir: Path | None) -> Path | None:
    root = sessions_dir or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    for offset in (0, -1):
        day = (datetime.now().astimezone() + timedelta(days=offset)).strftime("%Y/%m/%d")
        matches = list((root / day).glob(f"rollout-*-{thread_id}.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return None


def _rollout_usage(
    thread_id: str, sessions_dir: Path | None,
) -> tuple[dict | None, bool, list[tuple[str, float, int]], list[str]]:
    """Read terminal counters, opaque digests, and backend-reported durations."""
    path = _rollout_path(thread_id, sessions_dir)
    if path is None:
        return None, False, [], ["rollout_missing_or_ambiguous"]
    meta = None
    records: list[tuple[int, dict, str]] = []
    completions: list[tuple[int, dict, str]] = []
    runtime_calls: list[tuple[str, float, int]] = []
    runtime_duration_valid = True
    try:
        with path.open("rb") as source:
            for index, raw in enumerate(source):
                row = json.loads(raw)
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                if row.get("type") == "session_meta" and meta is None:
                    meta = payload
                elif row.get("type") == "token_usage_record":
                    records.append((index, payload, _digest(raw)))
                elif row.get("type") == "event_msg" and payload.get("type") == "task_complete":
                    completions.append((index, payload, _digest(raw)))
                elif row.get("type") == "event_msg" and payload.get("type") == "item_completed":
                    item = payload.get("item")
                    if isinstance(item, dict) and item.get("type") == "McpToolCall":
                        duration = item.get("duration")
                        if (not isinstance(duration, dict)
                                or type(duration.get("secs")) is not int
                                or type(duration.get("nanos")) is not int
                                or duration["secs"] < 0 or not 0 <= duration["nanos"] < 1_000_000_000):
                            runtime_duration_valid = False
                        else:
                            runtime_calls.append((
                                _kind(item), duration["secs"] * 1000 + duration["nanos"] / 1_000_000,
                                index,
                            ))
    except (OSError, ValueError, TypeError):
        return None, False, [], ["rollout_unreadable"]
    isolated = bool(meta and meta.get("id") == thread_id
                    and meta.get("session_id") == thread_id
                    and meta.get("source") == "exec"
                    and meta.get("originator") == "codex_exec")
    if not isolated:
        return None, False, [], ["rollout_session_not_isolated"]
    if len(completions) != 1:
        return None, True, [], ["task_complete_not_unique"]
    complete_index, complete, complete_hash = completions[0]
    turn_id = complete.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        return None, True, [], ["task_complete_turn_missing"]
    if any(row.get("turn_id") != turn_id or row.get("session_id") != thread_id
           for _, row, _ in records):
        return None, True, [], ["rollout_multiple_turns_or_sessions"]
    prior = [(i, row, digest) for i, row, digest in records if i < complete_index]
    if not prior or len(prior) != len(records):
        return None, True, [], ["terminal_usage_missing"]
    usage_index, terminal, usage_hash = prior[-1]
    counters = terminal.get("turn_token_usage")
    if (not isinstance(counters, dict) or set(counters) != TOKEN_FIELDS
            or any(type(value) is not int or value < 0 for value in counters.values())):
        return None, True, [], ["six_token_counters_missing"]
    usage = {
        "source": "codex_turn_token_usage_record",
        "session_sha256": _digest(thread_id),
        "turn_sha256": _digest(turn_id),
        "event_index": usage_index,
        "event_sha256": usage_hash,
        "turn_token_usage": dict(counters),
        "terminal_usage_verified": True,
        "task_complete": {
            "kind": "task_complete", "event_index": complete_index,
            "event_sha256": complete_hash, "turn_sha256": _digest(turn_id),
            # The caller must establish a fresh CUA verification before setting this.
            "after_verification": False,
        },
    }
    return usage, True, runtime_calls if runtime_duration_valid else [], (
        [] if runtime_duration_valid else ["runtime_tool_duration_invalid"]
    )


def capture_command(
    argv: Sequence[str], *, prepare_stdin: Callable[[], str], timeout_ms: int,
    cwd: str | Path, on_event: Callable[[dict, float], None] | None = None,
    on_process_start: Callable[[int], None] | None = None,
    sessions_dir: Path | None = None,
) -> CaptureResult:
    """Run one CLI turn, stamping JSONL receipts from before recipe preparation.

    The callback receives raw event data only in memory. It must not retain raw
    prompts or UI output in a diagnostic record. A missing/unpaired item leaves
    timing incomplete; callers must not turn receipt windows into backend times.
    """
    start_ns = time.monotonic_ns()
    start_ms = start_ns / 1_000_000
    result = CaptureResult(start_ms, start_ms, None, False, None)
    if type(timeout_ms) is not int or timeout_ms <= 0:
        result.error_kind = "invalid_timeout"
        return result
    deadline_ns = start_ns + timeout_ms * 1_000_000
    try:
        stdin_text = prepare_stdin()
        if not isinstance(stdin_text, str):
            raise TypeError("prepare_stdin must return text")
    except Exception:  # noqa: BLE001 - turn arbitrary recipe errors into metadata-only failure
        result.end_ms = time.monotonic_ns() / 1_000_000
        result.error_kind = "preparation_error"
        return result
    if time.monotonic_ns() >= deadline_ns:
        result.end_ms = time.monotonic_ns() / 1_000_000
        result.timed_out = True
        result.error_kind = "preparation_timeout"
        return result
    try:
        child = subprocess.Popen(
            list(argv), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, start_new_session=True,
        )
    except OSError:
        result.end_ms = time.monotonic_ns() / 1_000_000
        result.error_kind = "process_start_error"
        return result
    if on_process_start is not None:
        try:
            on_process_start(child.pid)
        except Exception:  # noqa: BLE001 - never leave a diagnostic child running
            _signal_process_group(child, signal.SIGTERM)
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _signal_process_group(child, signal.SIGKILL)
                child.wait()
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()
            result.end_ms = time.monotonic_ns() / 1_000_000
            result.returncode = child.returncode
            result.error_kind = "process_start_hook_error"
            return result
    assert child.stdin is not None and child.stdout is not None and child.stderr is not None
    stdin_bytes = stdin_text.encode("utf-8")
    del stdin_text
    stdin_offset = 0
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    selector.register(child.stderr, selectors.EVENT_READ)
    if stdin_bytes:
        os.set_blocking(child.stdin.fileno(), False)
        selector.register(child.stdin, selectors.EVENT_WRITE)
    else:
        child.stdin.close()
    pending = bytearray()
    started: dict[str, tuple[float, dict]] = {}
    completed: set[str] = set()
    thread_id: str | None = None
    try:
        while selector.get_map():
            remaining = (deadline_ns - time.monotonic_ns()) / 1e9
            if remaining <= 0:
                result.timed_out = True
                result.end_ms = time.monotonic_ns() / 1_000_000
                _signal_process_group(child, signal.SIGTERM)
                break
            for key, _ in selector.select(timeout=min(remaining, 0.1)):
                if key.fileobj is child.stdin:
                    try:
                        written = os.write(
                            child.stdin.fileno(),
                            memoryview(stdin_bytes)[stdin_offset:stdin_offset + 65536],
                        )
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        result.warnings.append("stdin_pipe_closed")
                        selector.unregister(child.stdin)
                        child.stdin.close()
                        stdin_bytes = b""
                        continue
                    stdin_offset += written
                    if stdin_offset == len(stdin_bytes):
                        selector.unregister(child.stdin)
                        child.stdin.close()
                        stdin_bytes = b""
                    continue
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is child.stderr:
                    result.stderr_bytes += len(chunk)
                    continue
                pending.extend(chunk)
                while b"\n" in pending:
                    raw, _, remainder = pending.partition(b"\n")
                    pending = bytearray(remainder)
                    receipt_ms = time.monotonic_ns() / 1_000_000
                    try:
                        event = json.loads(raw)
                    except (ValueError, UnicodeError):
                        result.warnings.append("invalid_jsonl_event")
                        continue
                    result.event_count += 1
                    event_type = event.get("type")
                    item = event.get("item") if isinstance(event.get("item"), dict) else {}
                    new_thread_id = event.get("thread_id")
                    if event_type == "thread.started" and isinstance(new_thread_id, str):
                        if thread_id is not None:
                            result.warnings.append("duplicate_thread_started")
                        thread_id = new_thread_id
                        result.thread_id_sha256 = _digest(new_thread_id)
                    if event_type == "turn.completed":
                        if result.turn_completed_ms is not None:
                            result.warnings.append("duplicate_turn_completed")
                        result.turn_completed_ms = receipt_ms
                    if event_type in ("item.started", "item.completed") and item.get("type") in TOOL_TYPES:
                        item_id = item.get("id")
                        if not isinstance(item_id, str):
                            result.warnings.append("tool_item_without_id")
                        elif event_type == "item.started":
                            if item_id in started:
                                result.warnings.append("duplicate_tool_start")
                            started[item_id] = (receipt_ms, item)
                        else:
                            previous = started.pop(item_id, None)
                            if previous is None or item_id in completed:
                                result.warnings.append("unpaired_tool_completion")
                            else:
                                call_start, first = previous
                                completed.add(item_id)
                                result.tool_calls.append({
                                    "kind": _kind(item) if _kind(item) != "other" else _kind(first),
                                    "start_ms": call_start, "end_ms": receipt_ms,
                                    "code_bytes": _payload_size(item, ("arguments", "input", "command"))
                                    or _payload_size(first, ("arguments", "input", "command")),
                                    "output_bytes": _payload_size(item, ("result", "output", "aggregated_output")),
                                })
                    if on_event is not None:
                        on_event(event, receipt_ms)
    except Exception:  # noqa: BLE001 - stop the child if a stream callback fails
        result.warnings.append("capture_stream_error")
        if child.poll() is None:
            _signal_process_group(child, signal.SIGTERM)
    finally:
        selector.close()
        if child.poll() is None:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _signal_process_group(child, signal.SIGKILL)
        result.returncode = child.wait()
        result.process_exited_ms = time.monotonic_ns() / 1_000_000
        # This child was started in its own process group. The leader exiting
        # does not prove that a CUA/MCP descendant stopped acting on the GUI.
        # Never start another serial GUI trial unless this group is gone.
        for _ in range(20):
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                result.process_group_quiescent = True
                break
            except PermissionError:
                result.process_group_quiescent = False
                break
            time.sleep(0.05)
        else:
            _signal_process_group(child, signal.SIGKILL)
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                result.process_group_quiescent = True
            except PermissionError:
                result.process_group_quiescent = False
            else:
                result.process_group_quiescent = False
        child.stdout.close()
        child.stderr.close()
        if not child.stdin.closed:
            child.stdin.close()
        if not result.timed_out:
            result.end_ms = time.monotonic_ns() / 1_000_000
        if started:
            result.warnings.append("unpaired_tool_start")
        if pending:
            result.warnings.append("unterminated_jsonl_event")
    if thread_id is not None:
        usage, isolated, runtime_calls, warnings = _rollout_usage(thread_id, sessions_dir)
        result.codex_usage = usage
        result.usage_isolated = isolated
        result.warnings.extend(warnings)
        if (runtime_calls and len(runtime_calls) == len(result.tool_calls)
                and all(kind == call["kind"] for (kind, _, _), call in zip(runtime_calls, result.tool_calls))):
            result.runtime_tool_durations_ms = [duration for _, duration, _ in runtime_calls]
            result.runtime_tool_event_indices = [index for _, _, index in runtime_calls]
            result.runtime_wrapper_overhead_ms = _wrapper_overheads(
                result.tool_calls, result.runtime_tool_durations_ms,
            )
            result.wrapper_preparation_ms = sum(result.runtime_wrapper_overhead_ms)
            result.runtime_durations_covered = True
            result.timing_complete = (
                not result.timed_out
                and not any(warning in result.warnings for warning in (
                    "duplicate_tool_start", "unpaired_tool_completion", "unpaired_tool_start",
                    "tool_item_without_id", "invalid_jsonl_event", "capture_stream_error",
                ))
                and _timing_consistent(
                    result.tool_calls, result.runtime_tool_durations_ms,
                    result.start_ms, result.end_ms,
                )
            )
            if not result.timing_complete:
                result.warnings.append("stream_backend_timing_mismatch")
        elif result.tool_calls:
            result.warnings.append("runtime_tool_duration_unpaired")
    else:
        result.warnings.append("thread_started_missing")
    return result
