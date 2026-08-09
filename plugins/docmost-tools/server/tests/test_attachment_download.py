"""Security and lifecycle tests for private Docmost attachment downloads."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import httpx
import pytest

from docmost_tools.attachment_download import AttachmentDownloadStore, AttachmentStageError
from docmost_tools.client import DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def envelope(data: object) -> dict[str, object]:
    return {"data": data, "success": True, "status": 200}


def settings() -> DocmostSettings:
    return DocmostSettings.model_validate({"base_url": "https://docs.example.test"})


def metadata(
    *,
    page_id: str = "page-canonical",
    filename: str = "paper.pdf",
    size: int = 9,
    extension: str = ".pdf",
    mime_type: str = "application/pdf",
) -> dict[str, object]:
    return {
        "id": "attachment-1",
        "fileName": filename,
        "fileSize": size,
        "fileExt": extension,
        "mimeType": mime_type,
        "type": "file",
        "pageId": page_id,
    }


def client_for(handler: httpx.MockTransport) -> DocmostReadClient:
    return DocmostReadClient(
        settings(),
        "session-secret",
        transport=handler,
        sleeper=lambda _: None,
        max_retries=0,
    )


def test_download_stages_private_pdf_with_integrity_receipt_and_idempotent_release() -> None:
    payload = b"%PDF-test"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope({"id": "page-canonical"}))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(metadata(size=len(payload))))
        return httpx.Response(
            200,
            content=payload,
            headers={"Content-Type": "application/pdf"},
        )

    client = client_for(httpx.MockTransport(handler))
    try:
        result = client.download_attachment("page-slug", "attachment-1")

        assert result.ok is True and result.data is not None
        destination = Path(result.data.local_path)
        assert destination.read_bytes() == payload
        assert result.data.filename == "paper.pdf"
        assert result.data.media_type == "application/pdf"
        assert result.data.size_bytes == len(payload)
        assert result.data.sha256 == hashlib.sha256(payload).hexdigest()
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(destination.parent.parent.stat().st_mode) == 0o700
        assert [(request.method, request.url.path) for request in seen] == [
            ("POST", "/api/pages/info"),
            ("POST", "/api/files/info"),
            ("GET", "/api/files/attachment-1/paper.pdf"),
        ]
        assert all(request.headers["cookie"] == "authToken=session-secret" for request in seen)

        released = client.release_attachment_download(result.data.download_token)
        repeated = client.release_attachment_download(result.data.download_token)
        assert released.ok is True and released.data is not None and released.data.released is True
        assert repeated.ok is True and repeated.data is not None and repeated.data.released is False
        assert not destination.exists()
    finally:
        client.close()


def test_utf8_text_is_allowed_and_invalid_utf8_is_rejected_without_a_staged_file() -> None:
    responses = [b"Review form", b"\xff\xfe"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope({"id": "page-canonical"}))
        if request.url.path == "/api/files/info":
            payload = responses[0]
            return httpx.Response(
                200,
                json=envelope(
                    metadata(
                        filename="review form.txt",
                        size=len(payload),
                        extension=".txt",
                        mime_type="text/plain",
                    )
                ),
            )
        payload = responses.pop(0)
        return httpx.Response(
            200,
            content=payload,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    client = client_for(httpx.MockTransport(handler))
    try:
        valid = client.download_attachment("page", "attachment-1")
        assert valid.ok is True and valid.data is not None
        assert Path(valid.data.local_path).read_text() == "Review form"
        assert client.release_attachment_download(valid.data.download_token).data is not None

        invalid = client.download_attachment("page", "attachment-1")
        assert invalid.ok is False and invalid.error is not None
        assert invalid.error.code is ErrorCode.UNSUPPORTED_ATTACHMENT
    finally:
        client.close()


@pytest.mark.parametrize(
    ("metadata_value", "expected_code"),
    [
        (metadata(page_id="other-page"), ErrorCode.ATTACHMENT_UNAVAILABLE),
        (metadata(filename="../paper.pdf"), ErrorCode.UNSUPPORTED_ATTACHMENT),
        (metadata(extension=".bin"), ErrorCode.UNSUPPORTED_ATTACHMENT),
        (metadata(mime_type="application/octet-stream"), ErrorCode.UNSUPPORTED_ATTACHMENT),
        (metadata(size=MAX_ATTACHMENT_BYTES + 1), ErrorCode.ATTACHMENT_TOO_LARGE),
    ],
)
def test_metadata_must_match_page_safe_name_allowed_type_and_size(
    metadata_value: dict[str, object], expected_code: ErrorCode
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope({"id": "page-canonical"}))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(metadata_value))
        pytest.fail("download request must not be sent")

    client = client_for(httpx.MockTransport(handler))
    try:
        result = client.download_attachment("page", "attachment-1")
        assert result.ok is False and result.error is not None
        assert result.error.code is expected_code
        assert requests == ["/api/pages/info", "/api/files/info"]
    finally:
        client.close()


@pytest.mark.parametrize(
    ("status", "headers", "payload", "expected_code"),
    [
        (
            302,
            {"Location": "https://elsewhere.example/file"},
            b"",
            ErrorCode.ATTACHMENT_UNAVAILABLE,
        ),
        (200, {"Content-Type": "text/plain"}, b"%PDF-test", ErrorCode.UNSUPPORTED_ATTACHMENT),
        (200, {"Content-Type": "application/pdf"}, b"not-a-pdf", ErrorCode.UNSUPPORTED_ATTACHMENT),
        (
            200,
            {"Content-Type": "application/pdf", "Content-Length": str(MAX_ATTACHMENT_BYTES + 1)},
            b"",
            ErrorCode.ATTACHMENT_TOO_LARGE,
        ),
    ],
)
def test_download_rejects_redirect_mime_signature_and_oversize(
    status: int, headers: dict[str, str], payload: bytes, expected_code: ErrorCode
) -> None:
    expected_size = len(payload) if expected_code is not ErrorCode.ATTACHMENT_TOO_LARGE else 9

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pages/info":
            return httpx.Response(200, json=envelope({"id": "page-canonical"}))
        if request.url.path == "/api/files/info":
            return httpx.Response(200, json=envelope(metadata(size=expected_size)))
        return httpx.Response(status, content=payload, headers=headers)

    client = client_for(httpx.MockTransport(handler))
    try:
        result = client.download_attachment("page", "attachment-1")
        assert result.ok is False and result.error is not None
        assert result.error.code is expected_code
        assert "session-secret" not in result.error.message
    finally:
        client.close()


def test_store_enforces_stream_cap_and_close_cleans_outstanding_files() -> None:
    store = AttachmentDownloadStore(max_bytes=8)
    with pytest.raises(AttachmentStageError, match="too_large"):
        store.stage(
            filename="paper.pdf",
            media_type="application/pdf",
            chunks=[b"%PDF-", b"toolong"],
            expected_size=12,
        )

    staged = store.stage(
        filename="paper.pdf",
        media_type="application/pdf",
        chunks=[b"%PDF-ok"],
        expected_size=7,
    )
    destination = Path(staged.local_path)
    root = destination.parent.parent
    assert destination.exists()
    store.close()
    assert not root.exists()
