#!/usr/bin/env python3
"""Create or repair one bounded Zotero attachment on its configured backend."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlparse
from xml.etree import ElementTree


WEBDAV_VARIABLES = (
    "ZOTERO_WEBDAV_URL",
    "ZOTERO_WEBDAV_USERNAME",
    "ZOTERO_WEBDAV_PASSWORD",
)
ZOTERO_API_VARIABLES = (
    "ZOTERO_LIBRARY_ID",
    "ZOTERO_API_KEY",
)
ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")
DEFAULT_MIN_PDF_BYTES = 1024
DEFAULT_MAX_PDF_BYTES = 200 * 1024 * 1024
REEXEC_MARKER = "CODEX_PAPER_INTAKE_REEXEC"


class IntakeError(RuntimeError):
    """A stable, credential-free intake failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AttachmentMutationError(IntakeError):
    """A resumable failure after a concrete Zotero attachment key exists."""

    def __init__(
        self,
        code: str,
        *,
        parent_key: str,
        attachment_key: str,
        basename: str,
        stage: str,
        backend: str = "webdav",
    ) -> None:
        super().__init__(code)
        self.parent_key = parent_key
        self.attachment_key = attachment_key
        self.basename = basename
        self.stage = stage
        self.backend = backend


def _value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _provider(url: str) -> str:
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return "webdav"
    return "koofr" if hostname == "koofr.net" or hostname.endswith(".koofr.net") else "webdav"


def detect_storage(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a redacted attachment backend state derived from WebDAV variables."""

    source = os.environ if env is None else env
    present = [name for name in WEBDAV_VARIABLES if _value(source, name)]
    if not present:
        return {"backend": "zotero-cloud", "configured": True, "provider": "zotero"}
    if len(present) != len(WEBDAV_VARIABLES):
        return {
            "backend": "incomplete",
            "configured": False,
            "missing": [name for name in WEBDAV_VARIABLES if name not in present],
        }
    return {
        "backend": "webdav",
        "configured": True,
        "provider": _provider(_value(source, "ZOTERO_WEBDAV_URL")),
    }


def _parse_pdf(path: Path) -> int:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise IntakeError("pdf_parser_unavailable") from exc

    try:
        with fitz.open(path) as document:
            pages = int(document.page_count)
            if pages < 1:
                raise IntakeError("unparseable_pdf")
            document.load_page(0).get_text("text")
            return pages
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("unparseable_pdf") from exc


def _hash_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(
    file_path: str | Path,
    *,
    parser_fn: Callable[[Path], int] | None = None,
    min_bytes: int = DEFAULT_MIN_PDF_BYTES,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> dict[str, int | str]:
    """Validate a bounded regular PDF and return non-sensitive file facts."""

    path = Path(file_path)
    if path.is_symlink():
        raise IntakeError("symlink_not_allowed")
    if not path.is_file():
        raise IntakeError("pdf_not_found")
    before = path.stat()
    if before.st_size < min_bytes:
        raise IntakeError("pdf_too_small")
    if before.st_size > max_bytes:
        raise IntakeError("pdf_too_large")
    with path.open("rb") as handle:
        prefix = handle.read(1024).lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if not prefix.startswith(b"%PDF-"):
        raise IntakeError("invalid_pdf_magic")

    parser = _parse_pdf if parser_fn is None else parser_fn
    try:
        pages = int(parser(path))
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("unparseable_pdf") from exc
    if pages < 1:
        raise IntakeError("unparseable_pdf")

    md5 = _hash_file(path)
    after = path.stat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise IntakeError("pdf_changed_during_validation")
    return {
        "size": before.st_size,
        "md5": md5,
        "mtime": int(before.st_mtime * 1000),
        "pages": pages,
    }


def _validate_key(key: str) -> str:
    if not ZOTERO_KEY.fullmatch(key):
        raise IntakeError("invalid_zotero_key")
    return key


def _record_data(record: Mapping[str, Any]) -> Mapping[str, Any]:
    data = record.get("data")
    return data if isinstance(data, Mapping) else {}


def _record_key(record: Mapping[str, Any]) -> str:
    key = record.get("key")
    if isinstance(key, str) and ZOTERO_KEY.fullmatch(key):
        return key
    data = _record_data(record)
    nested = data.get("key")
    if isinstance(nested, str) and ZOTERO_KEY.fullmatch(nested):
        return nested
    raise IntakeError("attachment_record_missing_key")


def _find_attachment(
    children: Sequence[Mapping[str, Any]],
    *,
    parent_key: str,
    basename: str,
    attachment_key: str | None,
    expected_md5: str,
) -> Mapping[str, Any] | None:
    attachments = [
        child
        for child in children
        if _record_data(child).get("itemType") == "attachment"
        and _record_data(child).get("parentItem") == parent_key
    ]
    if attachment_key is not None:
        for child in attachments:
            if _record_key(child) == attachment_key:
                data = _record_data(child)
                if data.get("linkMode") != "imported_file" or data.get("contentType") not in (
                    "",
                    "application/pdf",
                    None,
                ):
                    raise IntakeError("attachment_not_imported_file_pdf")
                existing_md5 = data.get("md5")
                if existing_md5 and existing_md5 != expected_md5:
                    raise IntakeError("attachment_checksum_conflict")
                return child
        raise IntakeError("attachment_not_child_of_parent")

    matches = []
    for child in attachments:
        data = _record_data(child)
        filename = data.get("filename") or data.get("title")
        if (
            data.get("linkMode") == "imported_file"
            and data.get("contentType") in ("", "application/pdf", None)
            and isinstance(filename, str)
            and Path(filename).name == basename
        ):
            matches.append(child)
    if len(matches) > 1:
        raise IntakeError("ambiguous_attachment_children")
    if not matches:
        return None
    existing_md5 = _record_data(matches[0]).get("md5")
    if existing_md5 and existing_md5 != expected_md5:
        raise IntakeError("attachment_checksum_conflict")
    return matches[0]


def _matching_imported_pdf_children(
    children: Sequence[Mapping[str, Any]],
    *,
    parent_key: str,
    basename: str,
) -> list[Mapping[str, Any]]:
    matches: list[Mapping[str, Any]] = []
    for child in children:
        data = _record_data(child)
        filename = data.get("filename") or data.get("title")
        if (
            data.get("itemType") == "attachment"
            and data.get("parentItem") == parent_key
            and data.get("linkMode") == "imported_file"
            and data.get("contentType") in ("", "application/pdf", None)
            and isinstance(filename, str)
            and Path(filename).name == basename
        ):
            matches.append(child)
    return matches


def _created_key(result: Mapping[str, Any]) -> str:
    success = result.get("success")
    if not isinstance(success, Mapping):
        success = result.get("successful")
    if not isinstance(success, Mapping) or not success:
        raise IntakeError("attachment_metadata_create_failed")
    created = success.get("0", next(iter(success.values())))
    if isinstance(created, str):
        return _validate_key(created)
    if isinstance(created, Mapping):
        return _record_key(created)
    raise IntakeError("attachment_metadata_create_failed")


def _create_attachment(
    client: Any,
    parent_key: str,
    basename: str,
    *,
    correlation_title: str | None = None,
) -> str:
    template = client.item_template("attachment", linkmode="imported_file")
    if not isinstance(template, dict):
        raise IntakeError("attachment_template_invalid")
    template.update(
        {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "parentItem": parent_key,
            "title": correlation_title or basename,
            "contentType": "application/pdf",
            "charset": "",
            "filename": basename,
        }
    )
    result = client.create_items([template])
    if not isinstance(result, Mapping):
        raise IntakeError("attachment_metadata_create_failed")
    return _created_key(result)


def _create_attachment_with_recovery(
    client: Any,
    parent_key: str,
    basename: str,
    before: Sequence[Mapping[str, Any]],
    expected_md5: str,
) -> str:
    """Recover only this request's committed child when its response is lost."""

    before_keys = {_record_key(child) for child in before}
    correlation_title = f"codex-paper-intake:{secrets.token_hex(16)}"
    try:
        return _create_attachment(
            client,
            parent_key,
            basename,
            correlation_title=correlation_title,
        )
    except IntakeError:
        raise
    except Exception as exc:
        try:
            after = client.children(parent_key)
        except Exception as reconcile_exc:
            raise IntakeError("attachment_metadata_create_outcome_unknown") from reconcile_exc
        if not isinstance(after, list):
            raise IntakeError("attachment_metadata_create_outcome_unknown") from exc
        candidates = [
            child
            for child in _matching_imported_pdf_children(
                after,
                parent_key=parent_key,
                basename=basename,
            )
            if _record_key(child) not in before_keys
            and _record_data(child).get("title") == correlation_title
        ]
        if len(candidates) == 1:
            recovered_md5 = _record_data(candidates[0]).get("md5")
            if recovered_md5 and recovered_md5 != expected_md5:
                raise IntakeError("attachment_metadata_create_outcome_unknown") from exc
            return _record_key(candidates[0])
        if len(candidates) > 1:
            raise IntakeError("ambiguous_attachment_create") from exc
        raise IntakeError("attachment_metadata_create_outcome_unknown") from exc


def _reconcile_created_attachment(
    client: Any,
    *,
    parent_key: str,
    attachment_key: str,
    basename: str,
    backend: str,
) -> None:
    post_create = client.children(parent_key)
    if not isinstance(post_create, list):
        raise _mutation_error(
            "attachment_metadata_reconciliation_failed",
            parent_key=parent_key,
            attachment_key=attachment_key,
            basename=basename,
            stage="metadata-create",
            backend=backend,
        )
    same_name = _matching_imported_pdf_children(
        post_create,
        parent_key=parent_key,
        basename=basename,
    )
    if len(same_name) != 1 or _record_key(same_name[0]) != attachment_key:
        raise _mutation_error(
            "concurrent_attachment_conflict",
            parent_key=parent_key,
            attachment_key=attachment_key,
            basename=basename,
            stage="metadata-create",
            backend=backend,
        )


def _require_api_configuration(env: Mapping[str, str]) -> None:
    if any(not _value(env, name) for name in ZOTERO_API_VARIABLES):
        raise IntakeError("incomplete_zotero_api_configuration")


def _new_client(env: Mapping[str, str]) -> Any:
    try:
        from pyzotero import zotero  # type: ignore
    except ImportError as exc:
        raise IntakeError("zotero_runtime_unavailable") from exc
    return zotero.Zotero(
        library_id=_value(env, "ZOTERO_LIBRARY_ID"),
        library_type=_value(env, "ZOTERO_LIBRARY_TYPE") or "user",
        api_key=_value(env, "ZOTERO_API_KEY"),
        local=False,
    )


def _webdav_endpoint(env: Mapping[str, str]) -> str:
    url = _value(env, "ZOTERO_WEBDAV_URL")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise IntakeError("invalid_webdav_endpoint")
    return url.rstrip("/") + "/"


def _new_webdav_session(env: Mapping[str, str]) -> Any:
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise IntakeError("zotero_runtime_unavailable") from exc
    session = requests.Session()
    session.auth = (
        _value(env, "ZOTERO_WEBDAV_USERNAME"),
        _value(env, "ZOTERO_WEBDAV_PASSWORD"),
    )
    session.trust_env = True
    return session


def _preflight_webdav(
    env: Mapping[str, str],
    *,
    session_factory: Callable[[Mapping[str, str]], Any] | None = None,
) -> None:
    """Perform one credential-redacted, read-only WebDAV connectivity check."""

    url = _webdav_endpoint(env)
    session = (session_factory or _new_webdav_session)(env)
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
    )
    response: Any | None = None
    try:
        response = session.request(
            "PROPFIND",
            url,
            data=body.encode("utf-8"),
            headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
            timeout=(10.0, 30.0),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code != 207:
            raise IntakeError("invalid_webdav_preflight_response")
        limit = 1024 * 1024
        headers = getattr(response, "headers", {})
        content_length = headers.get("Content-Length") if isinstance(headers, Mapping) else None
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError) as exc:
                raise IntakeError("invalid_webdav_preflight_response") from exc
            if declared_length < 0 or declared_length > limit:
                raise IntakeError("invalid_webdav_preflight_response")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > limit:
                raise IntakeError("invalid_webdav_preflight_response")
        if not content:
            raise IntakeError("invalid_webdav_preflight_response")
        root = ElementTree.fromstring(bytes(content))
        if root.tag != "{DAV:}multistatus":
            raise IntakeError("invalid_webdav_preflight_response")
        responses = root.findall("{DAV:}response")
        usable = False
        for dav_response in responses:
            for status_element in dav_response.findall(".//{DAV:}status"):
                status_text = (status_element.text or "").strip()
                match = re.match(r"^HTTP/\S+\s+(\d{3})(?:\s|$)", status_text)
                if match and 200 <= int(match.group(1)) < 300:
                    usable = True
                    break
            if usable:
                break
        if not responses or not usable:
            raise IntakeError("invalid_webdav_preflight_response")
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("webdav_preflight_failed") from exc
    finally:
        close_response = getattr(response, "close", None)
        if callable(close_response):
            close_response()
        session.close()


def _webdav_upload_function() -> Callable[..., Any]:
    try:
        from zotero_mcp.webdav import upload_attachment_to_webdav  # type: ignore
    except ImportError as exc:
        raise IntakeError("zotero_runtime_unavailable") from exc
    return upload_attachment_to_webdav


def extract_bounded_webdav_zip(
    archive_path: str | Path,
    destination_dir: str | Path,
    *,
    expected_filename: str,
    max_bytes: int,
) -> Path:
    """Extract exactly one expected regular file from a bounded Zotero ZIP."""

    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            files = [member for member in archive.infolist() if not member.is_dir()]
            if len(files) != 1:
                raise IntakeError("unsafe_webdav_archive")
            member = files[0]
            member_path = Path(member.filename)
            member_mode = (member.external_attr >> 16) & 0xFFFF
            if (
                member.filename != expected_filename
                or member_path.is_absolute()
                or ".." in member_path.parts
                or member_path.name != member.filename
                or member.flag_bits & 0x1
                or stat.S_ISLNK(member_mode)
            ):
                raise IntakeError("unsafe_webdav_archive")
            if member.file_size > max_bytes:
                raise IntakeError("webdav_archive_too_large")
            if member.file_size > max(10 * 1024 * 1024, member.compress_size * 200):
                raise IntakeError("unsafe_webdav_archive")
            output = destination / expected_filename
            written = 0
            with archive.open(member) as source, output.open("xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    written += len(chunk)
                    if written > max_bytes:
                        raise IntakeError("webdav_archive_too_large")
                    target.write(chunk)
            os.chmod(output, 0o600)
            return output
    except IntakeError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise IntakeError("invalid_webdav_archive") from exc


def _download_webdav_attachment_bounded(
    attachment_key: str,
    destination_dir: str | Path,
    expected_filename: str,
    *,
    env: Mapping[str, str],
    max_bytes: int,
    session_factory: Callable[[Mapping[str, str]], Any] | None = None,
) -> Path:
    url = f"{_webdav_endpoint(env)}{quote(attachment_key, safe='')}.zip"
    session = (session_factory or _new_webdav_session)(env)
    archive_limit = max_bytes + 1024 * 1024
    archive_path: str | None = None
    try:
        response = session.get(url, timeout=(10.0, 30.0), stream=True, allow_redirects=False)
        if response.status_code != 200:
            raise IntakeError("webdav_download_failed")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > archive_limit:
            raise IntakeError("webdav_archive_too_large")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as archive_file:
            archive_path = archive_file.name
            downloaded = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > archive_limit:
                    raise IntakeError("webdav_archive_too_large")
                archive_file.write(chunk)
        return extract_bounded_webdav_zip(
            archive_path,
            destination_dir,
            expected_filename=expected_filename,
            max_bytes=max_bytes,
        )
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("webdav_download_failed") from exc
    finally:
        if archive_path:
            Path(archive_path).unlink(missing_ok=True)
        session.close()


def _verify_download(
    download_fn: Callable[..., Any],
    attachment_key: str,
    basename: str,
    expected_md5: str,
    parser_fn: Callable[[Path], int] | None,
    max_bytes: int,
) -> dict[str, int | str]:
    with tempfile.TemporaryDirectory(prefix="paper-intake-verify-") as directory:
        downloaded = Path(download_fn(attachment_key, Path(directory), basename))
        verified = validate_pdf(downloaded, parser_fn=parser_fn, max_bytes=max_bytes)
    if verified["md5"] != expected_md5:
        raise IntakeError("webdav_checksum_mismatch")
    return verified


@contextmanager
def _snapshot_pdf(
    file_path: str | Path,
    *,
    parser_fn: Callable[[Path], int] | None,
    max_bytes: int,
) -> Any:
    """Hold a private, validated snapshot stable for the complete upload transaction."""

    source = Path(file_path)
    initial = validate_pdf(source, parser_fn=parser_fn, max_bytes=max_bytes)
    with tempfile.TemporaryDirectory(prefix="paper-intake-source-") as directory:
        snapshot = Path(directory) / source.name
        shutil.copyfile(source, snapshot)
        os.chmod(snapshot, 0o400)
        stable = validate_pdf(snapshot, parser_fn=parser_fn, max_bytes=max_bytes)
        if stable["md5"] != initial["md5"]:
            raise IntakeError("pdf_changed_during_snapshot")
        yield snapshot, stable


@contextmanager
def _attachment_lock(env: Mapping[str, str], parent_key: str, basename: str) -> Any:
    """Serialize one parent transaction across local helper processes."""

    lock_root = Path(tempfile.gettempdir()) / "codex-paper-library-intake-locks"
    lock_root.mkdir(mode=0o700, exist_ok=True)
    root_stat = lock_root.lstat()
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.getuid()
        or root_stat.st_mode & 0o077
    ):
        raise IntakeError("unsafe_attachment_lock_directory")
    del basename
    identity = "\0".join((_value(env, "ZOTERO_LIBRARY_ID"), parent_key))
    lock_name = hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_root / lock_name, flags, 0o600)
    try:
        with os.fdopen(descriptor, "r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _attachment_metadata_matches(
    record: Mapping[str, Any],
    *,
    parent_key: str,
    basename: str,
    md5: str,
    mtime: int | None = None,
) -> bool:
    data = _record_data(record)
    matches = (
        _record_key(record)
        and data.get("itemType") == "attachment"
        and data.get("linkMode") == "imported_file"
        and data.get("parentItem") == parent_key
        and data.get("filename") == basename
        and data.get("title") == basename
        and data.get("contentType") == "application/pdf"
        and data.get("md5") == md5
    )
    if mtime is not None:
        matches = matches and str(data.get("mtime")) == str(mtime)
    return bool(matches)


def _mutation_error(
    code: str,
    *,
    parent_key: str,
    attachment_key: str,
    basename: str,
    stage: str,
    backend: str = "webdav",
    cause: BaseException | None = None,
) -> AttachmentMutationError:
    error = AttachmentMutationError(
        code,
        parent_key=parent_key,
        attachment_key=attachment_key,
        basename=basename,
        stage=stage,
        backend=backend,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def attach_webdav(
    *,
    parent_key: str,
    file_path: str | Path,
    attachment_key: str | None = None,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
    client_factory: Callable[[Mapping[str, str]], Any] | None = None,
    preflight_fn: Callable[[Mapping[str, str]], None] | None = None,
    upload_fn: Callable[..., Any] | None = None,
    download_fn: Callable[..., Any] | None = None,
    parser_fn: Callable[[Path], int] | None = None,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> dict[str, Any]:
    """Create or repair one imported-file attachment through Zotero WebDAV."""

    source = os.environ if env is None else env
    storage = detect_storage(source)
    if storage["backend"] == "incomplete":
        raise IntakeError("incomplete_webdav_configuration")
    if storage["backend"] != "webdav":
        raise IntakeError("webdav_backend_required")
    _require_api_configuration(source)
    parent_key = _validate_key(parent_key)
    if attachment_key is not None:
        attachment_key = _validate_key(attachment_key)

    path = Path(file_path)
    basename = path.name
    if not basename or basename in {".", ".."}:
        raise IntakeError("invalid_pdf_basename")
    if client is not None and client_factory is not None:
        raise IntakeError("conflicting_client_configuration")

    with _snapshot_pdf(path, parser_fn=parser_fn, max_bytes=max_bytes) as prepared:
        snapshot, source_pdf = prepared
        (preflight_fn or _preflight_webdav)(source)
        if client is None:
            client = (client_factory or _new_client)(source)
        if upload_fn is None:
            upload_fn = _webdav_upload_function()
        if download_fn is None:
            download_fn = lambda key, destination, filename: _download_webdav_attachment_bounded(
                key,
                destination,
                filename,
                env=source,
                max_bytes=max_bytes,
            )

        with _attachment_lock(source, parent_key, basename):
            parent = client.item(parent_key)
            if _record_data(parent).get("itemType") == "attachment":
                raise IntakeError("parent_is_attachment")
            children = client.children(parent_key)
            if not isinstance(children, list):
                raise IntakeError("invalid_children_response")
            existing = _find_attachment(
                children,
                parent_key=parent_key,
                basename=basename,
                attachment_key=attachment_key,
                expected_md5=str(source_pdf["md5"]),
            )

            if existing is not None:
                attachment_key = _record_key(existing)
                existing_data = _record_data(existing)
                if _attachment_metadata_matches(
                    existing,
                    parent_key=parent_key,
                    basename=basename,
                    md5=str(source_pdf["md5"]),
                ):
                    try:
                        verified = _verify_download(
                            download_fn,
                            attachment_key,
                            basename,
                            str(source_pdf["md5"]),
                            parser_fn,
                            max_bytes,
                        )
                    except Exception:
                        pass
                    else:
                        return {
                            "status": "unchanged",
                            "backend": "webdav",
                            "provider": storage["provider"],
                            "parent_key": parent_key,
                            "attachment_key": attachment_key,
                            "basename": basename,
                            "size": verified["size"],
                            "md5": verified["md5"],
                            "mtime": existing_data.get("mtime", source_pdf["mtime"]),
                            "pages": verified["pages"],
                        }
                status = "repaired"
            else:
                attachment_key = _create_attachment_with_recovery(
                    client,
                    parent_key,
                    basename,
                    children,
                    str(source_pdf["md5"]),
                )
                status = "created"
                _reconcile_created_attachment(
                    client,
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    backend="webdav",
                )

            try:
                upload_result = upload_fn(
                    attachment_key,
                    snapshot,
                    str(source_pdf["md5"]),
                    int(source_pdf["mtime"]),
                )
                if not (
                    isinstance(upload_result, tuple)
                    and len(upload_result) == 2
                    and isinstance(upload_result[0], str)
                ):
                    raise IntakeError("invalid_webdav_upload_response")
                stored_md5, stored_mtime = upload_result
                stored_mtime = int(stored_mtime)
                if stored_md5 != source_pdf["md5"]:
                    raise IntakeError("webdav_upload_checksum_mismatch")
            except AttachmentMutationError:
                raise
            except Exception as exc:
                raise _mutation_error(
                    "webdav_upload_failed",
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    stage="webdav-upload",
                    cause=exc,
                ) from exc

            try:
                record = client.item(attachment_key)
                if not isinstance(record, dict):
                    raise IntakeError("attachment_record_invalid")
                data = record.get("data")
                if not isinstance(data, dict):
                    raise IntakeError("attachment_record_invalid")
                data.update(
                    {
                        "itemType": "attachment",
                        "linkMode": "imported_file",
                        "parentItem": parent_key,
                        "title": basename,
                        "contentType": "application/pdf",
                        "filename": basename,
                        "md5": stored_md5,
                        "mtime": stored_mtime,
                    }
                )
                response = client.update_item(record)
                raise_for_status = getattr(response, "raise_for_status", None)
                if not callable(raise_for_status):
                    raise IntakeError("invalid_metadata_update_response")
                raise_for_status()
                persisted = client.item(attachment_key)
                if not isinstance(persisted, Mapping) or not _attachment_metadata_matches(
                    persisted,
                    parent_key=parent_key,
                    basename=basename,
                    md5=stored_md5,
                    mtime=stored_mtime,
                ):
                    raise IntakeError("attachment_metadata_not_persisted")
            except AttachmentMutationError:
                raise
            except Exception as exc:
                raise _mutation_error(
                    "zotero_metadata_update_failed",
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    stage="zotero-metadata",
                    cause=exc,
                ) from exc

            try:
                verified = _verify_download(
                    download_fn,
                    attachment_key,
                    basename,
                    stored_md5,
                    parser_fn,
                    max_bytes,
                )
            except Exception as exc:
                raise _mutation_error(
                    "webdav_verification_failed",
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    stage="webdav-verification",
                    cause=exc,
                ) from exc
            return {
                "status": status,
                "backend": "webdav",
                "provider": storage["provider"],
                "parent_key": parent_key,
                "attachment_key": attachment_key,
                "basename": basename,
                "size": verified["size"],
                "md5": stored_md5,
                "mtime": stored_mtime,
                "pages": verified["pages"],
            }


def attach_zotero_cloud(
    *,
    parent_key: str,
    file_path: str | Path,
    attachment_key: str | None = None,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
    client_factory: Callable[[Mapping[str, str]], Any] | None = None,
    parser_fn: Callable[[Path], int] | None = None,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> dict[str, Any]:
    """Create or repair one official Zotero Storage attachment on a known parent."""

    source = os.environ if env is None else env
    storage = detect_storage(source)
    if storage["backend"] == "incomplete":
        raise IntakeError("incomplete_webdav_configuration")
    if storage["backend"] != "zotero-cloud":
        raise IntakeError("zotero_cloud_backend_required")
    _require_api_configuration(source)
    parent_key = _validate_key(parent_key)
    if attachment_key is not None:
        attachment_key = _validate_key(attachment_key)
    if client is not None and client_factory is not None:
        raise IntakeError("conflicting_client_configuration")

    path = Path(file_path)
    basename = path.name
    if not basename or basename in {".", ".."}:
        raise IntakeError("invalid_pdf_basename")
    with _snapshot_pdf(path, parser_fn=parser_fn, max_bytes=max_bytes) as prepared:
        snapshot, source_pdf = prepared
        if client is None:
            client = (client_factory or _new_client)(source)
        with _attachment_lock(source, parent_key, basename):
            parent = client.item(parent_key)
            if _record_data(parent).get("itemType") == "attachment":
                raise IntakeError("parent_is_attachment")
            children = client.children(parent_key)
            if not isinstance(children, list):
                raise IntakeError("invalid_children_response")
            existing = _find_attachment(
                children,
                parent_key=parent_key,
                basename=basename,
                attachment_key=attachment_key,
                expected_md5=str(source_pdf["md5"]),
            )
            if existing is not None:
                attachment_key = _record_key(existing)
                status = "repaired"
            else:
                attachment_key = _create_attachment_with_recovery(
                    client,
                    parent_key,
                    basename,
                    children,
                    str(source_pdf["md5"]),
                )
                status = "created"
                _reconcile_created_attachment(
                    client,
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    backend="zotero-cloud",
                )

            try:
                record = client.item(attachment_key)
                if not isinstance(record, Mapping):
                    raise IntakeError("attachment_record_invalid")
                upload_payload = dict(_record_data(record))
                upload_payload.update(
                    {
                        "key": attachment_key,
                        "itemType": "attachment",
                        "linkMode": "imported_file",
                        "parentItem": parent_key,
                        "title": basename,
                        "contentType": "application/pdf",
                        "filename": basename,
                    }
                )
                result = client.upload_attachments(
                    [upload_payload],
                    basedir=snapshot.parent,
                )
                if not isinstance(result, Mapping) or result.get("failure"):
                    raise IntakeError("zotero_storage_upload_failed")
                if not result.get("success") and not result.get("unchanged"):
                    raise IntakeError("invalid_zotero_storage_upload_response")
            except Exception as exc:
                raise _mutation_error(
                    "zotero_storage_upload_failed",
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    stage="zotero-storage-upload",
                    backend="zotero-cloud",
                    cause=exc,
                ) from exc

            stored_md5 = str(source_pdf["md5"])
            stored_mtime = int(source_pdf["mtime"])
            try:
                record = client.item(attachment_key)
                if not isinstance(record, dict) or not isinstance(record.get("data"), dict):
                    raise IntakeError("attachment_record_invalid")
                record["data"].update(
                    {
                        "itemType": "attachment",
                        "linkMode": "imported_file",
                        "parentItem": parent_key,
                        "title": basename,
                        "contentType": "application/pdf",
                        "filename": basename,
                        "md5": stored_md5,
                        "mtime": stored_mtime,
                    }
                )
                response = client.update_item(record)
                raise_for_status = getattr(response, "raise_for_status", None)
                if not callable(raise_for_status):
                    raise IntakeError("invalid_metadata_update_response")
                raise_for_status()
                persisted = client.item(attachment_key)
                if not isinstance(persisted, Mapping) or not _attachment_metadata_matches(
                    persisted,
                    parent_key=parent_key,
                    basename=basename,
                    md5=stored_md5,
                    mtime=stored_mtime,
                ):
                    raise IntakeError("attachment_metadata_not_persisted")
            except Exception as exc:
                raise _mutation_error(
                    "zotero_metadata_update_failed",
                    parent_key=parent_key,
                    attachment_key=attachment_key,
                    basename=basename,
                    stage="zotero-metadata",
                    backend="zotero-cloud",
                    cause=exc,
                ) from exc
            return {
                "status": status,
                "backend": "zotero-cloud",
                "provider": "zotero",
                "parent_key": parent_key,
                "attachment_key": attachment_key,
                "basename": basename,
                "size": source_pdf["size"],
                "md5": stored_md5,
                "mtime": stored_mtime,
                "verification": "requires_zotero_read_pdf_pages",
            }


def _runtime_available() -> bool:
    try:
        import fitz  # noqa: F401
        import pyzotero  # noqa: F401
        from zotero_mcp.webdav import upload_attachment_to_webdav  # noqa: F401
    except ImportError:
        return False
    return True


def _reexec_with_zotero_runtime(argv: Sequence[str]) -> None:
    if _runtime_available():
        return
    if os.environ.get(REEXEC_MARKER) == "1":
        raise IntakeError("zotero_runtime_unavailable")
    launcher = shutil.which("zotero-mcp")
    if not launcher:
        local_bin = os.environ.get("CODEX_LOCAL_BIN_DIR", "").strip()
        candidate = Path(local_bin) / "zotero-mcp" if local_bin else None
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            launcher = str(candidate)
    if not launcher:
        raise IntakeError("zotero_runtime_unavailable")
    try:
        first_line = Path(launcher).read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError) as exc:
        raise IntakeError("zotero_runtime_unavailable") from exc
    if not first_line.startswith("#!"):
        raise IntakeError("zotero_runtime_unavailable")
    interpreter = first_line[2:].strip().split()[0]
    if not Path(interpreter).is_absolute() or not os.access(interpreter, os.X_OK):
        raise IntakeError("zotero_runtime_unavailable")
    next_env = dict(os.environ)
    next_env[REEXEC_MARKER] = "1"
    os.execve(
        interpreter,
        [interpreter, str(Path(__file__).resolve()), *argv],
        next_env,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("detect", help="print the redacted attachment backend")
    for name, help_text in (
        ("attach", "create or repair one WebDAV attachment"),
        ("attach-cloud", "create or repair one official Zotero Storage attachment"),
    ):
        attach = subparsers.add_parser(name, help=help_text)
        attach.add_argument("--parent-key", required=True)
        attach.add_argument("--file", required=True, type=Path)
        attach.add_argument("--attachment-key")
        attach.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_PDF_BYTES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(args_list)
    try:
        if args.command == "detect":
            result = detect_storage()
            if result["backend"] == "webdav":
                _reexec_with_zotero_runtime(args_list)
                _preflight_webdav(os.environ)
                result["reachable"] = True
            print(json.dumps(result, sort_keys=True))
            return 2 if result["backend"] == "incomplete" else 0
        _reexec_with_zotero_runtime(args_list)
        attach_function = attach_webdav if args.command == "attach" else attach_zotero_cloud
        result = attach_function(
            parent_key=args.parent_key,
            attachment_key=args.attachment_key,
            file_path=args.file,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except AttachmentMutationError as exc:
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "error": exc.code,
                    "backend": exc.backend,
                    "parent_key": exc.parent_key,
                    "attachment_key": exc.attachment_key,
                    "basename": exc.basename,
                    "stage": exc.stage,
                },
                sort_keys=True,
            )
        )
        return 1
    except IntakeError as exc:
        print(json.dumps({"status": "error", "error": exc.code}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"status": "error", "error": "attachment_operation_failed"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
