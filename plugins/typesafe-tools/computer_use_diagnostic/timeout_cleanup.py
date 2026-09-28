"""Bounded, exact-tab cleanup after an isolated browser trial has stopped.

A resumed Codex turn can recover its own CUA browser session. This module never
searches by title or URL and never treats a generated statement as a receipt.
Its duration is outside the measured trial span.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import tab_lease
from .stream_capture import CaptureResult, capture_command

RECOVERY_TIMEOUT_MS = 100_000
_UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
_MARKER = re.compile(r"CU_TAB_RECOVERED (\{[^\n]+\})")
_PROMPT_TEMPLATE = """The preceding synthetic browser trial has stopped. Close only its
exact trial-owned tab. Do not act on the fixture, search by title or URL, or
close any other tab. Use only cua_repl and the two exact JavaScript calls below.
First CUA call (one documented entrypoint only):
{bind}
Second CUA call (the URL guard runs before close):
{close}
If binding or the guard fails, stop without another action. Report only whether
the exact-tab close receipt was observed.
"""


def prompt_template_sha256() -> str:
    return hashlib.sha256(_PROMPT_TEMPLATE.encode()).hexdigest()


def bind_script(tab_id: str, browser_id: str = "1") -> str:
    return ("var cuRecoveryTab = await cua.getTab("
            + json.dumps(tab_id) + ", {browser:" + json.dumps(browser_id) + "});")


def close_script(tab_id: str, url: str, browser_id: str = "1") -> str:
    tab = json.dumps(tab_id)
    browser = json.dumps(browser_id)
    expected = json.dumps(url)
    return ("var cuRecoveryTabsBefore = await cua.listTabs({browser:" + browser + ",emit:false});\n"
            "var cuRecoveryOwned = cuRecoveryTabsBefore.find(t => t.id === " + tab + ");\n"
            "if (cuRecoveryTab.id !== " + tab + " || cuRecoveryOwned?.url !== "
            + expected + ") throw new Error('trial tab identity mismatch');\n"
            "await cuRecoveryTab.close();\n"
            "var cuRecoveryTabsAfter = await cua.listTabs({browser:" + browser + ",emit:false});\n"
            "nodeRepl.write('CU_TAB_RECOVERED ' + JSON.stringify({id:" + tab
            + ",urlMatched:true,absent:!cuRecoveryTabsAfter.some(t => t.id === "
            + tab + ")}));")


@dataclass(frozen=True)
class RecoveryResult:
    attempted: bool
    verified: bool
    elapsed_ms: float | None
    controller_terminated_ms: float | None
    tool_calls: int
    error_kind: str | None

    def metadata(self) -> dict[str, object]:
        return {"recovery_attempted": self.attempted,
                "recovery_verified": self.verified,
                "recovery_elapsed_ms": self.elapsed_ms,
                "recovery_controller_terminated_ms": self.controller_terminated_ms,
                "recovery_tool_calls": self.tool_calls,
                "recovery_error_kind": self.error_kind}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _valid_trial_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, strict_parsing=True)
        if (parts.scheme != "http" or parts.netloc != "127.0.0.1:8765"
                or parts.path != "/" or parts.fragment
                or set(query) != {"case_id", "trial"}
                or len(query["case_id"]) != 1 or len(query["trial"]) != 1):
            return False
        return tab_lease.trial_url(query["case_id"][0], query["trial"][0]) == url
    except ValueError:
        return False


def recover(
    *, thread_id: str, expected_thread_sha256: str | None,
    tab_id: str, url: str, browser_id: str, cwd: Path,
    model: str, reasoning: str, isolated_config_args: Sequence[str],
    capture: Callable[..., CaptureResult] = capture_command,
) -> RecoveryResult:
    """Resume only the owning Codex thread and prove exact-ID close/absence."""
    if (not _UUID.fullmatch(thread_id) or expected_thread_sha256 != _digest(thread_id)
            or not tab_lease._TAB_ID.fullmatch(tab_id)
            or not _valid_trial_url(url)
            or browser_id != "1"):
        return RecoveryResult(False, False, None, None, 0, "invalid_owned_identity")
    bind = bind_script(tab_id, browser_id)
    close = close_script(tab_id, url, browser_id)
    calls: list[str] = []
    started_tool_count = 0
    marker_verified = False
    unexpected_tool = False

    def on_event(event: dict[str, Any], _receipt_ms: float) -> None:
        nonlocal marker_verified, unexpected_tool, started_tool_count
        if event.get("type") not in {"item.started", "item.completed"}:
            return
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") not in {
                "mcp_tool_call", "tool_call", "command_execution"}:
            return
        if event["type"] == "item.started":
            started_tool_count += 1
            if started_tool_count > 2:
                unexpected_tool = True
            return
        receipt = tab_lease._cua_result(event)
        if receipt is None:
            unexpected_tool = True
            return
        code, output = receipt
        calls.append(code)
        if len(calls) == 1 and code == bind:
            return
        if len(calls) != 2 or code != close or calls[0] != bind:
            unexpected_tool = True
            return
        matches = _MARKER.findall(output)
        if len(matches) != 1:
            return
        try:
            marker = json.loads(matches[0])
        except (ValueError, TypeError):
            return
        marker_verified = (isinstance(marker, dict)
                           and set(marker) == {"id", "urlMatched", "absent"}
                           and marker["id"] == tab_id
                           and marker["urlMatched"] is True
                           and marker["absent"] is True)

    command = ["codex", "exec", "resume", "--json", "--ignore-user-config",
               "-m", model, "-c", f"model_reasoning_effort={reasoning}",
               *isolated_config_args, thread_id, "-"]
    captured = capture(
        command,
        prepare_stdin=lambda: _PROMPT_TEMPLATE.format(bind=bind, close=close),
        timeout_ms=RECOVERY_TIMEOUT_MS,
        cwd=cwd,
        on_event=on_event,
    )
    verified = (marker_verified and not unexpected_tool and calls == [bind, close]
                and captured.thread_id_sha256 == _digest(thread_id)
                and captured.returncode == 0 and not captured.timed_out
                and captured.turn_completed_ms is not None
                and captured.process_group_quiescent is True
                and len(captured.tool_calls) == 2
                and not any(warning in captured.warnings for warning in (
                    "unpaired_tool_start", "unpaired_tool_completion",
                    "invalid_jsonl_event", "capture_stream_error"))
                and all(call.get("kind") == "cua" for call in captured.tool_calls))
    return RecoveryResult(
        True, verified, max(0.0, captured.end_ms - captured.start_ms),
        captured.process_exited_ms, len(captured.tool_calls),
        None if verified else (captured.error_kind or "recovery_receipt_unverified"),
    )
