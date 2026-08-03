#!/usr/bin/env python3
"""Read and normalize one BestBlogs public or personal brief without retaining content."""

import argparse
import http.client
import ipaddress
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
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
MAX_HISTORY_EDITIONS = 30
API_KEY = re.compile(r"^bb_[0-9A-Fa-f]{32}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
STABLE_STATUSES = frozenset(("COMPLETED", "PUBLISHED"))
CONTENT_TYPES = frozenset(("ARTICLE", "NEWSLETTER", "PODCAST", "VIDEO", "TWITTER"))
PUBLIC_LANGUAGES = frozenset(("zh", "en"))
MAX_READ_TIME_MINUTES = 1_440
MIN_SCORE = -1_000_000
MAX_SCORE = 1_000_000
DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ZONED_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
NUMERIC_HOST_LABEL = re.compile(r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)$")
BLOCKED_HOST_SUFFIXES = frozenset((
    "bestblogs.dev", "localhost", "local", "internal", "intranet", "private", "invalid", "localdomain",
    "lan", "home", "corp", "arpa", "svc", "onion", "test", "example", "nip.io", "sslip.io", "xip.io",
    "localtest.me", "lvh.me", "localhost.direct", "local.gd", "vcap.me", "traefik.me", "my.local-ip.co",
    "local-ip.sh", "nar0.com",
))
COVER_EXACT_HOSTS = frozenset((
    "image.jido.dev", "storage.googleapis.com", "res.infoq.com", "pbs.twimg.com", "mmbiz.qpic.cn",
))
COVER_HOST_SUFFIXES = frozenset(("ytimg.com",))
IPV4_RELAY_NETWORK = ipaddress.ip_network("192.88.99.0/24")
SIX_TO_FOUR_NETWORK = ipaddress.ip_network("2002::/16")
NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


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
    if not isinstance(value, str) or "\x00" in value:
        raise BriefError("invalid %s" % description)
    value = value.strip()
    if not value or len(value) > 16_384:
        raise BriefError("invalid %s" % description)
    return value


def _optional_text(value, description):
    if value is None:
        return None
    return _required_text(value, description)


def _validated_timestamp(value, description):
    value = _required_text(value, description)
    if not ZONED_TIMESTAMP.fullmatch(value):
        raise BriefError("invalid %s" % description)
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BriefError("invalid %s" % description) from error
    return _utc_timestamp_text(moment)


def _validated_date(value, description):
    if not isinstance(value, str) or not DATE_TEXT.fullmatch(value):
        raise BriefError("invalid %s" % description)
    try:
        normalized = datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise BriefError("invalid %s" % description) from error
    if normalized != value:
        raise BriefError("invalid %s" % description)
    return value


def _is_public_ip(address):
    if getattr(address, "scope_id", None) is not None or not address.is_global or address.is_multicast \
            or address.is_unspecified or address.is_reserved or address.is_private or address.is_loopback \
            or address.is_link_local:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address not in IPV4_RELAY_NETWORK
    if address in SIX_TO_FOUR_NETWORK:
        return False
    mapped = address.ipv4_mapped
    if mapped is not None and not _is_public_ip(mapped):
        return False
    teredo = address.teredo
    if teredo is not None and not all(_is_public_ip(component) for component in teredo):
        return False
    for network in NAT64_NETWORKS:
        if address in network:
            embedded = ipaddress.IPv4Address(int(address) & 0xffffffff)
            if not _is_public_ip(embedded):
                return False
    return True


def _optional_https_url(value, description):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4096 or "#" in value or any(
            char.isspace() or ord(char) <= 0x1f or ord(char) == 0x7f or char == "\\" for char in value):
        raise BriefError("invalid %s HTTPS URL" % description)
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        bracketed = parsed.netloc.startswith("[")
        if parsed.scheme != "https" or not hostname or parsed.username is not None or parsed.password is not None \
                or parsed.port is not None or parsed.fragment:
            raise BriefError("invalid %s HTTPS URL" % description)
        if (bracketed and not re.fullmatch(r"\[[^\]]+\]", parsed.netloc)) or \
                (not bracketed and ":" in parsed.netloc):
            raise BriefError("invalid %s HTTPS URL" % description)
        try:
            address = ipaddress.ip_address(hostname)
            if (isinstance(address, ipaddress.IPv4Address) and bracketed) or \
                    (isinstance(address, ipaddress.IPv6Address) and not bracketed) or \
                    hostname.lower() != address.compressed.lower() or not _is_public_ip(address):
                raise BriefError("invalid %s HTTPS URL" % description)
        except ValueError as error:
            if bracketed:
                raise BriefError("invalid %s HTTPS URL" % description) from error
            hostname = hostname.encode("idna").decode("ascii").lower()
            labels = hostname.split(".")
            if len(hostname) > 253 or hostname.endswith(".") or len(labels) < 2 or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in labels) or all(NUMERIC_HOST_LABEL.fullmatch(label) for label in labels):
                raise BriefError("invalid %s HTTPS URL" % description)
            if hostname in BLOCKED_HOST_SUFFIXES or any(
                    hostname.endswith("." + suffix) for suffix in BLOCKED_HOST_SUFFIXES):
                raise BriefError("invalid %s HTTPS URL" % description)
    except ValueError as error:
        raise BriefError("invalid %s HTTPS URL" % description) from error
    return value


def _authoritative_publisher_url(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise BriefError("invalid resource HTTPS URL")
    try:
        scheme = urlparse(value).scheme
    except ValueError as error:
        raise BriefError("invalid resource HTTPS URL") from error
    if scheme == "http":
        value = "https" + value[len(scheme):]
    return _optional_https_url(value, "resource")


def _optional_cover_url(value):
    value = _optional_https_url(value, "cover")
    if value is None:
        return None
    hostname = urlparse(value).hostname.encode("idna").decode("ascii").lower()
    if hostname in COVER_EXACT_HOSTS or any(
            hostname.endswith("." + suffix) for suffix in COVER_HOST_SUFFIXES):
        return value
    raise BriefError("invalid cover HTTPS URL")


def _boolean(value, description):
    if not isinstance(value, bool):
        raise BriefError("invalid %s" % description)
    return value


def _number_or_none(value, description, minimum=None, maximum=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BriefError("invalid %s" % description)
    if isinstance(value, float) and not math.isfinite(value):
        raise BriefError("invalid %s" % description)
    if minimum is not None and value < minimum:
        raise BriefError("invalid %s" % description)
    if maximum is not None and value > maximum:
        raise BriefError("invalid %s" % description)
    return value


def _string_list(value, description):
    values = _list(value, description)
    if len(values) > 1000:
        raise BriefError("invalid %s" % description)
    return [_required_text(item, description) for item in values]


def _main_points(value):
    values = _list(value, "main points")
    if len(values) > 1000:
        raise BriefError("invalid main points")
    normalized = []
    for entry in values:
        if isinstance(entry, dict):
            point = entry.get("point")
            if point is None:
                continue
            normalized.append(_required_text(point, "main points"))
        else:
            normalized.append(_required_text(entry, "main points"))
    return normalized


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _normalized_content_type(value):
    if not isinstance(value, str):
        raise BriefError("unknown content type")
    mapping = {
        "ARTICLE": "ARTICLE", "NEWSLETTER": "NEWSLETTER", "PODCAST": "PODCAST", "VIDEO": "VIDEO",
        "TWITTER": "TWITTER", "TWEET": "TWITTER",
    }
    try:
        return mapping[value.upper()]
    except KeyError as error:
        raise BriefError("unknown content type") from error


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
        body = None if payload is None else json.dumps(
            payload, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
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
            return validate_envelope(json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise BriefError("invalid JSON response from BestBlogs") from error

    def me(self):
        return self._request("GET", "/me")

    def today_brief(self):
        return self._request("GET", "/me/briefs/today")

    def brief_history(self, page=1, page_size=30):
        if isinstance(page, bool) or not isinstance(page, int) or page != 1 or \
                isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_HISTORY_EDITIONS:
            raise ValueError("brief history requires page 1 and one to %d editions" % MAX_HISTORY_EDITIONS)
        return _list(self._request("GET", "/me/briefs/history?page=%d&pageSize=%d" % (page, page_size)), "brief history")

    def public_brief(self, date, language):
        date = _validated_date(date, "public date")
        language = _validated_public_language(language)
        return self._request("GET", "/brief?date=%s&language=%s" % (date, language))

    def batch_meta(self, resource_ids):
        if not isinstance(resource_ids, list) or not resource_ids or len(resource_ids) > MAX_BATCH_SIZE or \
                any(not _safe_id(resource_id) for resource_id in resource_ids):
            raise ValueError("batch metadata requires one to 100 safe resource IDs")
        return self._request("POST", "/resources/batch-meta", {"ids": resource_ids})


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


def retrieved_at_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_timestamp_text(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _reject_json_constant(value):
    raise ValueError("non-standard JSON constant")


def _normalized_publication_time(metadata):
    timestamp = metadata.get("publishTimeStamp")
    if timestamp is not None:
        try:
            timestamp = _number_or_none(timestamp, "publish timestamp")
        except BriefError as error:
            raise BriefError("invalid publication time") from error
        try:
            if abs(timestamp) > 100_000_000_000:
                timestamp /= 1000
            return _utc_timestamp_text(datetime.fromtimestamp(timestamp, timezone.utc))
        except (OverflowError, OSError, ValueError) as error:
            raise BriefError("invalid publication time") from error

    value = _first_present(metadata.get("publishDateTimeStr"), metadata.get("publishedAt"))
    if value is None:
        return None
    return _validated_timestamp(value, "publication time")


def _metadata_records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "resources", "dataList"):
            if key in value:
                return _list(value[key], "metadata records")
    raise BriefError("invalid metadata records")


def _selection_flags(brief_item, public):
    if public:
        for field in ("deepRead", "featured", "personalized"):
            if field in brief_item:
                _boolean(brief_item[field], field)
        if brief_item.get("personalized") is True:
            raise BriefError("invalid personalized")
        return {
            "deepRead": brief_item.get("deepRead", False),
            "featured": brief_item.get("featured", True),
            "personalized": False,
        }
    return {
        "deepRead": _boolean(brief_item.get("deepRead") if "deepRead" in brief_item else None, "deepRead"),
        "featured": _boolean(brief_item.get("featured") if "featured" in brief_item else None, "featured"),
        "personalized": _boolean(brief_item.get("personalized") if "personalized" in brief_item else None, "personalized"),
    }


def _normalize_item(brief_item, metadata, public=False):
    brief_item = _object(brief_item, "brief item")
    metadata = _object(metadata, "metadata record")
    resource_id = brief_item.get("resourceId")
    metadata_id = _first_present(metadata.get("id"), metadata.get("resourceId"))
    if not _safe_id(resource_id) or metadata_id != resource_id:
        raise BriefError("invalid resource ID")
    content_type = _normalized_content_type(_first_present(
        brief_item.get("contentType"), metadata.get("resourceType"), metadata.get("contentType"),
    ))
    original_url = _first_present(
        metadata.get("originalUrl"), metadata.get("canonicalUrl"), metadata.get("publisherUrl"), metadata.get("url"),
    )
    normalized = {
        "resourceId": resource_id,
        "sourceId": _required_text(_first_present(brief_item.get("sourceId"), metadata.get("sourceId")), "source ID"),
        "sourceName": _required_text(_first_present(brief_item.get("sourceName"), metadata.get("sourceName")), "source name"),
        "title": _required_text(_first_present(brief_item.get("title"), metadata.get("title")), "title"),
        "contentType": content_type,
        "url": _authoritative_publisher_url(original_url),
        "readTime": _number_or_none(
            _first_present(metadata.get("readTime"), brief_item.get("readTime")), "read time", 0, MAX_READ_TIME_MINUTES,
        ),
        "score": _number_or_none(
            _first_present(brief_item.get("totalScore"), brief_item.get("weightedScore"), brief_item.get("score")),
            "score", MIN_SCORE, MAX_SCORE,
        ),
        "tags": _string_list(_first_present(metadata.get("tags"), brief_item.get("tags"), []), "tags"),
        "mainPoints": _main_points(_first_present(metadata.get("mainPoints"), brief_item.get("mainPoints"), [])),
    }
    normalized.update(_selection_flags(brief_item, public))
    if normalized["url"] is None:
        raise BriefError("invalid resource HTTPS URL")
    cover = _first_present(metadata.get("cover"), metadata.get("coverUrl"))
    if cover is not None:
        try:
            cover = _optional_cover_url(cover)
        except BriefError:
            cover = None
        if cover is not None:
            normalized["coverUrl"] = cover
    for source, target, description in (
        (_first_present(metadata.get("oneSentenceSummary"), brief_item.get("oneSentenceSummary")), "oneSentenceSummary", "one sentence summary"),
        (_first_present(metadata.get("summary"), brief_item.get("summary")), "summary", "summary"),
    ):
        value = _optional_text(source, description)
        if value is not None:
            normalized[target] = value
    published_at = _normalized_publication_time(metadata)
    if published_at is not None:
        normalized["publishedAt"] = published_at
    return normalized


def _normalize_brief(client, source, expected_date, clock=None, public=False):
    source = _object(source, "brief")
    brief_date = _validated_date(source.get("briefDate"), "brief date")
    if brief_date != expected_date:
        raise BriefError("brief date does not match Beijing date")
    status = source.get("status")
    if status not in STABLE_STATUSES:
        raise BriefError("brief status is not stable")
    items_value = source.get("contentItems")
    if items_value is None:
        items_value = source.get("items")
    items = _list(items_value, "brief items")
    if not items:
        raise BriefError("brief items are empty")
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
            resource_id = _first_present(entry.get("id"), entry.get("resourceId"))
            if not _safe_id(resource_id):
                raise BriefError("invalid metadata resource ID")
            if resource_id not in ids:
                raise BriefError("foreign metadata resource ID")
            if resource_id in metadata_by_id:
                raise BriefError("duplicate metadata resource ID")
            metadata_by_id[resource_id] = entry
    if set(metadata_by_id) != set(ids):
        raise BriefError("missing metadata resource ID")
    generated_at = _optional_text(source.get("generatedAt"), "generatedAt")
    if generated_at is None:
        generated_at = _validated_timestamp((retrieved_at_now if clock is None else clock)(), "retrieval timestamp")
    else:
        generated_at = _validated_timestamp(generated_at, "generatedAt")
    editor_intro = _optional_text(source.get("editorIntro"), "editor intro")
    keywords = _string_list(source.get("keywords", []), "keywords")
    return {
        "schemaVersion": 1,
        "briefDate": brief_date,
        "status": status,
        "generatedAt": generated_at,
        "editorIntro": editor_intro,
        "keywords": keywords,
        "items": [_normalize_item(entry, metadata_by_id[entry["resourceId"]], public=public) for entry in items],
    }


def read_today(client, expected_date=None, clock=None):
    expected_date = beijing_date_now() if expected_date is None else expected_date
    expected_date = _validated_date(expected_date, "Beijing date")
    require_pro(client.me())
    return _normalize_brief(client, client.today_brief(), expected_date, clock)


def _validated_public_language(value):
    if not isinstance(value, str) or value not in PUBLIC_LANGUAGES:
        raise BriefError("invalid public language")
    return value


def read_public(client, requested_date, language, clock=None):
    requested_date = _validated_date(requested_date, "public date")
    language = _validated_public_language(language)
    return _normalize_brief(
        client, client.public_brief(requested_date, language), requested_date, clock, public=True,
    )


def _select_history_brief(history, requested_date):
    matches = []
    for source in _list(history, "brief history"):
        source = _object(source, "history brief")
        if _validated_date(source.get("briefDate"), "brief date") == requested_date:
            matches.append(source)
    if not matches:
        raise BriefError("requested brief is not available in the most recent 30 editions")
    if len(matches) != 1:
        raise BriefError("requested brief date is ambiguous in history")
    source = matches[0]
    if source.get("status") not in STABLE_STATUSES:
        raise BriefError("requested history brief is not complete")
    items_value = source.get("contentItems")
    if items_value is None:
        items_value = source.get("items")
    if not _list(items_value, "brief items"):
        raise BriefError("brief items are empty")
    return source


def read_history(client, requested_date, clock=None):
    requested_date = _validated_date(requested_date, "history date")
    require_pro(client.me())
    source = _select_history_brief(client.brief_history(page=1, page_size=MAX_HISTORY_EDITIONS), requested_date)
    return _normalize_brief(client, source, requested_date, clock)


def _parser():
    parser = argparse.ArgumentParser(prog="bestblogs_brief.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    today = commands.add_parser("today")
    today.add_argument("--beijing-date")
    history = commands.add_parser("history")
    history.add_argument("--date", required=True)
    public = commands.add_parser("public")
    public.add_argument("--date", required=True)
    public.add_argument("--language", required=True, choices=sorted(PUBLIC_LANGUAGES))
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        client = BestBlogsClient(os.environ.get("BESTBLOGS_API_KEY", ""))
        if args.command == "doctor":
            tier = require_pro(client.me())
            result = {"configured": True, "tier": tier, "proAccess": True}
        elif args.command == "today":
            result = read_today(client, args.beijing_date)
        elif args.command == "public":
            result = read_public(client, args.date, args.language)
        else:
            result = read_history(client, args.date)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        return 0
    except (BriefError, ValueError) as error:
        print("bestblogs-brief: %s" % str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
