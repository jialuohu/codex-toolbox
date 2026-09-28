"""Extract bounded, privacy-safe evidence from completed diagnostic tool calls.

These values are *observed lower bounds* or dispatch counts, not the exact
``counts`` required by the screening importer. A CUA REPL script may make
multiple UI calls, skip a conditional branch, or suppress an intermediate
state. Its submitted JavaScript and final output cannot prove exact internal
observation, fallback, recovery, or unsafe-action totals.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_AX_NODE = re.compile(r"(?m)^\s*[~+\-]?\s*\d+\s+(?:AXWebArea|application|window|dialog|container|scroll area|text)\b")
_DIFF_NODE = re.compile(r"(?m)^\s*[~+\-]\s*\d+\s+[A-Za-z][\w]*\b")
_SCALAR_FIELD = re.compile(r"(?m)^  ['\"]?(?P<key>[a-z_]+)['\"]?:\s*(?P<value>[^,}\r\n]+),?\s*$")
_ACTION_METHOD = re.compile(r"\.(?:click|type|typeText|fill|press|pressKey|paste|setValue|selectOption)\s*\(")
_HELPER = re.compile(r"(?m)^\s*function\s+(?:cuSelectExcerpt|cuMatchUnique)\s*\(")
_OBJECT_WRITE = re.compile(r"\bnodeRepl\.write\s*\(\s*(?:\{|JSON\.stringify\s*\()")


def _result_text(result: object) -> str | None:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict) or result.get("isError") is True:
        return None
    blocks = result.get("content")
    if isinstance(blocks, list):
        return "\n".join(block["text"] for block in blocks
                         if isinstance(block, dict) and isinstance(block.get("text"), str))
    text = result.get("text")
    return text if isinstance(text, str) else None


def _explicit_fields(code: str, output: str) -> dict[str, object]:
    """Read top-level values written as an object, never arbitrary UI text."""
    if not _OBJECT_WRITE.search(code) or not output.lstrip().startswith("{"):
        return {}
    try:
        value = json.loads(output)
    except ValueError:
        # nodeRepl.write(object) uses Node's inspection format. Only the
        # two-space top-level scalar lines are recognized, not state strings.
        return {match.group("key"): match.group("value").strip()
                for match in _SCALAR_FIELD.finditer(output)}
    return value if isinstance(value, dict) else {}


def _is_false(value: object) -> bool:
    return value is False or value == "false"


def _is_error(value: object) -> bool:
    return value not in (None, "null", "None", "undefined")


def _integer_field(value: object) -> bool:
    return type(value) is int or (isinstance(value, str) and value.isdigit())


@dataclass
class ObservedEvidence:
    """Keep counts only; discard submitted code and UI text after each event."""

    ax_result_receipts: int = 0
    diff_result_receipts: int = 0
    excerpt_result_receipts: int = 0
    helper_definition_sites_submitted: int = 0
    candidate_sets_submitted: int = 0
    candidates_submitted: int = 0
    explicit_action_error_receipts: int = 0
    explicit_failed_verification_receipts: int = 0
    action_method_sites_without_error_receipt: int = 0
    _seen_ids: set[str] = field(default_factory=set, repr=False)

    def on_event(self, event: object) -> None:
        """Accept only a unique completed MCP call from the live JSONL stream."""
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            return
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            return
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in self._seen_ids:
            return
        self._seen_ids.add(item_id)
        server, tool = item.get("server"), item.get("tool")
        if server == "typesafe" and tool == "typesafe_choose_action":
            arguments = item.get("arguments")
            candidates = arguments.get("candidates") if isinstance(arguments, dict) else None
            if isinstance(candidates, list) and candidates:
                self.candidate_sets_submitted += 1
                self.candidates_submitted += len(candidates)
            return
        if server != "cua_repl" or tool != "js" or item.get("status") != "completed":
            return
        arguments = item.get("arguments")
        code = arguments.get("code") if isinstance(arguments, dict) else None
        output = _result_text(item.get("result", item.get("output")))
        if not isinstance(code, str) or output is None:
            return
        # A result can contain an initial state or one selected state even
        # when several getAXState calls ran. Therefore count receipts only.
        if _AX_NODE.search(output):
            self.ax_result_receipts += 1
        if _DIFF_NODE.search(output):
            self.diff_result_receipts += 1
        fields = _explicit_fields(code, output)
        if all(_integer_field(fields.get(key))
               for key in ("total_lines", "shown_lines", "omitted_lines")):
            self.excerpt_result_receipts += 1
        self.helper_definition_sites_submitted += len(_HELPER.findall(code))
        if _ACTION_METHOD.search(code):
            if "action_error" not in fields:
                self.action_method_sites_without_error_receipt += 1
            elif _is_error(fields["action_error"]):
                self.explicit_action_error_receipts += 1
        if _is_false(fields.get("verified")):
            self.explicit_failed_verification_receipts += 1

    def metadata(self) -> dict[str, int]:
        """Return only aggregate counts; no IDs, UI, code, or candidate text."""
        return {
            "ax_result_receipts": self.ax_result_receipts,
            "diff_result_receipts": self.diff_result_receipts,
            "excerpt_result_receipts": self.excerpt_result_receipts,
            "helper_definition_sites_submitted": self.helper_definition_sites_submitted,
            "candidate_sets_submitted": self.candidate_sets_submitted,
            "candidates_submitted": self.candidates_submitted,
            "explicit_action_error_receipts": self.explicit_action_error_receipts,
            "explicit_failed_verification_receipts": self.explicit_failed_verification_receipts,
            "action_method_sites_without_error_receipt": self.action_method_sites_without_error_receipt,
        }


def exact_screening_counts(_: ObservedEvidence) -> dict[str, Any]:
    """No aggregate above proves all required event totals in a REPL script."""
    from .report import COUNT_FIELDS

    return {field: None for field in COUNT_FIELDS}
