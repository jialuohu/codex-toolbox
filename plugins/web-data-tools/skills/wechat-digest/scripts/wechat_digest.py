#!/usr/bin/env python3
"""Small, durable local state helper for the BestBlogs WeChat digest skill."""

import argparse
import errno
import fcntl
import hashlib
import http.client
import json
import os
import re
import secrets
import tempfile
import time
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ supplies zoneinfo
    ZoneInfo = None


API_ORIGIN = "https://api.bestblogs.dev/openapi/v2"
LEGACY_STATE_VERSION = 1
PREVIOUS_STATE_VERSION = 2
STATE_VERSION = 3
MAX_BODY_BYTES = 1_000_000
BODY_DAILY_LIMIT = 35
TOTAL_DAILY_LIMIT = 50
MAX_RECENT = 500
MAX_TOMBSTONES = 5000
MAX_FEED_PAGES = 14
DEFAULT_PAGE_SIZE = 100
CLAIM_LEASE_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SAFE_REASON = re.compile(r"^[A-Z0-9][A-Z0-9_:-]{0,63}$")
API_KEY = re.compile(r"^bb_[0-9A-Fa-f]{32}$")
CLAIM_TOKEN = re.compile(r"^[0-9a-f]{32}$")
CANONICAL_DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
PENDING_FIELDS = frozenset((
    "identity", "resource_id", "source_id", "source_name", "title", "url",
    "published_at", "attempts", "last_failure_reason", "claim_id", "claim_expires_at",
    "claim_fetch_started",
))
STATE_FIELDS = frozenset((
    "version", "sources", "pending", "body_budget", "total_budget",
    "last_successful_scan", "api_calls", "warnings", "next_scan_seq",
    "last_applied_scan_generation", "ack_tombstones", "scan_health",
))


class APIError(RuntimeError):
    """A safe API error: its text never includes authentication material."""


class StateError(RuntimeError):
    pass


class BodyBudgetExhausted(StateError):
    pass


class TotalBudgetExhausted(StateError):
    pass


class ClaimUnavailable(StateError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_id(value):
    return isinstance(value, str) and bool(SAFE_ID.fullmatch(value))


def validate_envelope(payload):
    if not isinstance(payload, dict) or set(("success", "code", "message", "requestId", "data")) - set(payload):
        raise APIError("invalid BestBlogs response envelope")
    if payload["success"] is not True:
        raise APIError("BestBlogs request was not successful")
    if (payload["code"] is not None and not isinstance(payload["code"], (int, str))) or \
            (payload["message"] is not None and not isinstance(payload["message"], str)) or \
            not isinstance(payload["requestId"], str):
        raise APIError("invalid BestBlogs response envelope")
    return payload["data"]


class BestBlogsClient:
    """GET-only client deliberately constrained to the fixed BestBlogs origin."""

    def __init__(self, api_key, origin=API_ORIGIN, timeout=20):
        if not isinstance(api_key, str) or not API_KEY.fullmatch(api_key):
            raise ValueError("invalid BestBlogs API key")
        if origin != API_ORIGIN:
            raise ValueError("BestBlogs origin is fixed")
        self.api_key = api_key
        self.origin = origin
        self.timeout = timeout
        self.calls = {}
        self._opener = build_opener(_NoRedirect())

    def get(self, path, query=None, before_attempt=None):
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must be an origin-relative path")
        if before_attempt is not None and not callable(before_attempt):
            raise ValueError("before_attempt must be callable")
        url = self.origin + path
        if query:
            url += "?" + urlencode(query)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != urlparse(self.origin).netloc:
            raise ValueError("request origin is not allowed")
        request = Request(url, headers={"X-API-KEY": self.api_key, "Accept": "application/json"}, method="GET")
        for attempt in range(2):
            if before_attempt is not None:
                before_attempt()
            self.calls[path] = self.calls.get(path, 0) + 1
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    if response.geturl() != url:
                        raise APIError("redirected response rejected")
                    if not 200 <= response.getcode() < 300:
                        raise APIError("BestBlogs HTTP request was not successful")
                    body = response.read(MAX_BODY_BYTES + 1)
                    if len(body) > MAX_BODY_BYTES:
                        raise APIError("BestBlogs response exceeds size limit")
                    try:
                        return validate_envelope(json.loads(body.decode("utf-8")))
                    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
                        raise APIError("invalid JSON response from BestBlogs") from error
            except HTTPError as error:
                if error.code == 429 and attempt == 0:
                    retry_after = error.headers.get("Retry-After", "1")
                    try:
                        delay = min(5, max(0, int(retry_after)))
                    except ValueError:
                        delay = 1
                    time.sleep(delay)
                    continue
                raise APIError("BestBlogs HTTP request failed") from error
            except (URLError, http.client.HTTPException, OSError) as error:
                raise APIError("BestBlogs network request failed") from error
        raise APIError("BestBlogs rate limit retry exhausted")

    def me(self, before_attempt=None):
        return self.get("/me", before_attempt=before_attempt)

    def subscription_page(self, page, page_size, before_attempt=None):
        return self.get("/me/feeds/subscriptions", {"page": page, "pageSize": page_size, "timeFilter": "week"},
                        before_attempt=before_attempt)

    def markdown(self, resource_id, before_attempt=None):
        data = self.get("/resources/%s/markdown" % resource_id, before_attempt=before_attempt)
        if isinstance(data, dict):
            data = data.get("markdown", data.get("content"))
        return data


def canonical_wechat_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != "mp.weixin.qq.com" or parsed.username is not None or parsed.password is not None:
        return None
    try:
        if parsed.port is not None or parsed.netloc.lower() != "mp.weixin.qq.com":
            return None
    except ValueError:
        return None
    if parsed.params:
        return None
    pairs = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"from", "scene", "src"}]
    if parsed.path == "/s":
        for required in ("__biz", "mid", "idx", "sn"):
            values = [item for key, item in pairs if key == required]
            if len(values) != 1 or not values[0]:
                return None
    elif not re.fullmatch(r"/s/[A-Za-z0-9_-]+", parsed.path):
        return None
    return urlunparse(("https", "mp.weixin.qq.com", parsed.path, "", urlencode(sorted(pairs)), ""))


def _publication_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return None
        try:
            return datetime.fromtimestamp(value / (1000 if abs(value) > 10_000_000_000 else 1), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return _publication_time(int(value))
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
        except (OverflowError, ValueError):
            return None
    return None


def parse_article(raw):
    if not isinstance(raw, dict):
        return None
    kind = raw.get("resourceType", raw.get("type", "article"))
    if isinstance(kind, str) and kind.lower() not in ("article", "wechat", "weixin"):
        return None
    source_object = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    source = raw.get("sourceId") or source_object.get("id")
    if not _safe_id(source):
        return None
    resource_id = raw.get("id") or raw.get("resourceId")
    if resource_id is not None and not _safe_id(resource_id):
        return None
    url = canonical_wechat_url(raw.get("url") or raw.get("link") or raw.get("originalUrl"))
    if not url:
        return None
    identity = "resource:" + resource_id if resource_id else "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    timestamp = None
    supplied_time = False
    for field in ("publishTimeStamp", "publishTime", "publishDateTimeStr", "publishDateStr"):
        value = raw.get(field)
        supplied_time = supplied_time or value is not None
        timestamp = _publication_time(value)
        if timestamp:
            break
    if supplied_time and not timestamp:
        return None
    return {"identity": identity, "resource_id": resource_id, "source_id": source,
            "source_name": str(raw.get("sourceName") or source_object.get("name") or source)[:200],
            "title": str(raw.get("title") or "Untitled")[:500], "url": url,
            "published_at": timestamp or "", "attempts": 0}


def new_state():
    return {"version": STATE_VERSION, "sources": {}, "pending": {},
            "body_budget": {"day": "", "count": 0}, "total_budget": {"day": "", "count": 0},
            "last_successful_scan": None, "api_calls": {}, "warnings": [],
            "next_scan_seq": 0, "last_applied_scan_generation": 0, "ack_tombstones": {},
            "scan_health": {"pages": 0, "records": 0, "complete": False, "skipped": {"invalid_or_non_wechat": 0}}}


def _validate_day_budget(budget, limit):
    if not isinstance(budget, dict) or set(budget) != {"day", "count"} or \
            not isinstance(budget.get("day"), str) or not isinstance(budget.get("count"), int) or \
            isinstance(budget.get("count"), bool) or not 0 <= budget["count"] <= limit:
        raise StateError("unsupported or malformed state schema")
    day = budget["day"]
    if not day:
        if budget["count"] != 0:
            raise StateError("unsupported or malformed state schema")
        return
    if not CANONICAL_DAY.fullmatch(day):
        raise StateError("unsupported or malformed state schema")
    try:
        if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
            raise ValueError
    except ValueError as error:
        raise StateError("unsupported or malformed state schema") from error


def _parse_claim_expiry(value):
    if not isinstance(value, str) or len(value) > 32 or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _valid_health(health, allow_empty=False, include_pages=False):
    if allow_empty and health == {}:
        return True
    expected = {"records", "complete", "skipped"} | ({"pages"} if include_pages else set())
    return isinstance(health, dict) and set(health) == expected and \
        isinstance(health.get("records"), int) and not isinstance(health.get("records"), bool) and health["records"] >= 0 and \
        isinstance(health.get("complete"), bool) and isinstance(health.get("skipped"), dict) and \
        set(health["skipped"]) == {"invalid_or_non_wechat"} and \
        isinstance(health["skipped"].get("invalid_or_non_wechat"), int) and \
        not isinstance(health["skipped"].get("invalid_or_non_wechat"), bool) and \
        health["skipped"]["invalid_or_non_wechat"] >= 0 and \
        (not include_pages or isinstance(health.get("pages"), int) and not isinstance(health.get("pages"), bool) and
         0 <= health["pages"] <= MAX_FEED_PAGES)


def _valid_identity(identity):
    if not isinstance(identity, str) or len(identity) > 200:
        return False
    if identity.startswith("resource:"):
        return _safe_id(identity[len("resource:"):])
    return bool(re.fullmatch(r"url:[0-9a-f]{64}", identity))


def _validate_state(state):
    if not isinstance(state, dict) or set(state) != STATE_FIELDS or state.get("version") != STATE_VERSION:
        raise StateError("unsupported or malformed state schema")
    if not isinstance(state["sources"], dict) or not isinstance(state["pending"], dict) or \
            not isinstance(state["api_calls"], dict) or not isinstance(state["warnings"], list) or \
            not isinstance(state["ack_tombstones"], dict) or len(state["ack_tombstones"]) > MAX_TOMBSTONES:
        raise StateError("unsupported or malformed state schema")
    _validate_day_budget(state["body_budget"], BODY_DAILY_LIMIT)
    _validate_day_budget(state["total_budget"], TOTAL_DAILY_LIMIT)
    if state["body_budget"]["day"] and state["body_budget"]["day"] == state["total_budget"]["day"] and \
            state["body_budget"]["count"] > state["total_budget"]["count"]:
        raise StateError("unsupported or malformed state schema")
    if state.get("last_successful_scan") is not None and not isinstance(state["last_successful_scan"], str):
        raise StateError("unsupported or malformed state schema")
    for sequence in ("next_scan_seq", "last_applied_scan_generation"):
        if not isinstance(state[sequence], int) or isinstance(state[sequence], bool) or state[sequence] < 0:
            raise StateError("unsupported or malformed state schema")
    if state["last_applied_scan_generation"] > state["next_scan_seq"]:
        raise StateError("unsupported or malformed state schema")
    if any(not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0
           for key, value in state["api_calls"].items()) or \
            any(not isinstance(item, str) for item in state["warnings"]):
        raise StateError("unsupported or malformed state schema")
    health = state["scan_health"]
    if not _valid_health(health, include_pages=True):
        raise StateError("unsupported or malformed state schema")
    for source_id, source in state["sources"].items():
        if not _safe_id(source_id) or not isinstance(source, dict) or \
                set(source) != {"id", "name", "initialized", "recent", "health"} or \
                source.get("id") != source_id or not isinstance(source.get("name"), str) or \
                not isinstance(source.get("initialized"), bool):
            raise StateError("unsupported or malformed state schema")
        if not isinstance(source.get("recent"), dict) or len(source["recent"]) > MAX_RECENT or not isinstance(source.get("health"), dict):
            raise StateError("unsupported or malformed state schema")
        if any(not _valid_identity(identity) or value is not True for identity, value in source["recent"].items()):
            raise StateError("unsupported or malformed state schema")
        if not _valid_health(source["health"], allow_empty=True):
            raise StateError("unsupported or malformed state schema")
    for identity, entry in state["pending"].items():
        required = {"identity", "resource_id", "source_id", "source_name", "title", "url", "published_at", "attempts"}
        if not _valid_identity(identity) or not isinstance(entry, dict) or not required.issubset(entry) or \
                not set(entry).issubset(PENDING_FIELDS) or entry.get("identity") != identity or \
                not _safe_id(entry.get("source_id")) or canonical_wechat_url(entry.get("url")) != entry.get("url") or \
                entry.get("resource_id") is not None and not _safe_id(entry.get("resource_id")) or \
                not isinstance(entry.get("attempts"), int) or isinstance(entry.get("attempts"), bool) or not 0 <= entry["attempts"] <= 3 or \
                not isinstance(entry.get("title"), str) or not isinstance(entry.get("source_name"), str) or not isinstance(entry.get("published_at"), str):
            raise StateError("unsupported or malformed state schema")
        if entry.get("resource_id") and identity != "resource:" + entry["resource_id"]:
            raise StateError("unsupported or malformed state schema")
        if not entry.get("resource_id") and identity != "url:" + hashlib.sha256(entry["url"].encode("utf-8")).hexdigest():
            raise StateError("unsupported or malformed state schema")
        if entry.get("last_failure_reason") is not None and (not isinstance(entry["last_failure_reason"], str) or not SAFE_REASON.fullmatch(entry["last_failure_reason"])):
            raise StateError("unsupported or malformed state schema")
        has_claim_id = "claim_id" in entry
        has_claim_expiry = "claim_expires_at" in entry
        if has_claim_id != has_claim_expiry or has_claim_id and \
                (not isinstance(entry["claim_id"], str) or not CLAIM_TOKEN.fullmatch(entry["claim_id"]) or
                 _parse_claim_expiry(entry["claim_expires_at"]) is None):
            raise StateError("unsupported or malformed state schema")
        if "claim_fetch_started" in entry and (not has_claim_id or entry["claim_fetch_started"] is not True):
            raise StateError("unsupported or malformed state schema")
    for identity, tombstone in state["ack_tombstones"].items():
        if not _valid_identity(identity) or not isinstance(tombstone, dict) or \
                set(tombstone) != {"source_id", "ack_after_scan_seq"} or \
                not _safe_id(tombstone.get("source_id")) or \
                not isinstance(tombstone.get("ack_after_scan_seq"), int) or \
                isinstance(tombstone.get("ack_after_scan_seq"), bool) or \
                not 0 <= tombstone["ack_after_scan_seq"] <= state["next_scan_seq"]:
            raise StateError("unsupported or malformed state schema")
    return state


def default_state_path():
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return Path(home) / "state" / "wechat-digest.json"


def _migrate_state(state):
    if not isinstance(state, dict):
        raise StateError("unsupported or malformed state schema")
    version = state.get("version")
    if version == LEGACY_STATE_VERSION:
        expected = {"version", "sources", "pending", "body_budget", "last_successful_scan",
                    "api_calls", "warnings", "scan_health"}
        if set(state) != expected:
            raise StateError("unsupported or malformed state schema")
        migrated = dict(state)
        migrated["total_budget"] = {"day": _beijing_day(), "count": TOTAL_DAILY_LIMIT}
        next_sequence = 0
    elif version == PREVIOUS_STATE_VERSION:
        expected = {"version", "sources", "pending", "body_budget", "total_budget",
                    "last_successful_scan", "api_calls", "warnings", "scan_generation", "scan_health"}
        if set(state) != expected:
            raise StateError("unsupported or malformed state schema")
        migrated = dict(state)
        next_sequence = migrated.pop("scan_generation")
    else:
        raise StateError("unsupported or malformed state schema")
    migrated["version"] = STATE_VERSION
    migrated["next_scan_seq"] = next_sequence
    migrated["last_applied_scan_generation"] = 0
    migrated["ack_tombstones"] = {}
    return _validate_state(migrated)


def _read_state(path=None):
    path = Path(path or default_state_path())
    if not path.exists():
        return new_state(), False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RecursionError) as error:
        raise StateError("state cannot be read safely") from error
    if isinstance(state, dict) and state.get("version") in (LEGACY_STATE_VERSION, PREVIOUS_STATE_VERSION):
        return _migrate_state(state), True
    return _validate_state(state), False


def load_state(path=None):
    return _read_state(path)[0]


def _load_locked_state(path):
    state, migrated = _read_state(path)
    if migrated:
        save_state(path, state)
    return state


@contextmanager
def state_lock(path, timeout=5.0):
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("lock timeout must be a bounded non-negative number")
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    descriptor = None
    acquired = False
    try:
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(lock_path, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            deadline = time.monotonic() + float(timeout)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StateError("state is busy; retry later")
                    time.sleep(min(0.05, remaining))
        except OSError as error:
            raise StateError("state lock is unavailable") from error
        yield
    finally:
        if descriptor is not None:
            if acquired:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                os.close(descriptor)
            except OSError:
                pass


def save_state(path, state):
    _validate_state(state)
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            try:
                os.fsync(directory)
            except OSError as error:
                if error.errno not in (errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)):
                    raise
        finally:
            os.close(directory)
    except RecursionError as error:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise StateError("state cannot be serialized safely") from error
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def configure_sources(state, source_ids):
    if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 10 or len(set(source_ids)) != len(source_ids) or not all(_safe_id(item) for item in source_ids):
        raise ValueError("choose between 1 and 10 unique safe source IDs")
    old = state["sources"]
    state["sources"] = {source: old.get(source, {"id": source, "name": source, "initialized": False, "recent": {}, "health": {}})
                        for source in source_ids}
    return {"configured_sources": list(state["sources"])}


def _page_items(data):
    if not isinstance(data, dict):
        return [], None, "feed_page_not_object"
    if "dataList" not in data or not isinstance(data["dataList"], list):
        return [], None, "feed_data_list_invalid"
    counters = []
    for name in ("total", "totalCount", "count"):
        if name not in data:
            continue
        value = data[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return data["dataList"], None, "feed_counter_invalid"
        counters.append(value)
    if len(set(counters)) > 1:
        return data["dataList"], None, "feed_counters_conflict"
    return data["dataList"], counters[0] if counters else None, None


def _feed_pages(client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    all_items, warnings, page, expected = [], [], 1, None
    counter_presence = None
    previous_full_page = None
    while page <= MAX_FEED_PAGES:
        data = client.subscription_page(page, page_size, before_attempt=before_attempt)
        items, counter, schema_error = _page_items(data)
        all_items.extend(items)
        if schema_error:
            return all_items, False, warnings + [schema_error], page
        has_counter = counter is not None
        if counter_presence is None:
            counter_presence = has_counter
            expected = counter
        elif counter_presence != has_counter or has_counter and counter != expected:
            return all_items, False, warnings + ["feed_counter_changed"], page
        if expected is not None and len(all_items) > expected:
            return all_items, False, warnings + ["feed_total_less_than_observed"], page
        if previous_full_page is not None and len(items) == page_size and items == previous_full_page:
            return all_items, False, warnings + ["feed_repeated_full_page"], page
        previous_full_page = list(items) if len(items) == page_size else None
        if expected is not None and len(all_items) == expected:
            return all_items, True, warnings, page
        if not items:
            complete = expected is None or len(all_items) == expected
            return all_items, complete, warnings + ([] if complete else ["feed_ended_before_total"]), page
        if len(items) < page_size:
            complete = expected is None or len(all_items) == expected
            return all_items, complete, warnings + ([] if complete else ["feed_shorter_than_total"]), page
        page += 1
    return all_items, False, warnings + ["feed page cap reached"], MAX_FEED_PAGES


def _merge_calls(state, client):
    seen = getattr(client, "_wechat_calls_seen", {})
    for endpoint, count in getattr(client, "calls", {}).items():
        prior = int(seen.get(endpoint, 0))
        state["api_calls"][endpoint] = int(state["api_calls"].get(endpoint, 0)) + max(0, int(count) - prior)
    client._wechat_calls_seen = dict(getattr(client, "calls", {}))


def list_sources(client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    records, complete, warnings, _ = _feed_pages(client, page_size, before_attempt=before_attempt)
    sources = {}
    malformed = 0
    for raw in records:
        article = parse_article(raw)
        if not article:
            malformed += 1
            if isinstance(raw, dict):
                source_object = raw.get("source") if isinstance(raw.get("source"), dict) else {}
                source_id = raw.get("sourceId") or source_object.get("id")
                source_name = raw.get("sourceName") or source_object.get("name") or source_id
                if _safe_id(source_id):
                    sources.setdefault(source_id, {"id": source_id, "name": str(source_name)[:200]})
            continue
        sources.setdefault(article["source_id"], {"id": article["source_id"], "name": article["source_name"]})
    if malformed:
        warnings.append("skipped_malformed_records:%d" % malformed)
    if not complete:
        warnings.append("partial_feed")
    return {"sources": list(sources.values()), "skipped": {"invalid_or_non_wechat": malformed}, "warnings": warnings}


def _remember(source, identity):
    recent = source.setdefault("recent", {})
    recent[identity] = True
    while len(recent) > MAX_RECENT:
        recent.pop(next(iter(recent)))


def _scan_observation(client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    records, complete, warnings, pages = _feed_pages(client, page_size, before_attempt=before_attempt)
    return {"records": records, "complete": complete, "warnings": warnings, "pages": pages}


def _apply_scan_observation(state, observation, generation=None):
    if generation is not None and generation <= state["last_applied_scan_generation"]:
        return {"complete": False, "enqueued": 0, "skipped": {"invalid_or_non_wechat": 0},
                "warnings": ["superseded_scan"], "superseded": True}
    records = observation["records"]
    complete = observation["complete"]
    warnings = list(observation["warnings"])
    pages = observation["pages"]
    selected = state["sources"]
    parsed, malformed = [], 0
    for raw in records:
        article = parse_article(raw)
        if article is None:
            malformed += 1
        elif article["source_id"] in selected:
            parsed.append(article)
    by_source = {source: {} for source in selected}
    for article in parsed:
        by_source[article["source_id"]].setdefault(article["identity"], article)
    if malformed:
        warnings.append("skipped_malformed_records:%d" % malformed)
        complete = False
    for source_id, articles in by_source.items():
        if len(articles) > MAX_RECENT:
            warnings.append("source_snapshot_limit_exceeded:%s:%d" % (source_id, len(articles)))
            complete = False
    if not complete:
        if "partial_feed" not in warnings:
            warnings.append("partial_feed")
        for source_id, source in selected.items():
            source["health"] = {"records": len(by_source[source_id]), "complete": False,
                                "skipped": {"invalid_or_non_wechat": malformed}}
        state["warnings"] = warnings
        state["scan_health"] = {"pages": pages, "records": len(records), "complete": False,
                                "skipped": {"invalid_or_non_wechat": malformed}}
        return {"complete": False, "enqueued": 0,
                "skipped": {"invalid_or_non_wechat": malformed}, "warnings": warnings}

    enqueued = 0
    for source_id, source in selected.items():
        articles = by_source[source_id]
        source["health"] = {"records": len(articles), "complete": True,
                            "skipped": {"invalid_or_non_wechat": malformed}}
        if not source.get("initialized"):
            source["recent"] = {identity: True for identity in articles}
            source["initialized"] = True
            continue
        seen_before = frozenset(source.get("recent", {}))
        pending_before = frozenset(state["pending"])
        tombstones = state["ack_tombstones"]
        for identity, article in articles.items():
            if identity not in seen_before and identity not in pending_before and identity not in tombstones:
                state["pending"][identity] = article
                enqueued += 1
        source["recent"] = {identity: True for identity in articles}
    if generation is not None:
        for identity, tombstone in list(state["ack_tombstones"].items()):
            source_id = tombstone["source_id"]
            if source_id in by_source and generation > tombstone["ack_after_scan_seq"] and identity not in by_source[source_id]:
                del state["ack_tombstones"][identity]
        state["last_applied_scan_generation"] = generation
    state["last_successful_scan"] = datetime.now(timezone.utc).isoformat()
    state["warnings"] = warnings
    state["scan_health"] = {"pages": pages, "records": len(records), "complete": True,
                            "skipped": {"invalid_or_non_wechat": malformed}}
    return {"complete": True, "enqueued": enqueued,
            "skipped": {"invalid_or_non_wechat": malformed}, "warnings": warnings}


def scan(state, client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    observation = _scan_observation(client, page_size, before_attempt=before_attempt)
    result = _apply_scan_observation(state, observation)
    if before_attempt is None:
        _merge_calls(state, client)
    return result


def _utc_now(now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise StateError("timezone-aware time is required")
    return now.astimezone(timezone.utc)


def _claim_active(entry, now=None):
    expiry = _parse_claim_expiry(entry.get("claim_expires_at"))
    return bool(entry.get("claim_id") and expiry and expiry > _utc_now(now))


def _require_claim(entry, claim_id, now=None, require_active=False):
    stored = entry.get("claim_id")
    if stored is None:
        if claim_id is None and not require_active:
            return
        raise ClaimUnavailable("claim is unavailable")
    if not isinstance(claim_id, str) or not CLAIM_TOKEN.fullmatch(claim_id) or not secrets.compare_digest(stored, claim_id):
        raise ClaimUnavailable("claim is unavailable")
    if require_active and not _claim_active(entry, now):
        raise ClaimUnavailable("claim is unavailable")


def pending(state, now=None):
    def order_key(item):
        normalized = _publication_time(item.get("published_at"))
        if not normalized:
            return (0, datetime.min.replace(tzinfo=timezone.utc), item["identity"])
        instant = datetime.fromisoformat(normalized).astimezone(timezone.utc)
        return (1, instant, item["identity"])

    entries = sorted(state["pending"].values(), key=order_key)
    current = _utc_now(now)
    result = {"retryable": [], "claimed": [], "exhausted": []}
    for entry in entries:
        if entry.get("attempts", 0) >= 3:
            result["exhausted"].append(entry)
        elif _claim_active(entry, current):
            result["claimed"].append(entry)
        else:
            result["retryable"].append(entry)
    return result


def _identity_for(state, article_id):
    if article_id in state["pending"]:
        return article_id
    resource_identity = "resource:" + article_id if isinstance(article_id, str) else ""
    if resource_identity in state["pending"]:
        return resource_identity
    return article_id


def claim(state, identity, now=None):
    identity = _identity_for(state, identity)
    entry = state["pending"].get(identity)
    if not entry:
        raise KeyError("unknown pending article")
    if entry.get("attempts", 0) >= 3:
        return {"claim_status": "exhausted"}
    if _claim_active(entry, now):
        return {"claim_status": "already_claimed"}
    issued_at = _utc_now(now)
    claim_id = secrets.token_hex(16)
    expiry = (issued_at + timedelta(seconds=CLAIM_LEASE_SECONDS)).replace(microsecond=0)
    entry["claim_id"] = claim_id
    entry["claim_expires_at"] = expiry.isoformat().replace("+00:00", "Z")
    entry.pop("claim_fetch_started", None)
    return {"claim_id": claim_id, "claim_expires_at": entry["claim_expires_at"]}


def ack(state, identity, claim_id=None):
    identity = _identity_for(state, identity)
    if identity not in state["pending"]:
        raise KeyError("unknown pending article")
    entry = state["pending"][identity]
    _require_claim(entry, claim_id)
    source_id = entry.get("source_id")
    if _safe_id(source_id) and identity not in state.get("ack_tombstones", {}) and \
            len(state.get("ack_tombstones", {})) >= MAX_TOMBSTONES:
        raise StateError("ack tombstone capacity exhausted")
    source = state.get("sources", {}).get(source_id)
    if source is not None:
        _remember(source, identity)
    if _safe_id(source_id):
        state["ack_tombstones"][identity] = {
            "source_id": source_id, "ack_after_scan_seq": state["next_scan_seq"],
        }
    del state["pending"][identity]
    return {"acknowledged": identity}


def fail(state, identity, reason, claim_id=None):
    identity = _identity_for(state, identity)
    if identity not in state["pending"]:
        raise KeyError("unknown pending article")
    if not isinstance(reason, str) or not SAFE_REASON.fullmatch(reason):
        raise ValueError("reason must be a bounded safe code")
    entry = state["pending"][identity]
    _require_claim(entry, claim_id)
    entry["attempts"] = min(3, int(entry.get("attempts", 0)) + 1)
    entry["last_failure_reason"] = reason
    entry.pop("claim_id", None)
    entry.pop("claim_expires_at", None)
    entry.pop("claim_fetch_started", None)
    return {"identity": identity, "attempts": entry["attempts"], "exhausted": entry["attempts"] >= 3}


def _beijing_day(now=None):
    if ZoneInfo is None:
        raise StateError("Beijing timezone support is unavailable")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise StateError("timezone-aware time is required")
    return now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _reserve_api_attempt(state, now=None, body=False):
    day = _beijing_day(now)
    total_budget = state["total_budget"]
    body_budget = state["body_budget"]
    for budget in (total_budget, body_budget):
        if budget.get("day") and budget["day"] > day:
            raise StateError("budget clock rollback detected")
    total_count = 0 if total_budget.get("day") != day else int(total_budget.get("count", 0))
    body_count = 0 if body_budget.get("day") != day else int(body_budget.get("count", 0))
    if total_count >= TOTAL_DAILY_LIMIT:
        raise TotalBudgetExhausted("daily total budget exhausted")
    if body and body_count >= BODY_DAILY_LIMIT:
        raise BodyBudgetExhausted("daily body budget exhausted")
    new_total_count = total_count + 1
    new_body_count = body_count + (1 if body else 0)
    if body_budget.get("day") == day and new_body_count > new_total_count:
        raise StateError("inconsistent daily budgets")
    total_budget.update({"day": day, "count": new_total_count})
    if body:
        body_budget.update({"day": day, "count": new_body_count})


def _reserve_body_attempt(state, now=None):
    _reserve_api_attempt(state, now=now, body=True)


def _durable_reservation(path, endpoint, body=False, now=None, identity=None, resource_id=None, claim_id=None):
    def reserve_attempt():
        with state_lock(path):
            state = _load_locked_state(path)
            if identity is not None:
                entry = state["pending"].get(identity)
                if not entry or entry.get("resource_id") != resource_id or entry.get("claim_fetch_started") is not True:
                    raise ClaimUnavailable("claim is unavailable")
                _require_claim(entry, claim_id, now=now, require_active=True)
            _reserve_api_attempt(state, now=now, body=body)
            state["api_calls"][endpoint] = int(state["api_calls"].get(endpoint, 0)) + 1
            save_state(path, state)
    return reserve_attempt


def markdown(state, client, identity, now=None, reserve_attempt=None):
    identity = _identity_for(state, identity)
    entry = state["pending"].get(identity)
    if not entry:
        return {"fallback_reason": "unknown_or_not_pending"}
    if not entry.get("resource_id"):
        return {"fallback_reason": "missing_resource_id"}
    try:
        _beijing_day(now)
    except StateError:
        return {"fallback_reason": "beijing_timezone_unavailable"}
    durable_reservation = reserve_attempt is not None
    if reserve_attempt is None:
        reserve_attempt = lambda: _reserve_body_attempt(state, now)
    try:
        body = client.markdown(entry["resource_id"], before_attempt=reserve_attempt)
    except ClaimUnavailable:
        return {"claim_status": "claim_lost"}
    except TotalBudgetExhausted:
        if not durable_reservation:
            _merge_calls(state, client)
        return {"fallback_reason": "daily_total_budget_exhausted"}
    except BodyBudgetExhausted:
        if not durable_reservation:
            _merge_calls(state, client)
        return {"fallback_reason": "daily_body_budget_exhausted"}
    except (APIError, ValueError):
        if not durable_reservation:
            _merge_calls(state, client)
        return {"fallback_reason": "bestblogs_markdown_unavailable"}
    if not isinstance(body, str):
        if not durable_reservation:
            _merge_calls(state, client)
        return {"fallback_reason": "bestblogs_markdown_unavailable"}
    if not durable_reservation:
        _merge_calls(state, client)
    return {"markdown": body, "source": "bestblogs"}


def doctor(client, api_key=None, before_attempt=None):
    profile = client.me(before_attempt=before_attempt)
    return {"ready": True, "tier": str(profile.get("userTier", profile.get("tier", "unknown")))[:80] if isinstance(profile, dict) else "unknown",
            "profile_ready": bool(profile)}


def status(state):
    items = pending(state)
    return {"configured_sources": len(state["sources"]),
            "initialized_sources": sum(bool(source.get("initialized")) for source in state["sources"].values()),
            "pending": len(state["pending"]), "retryable": len(items["retryable"]),
            "claimed": len(items["claimed"]), "exhausted": len(items["exhausted"]),
            "last_successful_scan": state.get("last_successful_scan"), "api_calls": state.get("api_calls", {}),
            "warnings": state.get("warnings", []), "scan_health": state.get("scan_health", {}),
            "body_budget": {"day": state["body_budget"]["day"], "used": state["body_budget"]["count"],
                            "limit": BODY_DAILY_LIMIT},
            "total_budget": {"day": state["total_budget"]["day"], "used": state["total_budget"]["count"],
                             "limit": TOTAL_DAILY_LIMIT}}


def _client_from_env():
    key = os.environ.get("BESTBLOGS_API_KEY")
    if not key:
        raise APIError("BESTBLOGS_API_KEY is required")
    return BestBlogsClient(key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("sources")
    configure = sub.add_parser("configure")
    configure.add_argument("--source-id", action="append", required=True)
    sub.add_parser("scan")
    claim_parser = sub.add_parser("claim")
    claim_parser.add_argument("article_id")
    pending_parser = sub.add_parser("pending")
    pending_parser.set_defaults(command="pending")
    markdown_parser = sub.add_parser("markdown")
    markdown_parser.add_argument("article_id")
    markdown_parser.add_argument("--claim-id", required=True)
    ack_parser = sub.add_parser("ack")
    ack_parser.add_argument("article_id")
    ack_parser.add_argument("--claim-id")
    fail_parser = sub.add_parser("fail")
    fail_parser.add_argument("article_id")
    fail_parser.add_argument("--reason", required=True)
    fail_parser.add_argument("--claim-id")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    path = Path(args.state_file) if args.state_file else default_state_path()
    try:
        result = None
        state = None
        scan_generation = None
        markdown_identity = None
        markdown_resource_id = None
        with state_lock(path):
            state = _load_locked_state(path)
            if args.command == "configure":
                result = configure_sources(state, args.source_id)
                save_state(path, state)
            elif args.command == "claim":
                result = claim(state, args.article_id)
                if "claim_id" in result:
                    save_state(path, state)
            elif args.command == "pending":
                result = pending(state)
            elif args.command == "ack":
                result = ack(state, args.article_id, claim_id=args.claim_id); save_state(path, state)
            elif args.command == "fail":
                result = fail(state, args.article_id, args.reason, claim_id=args.claim_id); save_state(path, state)
            elif args.command == "status":
                result = status(state)
            else:
                if args.command == "scan":
                    state["next_scan_seq"] += 1
                    scan_generation = state["next_scan_seq"]
                    save_state(path, state)
                elif args.command == "markdown":
                    markdown_identity = _identity_for(state, args.article_id)
                    entry = state["pending"].get(markdown_identity)
                    try:
                        if not entry:
                            raise ClaimUnavailable("claim is unavailable")
                        _require_claim(entry, args.claim_id, require_active=True)
                        if entry.get("claim_fetch_started") is True:
                            result = {"claim_status": "already_fetching"}
                            entry = None
                        else:
                            entry["claim_fetch_started"] = True
                            markdown_resource_id = entry.get("resource_id")
                            save_state(path, state)
                    except ClaimUnavailable:
                        result = {"claim_status": "claim_lost"}
                        entry = None
                    if entry is None:
                        pass
                    else:
                        result = None
                else:
                    result = None
        if result is None:
            client = _client_from_env()
            if args.command == "doctor":
                result = doctor(client, before_attempt=_durable_reservation(path, "me"))
            elif args.command == "sources":
                result = list_sources(client, before_attempt=_durable_reservation(path, "subscription"))
            elif args.command == "scan":
                observation = _scan_observation(
                    client, before_attempt=_durable_reservation(path, "subscription"),
                )
                with state_lock(path):
                    fresh_state = _load_locked_state(path)
                    result = _apply_scan_observation(fresh_state, observation, generation=scan_generation)
                    save_state(path, fresh_state)
            else:
                result = markdown(
                    state, client, args.article_id,
                    reserve_attempt=_durable_reservation(
                        path, "markdown", body=True, identity=markdown_identity,
                        resource_id=markdown_resource_id, claim_id=args.claim_id,
                    ),
                )
    except OSError:
        result = {"error": "state operation failed safely"}
    except (APIError, StateError, ValueError, KeyError) as error:
        result = {"error": str(error)}
    except RecursionError:
        result = {"error": "operation failed safely"}
    try:
        output = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (RecursionError, TypeError, ValueError):
        result = {"error": "output serialization failed safely"}
        output = '{"error": "output serialization failed safely"}'
    print(output)
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
