#!/usr/bin/env python3
"""Bounded, metered stdio proxy for the Firecrawl MCP server.

The proxy deliberately exposes only search, scrape, and a local budget status
tool.  A durable reservation is made before each upstream metered tool call.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import json
import os
import pathlib
import select
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, BinaryIO, Mapping, Sequence


BUDGET_CAP_CREDITS = 900
STATE_FILENAME = "firecrawl-budget.json"
STATE_VERSION = 1
MAX_STATE_BYTES = 64 * 1024
MAX_USAGE_RESPONSE_BYTES = 64 * 1024
MAX_CREDIT_VALUE = 1_000_000_000_000
DEFAULT_CREDIT_USAGE_URL = "https://api.firecrawl.dev/v2/team/credit-usage"
FIRECRAWL_CREDENTIAL_ENV = "FIRECRAWL_" + "API_" + "KEY"

SEARCH_TOOL_NAME = "firecrawl_search"
SCRAPE_TOOL_NAME = "firecrawl_scrape"
STATUS_TOOL_NAME = "firecrawl_budget_status"
ALLOWED_UPSTREAM_TOOLS = frozenset({SEARCH_TOOL_NAME, SCRAPE_TOOL_NAME})
ALLOWED_TOOLS = frozenset({*ALLOWED_UPSTREAM_TOOLS, STATUS_TOOL_NAME})

ERROR_BUDGET_EXHAUSTED = "FIRECRAWL_BUDGET_EXHAUSTED"
ERROR_BUDGET_UNAVAILABLE = "FIRECRAWL_BUDGET_UNAVAILABLE"
ERROR_REQUEST_NOT_BOUNDED = "FIRECRAWL_REQUEST_NOT_BOUNDED"

SEARCH_RESERVATION_CREDITS = 2
SCRAPE_RESERVATION_CREDITS = 1


class ProxyFailure(Exception):
    """A safe, stable failure returned to an MCP caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class UsageSnapshot:
    plan_credits: int
    remaining_credits: int
    billing_period_start: str
    billing_period_end: str
    start_time: dt.datetime
    end_time: dt.datetime

    @property
    def spent_credits(self) -> int:
        return self.plan_credits - self.remaining_credits


def _unavailable(message: str) -> ProxyFailure:
    return ProxyFailure(ERROR_BUDGET_UNAVAILABLE, message)


def _not_bounded(message: str) -> ProxyFailure:
    return ProxyFailure(ERROR_REQUEST_NOT_BOUNDED, message)


def _parse_timestamp(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise _unavailable(f"Firecrawl credit usage omitted {field}.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _unavailable(f"Firecrawl credit usage returned invalid {field}.") from exc
    if parsed.tzinfo is None:
        raise _unavailable(f"Firecrawl credit usage returned timezone-free {field}.")
    return parsed.astimezone(dt.timezone.utc)


def _nonnegative_integer(value: Any, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_CREDIT_VALUE
    ):
        raise _unavailable(f"Firecrawl credit usage returned invalid {field}.")
    return value


def _extract_usage(payload: Any) -> UsageSnapshot:
    if not isinstance(payload, dict):
        raise _unavailable("Firecrawl credit usage returned a non-object response.")
    if payload.get("success") is False:
        raise _unavailable("Firecrawl credit usage returned an unsuccessful response.")
    if "data" in payload:
        if not isinstance(payload["data"], dict):
            raise _unavailable("Firecrawl credit usage returned an unsuccessful response.")
        payload = payload["data"]

    plan = _nonnegative_integer(payload.get("planCredits"), "planCredits")
    remaining = _nonnegative_integer(
        payload.get("remainingCredits"), "remainingCredits"
    )
    if remaining > plan:
        raise _unavailable(
            "Firecrawl credit usage reported more remaining credits than plan credits."
        )
    start_raw = payload.get("billingPeriodStart")
    end_raw = payload.get("billingPeriodEnd")
    start = _parse_timestamp(start_raw, "billingPeriodStart")
    end = _parse_timestamp(end_raw, "billingPeriodEnd")
    if end <= start:
        raise _unavailable("Firecrawl credit usage returned an invalid billing period.")
    return UsageSnapshot(
        plan_credits=plan,
        remaining_credits=remaining,
        billing_period_start=start_raw,
        billing_period_end=end_raw,
        start_time=start,
        end_time=end,
    )


class BudgetManager:
    """Serializes and persists conservative Firecrawl credit reservations."""

    def __init__(
        self,
        *,
        state_path: pathlib.Path | None = None,
        usage_url: str = DEFAULT_CREDIT_USAGE_URL,
        timeout_seconds: float = 15.0,
    ) -> None:
        if state_path is None:
            codex_home = os.environ.get("CODEX_HOME")
            root = (
                pathlib.Path(codex_home).expanduser()
                if codex_home
                else pathlib.Path("~/.codex").expanduser()
            )
            state_path = root / "state" / STATE_FILENAME
        self.state_path = state_path
        self.lock_path = state_path.with_name(state_path.name + ".lock")
        self.usage_url = usage_url
        self.timeout_seconds = timeout_seconds

    def status(self) -> dict[str, Any]:
        return self._update(reservation=0)

    def reserve(self, credits: int) -> dict[str, Any]:
        if isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0:
            raise ValueError("reservation must be a positive integer")
        return self._update(reservation=credits)

    def _ensure_state_directory(self) -> None:
        parent = self.state_path.parent
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise _unavailable("Unable to create the Firecrawl budget state directory.") from exc
        try:
            if parent.is_symlink() or not parent.is_dir():
                raise _unavailable("The Firecrawl budget state directory is not secure.")
        except OSError as exc:
            raise _unavailable("Unable to inspect the Firecrawl budget state directory.") from exc

    def _open_lock(self) -> int:
        if self.lock_path.is_symlink():
            raise _unavailable("The Firecrawl budget lock must not be a symlink.")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise _unavailable("Unable to open the Firecrawl budget lock.") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise _unavailable("The Firecrawl budget lock is not a regular file.")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise _unavailable("The Firecrawl budget lock must have mode 600.")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise _unavailable("The Firecrawl budget lock has an unexpected owner.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as exc:
                raise _unavailable("Unable to acquire the Firecrawl budget lock.") from exc
            return fd
        except ProxyFailure:
            os.close(fd)
            raise
        except OSError as exc:
            os.close(fd)
            raise _unavailable("Unable to inspect the Firecrawl budget lock.") from exc

    def _read_state(self) -> dict[str, Any] | None:
        if self.state_path.is_symlink():
            raise _unavailable("The Firecrawl budget state must not be a symlink.")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.state_path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _unavailable("Unable to open the Firecrawl budget state.") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise _unavailable("The Firecrawl budget state is not a regular file.")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise _unavailable("The Firecrawl budget state must have mode 600.")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise _unavailable("The Firecrawl budget state has an unexpected owner.")
            if info.st_size > MAX_STATE_BYTES:
                raise _unavailable("The Firecrawl budget state is oversized.")
            raw = os.read(fd, MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise _unavailable("The Firecrawl budget state is oversized.")
        finally:
            os.close(fd)
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _unavailable("The Firecrawl budget state is malformed.") from exc
        self._validate_state(state)
        return state

    @staticmethod
    def _validate_state(state: Any) -> None:
        if not isinstance(state, dict):
            raise _unavailable("The Firecrawl budget state is malformed.")
        expected_fields = {
            "version",
            "capCredits",
            "countedCredits",
            "accountPlanCredits",
            "accountRemainingCredits",
            "billingPeriodStart",
            "billingPeriodEnd",
            "updatedAt",
        }
        if set(state) != expected_fields:
            raise _unavailable("The Firecrawl budget state has unexpected fields.")
        if state.get("version") != STATE_VERSION:
            raise _unavailable("The Firecrawl budget state has an unsupported version.")
        if state.get("capCredits") != BUDGET_CAP_CREDITS:
            raise _unavailable("The Firecrawl budget state has an unexpected cap.")
        for field in (
            "countedCredits",
            "accountPlanCredits",
            "accountRemainingCredits",
        ):
            value = state.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > MAX_CREDIT_VALUE
            ):
                raise _unavailable("The Firecrawl budget state is malformed.")
        expected_remaining = max(
            0, state["accountPlanCredits"] - state["countedCredits"]
        )
        if state["accountRemainingCredits"] != expected_remaining:
            raise _unavailable(
                "The Firecrawl budget state has inconsistent account credits."
            )
        start = _parse_timestamp(state.get("billingPeriodStart"), "billingPeriodStart")
        end = _parse_timestamp(state.get("billingPeriodEnd"), "billingPeriodEnd")
        if end <= start:
            raise _unavailable("The Firecrawl budget state has an invalid billing period.")
        _parse_timestamp(state.get("updatedAt"), "updatedAt")

    def _fetch_usage(self) -> UsageSnapshot:
        credential = os.environ.get(FIRECRAWL_CREDENTIAL_ENV)
        if not credential:
            raise _unavailable("The Firecrawl API credential is unavailable.")
        request = urllib.request.Request(
            self.usage_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {credential}",
                "User-Agent": "codex-toolbox-firecrawl-budget/1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read(MAX_USAGE_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise _unavailable("Firecrawl credit usage is unavailable.") from exc
        if len(raw) > MAX_USAGE_RESPONSE_BYTES:
            raise _unavailable("Firecrawl credit usage returned an oversized response.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _unavailable("Firecrawl credit usage returned malformed JSON.") from exc
        return _extract_usage(payload)

    @staticmethod
    def _reconcile(
        state: dict[str, Any] | None, usage: UsageSnapshot
    ) -> int:
        if state is None:
            return usage.spent_credits
        state_start = _parse_timestamp(
            state["billingPeriodStart"], "billingPeriodStart"
        )
        state_end = _parse_timestamp(state["billingPeriodEnd"], "billingPeriodEnd")
        if usage.start_time < state_start:
            raise _unavailable("Firecrawl billing period moved backwards.")
        if usage.start_time > state_start:
            return usage.spent_credits
        if usage.end_time < state_end:
            raise _unavailable("Firecrawl billing period end moved backwards.")
        return max(state["countedCredits"], usage.spent_credits)

    def _write_state(self, state: Mapping[str, Any]) -> None:
        if self.state_path.is_symlink():
            raise _unavailable("The Firecrawl budget state must not be a symlink.")
        encoded = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if len(encoded) > MAX_STATE_BYTES:
            raise _unavailable("The Firecrawl budget state is oversized.")
        temporary_path: str | None = None
        try:
            fd, temporary_path = tempfile.mkstemp(
                prefix=".firecrawl-budget.", dir=self.state_path.parent
            )
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self.state_path)
                temporary_path = None
                directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise
        except ProxyFailure:
            raise
        except OSError as exc:
            raise _unavailable("Unable to persist the Firecrawl budget state.") from exc
        finally:
            if temporary_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temporary_path)

    @staticmethod
    def _state_document(usage: UsageSnapshot, counted: int) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "capCredits": BUDGET_CAP_CREDITS,
            "countedCredits": counted,
            "accountPlanCredits": usage.plan_credits,
            "accountRemainingCredits": max(0, usage.plan_credits - counted),
            "billingPeriodStart": usage.billing_period_start,
            "billingPeriodEnd": usage.billing_period_end,
            "updatedAt": dt.datetime.now(dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def _update(self, reservation: int) -> dict[str, Any]:
        self._ensure_state_directory()
        lock_fd = self._open_lock()
        try:
            state = self._read_state()
            usage = self._fetch_usage()
            counted = self._reconcile(state, usage)
            account_remaining = max(0, usage.plan_credits - counted)
            if reservation:
                if counted + reservation > BUDGET_CAP_CREDITS:
                    self._write_state(self._state_document(usage, counted))
                    raise ProxyFailure(
                        ERROR_BUDGET_EXHAUSTED,
                        "The fixed 900-credit Firecrawl billing-period cap would be exceeded.",
                    )
                if account_remaining < reservation:
                    self._write_state(self._state_document(usage, counted))
                    raise ProxyFailure(
                        ERROR_BUDGET_EXHAUSTED,
                        "The Firecrawl account has insufficient remaining credits.",
                    )
                counted += reservation
                account_remaining -= reservation

            durable = self._state_document(usage, counted)
            self._write_state(durable)
            return {
                "capCredits": BUDGET_CAP_CREDITS,
                "countedCredits": counted,
                "remainingAllowanceCredits": max(
                    0, BUDGET_CAP_CREDITS - counted
                ),
                "accountRemainingCredits": account_remaining,
                "billingPeriodStart": usage.billing_period_start,
                "billingPeriodEnd": usage.billing_period_end,
                "allowedTools": sorted(ALLOWED_TOOLS),
            }
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def normalize_search_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise _not_bounded("Search arguments must be an object.")
    allowed = {"query", "limit", "sources"}
    unsupported = sorted(set(arguments) - allowed)
    if unsupported:
        raise _not_bounded(
            "Search parameters are not bounded: " + ", ".join(unsupported)
        )
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 4096:
        raise _not_bounded("Search requires a non-empty query of at most 4096 characters.")
    limit = arguments.get("limit", 5)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise _not_bounded("Search limit must be an integer from 1 through 5.")
    sources = arguments.get("sources", [{"type": "web"}])
    if sources != [{"type": "web"}]:
        raise _not_bounded("Search requires exactly one web source.")
    return {"query": query, "limit": limit, "sources": [{"type": "web"}]}


def _is_public_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 8192:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        return False
    if hostname.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        import ipaddress

        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def normalize_scrape_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise _not_bounded("Scrape arguments must be an object.")
    allowed = {
        "url",
        "formats",
        "proxy",
        "parsers",
        "onlyMainContent",
        "mobile",
        "storeInCache",
    }
    unsupported = sorted(set(arguments) - allowed)
    if unsupported:
        raise _not_bounded(
            "Scrape parameters are not bounded: " + ", ".join(unsupported)
        )
    url = arguments.get("url")
    if not _is_public_http_url(url):
        raise _not_bounded("Scrape requires a public HTTP or HTTPS URL.")
    if urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
        raise _not_bounded("Scrape supports public HTML pages, not PDF documents.")
    formats = arguments.get("formats", ["markdown"])
    if formats != ["markdown"]:
        raise _not_bounded("Scrape output must be Markdown only.")
    proxy = arguments.get("proxy", "basic")
    if proxy != "basic":
        raise _not_bounded("Scrape requires the basic proxy.")
    parsers = arguments.get("parsers", [])
    if parsers != []:
        raise _not_bounded("Scrape parsers must be empty.")
    normalized = {
        "url": url,
        "formats": ["markdown"],
        "proxy": "basic",
        "parsers": [],
    }
    for name in ("onlyMainContent", "mobile", "storeInCache"):
        if name in arguments:
            value = arguments[name]
            if not isinstance(value, bool):
                raise _not_bounded(f"Scrape {name} must be a boolean.")
            normalized[name] = value
    return normalized


def _search_tool_definition() -> dict[str, Any]:
    return {
        "name": SEARCH_TOOL_NAME,
        "description": "Search one public web source with a maximum of five results (2-credit reservation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4096},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                "sources": {
                    "type": "array",
                    "const": [{"type": "web"}],
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def _scrape_tool_definition() -> dict[str, Any]:
    return {
        "name": SCRAPE_TOOL_NAME,
        "description": "Scrape one public HTML page as Markdown with the basic proxy (1-credit reservation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1, "maxLength": 8192},
                "formats": {"type": "array", "const": ["markdown"]},
                "proxy": {"type": "string", "const": "basic"},
                "parsers": {"type": "array", "maxItems": 0},
                "onlyMainContent": {"type": "boolean"},
                "mobile": {"type": "boolean"},
                "storeInCache": {"type": "boolean"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    }


def _status_tool_definition() -> dict[str, Any]:
    return {
        "name": STATUS_TOOL_NAME,
        "description": "Read and reconcile the fixed Firecrawl billing-period budget without spending credits.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }


SAFE_TOOL_DEFINITIONS = {
    SEARCH_TOOL_NAME: _search_tool_definition(),
    SCRAPE_TOOL_NAME: _scrape_tool_definition(),
    STATUS_TOOL_NAME: _status_tool_definition(),
}

BOUNDED_SERVER_INSTRUCTIONS = (
    "This Firecrawl server is a bounded, metered surface. Use only "
    "firecrawl_search for one web source with at most five results, "
    "firecrawl_scrape for one public HTML page as Markdown through the basic "
    "proxy, and firecrawl_budget_status for read-only budget status. All other "
    "Firecrawl tools and costly options are unavailable."
)


def sanitize_initialize_result(message: dict[str, Any]) -> dict[str, Any]:
    result = message.get("result")
    if not isinstance(result, dict):
        return message
    sanitized = dict(message)
    sanitized_result = dict(result)
    sanitized_result["instructions"] = BOUNDED_SERVER_INSTRUCTIONS
    sanitized["result"] = sanitized_result
    return sanitized


def filter_tool_list(message: dict[str, Any]) -> dict[str, Any]:
    result = message.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        return message
    available = {
        tool.get("name")
        for tool in result["tools"]
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    tools = [
        SAFE_TOOL_DEFINITIONS[name]
        for name in (SEARCH_TOOL_NAME, SCRAPE_TOOL_NAME)
        if name in available
    ]
    tools.append(SAFE_TOOL_DEFINITIONS[STATUS_TOOL_NAME])
    filtered = dict(message)
    filtered_result = dict(result)
    filtered_result["tools"] = tools
    filtered["result"] = filtered_result
    return filtered


def _failure_result(request_id: Any, failure: ProxyFailure) -> dict[str, Any]:
    payload = {"code": failure.code, "message": failure.message}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                }
            ],
            "structuredContent": payload,
            "isError": True,
        },
    }


def _status_result(request_id: Any, status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(status, sort_keys=True, separators=(",", ":")),
                }
            ],
            "structuredContent": dict(status),
            "isError": False,
        },
    }


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _message_id_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class StdioProxy:
    def __init__(
        self,
        child_command: Sequence[str],
        budget: BudgetManager,
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        stderr: BinaryIO | None = None,
    ) -> None:
        if not child_command:
            raise ValueError("child command is required")
        self.child_command = list(child_command)
        self.budget = budget
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self.stderr = stderr or sys.stderr.buffer
        self._write_lock = threading.Lock()
        self._pending_tool_lists: set[str] = set()
        self._pending_initializations: set[str] = set()
        self._pending_lock = threading.Lock()

    def _write_client(self, message: Mapping[str, Any]) -> None:
        encoded = (
            json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        with self._write_lock:
            self.stdout.write(encoded)
            self.stdout.flush()

    @staticmethod
    def _write_child(child: subprocess.Popen[bytes], message: Mapping[str, Any]) -> None:
        if child.stdin is None:
            raise BrokenPipeError("child stdin is unavailable")
        encoded = (
            json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        child.stdin.write(encoded)
        child.stdin.flush()

    def _child_stdout_loop(self, child: subprocess.Popen[bytes]) -> None:
        assert child.stdout is not None
        for raw in iter(child.stdout.readline, b""):
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.stderr.write(b"Firecrawl child emitted invalid JSON-RPC.\n")
                self.stderr.flush()
                continue
            if isinstance(message, dict) and "id" in message:
                key = _message_id_key(message["id"])
                with self._pending_lock:
                    is_tool_list = key in self._pending_tool_lists
                    if is_tool_list:
                        self._pending_tool_lists.remove(key)
                    is_initialization = key in self._pending_initializations
                    if is_initialization:
                        self._pending_initializations.remove(key)
                if is_tool_list:
                    message = filter_tool_list(message)
                if is_initialization:
                    message = sanitize_initialize_result(message)
            if isinstance(message, dict):
                self._write_client(message)

    def _child_stderr_loop(self, child: subprocess.Popen[bytes]) -> None:
        assert child.stderr is not None
        for chunk in iter(lambda: child.stderr.read(8192), b""):
            self.stderr.write(chunk)
            self.stderr.flush()

    def _handle_tool_call(
        self, child: subprocess.Popen[bytes], message: dict[str, Any]
    ) -> None:
        request_id = message.get("id")
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            self._write_client(
                _failure_result(
                    request_id, _not_bounded("Tool call parameters are malformed.")
                )
            )
            return
        name = params["name"]
        arguments = params.get("arguments", {})
        try:
            if name == STATUS_TOOL_NAME:
                if arguments != {}:
                    raise _not_bounded("Budget status does not accept arguments.")
                self._write_client(_status_result(request_id, self.budget.status()))
                return
            if name == SEARCH_TOOL_NAME:
                normalized = normalize_search_arguments(arguments)
                self.budget.reserve(SEARCH_RESERVATION_CREDITS)
            elif name == SCRAPE_TOOL_NAME:
                normalized = normalize_scrape_arguments(arguments)
                self.budget.reserve(SCRAPE_RESERVATION_CREDITS)
            else:
                raise _not_bounded(f"Firecrawl tool {name!r} is not exposed.")
        except ProxyFailure as failure:
            if "id" in message:
                self._write_client(_failure_result(request_id, failure))
            return
        forwarded = dict(message)
        forwarded_params = dict(params)
        forwarded_params["arguments"] = normalized
        forwarded["params"] = forwarded_params
        self._write_child(child, forwarded)

    def _handle_client_line(
        self, child: subprocess.Popen[bytes], raw: bytes
    ) -> None:
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_client(_jsonrpc_error(None, -32700, "Parse error"))
            return
        if not isinstance(message, dict):
            self._write_client(
                _jsonrpc_error(None, -32600, "JSON-RPC batches are not supported")
            )
            return
        method = message.get("method")
        if method == "initialize" and "id" in message:
            with self._pending_lock:
                self._pending_initializations.add(_message_id_key(message["id"]))
            self._write_child(child, message)
        elif method == "tools/list" and "id" in message:
            with self._pending_lock:
                self._pending_tool_lists.add(_message_id_key(message["id"]))
            self._write_child(child, message)
        elif method == "tools/call":
            self._handle_tool_call(child, message)
        else:
            self._write_child(child, message)

    def run(self) -> int:
        child = subprocess.Popen(
            self.child_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        stdout_thread = threading.Thread(
            target=self._child_stdout_loop, args=(child,), daemon=True
        )
        stderr_thread = threading.Thread(
            target=self._child_stderr_loop, args=(child,), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            stdin_fd = self.stdin.fileno()
            pending = bytearray()
            while child.poll() is None:
                readable, _, _ = select.select([stdin_fd], [], [], 0.1)
                if not readable:
                    continue
                chunk = os.read(stdin_fd, 8192)
                if not chunk:
                    if pending:
                        self._handle_client_line(child, bytes(pending))
                    break
                pending.extend(chunk)
                while True:
                    newline = pending.find(b"\n")
                    if newline < 0:
                        break
                    raw = bytes(pending[:newline])
                    del pending[: newline + 1]
                    if raw.strip():
                        self._handle_client_line(child, raw)
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            if child.stdin is not None:
                with contextlib.suppress(OSError):
                    child.stdin.close()
            if child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        child.wait(timeout=5)
                if child.poll() is None:
                    child.kill()
                    child.wait()
            else:
                child.wait()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
        return child.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("serve", "status"):
        subparsers.add_parser(name)
    serve = subparsers.choices["serve"]
    serve.add_argument("child", nargs=argparse.REMAINDER)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    usage_url: str = DEFAULT_CREDIT_USAGE_URL,
) -> int:
    args = _parser().parse_args(argv)
    budget = BudgetManager(usage_url=usage_url)
    if args.operation == "status":
        try:
            print(json.dumps(budget.status(), indent=2, sort_keys=True))
            return 0
        except ProxyFailure as failure:
            print(
                json.dumps(
                    {"code": failure.code, "message": failure.message},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1
    child = list(args.child)
    if child and child[0] == "--":
        child = child[1:]
    if not child:
        print("A child MCP command is required.", file=sys.stderr)
        return 2
    return StdioProxy(child, budget).run()


if __name__ == "__main__":
    raise SystemExit(main())
