#!/usr/bin/env python3
"""Read and normalize one BestBlogs personal brief without retaining content."""

import argparse
import http.client
import json
import os
import re
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9 includes zoneinfo
    ZoneInfo = None


API_ORIGIN = "https://api.bestblogs.dev/openapi/v2"
MAX_RESPONSE_BYTES = 1_000_000
MAX_BATCH_SIZE = 100
API_KEY = re.compile(r"^bb_[0-9A-Fa-f]{32}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
STABLE_STATUSES = frozenset(("COMPLETED", "PUBLISHED"))
CONTENT_TYPES = frozenset(("ARTICLE", "VIDEO", "TWITTER"))


class BriefError(RuntimeError):
    """A bounded user-facing failure that never includes remote payloads."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_id(value):
    return isinstance(value, str) and bool(SAFE_ID.fullmatch(value))


def _object(value, description):
    if not isinstance(value, dict):
        raise BriefError("invalid %s" % description)
    return value


def _list(value, description):
    if not isinstance(value, list):
        raise BriefError("invalid %s" % description)
    return value


def _required_text(value, description):
    if not isinstance(value, str) or not value or len(value) > 16_384 or "\x00" in value:
        raise BriefError("invalid %s" % description)
    return value


def _optional_text(value, description):
    if value is None:
        return None
    return _required_text(value, description)


def _optional_https_url(value, description):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise BriefError("invalid %s HTTPS URL" % description)
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise BriefError("invalid %s HTTPS URL" % description)
        parsed.port
    except ValueError as error:
        raise BriefError("invalid %s HTTPS URL" % description) from error
    return value


def _boolean(value, description):
    if not isinstance(value, bool):
        raise BriefError("invalid %s" % description)
    return value


def _number_or_none(value, description):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BriefError("invalid %s" % description)
    return value


def _string_list(value, description):
    values = _list(value, description)
    if len(values) > 1000:
        raise BriefError("invalid %s" % description)
    return [_required_text(item, description) for item in values]


def validate_envelope(payload):
    payload = _object(payload, "BestBlogs response envelope")
    expected = {"success", "code", "message", "requestId", "data"}
    if not expected.issubset(payload) or payload["success"] is not True or not isinstance(payload["requestId"], str):
        raise BriefError("invalid BestBlogs response envelope")
    if payload["code"] is not None and not isinstance(payload["code"], (int, str)):
        raise BriefError("invalid BestBlogs response envelope")
    if payload["message"] is not None and not isinstance(payload["message"], str):
        raise BriefError("invalid BestBlogs response envelope")
    return payload["data"]


class BestBlogsClient:
    """Fixed-origin, read-only BestBlogs HTTP client."""

    def __init__(self, api_key, origin=API_ORIGIN, timeout=20):
        if not isinstance(api_key, str) or not API_KEY.fullmatch(api_key):
            raise ValueError("invalid BestBlogs API key")
        if origin != API_ORIGIN:
            raise ValueError("BestBlogs origin is fixed")
        self.api_key = api_key
        self.origin = origin
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _request(self, method, path, payload=None):
        if method not in ("GET", "POST") or not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("invalid BestBlogs request")
        url = self.origin + path
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"X-API-KEY": self.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if response.geturl() != url or not 200 <= response.getcode() < 300:
                    raise BriefError("BestBlogs HTTP request failed")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise BriefError("BestBlogs HTTP request failed") from error
        except (URLError, http.client.HTTPException, OSError) as error:
            raise BriefError("BestBlogs network request failed") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BriefError("BestBlogs response exceeds size limit")
        try:
            return validate_envelope(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise BriefError("invalid JSON response from BestBlogs") from error

    def me(self):
        return self._request("GET", "/me")

    def today_brief(self):
        return self._request("GET", "/me/briefs/today")

    def batch_meta(self, resource_ids):
        if not isinstance(resource_ids, list) or not resource_ids or len(resource_ids) > MAX_BATCH_SIZE or \
                any(not _safe_id(resource_id) for resource_id in resource_ids):
            raise ValueError("batch metadata requires one to 100 safe resource IDs")
        return self._request("POST", "/resources/batch-meta", {"resourceIds": resource_ids})


def _account_tier(account):
    account = _object(account, "account")
    tier = account.get("userTier", account.get("tier"))
    if not isinstance(tier, str) or not tier:
        raise BriefError("invalid account tier")
    return tier


def require_pro(account):
    tier = _account_tier(account)
    if tier.upper() != "PRO":
        raise BriefError("BestBlogs Pro access is required")
    return tier.upper()


def beijing_date_now():
    if ZoneInfo is None:
        raise BriefError("Asia/Shanghai timezone support is unavailable")
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _metadata_records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "resources", "dataList"):
            if key in value:
                return _list(value[key], "metadata records")
    raise BriefError("invalid metadata records")


def _normalize_item(brief_item, metadata):
    brief_item = _object(brief_item, "brief item")
    metadata = _object(metadata, "metadata record")
    resource_id = brief_item.get("resourceId")
    if not _safe_id(resource_id) or metadata.get("resourceId") != resource_id:
        raise BriefError("invalid resource ID")
    content_type = metadata.get("contentType")
    if not isinstance(content_type, str) or content_type.upper() not in CONTENT_TYPES:
        raise BriefError("unknown content type")
    normalized = {
        "resourceId": resource_id,
        "sourceId": _required_text(metadata.get("sourceId"), "source ID"),
        "sourceName": _required_text(metadata.get("sourceName"), "source name"),
        "title": _required_text(metadata.get("title"), "title"),
        "contentType": content_type.upper(),
        "url": _optional_https_url(metadata.get("url"), "resource"),
        "readTime": _number_or_none(metadata.get("readTime"), "read time"),
        "score": _number_or_none(brief_item.get("score"), "score"),
        "tags": _string_list(brief_item.get("tags", []), "tags"),
        "mainPoints": _string_list(brief_item.get("mainPoints", []), "main points"),
        "deepRead": _boolean(brief_item.get("deepRead", False), "deepRead"),
        "featured": _boolean(brief_item.get("featured", False), "featured"),
        "personalized": _boolean(brief_item.get("personalized", False), "personalized"),
    }
    if normalized["url"] is None:
        raise BriefError("invalid resource HTTPS URL")
    for source, target, description in (
        (metadata.get("coverUrl"), "coverUrl", "cover"),
        (metadata.get("publishedAt"), "publishedAt", "publishedAt"),
        (brief_item.get("oneSentenceSummary"), "oneSentenceSummary", "one sentence summary"),
        (brief_item.get("summary"), "summary", "summary"),
    ):
        if target == "coverUrl":
            value = _optional_https_url(source, description)
        else:
            value = _optional_text(source, description)
        if value is not None:
            normalized[target] = value
    return normalized


def read_today(client, expected_date=None):
    expected_date = beijing_date_now() if expected_date is None else expected_date
    try:
        datetime.strptime(expected_date, "%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise BriefError("invalid Beijing date") from error
    require_pro(client.me())
    source = _object(client.today_brief(), "today brief")
    brief_date = source.get("briefDate")
    if not isinstance(brief_date, str) or brief_date != expected_date:
        raise BriefError("brief date does not match Beijing date")
    status = source.get("status")
    if status not in STABLE_STATUSES:
        raise BriefError("brief status is not stable")
    items = _list(source.get("items"), "brief items")
    ids = []
    for entry in items:
        entry = _object(entry, "brief item")
        resource_id = entry.get("resourceId")
        if not _safe_id(resource_id):
            raise BriefError("invalid resource ID")
        if resource_id in ids:
            raise BriefError("duplicate resource ID in brief")
        ids.append(resource_id)
    metadata_by_id = {}
    for start in range(0, len(ids), MAX_BATCH_SIZE):
        for entry in _metadata_records(client.batch_meta(ids[start:start + MAX_BATCH_SIZE])):
            entry = _object(entry, "metadata record")
            resource_id = entry.get("resourceId")
            if not _safe_id(resource_id):
                raise BriefError("invalid metadata resource ID")
            if resource_id not in ids:
                raise BriefError("foreign metadata resource ID")
            if resource_id in metadata_by_id:
                raise BriefError("duplicate metadata resource ID")
            metadata_by_id[resource_id] = entry
    if set(metadata_by_id) != set(ids):
        raise BriefError("missing metadata resource ID")
    generated_at = _required_text(source.get("generatedAt"), "generatedAt")
    editor_intro = _optional_text(source.get("editorIntro"), "editor intro")
    keywords = _string_list(source.get("keywords", []), "keywords")
    return {
        "schemaVersion": 1,
        "briefDate": brief_date,
        "status": status,
        "generatedAt": generated_at,
        "editorIntro": editor_intro,
        "keywords": keywords,
        "items": [_normalize_item(entry, metadata_by_id[entry["resourceId"]]) for entry in items],
    }


def _parser():
    parser = argparse.ArgumentParser(prog="bestblogs_brief.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    today = commands.add_parser("today")
    today.add_argument("--beijing-date")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        client = BestBlogsClient(os.environ.get("BESTBLOGS_API_KEY", ""))
        if args.command == "doctor":
            tier = require_pro(client.me())
            result = {"configured": True, "tier": tier, "proAccess": True}
        else:
            result = read_today(client, args.beijing_date)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (BriefError, ValueError) as error:
        print("bestblogs-brief: %s" % str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
