#!/usr/bin/env python3
"""Small, durable local state helper for the BestBlogs WeChat digest skill."""

import argparse
import copy
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
import unicodedata
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
SEQUENCE_STATE_VERSION = 2
PREVIOUS_STATE_VERSION = 3
STATE_VERSION = 4
MAX_BODY_BYTES = 1_000_000
MAX_STATE_BYTES = 16 * 1024 * 1024
BODY_DAILY_LIMIT = 35
TOTAL_DAILY_LIMIT = 50
MAX_RECENT = 500
MAX_TOMBSTONES = 5000
MAX_TOMBSTONE_ALIASES = 8
MAX_FEED_PAGES = 14
DEFAULT_PAGE_SIZE = 50
CLAIM_LEASE_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SAFE_REASON = re.compile(r"^[A-Z0-9][A-Z0-9_:-]{0,63}$")
API_KEY = re.compile(r"^bb_[0-9A-Fa-f]{32}$")
CLAIM_TOKEN = re.compile(r"^[0-9a-f]{32}$")
CANONICAL_DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
NON_TARGET_RESOURCE_TYPES = frozenset(("blog", "newsletter", "podcast", "tweet", "video"))
MIGRATION_WARNING_PREFIXES = (
    "identity_rebaseline:", "legacy_pending_discarded:", "legacy_tombstones_discarded:",
)
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
    """Fixed-origin client with one bounded POST for explicit onboarding follows."""

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

    def subscription_source_page(self, page, page_size, source_id, before_attempt=None, time_filter=None):
        if not _safe_id(source_id):
            raise ValueError("source ID must be safe")
        if time_filter not in (None, "today", "week", "month"):
            raise ValueError("invalid time filter")
        query = {"page": page, "pageSize": page_size, "sourceId": source_id}
        if time_filter is not None:
            query["timeFilter"] = time_filter
        return self.get(
            "/me/feeds/subscriptions",
            query,
            before_attempt=before_attempt,
        )

    def source_search(self, name, before_attempt=None):
        if not isinstance(name, str):
            raise ValueError("source name must be a bounded string")
        name = name.strip()
        if not name or len(name) > 200 or any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise ValueError("source name must be a bounded string")
        return self.get(
            "/search",
            {"q": name, "language": "zh_CN", "page": 1, "pageSize": 50},
            before_attempt=before_attempt,
        )

    def follow_sources(self, source_ids, before_attempt=None):
        if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 10 or \
                len(set(source_ids)) != len(source_ids) or any(not _safe_id(item) for item in source_ids):
            raise ValueError("follow requires one to ten unique safe source IDs")
        if before_attempt is not None and not callable(before_attempt):
            raise ValueError("before_attempt must be callable")
        path = "/me/onboarding/follow"
        url = self.origin + path
        encoded = json.dumps({"sourceIds": source_ids}, separators=(",", ":")).encode("utf-8")
        request = Request(
            url,
            data=encoded,
            headers={
                "X-API-KEY": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
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

    def markdown(self, resource_id, before_attempt=None):
        if not _safe_id(resource_id):
            raise ValueError("resource ID must be safe")
        data = self.get("/resources/%s/markdown" % resource_id, before_attempt=before_attempt)
        if isinstance(data, dict):
            data = data.get("markdown", data.get("content"))
        return data

    def resource_metadata(self, resource_id, before_attempt=None):
        if not _safe_id(resource_id):
            raise ValueError("resource ID must be safe")
        return self.get("/resources/%s/meta" % resource_id, before_attempt=before_attempt)


def canonical_wechat_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host != "mp.weixin.qq.com" or \
                parsed.username is not None or parsed.password is not None or \
                parsed.port is not None or parsed.netloc.lower() != "mp.weixin.qq.com":
            return None
    except ValueError:
        return None
    if parsed.params:
        return None
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if parsed.path == "/s":
        canonical_pairs = []
        for required in ("__biz", "mid", "idx", "sn"):
            values = [item for key, item in pairs if key == required]
            if len(values) != 1 or not values[0]:
                return None
            canonical_pairs.append((required, values[0]))
    elif not re.fullmatch(r"/s/[A-Za-z0-9_-]+", parsed.path):
        return None
    else:
        canonical_pairs = []
    return urlunparse(("https", "mp.weixin.qq.com", parsed.path, "", urlencode(sorted(canonical_pairs)), ""))


def canonical_article_url(value):
    wechat_url = canonical_wechat_url(value)
    if wechat_url is not None:
        return wechat_url
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or \
                parsed.port is not None or parsed.netloc.lower() != host or parsed.params or parsed.query or \
                parsed.fragment or "%" in parsed.path:
            return None
    except ValueError:
        return None
    allowed = (
        host == "www.qbitai.com" and re.fullmatch(r"/[0-9]{4}/[0-9]{2}/[1-9][0-9]*\.html", parsed.path)
    ) or (
        host == "www.jiqizhixin.com" and
        re.fullmatch(r"/articles/[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[A-Za-z0-9_-]+)?", parsed.path)
    )
    if not allowed:
        return None
    return urlunparse(("https", host, parsed.path, "", "", ""))


def _publication_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return datetime.fromtimestamp(value / (1000 if abs(value) > 10_000_000_000 else 1), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            if len(value) > 20:
                return None
            try:
                return _publication_time(int(value))
            except ValueError:
                return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
        except (OverflowError, ValueError):
            return None
    return None


def _field_values(raw, fields):
    return [raw[field] for field in fields if field in raw and raw[field] is not None]


def _single_value(values, normalizer, default=None):
    normalized = []
    for value in values:
        item = normalizer(value)
        if item is None:
            return None, False
        normalized.append(item)
    if not normalized:
        return default, True
    if len(set(normalized)) != 1:
        return None, False
    return normalized[0], True


def _safe_id_value(value):
    return value if _safe_id(value) else None


def _kind_value(value):
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _source_values(raw):
    values = _field_values(raw, ("sourceId",))
    source_object = raw.get("source")
    if isinstance(source_object, dict):
        values.extend(_field_values(source_object, ("id",)))
    elif source_object is not None:
        values.append(source_object)
    return values


def parse_article(raw):
    if not isinstance(raw, dict):
        return None
    kind, kind_valid = _single_value(
        _field_values(raw, ("resourceType", "type")), _kind_value, default="article",
    )
    if not kind_valid or kind not in ("article", "wechat", "weixin"):
        return None
    source_object = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    source, source_valid = _single_value(_source_values(raw), _safe_id_value)
    if not source_valid or source is None:
        return None
    resource_id, resource_valid = _single_value(
        _field_values(raw, ("id", "resourceId")), _safe_id_value,
    )
    if not resource_valid:
        return None
    url, url_valid = _single_value(
        _field_values(raw, ("url", "link", "originalUrl")), canonical_article_url,
    )
    if not url_valid or url is None:
        return None
    identity = "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
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


def _bounded_display_text(value, limit, fallback=None):
    if value is None:
        value = fallback
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(unicodedata.category(character) == "Cc" for character in value):
        return None
    return value[:limit]


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


def _valid_alias_list(aliases, identity):
    if not isinstance(aliases, list) or not 1 <= len(aliases) <= MAX_TOMBSTONE_ALIASES:
        return False
    if any(not _valid_identity(alias) for alias in aliases):
        return False
    return identity in aliases and aliases == sorted(aliases) and len(aliases) == len(set(aliases))


def _url_identity(url):
    canonical = canonical_article_url(url)
    if canonical is None:
        return None
    return "url:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_aliases(entry, identity=None):
    aliases = set()
    if _valid_identity(identity):
        aliases.add(identity)
    if isinstance(entry, dict):
        resource_id = entry.get("resource_id")
        if _safe_id(resource_id):
            aliases.add("resource:" + resource_id)
        url_identity = _url_identity(entry.get("url"))
        if url_identity:
            aliases.add(url_identity)
    return frozenset(aliases)


def _all_pending_aliases(pending_entries):
    return frozenset(
        alias
        for identity, entry in pending_entries.items()
        for alias in _entry_aliases(entry, identity)
    )


def _all_tombstone_aliases(tombstones):
    return frozenset(
        alias
        for identity, tombstone in tombstones.items()
        for alias in tombstone.get("aliases", (identity,))
        if _valid_identity(alias)
    )


def _recent_aliases(recent):
    aliases = set()
    for identity, stored in recent.items():
        aliases.update(stored if isinstance(stored, list) else (identity,))
    return frozenset(alias for alias in aliases if _valid_identity(alias))


def _merge_recent_frontier(current, observed):
    merged = {identity: list(stored) for identity, stored in observed.items()}
    alias_owners = {}
    for identity, stored in merged.items():
        for alias in stored:
            owner = alias_owners.setdefault(alias, identity)
            if owner != identity:
                return None
    for identity, stored in current.items():
        stored_aliases = set(stored if isinstance(stored, list) else (identity,))
        owners = {alias_owners[alias] for alias in stored_aliases if alias in alias_owners}
        if len(owners) > 1:
            return None
        if owners:
            owner = next(iter(owners))
            combined = set(merged[owner]) | stored_aliases
            if len(combined) > MAX_TOMBSTONE_ALIASES:
                return None
            merged[owner] = sorted(combined)
            for alias in combined:
                alias_owners[alias] = owner
            continue
        if len(merged) >= MAX_RECENT:
            break
        merged[identity] = list(stored) if isinstance(stored, list) else [identity]
        for alias in stored_aliases:
            alias_owners[alias] = identity
    return merged


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
        for identity, aliases in source["recent"].items():
            if not isinstance(identity, str) or not identity.startswith("url:") or \
                    not _valid_identity(identity) or not _valid_alias_list(aliases, identity):
                raise StateError("unsupported or malformed state schema")
        if not _valid_health(source["health"], allow_empty=True):
            raise StateError("unsupported or malformed state schema")
    pending_aliases = set()
    for identity, entry in state["pending"].items():
        required = {"identity", "resource_id", "source_id", "source_name", "title", "url", "published_at", "attempts"}
        if not _valid_identity(identity) or not isinstance(entry, dict) or not required.issubset(entry) or \
                not set(entry).issubset(PENDING_FIELDS) or entry.get("identity") != identity or \
                not _safe_id(entry.get("source_id")) or canonical_article_url(entry.get("url")) != entry.get("url") or \
                entry.get("resource_id") is not None and not _safe_id(entry.get("resource_id")) or \
                not isinstance(entry.get("attempts"), int) or isinstance(entry.get("attempts"), bool) or not 0 <= entry["attempts"] <= 3 or \
                not isinstance(entry.get("title"), str) or not isinstance(entry.get("source_name"), str) or not isinstance(entry.get("published_at"), str):
            raise StateError("unsupported or malformed state schema")
        entry_aliases = _entry_aliases(entry)
        if _url_identity(entry.get("url")) != identity or \
                not entry_aliases.isdisjoint(pending_aliases):
            raise StateError("unsupported or malformed state schema")
        pending_aliases.update(entry_aliases)
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
    tombstone_aliases = set()
    for identity, tombstone in state["ack_tombstones"].items():
        if not isinstance(identity, str) or not identity.startswith("url:") or \
                not _valid_identity(identity) or not isinstance(tombstone, dict) or \
                set(tombstone) != {"source_id", "ack_after_scan_seq", "aliases"} or \
                not _safe_id(tombstone.get("source_id")) or \
                not isinstance(tombstone.get("ack_after_scan_seq"), int) or \
                isinstance(tombstone.get("ack_after_scan_seq"), bool) or \
                not 0 <= tombstone["ack_after_scan_seq"] <= state["next_scan_seq"]:
            raise StateError("unsupported or malformed state schema")
        aliases = tombstone.get("aliases")
        if not _valid_alias_list(aliases, identity):
            raise StateError("unsupported or malformed state schema")
        aliases = set(aliases)
        if not aliases.isdisjoint(pending_aliases) or not aliases.isdisjoint(tombstone_aliases):
            raise StateError("unsupported or malformed state schema")
        tombstone_aliases.update(aliases)
    return state


def default_state_path():
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return Path(home) / "state" / "wechat-digest.json"


def _validate_legacy_sources(sources):
    if not isinstance(sources, dict):
        raise StateError("unsupported or malformed state schema")
    for source_id, source in sources.items():
        if not _safe_id(source_id) or not isinstance(source, dict) or \
                set(source) != {"id", "name", "initialized", "recent", "health"} or \
                source.get("id") != source_id or not isinstance(source.get("name"), str) or \
                not isinstance(source.get("initialized"), bool) or \
                not isinstance(source.get("recent"), dict) or len(source["recent"]) > MAX_RECENT or \
                not isinstance(source.get("health"), dict) or \
                any(not _valid_identity(identity) or value is not True
                    for identity, value in source["recent"].items()) or \
                not _valid_health(source["health"], allow_empty=True):
            raise StateError("unsupported or malformed state schema")


def _validate_legacy_pending(pending):
    if not isinstance(pending, dict):
        raise StateError("unsupported or malformed state schema")
    required = {"identity", "resource_id", "source_id", "source_name", "title", "url", "published_at", "attempts"}
    for identity, entry in pending.items():
        legacy_url = entry.get("url") if isinstance(entry, dict) else None
        if not _valid_identity(identity) or not isinstance(entry, dict) or \
                not required.issubset(entry) or not set(entry).issubset(PENDING_FIELDS) or \
                entry.get("identity") != identity or not _safe_id(entry.get("source_id")) or \
                not isinstance(legacy_url, str) or not 1 <= len(legacy_url) <= 4096 or \
                entry.get("resource_id") is not None and not _safe_id(entry.get("resource_id")) or \
                not isinstance(entry.get("attempts"), int) or isinstance(entry.get("attempts"), bool) or \
                not 0 <= entry["attempts"] <= 3 or not isinstance(entry.get("title"), str) or \
                not isinstance(entry.get("source_name"), str) or not isinstance(entry.get("published_at"), str):
            raise StateError("unsupported or malformed state schema")
        resource_id = entry.get("resource_id")
        if resource_id is not None and identity != "resource:" + resource_id:
            raise StateError("unsupported or malformed state schema")
        if resource_id is None and identity != "url:" + hashlib.sha256(legacy_url.encode("utf-8")).hexdigest():
            raise StateError("unsupported or malformed state schema")
        if entry.get("last_failure_reason") is not None and \
                (not isinstance(entry["last_failure_reason"], str) or
                 not SAFE_REASON.fullmatch(entry["last_failure_reason"])):
            raise StateError("unsupported or malformed state schema")
        has_claim_id = "claim_id" in entry
        has_claim_expiry = "claim_expires_at" in entry
        if has_claim_id != has_claim_expiry or has_claim_id and \
                (not isinstance(entry["claim_id"], str) or not CLAIM_TOKEN.fullmatch(entry["claim_id"]) or
                 _parse_claim_expiry(entry["claim_expires_at"]) is None):
            raise StateError("unsupported or malformed state schema")
        if "claim_fetch_started" in entry and (not has_claim_id or entry["claim_fetch_started"] is not True):
            raise StateError("unsupported or malformed state schema")


def _validate_legacy_tombstones(tombstones, next_sequence):
    if not isinstance(tombstones, dict) or len(tombstones) > MAX_TOMBSTONES or \
            not isinstance(next_sequence, int) or isinstance(next_sequence, bool) or next_sequence < 0:
        raise StateError("unsupported or malformed state schema")
    for identity, tombstone in tombstones.items():
        if not _valid_identity(identity) or not isinstance(tombstone, dict) or \
                set(tombstone) != {"source_id", "ack_after_scan_seq"} or \
                not _safe_id(tombstone.get("source_id")) or \
                not isinstance(tombstone.get("ack_after_scan_seq"), int) or \
                isinstance(tombstone.get("ack_after_scan_seq"), bool) or \
                not 0 <= tombstone["ack_after_scan_seq"] <= next_sequence:
            raise StateError("unsupported or malformed state schema")


def _migrate_state(state):
    if not isinstance(state, dict):
        raise StateError("unsupported or malformed state schema")
    version = state.get("version")
    if version == LEGACY_STATE_VERSION:
        earliest = {"version", "sources", "pending", "body_budget", "last_successful_scan",
                    "api_calls", "warnings"}
        with_health = earliest | {"scan_health"}
        if set(state) not in (earliest, with_health):
            raise StateError("unsupported or malformed state schema")
        migrated = copy.deepcopy(state)
        if set(state) == earliest:
            migrated["scan_health"] = new_state()["scan_health"]
        migrated["total_budget"] = {"day": _beijing_day(), "count": TOTAL_DAILY_LIMIT}
        next_sequence = 0
    elif version == SEQUENCE_STATE_VERSION:
        expected = {"version", "sources", "pending", "body_budget", "total_budget",
                    "last_successful_scan", "api_calls", "warnings", "scan_generation", "scan_health"}
        if set(state) != expected:
            raise StateError("unsupported or malformed state schema")
        migrated = copy.deepcopy(state)
        next_sequence = migrated.pop("scan_generation")
    elif version == PREVIOUS_STATE_VERSION:
        if set(state) != STATE_FIELDS:
            raise StateError("unsupported or malformed state schema")
        migrated = copy.deepcopy(state)
        next_sequence = migrated["next_scan_seq"]
    else:
        raise StateError("unsupported or malformed state schema")
    if version in (LEGACY_STATE_VERSION, SEQUENCE_STATE_VERSION):
        migrated["next_scan_seq"] = next_sequence
        migrated["last_applied_scan_generation"] = 0
        migrated["ack_tombstones"] = {}

    if not isinstance(migrated.get("warnings"), list) or \
            any(not isinstance(warning, str) for warning in migrated["warnings"]):
        raise StateError("unsupported or malformed state schema")
    _validate_legacy_sources(migrated.get("sources"))
    _validate_legacy_pending(migrated.get("pending"))
    _validate_legacy_tombstones(migrated.get("ack_tombstones"), next_sequence)

    pending_count = len(migrated["pending"])
    tombstone_count = len(migrated["ack_tombstones"])
    migrated["version"] = STATE_VERSION
    migrated["pending"] = {}
    migrated["ack_tombstones"] = {}
    for source_id, source in migrated["sources"].items():
        source["initialized"] = False
        source["recent"] = {}
        source["health"] = {}
        warning = "identity_rebaseline:" + source_id
        if warning not in migrated["warnings"]:
            migrated["warnings"].append(warning)
    if pending_count:
        migrated["warnings"].append("legacy_pending_discarded:%d" % pending_count)
    if tombstone_count:
        migrated["warnings"].append("legacy_tombstones_discarded:%d" % tombstone_count)
    return _validate_state(migrated)


def _read_state(path=None):
    path = Path(path or default_state_path())
    if not path.exists():
        return new_state(), False
    try:
        with path.open("rb") as handle:
            encoded = handle.read(MAX_STATE_BYTES + 1)
    except OSError as error:
        raise StateError("state cannot be read safely") from error
    if len(encoded) > MAX_STATE_BYTES:
        raise StateError("state exceeds size limit")
    try:
        state = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise StateError("state cannot be read safely") from error
    if isinstance(state, dict) and state.get("version") in (
            LEGACY_STATE_VERSION, SEQUENCE_STATE_VERSION, PREVIOUS_STATE_VERSION):
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
            if os.fstat(handle.fileno()).st_size > MAX_STATE_BYTES:
                raise StateError("state exceeds size limit")
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
    selected = set(source_ids)
    pending_entries = state.get("pending", {})
    tombstones = state.get("ack_tombstones", {})
    discarded_pending = [
        identity for identity, entry in pending_entries.items()
        if entry.get("source_id") not in selected
    ]
    discarded_tombstones = [
        identity for identity, tombstone in tombstones.items()
        if tombstone.get("source_id") not in selected
    ]
    for identity in discarded_pending:
        del pending_entries[identity]
    for identity in discarded_tombstones:
        del tombstones[identity]
    old = state["sources"]
    state["sources"] = {source: old.get(source, {"id": source, "name": source, "initialized": False, "recent": {}, "health": {}})
                        for source in source_ids}
    return {"configured_sources": list(state["sources"]),
            "discarded_pending": len(discarded_pending),
            "discarded_tombstones": len(discarded_tombstones)}


def configured_sources(state):
    return {"sources": [
        {
            "id": source_id,
            "name": _bounded_display_text(source.get("name"), 200, source_id) or source_id,
            "initialized": source["initialized"],
        }
        for source_id, source in state["sources"].items()
    ]}


def _configured_source_id(state, selector):
    if not isinstance(selector, str) or not 1 <= len(selector) <= 200 or \
            any(ord(character) < 32 or ord(character) == 127 for character in selector):
        raise ValueError("unsafe source selector")
    sources = state.get("sources")
    if not isinstance(sources, dict):
        raise StateError("unsupported or malformed state schema")
    if selector in sources:
        return selector
    matches = [
        source_id for source_id, source in sources.items()
        if _bounded_display_text(source.get("name"), 200, source_id) == selector
    ]
    if not matches:
        raise ValueError("unknown configured source")
    if len(matches) != 1:
        raise ValueError("ambiguous configured source name")
    return matches[0]


def _interactive_article(raw, expected_source_id):
    if not isinstance(raw, dict):
        raise APIError("malformed interactive response")
    raw_source_id, source_valid = _single_value(_source_values(raw), _safe_id_value)
    if not source_valid or raw_source_id is None:
        raise APIError("malformed interactive response")
    if raw_source_id != expected_source_id:
        raise APIError("feed source filter mismatch")
    article = parse_article(raw)
    if article is None:
        return None
    if not _safe_id(article["resource_id"]):
        return None
    source_object = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    raw_source_names = _field_values(raw, ("sourceName",)) + _field_values(source_object, ("name",))
    source_names = [_bounded_display_text(value, 200) for value in raw_source_names]
    if any(name is None for name in source_names):
        return None
    source_name = source_names[0] if source_names else article["source_id"]
    title = _bounded_display_text(raw.get("title"), 500, "Untitled")
    if title is None:
        return None
    return {
        "identity": article["identity"],
        "resource_id": article["resource_id"],
        "source_id": article["source_id"],
        "source_name": source_name,
        "title": title,
        "url": article["url"],
        "published_at": article["published_at"],
        "source_name_explicit": bool(source_names),
        "source_name_consistent": len(set(source_names)) <= 1,
    }


def interactive_articles(state, client, source_selector, limit, time_filter=None, before_attempt=None):
    source_id = _configured_source_id(state, source_selector)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if time_filter not in (None, "today", "week", "month"):
        raise ValueError("invalid time filter")
    data = client.subscription_source_page(
        1, DEFAULT_PAGE_SIZE, source_id, time_filter=time_filter, before_attempt=before_attempt,
    )
    records, unused_counter, schema_error = _page_items(data)
    if schema_error:
        raise APIError("malformed interactive response")
    articles = []
    identities, resource_ids = set(), set()
    for raw in records:
        article = _interactive_article(raw, source_id)
        if article is None:
            continue
        resource_id = article["resource_id"]
        if article["identity"] in identities or resource_id is not None and resource_id in resource_ids:
            raise APIError("duplicate identity in interactive response")
        identities.add(article["identity"])
        if resource_id is not None:
            resource_ids.add(resource_id)
        articles.append(article)
    if not articles:
        raise APIError("no safe article")
    warnings = []
    explicit_source_names = {
        article["source_name"] for article in articles if article["source_name_explicit"]
    }
    all_names_explicit = all(article["source_name_explicit"] for article in articles)
    explicit_names_consistent = all(
        article["source_name_consistent"] for article in articles if article["source_name_explicit"]
    )
    source = state["sources"][source_id]
    if all_names_explicit and len(explicit_source_names) == 1 and explicit_names_consistent:
        source["name"] = next(iter(explicit_source_names))
    elif len(explicit_source_names) > 1 or not explicit_names_consistent:
        warnings.append("source_name_conflict")
    if all(article["published_at"] for article in articles):
        articles = sorted(
            articles,
            key=lambda article: datetime.fromisoformat(article["published_at"]).astimezone(timezone.utc),
            reverse=True,
        )
    else:
        warnings.append("provider_order_used")
    return {
        "source": {
            "id": source_id,
            "name": _bounded_display_text(source.get("name"), 200, source_id) or source_id,
            "initialized": source["initialized"],
        },
        "articles": [
            {field: article[field] for field in (
                "resource_id", "source_id", "source_name", "title", "url", "published_at",
            )}
            for article in articles[:limit]
        ],
        "requested_limit": limit,
        "warnings": warnings,
    }


def _article_summary(article):
    return {field: article[field] for field in (
        "resource_id", "source_id", "source_name", "title", "url", "published_at",
    )}


def read_article(
        state, client, resource_id, source_selector, metadata_attempt=None,
        markdown_attempt=None, validate_source=None,
):
    if not _safe_id(resource_id):
        raise ValueError("resource ID must be safe")
    source_id = _configured_source_id(state, source_selector)
    metadata = client.resource_metadata(resource_id, before_attempt=metadata_attempt)
    article = _interactive_article(metadata, source_id)
    if article is None:
        raise APIError("unsafe resource metadata")
    if article["resource_id"] != resource_id:
        raise APIError("resource metadata mismatch")
    summary = _article_summary(article)

    def fallback(reason):
        if validate_source is not None:
            validate_source()
        return {"article": summary, "fallback": {"reason": reason, "url": summary["url"]}}

    try:
        body = client.markdown(resource_id, before_attempt=markdown_attempt)
    except TotalBudgetExhausted:
        return fallback("daily_total_budget_exhausted")
    except BodyBudgetExhausted:
        return fallback("daily_body_budget_exhausted")
    except (APIError, ValueError):
        return fallback("bestblogs_markdown_unavailable")
    if not isinstance(body, str) or not body.strip():
        return fallback("bestblogs_markdown_unavailable")
    if validate_source is not None:
        validate_source()
    return {"article": summary, "content": {"source": "bestblogs", "markdown": body}}


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


def _json_fingerprint(value):
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).digest()


def _source_configuration_fingerprint(sources):
    if not isinstance(sources, dict):
        raise StateError("source configuration cannot be fingerprinted")
    snapshot = {}
    for source_id, source in sources.items():
        if not isinstance(source, dict):
            raise StateError("source configuration cannot be fingerprinted")
        snapshot[source_id] = {
            "id": source.get("id"),
            "initialized": source.get("initialized"),
            "recent": source.get("recent"),
        }
    fingerprint = _json_fingerprint(snapshot)
    if fingerprint is None:
        raise StateError("source configuration cannot be fingerprinted")
    return fingerprint.hex()


def _feed_aliases(raw):
    if not isinstance(raw, dict):
        return frozenset()
    aliases = set()
    for resource_id in _field_values(raw, ("id", "resourceId")):
        if _safe_id(resource_id):
            aliases.add("resource:" + resource_id)
    raw_urls = _field_values(raw, ("url", "link", "originalUrl"))
    for raw_url in raw_urls:
        url = canonical_article_url(raw_url)
        if url:
            aliases.add("url:" + hashlib.sha256(url.encode("utf-8")).hexdigest())

    for raw_url in raw_urls:
        if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 4096 or canonical_article_url(raw_url):
            continue
        encoded = json.dumps(
            ["external_url", raw_url.strip()], ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        aliases.add("opaque:" + hashlib.sha256(encoded).hexdigest())
    return frozenset(aliases)


def _feed_pages(client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    all_items, warnings, page, expected = [], [], 1, None
    counter_presence = None
    full_pages = set()
    prior_records = set()
    prior_aliases = set()
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
        page_fingerprint = _json_fingerprint(items)
        record_fingerprints = [_json_fingerprint(item) for item in items]
        if page_fingerprint is None or any(fingerprint is None for fingerprint in record_fingerprints):
            return [], False, warnings + ["feed_json_too_deep"], page
        if len(items) == page_size and page_fingerprint in full_pages:
            return all_items, False, warnings + ["feed_repeated_full_page"], page
        if len(set(record_fingerprints)) != len(record_fingerprints) or \
                any(fingerprint in prior_records for fingerprint in record_fingerprints):
            return all_items, False, warnings + ["feed_duplicate_record"], page
        page_aliases = [alias for item in items for alias in _feed_aliases(item)]
        if len(set(page_aliases)) != len(page_aliases) or \
                any(alias in prior_aliases for alias in page_aliases):
            return all_items, False, warnings + ["feed_duplicate_identity"], page
        if len(items) == page_size:
            full_pages.add(page_fingerprint)
        prior_records.update(record_fingerprints)
        prior_aliases.update(page_aliases)
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
                source_id, source_valid = _single_value(_source_values(raw), _safe_id_value)
                source_name = raw.get("sourceName") or source_object.get("name") or source_id
                if source_valid and source_id is not None:
                    sources.setdefault(source_id, {"id": source_id, "name": str(source_name)[:200]})
            continue
        sources.setdefault(article["source_id"], {"id": article["source_id"], "name": article["source_name"]})
    if malformed:
        warnings.append("skipped_malformed_records:%d" % malformed)
    if not complete:
        warnings.append("partial_feed")
    return {"sources": list(sources.values()), "skipped": {"invalid_or_non_wechat": malformed}, "warnings": warnings}


def search_sources(client, name, before_attempt=None):
    data = client.source_search(name, before_attempt=before_attempt)
    if not isinstance(data, dict) or not isinstance(data.get("dataList"), list):
        raise APIError("invalid BestBlogs source search response")
    sources = {}
    for raw in data["dataList"]:
        if not isinstance(raw, dict):
            continue
        source_id = raw.get("sourceId")
        source_name = raw.get("sourceName")
        if source_name == name and _safe_id(source_id):
            sources.setdefault(source_id, {"id": source_id, "name": source_name})
    if not sources:
        raise APIError("no exact BestBlogs source match")
    if len(sources) > 1:
        raise APIError("ambiguous exact BestBlogs source match")
    return {"sources": list(sources.values())}


def follow_selected_sources(client, source_ids, before_attempt=None):
    data = client.follow_sources(source_ids, before_attempt=before_attempt)
    if not isinstance(data, dict):
        raise APIError("invalid BestBlogs follow response")
    legacy_fields = ("followedCount", "skippedCount")
    live_fields = ("requestedCount", "successCount", "alreadySubscribedCount", "failedCount")
    legacy_present = any(field in data for field in legacy_fields)
    live_present = any(field in data for field in live_fields)
    if legacy_present and live_present:
        raise APIError("invalid BestBlogs follow response")
    followed = data.get("followedCount")
    skipped = data.get("skippedCount")
    if legacy_present and isinstance(followed, int) and not isinstance(followed, bool) and followed >= 0 and \
            isinstance(skipped, int) and not isinstance(skipped, bool) and skipped >= 0 and \
            followed == len(source_ids) and skipped == 0:
        return {"followedCount": followed, "skippedCount": skipped}
    counts = [data.get(field) for field in live_fields]
    if live_present and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counts) and \
            counts[0] == len(source_ids) and sum(counts[1:]) == counts[0] and counts[3] == 0:
        return dict(zip(live_fields, counts))
    raise APIError("invalid BestBlogs follow response")


def _source_frontier_observation(client, sources, page_size, before_attempt=None):
    records, warnings, exhausted_source_ids = [], [], []
    prior_records, prior_aliases = set(), set()
    pages = 0
    for source_id, source in sources.items():
        baseline = not source.get("initialized")
        known_aliases = set() if baseline else _recent_aliases(source.get("recent", {}))
        frontier_required = not baseline and bool(known_aliases)
        page, expected, counter_presence, observed = 1, None, None, 0
        full_pages = set()
        source_complete = False
        while pages < MAX_FEED_PAGES:
            data = client.subscription_source_page(
                page, page_size, source_id, before_attempt=before_attempt,
            )
            pages += 1
            items, counter, schema_error = _page_items(data)
            if schema_error:
                return {"records": records + items, "complete": False,
                        "warnings": warnings + [schema_error], "pages": pages}
            has_counter = counter is not None
            if counter_presence is None:
                counter_presence, expected = has_counter, counter
            elif counter_presence != has_counter or has_counter and counter != expected:
                return {"records": records + items, "complete": False,
                        "warnings": warnings + ["feed_counter_changed"], "pages": pages}
            observed += len(items)
            if expected is not None and observed > expected:
                return {"records": records + items, "complete": False,
                        "warnings": warnings + ["feed_total_less_than_observed"], "pages": pages}

            frontier_index = None
            if known_aliases:
                for index, item in enumerate(items):
                    if not _feed_aliases(item).isdisjoint(known_aliases):
                        frontier_index = index
                        break
            included = items if frontier_index is None else items[:frontier_index + 1]
            baseline_has_target = False
            if baseline:
                for item in included:
                    parsed_item = parse_article(item)
                    if parsed_item is not None and parsed_item["source_id"] == source_id:
                        baseline_has_target = True
                        break
            fingerprints = [_json_fingerprint(item) for item in included]
            if any(fingerprint is None for fingerprint in fingerprints):
                return {"records": [], "complete": False,
                        "warnings": warnings + ["feed_json_too_deep"], "pages": pages}
            aliases = [alias for item in included for alias in _feed_aliases(item)]
            if len(set(fingerprints)) != len(fingerprints) or any(item in prior_records for item in fingerprints):
                return {"records": records + included, "complete": False,
                        "warnings": warnings + ["feed_duplicate_record"], "pages": pages}
            if len(set(aliases)) != len(aliases) or any(alias in prior_aliases for alias in aliases):
                return {"records": records + included, "complete": False,
                        "warnings": warnings + ["feed_duplicate_identity"], "pages": pages}
            for item in included:
                if isinstance(item, dict):
                    item_sources = {_safe_id_value(value) for value in _source_values(item)}
                    item_sources.discard(None)
                    if item_sources and item_sources != {source_id}:
                        return {"records": records + included, "complete": False,
                                "warnings": warnings + ["feed_source_filter_mismatch"], "pages": pages}
            page_fingerprint = _json_fingerprint(items)
            if page_fingerprint is None:
                return {"records": [], "complete": False,
                        "warnings": warnings + ["feed_json_too_deep"], "pages": pages}
            if len(items) == page_size and page_fingerprint in full_pages:
                return {"records": records + included, "complete": False,
                        "warnings": warnings + ["feed_repeated_full_page"], "pages": pages}
            if len(items) == page_size:
                full_pages.add(page_fingerprint)
            records.extend(included)
            prior_records.update(fingerprints)
            prior_aliases.update(aliases)

            if frontier_index is not None:
                source_complete = True
                break
            if expected is not None and observed == expected:
                if frontier_required:
                    return {"records": records, "complete": False,
                            "warnings": warnings + ["feed_frontier_not_found"], "pages": pages}
                exhausted_source_ids.append(source_id)
                source_complete = True
                break
            if not items:
                if expected is not None:
                    return {"records": records, "complete": False,
                            "warnings": warnings + ["feed_ended_before_total"], "pages": pages}
                if frontier_required:
                    return {"records": records, "complete": False,
                            "warnings": warnings + ["feed_frontier_not_found"], "pages": pages}
                exhausted_source_ids.append(source_id)
                source_complete = True
                break
            if len(items) < page_size:
                if expected is not None:
                    return {"records": records, "complete": False,
                            "warnings": warnings + ["feed_shorter_than_total"], "pages": pages}
                if frontier_required:
                    return {"records": records, "complete": False,
                            "warnings": warnings + ["feed_frontier_not_found"], "pages": pages}
                exhausted_source_ids.append(source_id)
                source_complete = True
                break
            if baseline and baseline_has_target:
                source_complete = True
                break
            if baseline:
                return {"records": records, "complete": False,
                        "warnings": warnings + ["baseline_frontier_not_found"], "pages": pages}
            page += 1
        if not source_complete:
            return {"records": records, "complete": False,
                    "warnings": warnings + ["feed page cap reached"], "pages": pages}
    return {"records": records, "complete": True, "warnings": warnings, "pages": pages,
            "exhausted_source_ids": exhausted_source_ids}


def _scan_observation(client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None, sources=None):
    if sources is not None and not sources:
        raise StateError("configure at least one source before scan")
    source_fingerprint = _source_configuration_fingerprint(sources) if sources is not None else None
    if sources and callable(getattr(client, "subscription_source_page", None)):
        observation = _source_frontier_observation(client, sources, page_size, before_attempt=before_attempt)
        observation["incremental_frontier"] = True
    else:
        records, complete, warnings, pages = _feed_pages(client, page_size, before_attempt=before_attempt)
        observation = {"records": records, "complete": complete, "warnings": warnings, "pages": pages}
    if sources is not None:
        observation["source_ids"] = list(sources)
        observation["source_configuration_fingerprint"] = source_fingerprint
    return observation


def _apply_scan_observation(state, observation, generation=None):
    if generation is not None and (
            generation <= state["last_applied_scan_generation"] or
            generation != state["next_scan_seq"]):
        return {"complete": False, "enqueued": 0, "skipped": {"invalid_or_non_wechat": 0},
                "warnings": ["superseded_scan"], "superseded": True}
    records = observation["records"]
    complete = observation["complete"]
    pages = observation["pages"]
    selected = state["sources"]
    observed_source_ids = observation.get("source_ids")
    if observed_source_ids is not None and set(observed_source_ids) != set(selected):
        return {"complete": False, "enqueued": 0,
                "skipped": {"invalid_or_non_wechat": 0},
                "warnings": ["superseded_configuration"], "superseded": True}
    if observed_source_ids is not None and (
            observation.get("source_configuration_fingerprint") !=
            _source_configuration_fingerprint(selected)):
        return {"complete": False, "enqueued": 0,
                "skipped": {"invalid_or_non_wechat": 0},
                "warnings": ["superseded_configuration"], "superseded": True}
    incremental_frontier = observation.get("incremental_frontier") is True
    exhausted_source_ids = observation.get("exhausted_source_ids", [])
    if incremental_frontier and (
            not isinstance(exhausted_source_ids, list) or
            len(set(exhausted_source_ids)) != len(exhausted_source_ids) or
            any(not _safe_id(source_id) or source_id not in selected for source_id in exhausted_source_ids)):
        if generation is not None:
            state["last_applied_scan_generation"] = generation
        return {"complete": False, "enqueued": 0,
                "skipped": {"invalid_or_non_wechat": 0},
                "warnings": ["feed_coverage_invalid"]}
    needs_baseline = not selected or any(not source["initialized"] for source in selected.values())
    migration_receipts = [
        warning for warning in state["warnings"]
        if needs_baseline and warning.startswith(MIGRATION_WARNING_PREFIXES)
    ]
    warnings = list(dict.fromkeys(migration_receipts + list(observation["warnings"])))
    parsed, malformed, non_target = [], 0, 0
    for raw in records:
        article = parse_article(raw)
        if article is None:
            if not isinstance(raw, dict):
                malformed += 1
                continue
            source_ids = {_safe_id_value(value) for value in _source_values(raw)}
            source_ids.discard(None)
            if source_ids and source_ids.isdisjoint(selected):
                continue
            raw_source_id, source_valid = _single_value(_source_values(raw), _safe_id_value)
            kind, kind_valid = _single_value(
                _field_values(raw, ("resourceType", "type")), _kind_value,
            )
            if source_valid and raw_source_id in selected and kind_valid and kind in NON_TARGET_RESOURCE_TYPES:
                non_target += 1
            else:
                malformed += 1
        elif article["source_id"] in selected:
            parsed.append(article)
    by_source = {source: {} for source in selected}
    for article in parsed:
        by_source[article["source_id"]].setdefault(article["identity"], article)
    skipped = malformed + non_target
    if non_target:
        warnings.append("skipped_non_target_records:%d" % non_target)
    if malformed:
        warnings.append("skipped_malformed_records:%d" % malformed)
        complete = False
    for source_id, articles in by_source.items():
        if len(articles) > MAX_RECENT:
            warnings.append("source_snapshot_limit_exceeded:%s:%d" % (source_id, len(articles)))
            complete = False
    prepared_recent = {}
    if complete:
        for source_id, source in selected.items():
            observed_recent = {
                identity: sorted(_entry_aliases(article, identity))
                for identity, article in by_source[source_id].items()
            }
            if source.get("initialized") and observation.get("incremental_frontier"):
                observed_recent = _merge_recent_frontier(source["recent"], observed_recent)
                if observed_recent is None:
                    warnings.append("source_alias_limit_exceeded:%s" % source_id)
                    complete = False
                    break
            prepared_recent[source_id] = observed_recent
    if not complete:
        if "partial_feed" not in warnings:
            warnings.append("partial_feed")
        for source_id, source in selected.items():
            source["health"] = {"records": len(by_source[source_id]), "complete": False,
                                "skipped": {"invalid_or_non_wechat": skipped}}
        state["warnings"] = warnings
        state["scan_health"] = {"pages": pages, "records": len(records), "complete": False,
                                "skipped": {"invalid_or_non_wechat": skipped}}
        if generation is not None:
            state["last_applied_scan_generation"] = generation
        return {"complete": False, "enqueued": 0,
                "skipped": {"invalid_or_non_wechat": skipped}, "warnings": warnings}

    enqueued = 0
    pending_aliases = set(_all_pending_aliases(state["pending"]))
    tombstone_aliases = set(_all_tombstone_aliases(state["ack_tombstones"]))
    for source_id, source in selected.items():
        articles = by_source[source_id]
        source["health"] = {"records": len(articles), "complete": True,
                            "skipped": {"invalid_or_non_wechat": skipped}}
        if not source.get("initialized"):
            source["recent"] = prepared_recent[source_id]
            source["initialized"] = True
            continue
        seen_before = _recent_aliases(source.get("recent", {}))
        for identity, article in articles.items():
            aliases = _entry_aliases(article, identity)
            if aliases.isdisjoint(seen_before) and aliases.isdisjoint(pending_aliases) and \
                    aliases.isdisjoint(tombstone_aliases):
                state["pending"][identity] = article
                pending_aliases.update(aliases)
                enqueued += 1
        source["recent"] = prepared_recent[source_id]
    if generation is not None:
        prunable_sources = set(exhausted_source_ids) if incremental_frontier else set(by_source)
        observed_aliases = {
            source_id: {
                alias
                for identity, article in articles.items()
                for alias in _entry_aliases(article, identity)
            }
            for source_id, articles in by_source.items()
        }
        for identity, tombstone in list(state["ack_tombstones"].items()):
            source_id = tombstone["source_id"]
            aliases = frozenset(tombstone["aliases"])
            if source_id in prunable_sources and generation > tombstone["ack_after_scan_seq"] and \
                    aliases.isdisjoint(observed_aliases[source_id]):
                del state["ack_tombstones"][identity]
        state["last_applied_scan_generation"] = generation
    state["last_successful_scan"] = datetime.now(timezone.utc).isoformat()
    state["warnings"] = warnings
    state["scan_health"] = {"pages": pages, "records": len(records), "complete": True,
                            "skipped": {"invalid_or_non_wechat": skipped}}
    return {"complete": True, "enqueued": enqueued,
            "skipped": {"invalid_or_non_wechat": skipped}, "warnings": warnings}


def scan(state, client, page_size=DEFAULT_PAGE_SIZE, before_attempt=None):
    observation = _scan_observation(
        client, page_size, before_attempt=before_attempt, sources=state["sources"],
    )
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


def _configured_pending(state, now=None):
    items = pending(state, now=now)
    selected = set(state["sources"])
    result = {
        category: [entry for entry in entries if entry.get("source_id") in selected]
        for category, entries in items.items()
    }
    result["deselected_count"] = sum(
        entry.get("source_id") not in selected
        for entries in items.values()
        for entry in entries
    )
    return result


def _identity_for(state, article_id):
    if isinstance(article_id, str):
        matches = set()
        if article_id in state["pending"]:
            matches.add(article_id)
        matches.update(
            identity for identity, entry in state["pending"].items()
            if entry.get("resource_id") == article_id
        )
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            raise KeyError("ambiguous pending article")
    return article_id


def _selected_identity_for(state, article_id):
    matches = set()
    if isinstance(article_id, str):
        direct = state["pending"].get(article_id)
        if direct is not None and direct.get("source_id") in state["sources"]:
            matches.add(article_id)
        matches.update(
            identity for identity, entry in state["pending"].items()
            if entry.get("source_id") in state["sources"] and entry.get("resource_id") == article_id
        )
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        raise KeyError("ambiguous pending article")
    raise ClaimUnavailable("pending article source is not configured or unavailable")


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


def renew(state, identity, claim_id, now=None):
    identity = _identity_for(state, identity)
    entry = state["pending"].get(identity)
    if not entry:
        raise KeyError("unknown pending article")
    current = _utc_now(now)
    _require_claim(entry, claim_id, now=current, require_active=True)
    expiry = (current + timedelta(seconds=CLAIM_LEASE_SECONDS)).replace(microsecond=0)
    entry["claim_expires_at"] = expiry.isoformat().replace("+00:00", "Z")
    return {"claim_id": entry["claim_id"], "claim_expires_at": entry["claim_expires_at"]}


def ack(state, identity, claim_id=None):
    identity = _identity_for(state, identity)
    if identity not in state["pending"]:
        raise KeyError("unknown pending article")
    entry = state["pending"][identity]
    _require_claim(entry, claim_id, require_active=True)
    source_id = entry.get("source_id")
    if _safe_id(source_id):
        canonical_identity = _url_identity(entry.get("url"))
        if canonical_identity is None:
            raise StateError("pending article URL is unavailable")
        aliases = set(_entry_aliases(entry, identity))
        aliases.add(canonical_identity)
        tombstones = state["ack_tombstones"]
        overlapping = [
            key for key, tombstone in tombstones.items()
            if not aliases.isdisjoint(tombstone["aliases"])
        ]
        if any(tombstones[key]["source_id"] != source_id for key in overlapping):
            raise StateError("ack tombstone alias conflict")
        for key in overlapping:
            aliases.update(tombstones[key]["aliases"])
        if len(aliases) > MAX_TOMBSTONE_ALIASES:
            raise StateError("ack tombstone alias capacity exhausted")
        resulting_count = len(tombstones) - len(overlapping) + 1
        if resulting_count > MAX_TOMBSTONES:
            raise StateError("ack tombstone capacity exhausted")
        for key in overlapping:
            del tombstones[key]
        tombstones[canonical_identity] = {
            "source_id": source_id,
            "ack_after_scan_seq": state["next_scan_seq"],
            "aliases": sorted(aliases),
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
    _require_claim(entry, claim_id, require_active=True)
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


def _durable_reservation(
        path, endpoint, body=False, now=None, identity=None, resource_id=None,
        claim_id=None, configured_source_id=None,
):
    def reserve_attempt():
        with state_lock(path):
            state = _load_locked_state(path)
            if configured_source_id is not None and configured_source_id not in state["sources"]:
                raise StateError("configured source changed during read request")
            if identity is not None:
                entry = state["pending"].get(identity)
                if not entry or entry.get("resource_id") != resource_id or entry.get("claim_fetch_started") is not True:
                    raise ClaimUnavailable("claim is unavailable")
                _require_claim(entry, claim_id, now=now, require_active=True)
            _reserve_api_attempt(state, now=now, body=body)
            state["api_calls"][endpoint] = int(state["api_calls"].get(endpoint, 0)) + 1
            save_state(path, state)
    return reserve_attempt


def _durable_source_validation(path, source_id):
    def validate_source():
        with state_lock(path):
            state = _load_locked_state(path)
            if source_id not in state["sources"]:
                raise StateError("configured source changed during read request")
    return validate_source


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
    if not isinstance(body, str) or not body.strip():
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
    items = _configured_pending(state)
    baseline_established = bool(state["sources"]) and state.get("scan_health", {}).get("complete") is True and \
        all(source.get("initialized") is True for source in state["sources"].values())
    return {"configured_sources": len(state["sources"]),
            "initialized_sources": sum(bool(source.get("initialized")) for source in state["sources"].values()),
            "baseline_established": baseline_established,
            "pending": len(items["retryable"]) + len(items["claimed"]) + len(items["exhausted"]),
            "deselected_pending": items["deselected_count"], "retryable": len(items["retryable"]),
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
    sub.add_parser("configured-sources")
    source_search = sub.add_parser("search-sources")
    source_search.add_argument("--name", required=True)
    follow = sub.add_parser("follow")
    follow.add_argument("--source-id", action="append", required=True)
    configure = sub.add_parser("configure")
    configure.add_argument("--source-id", action="append", required=True)
    latest_parser = sub.add_parser("latest")
    latest_parser.add_argument("--source", required=True)
    recent_parser = sub.add_parser("recent")
    recent_parser.add_argument("--source", required=True)
    recent_parser.add_argument("--limit", required=True)
    recent_parser.add_argument("--time-filter")
    read_parser = sub.add_parser("read")
    read_parser.add_argument("resource_id")
    read_parser.add_argument("--source", required=True)
    sub.add_parser("scan")
    claim_parser = sub.add_parser("claim")
    claim_parser.add_argument("article_id")
    renew_parser = sub.add_parser("renew")
    renew_parser.add_argument("article_id")
    renew_parser.add_argument("--claim-id", required=True)
    pending_parser = sub.add_parser("pending")
    pending_parser.set_defaults(command="pending")
    markdown_parser = sub.add_parser("markdown")
    markdown_parser.add_argument("article_id")
    markdown_parser.add_argument("--claim-id", required=True)
    ack_parser = sub.add_parser("ack")
    ack_parser.add_argument("article_id")
    ack_parser.add_argument("--claim-id", required=True)
    fail_parser = sub.add_parser("fail")
    fail_parser.add_argument("article_id")
    fail_parser.add_argument("--reason", required=True)
    fail_parser.add_argument("--claim-id", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    path = Path(args.state_file) if args.state_file else default_state_path()
    try:
        result = None
        state = None
        scan_generation = None
        markdown_identity = None
        markdown_resource_id = None
        interactive_source_id = None
        interactive_source_name = None
        with state_lock(path):
            state = _load_locked_state(path)
            if args.command == "configure":
                result = configure_sources(state, args.source_id)
                save_state(path, state)
            elif args.command == "configured-sources":
                result = configured_sources(state)
            elif args.command in ("latest", "recent"):
                interactive_source_id = _configured_source_id(state, args.source)
                interactive_source_name = state["sources"][interactive_source_id]["name"]
                if args.command == "recent":
                    try:
                        args.limit = int(args.limit)
                    except (TypeError, ValueError) as error:
                        raise ValueError("limit must be between 1 and 20") from error
                    if not 1 <= args.limit <= 20:
                        raise ValueError("limit must be between 1 and 20")
                    if args.time_filter not in (None, "today", "week", "month"):
                        raise ValueError("invalid time filter")
            elif args.command == "read":
                interactive_source_id = _configured_source_id(state, args.source)
                if not _safe_id(args.resource_id):
                    raise ValueError("resource ID must be safe")
            elif args.command == "claim":
                selected_identity = _selected_identity_for(state, args.article_id)
                result = claim(state, selected_identity)
                if "claim_id" in result:
                    save_state(path, state)
            elif args.command == "renew":
                selected_identity = _selected_identity_for(state, args.article_id)
                result = renew(state, selected_identity, args.claim_id)
                save_state(path, state)
            elif args.command == "pending":
                result = _configured_pending(state)
            elif args.command == "ack":
                selected_identity = _selected_identity_for(state, args.article_id)
                result = ack(state, selected_identity, claim_id=args.claim_id); save_state(path, state)
            elif args.command == "fail":
                selected_identity = _selected_identity_for(state, args.article_id)
                result = fail(state, selected_identity, args.reason, claim_id=args.claim_id); save_state(path, state)
            elif args.command == "status":
                result = status(state)
            else:
                if args.command == "scan":
                    if not state["sources"]:
                        result = {"error": "configure at least one source before scan"}
                    else:
                        state["next_scan_seq"] += 1
                        scan_generation = state["next_scan_seq"]
                        save_state(path, state)
                elif args.command == "markdown":
                    markdown_identity = _selected_identity_for(state, args.article_id)
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
            elif args.command == "search-sources":
                result = search_sources(
                    client, args.name,
                    before_attempt=_durable_reservation(path, "source_search"),
                )
            elif args.command == "follow":
                result = follow_selected_sources(
                    client,
                    args.source_id,
                    before_attempt=_durable_reservation(path, "onboarding_follow"),
                )
            elif args.command in ("latest", "recent"):
                interactive = interactive_articles(
                    state,
                    client,
                    interactive_source_id,
                    1 if args.command == "latest" else args.limit,
                    time_filter=None if args.command == "latest" else args.time_filter,
                    before_attempt=_durable_reservation(path, "subscription"),
                )
                with state_lock(path):
                    fresh_state = _load_locked_state(path)
                    fresh_source = fresh_state["sources"].get(interactive_source_id)
                    if fresh_source is None:
                        raise StateError("configured source changed during interactive request")
                    cached_name = state["sources"][interactive_source_id]["name"]
                    if cached_name != interactive_source_name and fresh_source["name"] == interactive_source_name:
                        fresh_source["name"] = cached_name
                        save_state(path, fresh_state)
                if args.command == "latest":
                    result = {
                        "source": interactive["source"],
                        "article": interactive["articles"][0],
                        "warnings": interactive["warnings"],
                    }
                else:
                    result = interactive
            elif args.command == "read":
                result = read_article(
                    state, client, args.resource_id, interactive_source_id,
                    metadata_attempt=_durable_reservation(
                        path, "resource_metadata", configured_source_id=interactive_source_id,
                    ),
                    markdown_attempt=_durable_reservation(
                        path, "markdown", body=True, configured_source_id=interactive_source_id,
                    ),
                    validate_source=_durable_source_validation(path, interactive_source_id),
                )
            elif args.command == "scan":
                observation = _scan_observation(
                    client, before_attempt=_durable_reservation(path, "subscription"),
                    sources=state["sources"],
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
