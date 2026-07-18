#!/usr/bin/env python3
"""Small, durable local state helper for the BestBlogs WeChat digest skill."""

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ supplies zoneinfo
    ZoneInfo = None


API_ORIGIN = "https://api.bestblogs.dev"
STATE_VERSION = 1
MAX_BODY_BYTES = 1_000_000
BODY_DAILY_LIMIT = 10
MAX_RECENT = 500
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SAFE_REASON = re.compile(r"^[A-Z0-9][A-Z0-9_:-]{0,63}$")


class APIError(RuntimeError):
    """A safe API error: its text never includes authentication material."""


class StateError(RuntimeError):
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
    if not isinstance(payload["code"], (int, str)) or not isinstance(payload["message"], str) or not isinstance(payload["requestId"], str):
        raise APIError("invalid BestBlogs response envelope")
    return payload["data"]


class BestBlogsClient:
    """GET-only client deliberately constrained to the fixed BestBlogs origin."""

    def __init__(self, api_key, origin=API_ORIGIN, timeout=20):
        if not isinstance(api_key, str) or len(api_key) < 8:
            raise ValueError("a valid API key is required")
        if origin != API_ORIGIN:
            raise ValueError("BestBlogs origin is fixed")
        self.api_key = api_key
        self.origin = origin
        self.timeout = timeout
        self.calls = {}
        self._opener = build_opener(_NoRedirect())

    def get(self, path, query=None):
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must be an origin-relative path")
        url = self.origin + path
        if query:
            url += "?" + urlencode(query)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != urlparse(self.origin).netloc:
            raise ValueError("request origin is not allowed")
        self.calls[path] = self.calls.get(path, 0) + 1
        request = Request(url, headers={"X-API-KEY": self.api_key, "Accept": "application/json"}, method="GET")
        for attempt in range(2):
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
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
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
            except URLError as error:
                raise APIError("BestBlogs network request failed") from error
        raise APIError("BestBlogs rate limit retry exhausted")

    def me(self):
        return self.get("/me")

    def subscription_page(self, page, page_size):
        return self.get("/resources/subscription", {"page": page, "pageSize": page_size, "days": 7})

    def markdown(self, resource_id):
        data = self.get("/resources/%s/markdown" % resource_id)
        if isinstance(data, dict):
            data = data.get("markdown", data.get("content"))
        return data


def canonical_wechat_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or not (host == "mp.weixin.qq.com" or host.endswith(".weixin.qq.com")):
        return None
    if not parsed.path.startswith("/"):
        return None
    pairs = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"from", "scene", "src"}]
    return urlunparse(("https", host, parsed.path, "", urlencode(sorted(pairs)), ""))


def _publication_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / (1000 if value > 10_000_000_000 else 1), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return _publication_time(int(value))
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
        except ValueError:
            return None
    return None


def parse_article(raw):
    if not isinstance(raw, dict):
        return None
    kind = raw.get("resourceType", raw.get("type", "article"))
    if isinstance(kind, str) and kind.lower() not in ("article", "wechat", "weixin"):
        return None
    source = raw.get("sourceId") or (raw.get("source") or {}).get("id")
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
    for field in ("publishTime", "publishDateTimeStr", "publishDateStr"):
        timestamp = _publication_time(raw.get(field))
        if timestamp:
            break
    return {"identity": identity, "resource_id": resource_id, "source_id": source,
            "source_name": str(raw.get("sourceName") or (raw.get("source") or {}).get("name") or source)[:200],
            "title": str(raw.get("title") or "Untitled")[:500], "url": url,
            "published_at": timestamp or "", "attempts": 0}


def new_state():
    return {"version": STATE_VERSION, "sources": {}, "pending": {}, "body_budget": {"day": "", "count": 0},
            "last_successful_scan": None, "api_calls": {}, "warnings": []}


def _validate_state(state):
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise StateError("unsupported or malformed state schema")
    required = ("sources", "pending", "body_budget", "api_calls", "warnings")
    if any(key not in state for key in required) or not isinstance(state["sources"], dict) or not isinstance(state["pending"], dict):
        raise StateError("unsupported or malformed state schema")
    if not isinstance(state["body_budget"], dict) or not isinstance(state["api_calls"], dict) or not isinstance(state["warnings"], list):
        raise StateError("unsupported or malformed state schema")
    for source_id, source in state["sources"].items():
        if not _safe_id(source_id) or not isinstance(source, dict) or not isinstance(source.get("initialized", False), bool):
            raise StateError("unsupported or malformed state schema")
        if "recent" in source and not isinstance(source["recent"], dict):
            raise StateError("unsupported or malformed state schema")
    for identity, entry in state["pending"].items():
        if not isinstance(identity, str) or not isinstance(entry, dict) or entry.get("identity") != identity:
            raise StateError("unsupported or malformed state schema")
    return state


def default_state_path():
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return Path(home) / "state" / "wechat-digest.json"


def load_state(path=None):
    path = Path(path or default_state_path())
    if not path.exists():
        return new_state()
    try:
        return _validate_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise StateError("state cannot be read safely") from error


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
    if isinstance(data, dict):
        items = data.get("dataList", [])
        return items if isinstance(items, list) else [], data
    return [], {}


def _feed_pages(client, page_size=100):
    all_items, warnings, page, expected = [], [], 1, None
    while page <= 100:
        data = client.subscription_page(page, page_size)
        items, meta = _page_items(data)
        if expected is None:
            for counter in ("total", "totalCount", "count"):
                if isinstance(meta.get(counter), int) and meta[counter] >= 0:
                    expected = meta[counter]
                    break
        all_items.extend(items)
        if expected is not None and len(all_items) >= expected:
            return all_items[:expected], True, warnings
        if not items:
            return all_items, expected is None or len(all_items) >= expected, warnings + (["feed ended before advertised total"] if expected is not None else [])
        if len(items) < page_size:
            return all_items, expected is None or len(all_items) >= expected, warnings + (["feed shorter than advertised total"] if expected is not None and len(all_items) < expected else [])
        page += 1
    return all_items, False, warnings + ["pagination safety limit reached"]


def _merge_calls(state, client):
    seen = getattr(client, "_wechat_calls_seen", {})
    for endpoint, count in getattr(client, "calls", {}).items():
        prior = int(seen.get(endpoint, 0))
        state["api_calls"][endpoint] = int(state["api_calls"].get(endpoint, 0)) + max(0, int(count) - prior)
    client._wechat_calls_seen = dict(getattr(client, "calls", {}))


def list_sources(client, page_size=100):
    records, complete, warnings = _feed_pages(client, page_size)
    sources = {}
    malformed = 0
    for raw in records:
        article = parse_article(raw)
        if not article:
            malformed += 1
            if isinstance(raw, dict):
                source_id = raw.get("sourceId") or (raw.get("source") or {}).get("id")
                source_name = raw.get("sourceName") or (raw.get("source") or {}).get("name") or source_id
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


def scan(state, client, page_size=100):
    records, complete, warnings = _feed_pages(client, page_size)
    selected = state["sources"]
    parsed, malformed = [], 0
    for raw in records:
        article = parse_article(raw)
        if article is None:
            malformed += 1
        elif article["source_id"] in selected:
            parsed.append(article)
    enqueued = 0
    by_source = {source: [] for source in selected}
    for article in parsed:
        by_source[article["source_id"]].append(article)
    for source_id, source in selected.items():
        articles = by_source[source_id]
        source["health"] = {"records": len(articles), "complete": complete,
                            "skipped": {"invalid_or_non_wechat": malformed}}
        if not source.get("initialized"):
            if complete:
                for article in articles:
                    _remember(source, article["identity"])
                source["initialized"] = True
            continue
        for article in articles:
            if article["identity"] not in source.setdefault("recent", {}) and article["identity"] not in state["pending"]:
                state["pending"][article["identity"]] = article
                enqueued += 1
            _remember(source, article["identity"])
    if malformed:
        warnings.append("skipped_malformed_records:%d" % malformed)
    if complete:
        state["last_successful_scan"] = datetime.now(timezone.utc).isoformat()
    else:
        warnings.append("partial_feed")
    state["warnings"] = warnings
    _merge_calls(state, client)
    return {"complete": complete, "enqueued": enqueued,
            "skipped": {"invalid_or_non_wechat": malformed}, "warnings": warnings}


def pending(state):
    entries = sorted(state["pending"].values(), key=lambda item: (item.get("published_at") or "", item["identity"]))
    return {"retryable": [entry for entry in entries if entry.get("attempts", 0) < 3],
            "exhausted": [entry for entry in entries if entry.get("attempts", 0) >= 3]}


def _identity_for(state, article_id):
    if article_id in state["pending"]:
        return article_id
    resource_identity = "resource:" + article_id if isinstance(article_id, str) else ""
    if resource_identity in state["pending"]:
        return resource_identity
    return article_id


def ack(state, identity):
    identity = _identity_for(state, identity)
    if identity not in state["pending"]:
        raise KeyError("unknown pending article")
    del state["pending"][identity]
    return {"acknowledged": identity}


def fail(state, identity, reason):
    identity = _identity_for(state, identity)
    if identity not in state["pending"]:
        raise KeyError("unknown pending article")
    if not isinstance(reason, str) or not SAFE_REASON.fullmatch(reason):
        raise ValueError("reason must be a bounded safe code")
    entry = state["pending"][identity]
    entry["attempts"] = min(3, int(entry.get("attempts", 0)) + 1)
    entry["last_failure_reason"] = reason
    return {"identity": identity, "attempts": entry["attempts"], "exhausted": entry["attempts"] >= 3}


def _beijing_day(now=None):
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def markdown(state, client, identity, now=None):
    identity = _identity_for(state, identity)
    entry = state["pending"].get(identity)
    if not entry:
        return {"fallback_reason": "unknown_or_not_pending"}
    if not entry.get("resource_id"):
        return {"fallback_reason": "missing_resource_id"}
    day = _beijing_day(now)
    budget = state["body_budget"]
    if budget.get("day") != day:
        budget.update({"day": day, "count": 0})
    if int(budget.get("count", 0)) >= BODY_DAILY_LIMIT:
        return {"fallback_reason": "daily_body_budget_exhausted"}
    body = client.markdown(entry["resource_id"])
    if not isinstance(body, str):
        return {"fallback_reason": "bestblogs_markdown_unavailable"}
    budget["count"] = int(budget.get("count", 0)) + 1
    _merge_calls(state, client)
    return {"markdown": body, "source": "bestblogs"}


def doctor(client, api_key=None):
    profile = client.me()
    return {"ready": True, "tier": str(profile.get("tier", "unknown"))[:80] if isinstance(profile, dict) else "unknown",
            "profile_ready": bool(profile)}


def status(state):
    items = pending(state)
    return {"configured_sources": len(state["sources"]),
            "initialized_sources": sum(bool(source.get("initialized")) for source in state["sources"].values()),
            "pending": len(state["pending"]), "retryable": len(items["retryable"]), "exhausted": len(items["exhausted"]),
            "last_successful_scan": state.get("last_successful_scan"), "api_calls": state.get("api_calls", {}),
            "warnings": state.get("warnings", [])}


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
    pending_parser = sub.add_parser("pending")
    pending_parser.set_defaults(command="pending")
    markdown_parser = sub.add_parser("markdown")
    markdown_parser.add_argument("article_id")
    ack_parser = sub.add_parser("ack")
    ack_parser.add_argument("article_id")
    fail_parser = sub.add_parser("fail")
    fail_parser.add_argument("article_id")
    fail_parser.add_argument("--reason", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    path = Path(args.state_file) if args.state_file else default_state_path()
    state = load_state(path)
    try:
        if args.command == "configure":
            result = configure_sources(state, args.source_id)
            save_state(path, state)
        elif args.command == "pending":
            result = pending(state)
        elif args.command == "ack":
            result = ack(state, args.article_id); save_state(path, state)
        elif args.command == "fail":
            result = fail(state, args.article_id, args.reason); save_state(path, state)
        elif args.command == "status":
            result = status(state)
        else:
            client = _client_from_env()
            if args.command == "doctor": result = doctor(client)
            elif args.command == "sources": result = list_sources(client)
            elif args.command == "scan": result = scan(state, client); save_state(path, state)
            else: result = markdown(state, client, args.article_id); save_state(path, state)
    except (APIError, StateError, ValueError, KeyError) as error:
        result = {"error": str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
