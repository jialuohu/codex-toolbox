"""Guarded PDF upload, linkage, and recovery contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
import pytest

from docmost_tools.attachment_upload import PdfUploadValidator
from docmost_tools.client import DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode
from docmost_tools.page_content import inspect_page_content

PDF_BYTES = b"%PDF-1.4\nminimal attachment fixture\n%%EOF\n"


def envelope(data: object) -> dict[str, object]:
    return {"data": data, "success": True, "status": 200}


def page_data(
    document: dict[str, object],
    *,
    updated_at: str = "same",
) -> dict[str, object]:
    return {
        "id": "page-1",
        "slugId": "page-slug",
        "title": "Report",
        "spaceId": "space-1",
        "updatedAt": updated_at,
        "content": document,
    }


def attachment_data(*, size: int = len(PDF_BYTES)) -> dict[str, object]:
    return {
        "id": "attachment-1",
        "fileName": "report.pdf",
        "fileSize": size,
        "fileExt": ".pdf",
        "mimeType": "application/pdf",
        "type": "file",
        "pageId": "page-1",
    }


def write_pdf(home: Path) -> tuple[Path, str]:
    path = home / "reports" / "report.pdf"
    path.parent.mkdir()
    path.write_bytes(PDF_BYTES)
    return path, hashlib.sha256(PDF_BYTES).hexdigest()


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    home: Path,
    *,
    writes: bool = True,
) -> DocmostReadClient:
    values: dict[str, object] = {"base_url": "https://docs.example.test"}
    if writes:
        values["write_profile"] = "v0_95"
    return DocmostReadClient(
        DocmostSettings.model_validate(values),
        "session-secret",
        transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
        max_retries=0,
        pdf_validator=PdfUploadValidator(
            home=home,
            secrets_root=home / "codex-secrets",
        ),
    )


def download_response(content: bytes = PDF_BYTES) -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={
            "content-type": "application/pdf",
            "content-length": str(len(content)),
        },
    )


def attachment_node() -> dict[str, object]:
    return {
        "type": "attachment",
        "attrs": {
            "url": "/api/files/attachment-1/report.pdf",
            "name": "report.pdf",
            "mime": "application/pdf",
            "size": len(PDF_BYTES),
            "attachmentId": "attachment-1",
        },
    }


def test_attach_uploads_raw_response_links_and_repeats_without_duplicate(
    tmp_path: Path,
) -> None:
    source, digest = write_pdf(tmp_path)
    state: dict[str, object] = {
        "document": {"type": "doc", "content": [{"type": "paragraph"}]},
        "updated_at": "same",
        "upload_count": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(
                200,
                json=envelope(
                    page_data(
                        cast(dict[str, object], state["document"]),
                        updated_at=cast(str, state["updated_at"]),
                    )
                ),
            )
        if request.url.path == "/api/files/upload":
            state["upload_count"] = cast(int, state["upload_count"]) + 1
            assert b'name="pageId"' in request.content
            assert b"page-1" in request.content
            assert PDF_BYTES in request.content
            return httpx.Response(200, json=attachment_data())
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            assert request.url.path == "/api/files/attachment-1/report.pdf"
            return download_response()
        if request.url.path == "/api/pages/update":
            payload = cast(dict[str, object], json.loads(request.content))
            state["document"] = payload["content"]
            state["updated_at"] = "new"
            return httpx.Response(
                200,
                json=envelope(
                    page_data(
                        cast(dict[str, object], state["document"]),
                        updated_at="new",
                    )
                ),
            )
        pytest.fail(f"unexpected request: {request.method} {request.url.path}")

    with client_for(handler, tmp_path) as client:
        original = cast(dict[str, object], state["document"])
        first = client.attach_pdf_to_page(
            "page-input",
            str(source),
            digest,
            "same",
            inspect_page_content(original).content_sha256,
        )
        assert first.ok is True and first.data is not None
        assert first.data.link_status == "linked"
        assert first.data.attachment.checksum_verified is True
        assert first.data.attachment.sha256 == digest
        assert first.data.page.updated_at == "new"
        assert first.data.content_sha256 is not None

        second = client.attach_pdf_to_page(
            "page-1",
            str(source),
            digest,
            "new",
            first.data.content_sha256,
        )
        assert second.ok is True and second.data is not None
        assert second.data.link_status == "already_linked"
        assert second.data.attachment.id == first.data.attachment.id

    assert state["upload_count"] == 1


def test_stale_page_guard_stops_before_file_read_or_upload(tmp_path: Path) -> None:
    paths: list[str] = []
    document: dict[str, object] = {"type": "doc", "content": []}

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=envelope(page_data(document, updated_at="current")))

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(tmp_path / "does-not-exist.pdf"),
        "0" * 64,
        "stale",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.CONFLICT
    assert paths == ["/api/pages/info"]


@pytest.mark.parametrize(
    ("upload_result", "expected_code"),
    [
        (httpx.Response(401), ErrorCode.AUTH_REQUIRED),
        (httpx.Response(403), ErrorCode.PAGE_UNAVAILABLE),
        (httpx.Response(503), ErrorCode.OUTCOME_UNKNOWN),
        (
            httpx.Response(200, json=envelope(attachment_data())),
            ErrorCode.OUTCOME_UNKNOWN,
        ),
    ],
)
def test_upload_authorization_transient_and_enveloped_responses_are_guarded(
    tmp_path: Path,
    upload_result: httpx.Response,
    expected_code: ErrorCode,
) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        assert request.url.path == "/api/files/upload"
        return upload_result

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is expected_code


def test_upload_transport_failure_is_outcome_unknown_and_never_links(tmp_path: Path) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        raise httpx.ReadTimeout("ambiguous upload", request=request)

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert paths == ["/api/pages/info", "/api/files/upload"]


def test_known_upload_with_mismatched_metadata_keeps_recovery_id(tmp_path: Path) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    mismatched = attachment_data(size=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/upload":
            return httpx.Response(200, json=mismatched)
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "uploaded_unlinked"
    assert result.data.attachment.id == "attachment-1"
    assert result.data.attachment.size_bytes == 0
    assert result.data.attachment.checksum_verified is False
    assert result.data.warning is not None
    assert result.data.warning.details["cause"] == ErrorCode.UPSTREAM_ERROR.value


def test_post_upload_page_race_returns_recoverable_attachment_id(tmp_path: Path) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    page_reads = 0
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_reads
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            page_reads += 1
            updated = "same" if page_reads == 1 else "raced"
            return httpx.Response(200, json=envelope(page_data(document, updated_at=updated)))
        if request.url.path == "/api/files/upload":
            return httpx.Response(200, json=attachment_data())
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "uploaded_unlinked"
    assert result.data.partial_success is True
    assert result.data.attachment.id == "attachment-1"
    assert result.data.attachment.checksum_verified is True
    assert result.data.warning is not None
    assert result.data.warning.details["cause"] == ErrorCode.CONFLICT.value
    assert "/api/pages/update" not in paths


def test_post_upload_local_file_race_returns_recoverable_attachment_id(
    tmp_path: Path,
) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/upload":
            source.write_bytes(PDF_BYTES + b"changed after dispatch")
            return httpx.Response(200, json=attachment_data())
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "uploaded_unlinked"
    assert result.data.attachment.id == "attachment-1"
    assert result.data.attachment.checksum_verified is False
    assert result.data.warning is not None
    assert result.data.warning.details["cause"] == ErrorCode.CONFLICT.value
    assert paths == ["/api/pages/info", "/api/files/upload"]


def test_download_checksum_mismatch_returns_known_unlinked_upload(tmp_path: Path) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    changed = PDF_BYTES[:-1] + b"X"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/upload":
            return httpx.Response(200, json=attachment_data())
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response(changed)
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "uploaded_unlinked"
    assert result.data.attachment.id == "attachment-1"
    assert result.data.attachment.checksum_verified is False
    assert result.data.warning is not None
    assert result.data.warning.details["cause"] == ErrorCode.CONFLICT.value
    assert paths.count("/api/pages/info") == 1
    assert "/api/pages/update" not in paths


@pytest.mark.parametrize("reconciled", [True, False])
def test_ambiguous_page_update_is_read_once_and_never_redispatched(
    tmp_path: Path,
    reconciled: bool,
) -> None:
    source, digest = write_pdf(tmp_path)
    state: dict[str, object] = {
        "document": {"type": "doc", "content": []},
        "update_calls": 0,
        "page_reads": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            state["page_reads"] = cast(int, state["page_reads"]) + 1
            return httpx.Response(
                200,
                json=envelope(page_data(cast(dict[str, object], state["document"]))),
            )
        if request.url.path == "/api/files/upload":
            return httpx.Response(200, json=attachment_data())
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        if request.url.path == "/api/pages/update":
            state["update_calls"] = cast(int, state["update_calls"]) + 1
            payload = cast(dict[str, object], json.loads(request.content))
            if reconciled:
                state["document"] = payload["content"]
            raise httpx.ReadTimeout("ambiguous page update", request=request)
        pytest.fail(f"unexpected request: {request.url.path}")

    original = cast(dict[str, object], state["document"])
    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(original).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == ("linked" if reconciled else "link_unknown")
    assert result.data.partial_success is (not reconciled)
    assert state["update_calls"] == 1
    assert state["page_reads"] == 3


def test_failed_page_update_returns_uploaded_unlinked_partial(tmp_path: Path) -> None:
    source, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/upload":
            return httpx.Response(200, json=attachment_data())
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        if request.url.path == "/api/pages/update":
            return httpx.Response(409)
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).attach_pdf_to_page(
        "page-1",
        str(source),
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "uploaded_unlinked"
    assert result.data.attachment.checksum_verified is True
    assert result.data.warning is not None
    assert result.data.warning.details["cause"] == ErrorCode.CONFLICT.value


def test_link_uploaded_pdf_recovers_without_uploading_again(tmp_path: Path) -> None:
    _, digest = write_pdf(tmp_path)
    document: dict[str, object] = {"type": "doc", "content": []}
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        if request.url.path == "/api/pages/update":
            payload = cast(dict[str, object], json.loads(request.content))
            return httpx.Response(
                200,
                json=envelope(page_data(cast(dict[str, object], payload["content"]))),
            )
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).link_uploaded_pdf(
        "page-1",
        "attachment-1",
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is True and result.data is not None
    assert result.data.link_status == "linked"
    assert "/api/files/upload" not in paths
    assert paths == [
        "/api/pages/info",
        "/api/files/info",
        "/api/files/attachment-1/report.pdf",
        "/api/pages/update",
    ]


def test_duplicate_attachment_ids_stop_recovery_before_update(tmp_path: Path) -> None:
    _, digest = write_pdf(tmp_path)
    document: dict[str, object] = {
        "type": "doc",
        "content": [attachment_node(), attachment_node()],
    }
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).link_uploaded_pdf(
        "page-1",
        "attachment-1",
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.CONFLICT
    assert "/api/pages/update" not in paths


def test_nested_attachment_node_is_not_accepted_as_canonical_link(tmp_path: Path) -> None:
    _, digest = write_pdf(tmp_path)
    document: dict[str, object] = {
        "type": "doc",
        "content": [
            {
                "type": "blockquote",
                "content": [attachment_node()],
            }
        ],
    }
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope(page_data(document)))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(attachment_data()))
        if request.method == "GET":
            return download_response()
        pytest.fail(f"unexpected request: {request.url.path}")

    result = client_for(handler, tmp_path).link_uploaded_pdf(
        "page-1",
        "attachment-1",
        digest,
        "same",
        inspect_page_content(document).content_sha256,
    )

    assert result.ok is False and result.error is not None
    assert result.error.code is ErrorCode.CONFLICT
    assert "/api/pages/update" not in paths
