"""Prove that one trial-created browser tab was closed in its owning CUA task.

The browser backend rejects binding a tab from another Codex task session.
Consequently, a missing close receipt blocks later browser trials; this module
never tries to sweep tabs by title, URL, or a foreign session's tab ID.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

_CASE = re.compile(r"browser-(?:duplicate_label|tabs|filter|long_tree)-0\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_TAB_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_OWNER = re.compile(r"CU_TAB_OWNER (\{[^\n]+\})")
_CLOSED = re.compile(r"CU_TAB_CLOSED (\{[^\n]+\})")


def trial_url(case_id: str, nonce: str) -> str:
    """Add an unguessable URL marker without changing fixture behavior."""
    if not _CASE.fullmatch(case_id) or not _NONCE.fullmatch(nonce):
        raise ValueError("invalid browser trial identity")
    return "http://127.0.0.1:8765/?" + urlencode({"case_id": case_id, "trial": nonce})


def create_script(url: str, browser_id: str = "1") -> str:
    """Use only the documented first-call browser entry point."""
    return ("var cuFixtureTab = await cua.createBrowserTab("
            + json.dumps(browser_id) + ", " + json.dumps(url) + ");")


def owner_script(url: str, browser_id: str = "1") -> str:
    """Report the actual bound tab ID and matching inventory entry."""
    browser = json.dumps(browser_id)
    expected = json.dumps(url)
    return ("var cuPreviousProbe = globalThis.__codexToolboxCuPreparationProbe;\n"
            "globalThis.__codexToolboxCuPreparationProbe = 'preparation-diagnostic-v2';\n"
            "nodeRepl.write('CU_REPL_PROBE ' + (cuPreviousProbe === undefined ? 'fresh' : 'reused') + '\\n');\n"
            "var cuOwnedTabs = await cua.listTabs({browser:" + browser + ",emit:false});\n"
            "var cuOwnedEntry = cuOwnedTabs.find(t => t.id === cuFixtureTab.id);\n"
            "nodeRepl.write('CU_TAB_OWNER ' + JSON.stringify({"
            "id:cuFixtureTab.id,url:cuOwnedEntry?.url,browserId:" + browser + ","
            "present:cuOwnedEntry?.url === " + expected + ","
            "existingFixtureCount:cuOwnedTabs.filter(t => t.id !== cuFixtureTab.id && "
            "(t.url||'').startsWith('http://127.0.0.1:8765/?case_id=browser-')).length}));")


def close_script(browser_id: str = "1") -> str:
    """Close only the bound tab and verify its ID is absent from inventory."""
    return ("var cuClosingId = cuFixtureTab.id;\n"
            "await cuFixtureTab.close();\n"
            "var cuRemainingTabs = await cua.listTabs({browser:"
            + json.dumps(browser_id) + ",emit:false});\n"
            "nodeRepl.write('CU_TAB_CLOSED ' + JSON.stringify({"
            "id:cuClosingId,absent:!cuRemainingTabs.some(t => t.id === cuClosingId)}));")


def _cua_result(event: object) -> tuple[str, str] | None:
    if not isinstance(event, dict) or event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if (not isinstance(item, dict) or item.get("type") not in ("mcp_tool_call", "tool_call")
            or item.get("server") not in ("cua_repl", "unified-computer-use")
            or item.get("status") not in (None, "completed")):
        return None
    args = item.get("arguments")
    code = args.get("code") if isinstance(args, dict) else None
    result = item.get("result")
    if not isinstance(code, str):
        return None
    if isinstance(result, str):
        return code, result
    if isinstance(result, dict):
        if result.get("isError") is True:
            return None
        content = result.get("content")
        if isinstance(content, list):
            return code, "\n".join(block.get("text", "") for block in content
                                    if isinstance(block, dict) and block.get("type") == "text")
    return None


def _single_marker(text: str, pattern: re.Pattern[str]) -> dict | None:
    matches = pattern.findall(text)
    if len(matches) != 1:
        return None
    try:
        value = json.loads(matches[0])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


@dataclass
class TabLeaseObserver:
    """Consume completed CUA receipts without persisting UI trees or URLs."""

    case_id: str
    nonce: str
    browser_id: str = "1"
    creation_observed: bool = False
    owned_tab_id: str | None = None
    existing_fixture_count: int | None = None
    owner_receipt_ms: float | None = None
    closed_receipt_ms: float | None = None
    contradiction: bool = False

    @property
    def url(self) -> str:
        return trial_url(self.case_id, self.nonce)

    @property
    def verified(self) -> bool:
        return (not self.contradiction and self.creation_observed
                and self.owned_tab_id is not None
                and self.owner_receipt_ms is not None and self.closed_receipt_ms is not None
                and self.owner_receipt_ms < self.closed_receipt_ms)

    def on_event(self, event: object, receipt_ms: float) -> None:
        receipt = _cua_result(event)
        if receipt is None:
            return
        code, text = receipt
        if code == create_script(self.url, self.browser_id):
            if self.creation_observed:
                self.contradiction = True
            self.creation_observed = True
        owner = _single_marker(text, _OWNER)
        if owner is not None:
            tab_id = owner.get("id")
            count = owner.get("existingFixtureCount")
            if (set(owner) != {"id", "url", "browserId", "present", "existingFixtureCount"}
                    or not isinstance(tab_id, str) or not _TAB_ID.fullmatch(tab_id)
                    or type(count) is not int or count < 0
                    or owner.get("url") != self.url or owner.get("browserId") != self.browser_id
                    or owner.get("present") is not True
                    or code != owner_script(self.url, self.browser_id)
                    or not self.creation_observed):
                self.contradiction = True
            elif self.owned_tab_id is None:
                self.owned_tab_id = tab_id
                self.existing_fixture_count = count
                self.owner_receipt_ms = receipt_ms
            else:
                self.contradiction = True
        closed = _single_marker(text, _CLOSED)
        if closed is not None:
            if (set(closed) != {"id", "absent"}
                    or closed.get("id") != self.owned_tab_id or closed.get("absent") is not True
                    or code != close_script(self.browser_id)
                    or self.closed_receipt_ms is not None):
                self.contradiction = True
            else:
                self.closed_receipt_ms = receipt_ms

    def metadata(self, process_exited_ms: float | None) -> dict[str, object]:
        """Return allowlisted metadata; never persist tab IDs or URLs."""
        after_exit = (process_exited_ms is not None
                      and self.closed_receipt_ms is not None
                      and self.closed_receipt_ms <= process_exited_ms)
        return {"creation_observed": self.creation_observed,
                "owner_observed": self.owned_tab_id is not None,
                "existing_fixture_count": self.existing_fixture_count,
                "close_verified": self.verified and after_exit,
                "contradiction": self.contradiction,
                "owner_receipt_ms": self.owner_receipt_ms,
                "closed_receipt_ms": self.closed_receipt_ms}
