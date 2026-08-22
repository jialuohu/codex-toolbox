from __future__ import annotations

from typing import cast

import pytest
from pydantic import JsonValue, ValidationError

from docmost_tools.models import (
    CurrentUser,
    ErrorCode,
    OperationError,
    OperationResult,
    Page,
    PageContentPatchResult,
    PageContentResult,
    PageTextEditResult,
    PdfAttachmentResult,
    UploadedPdf,
)


def test_success_result_contains_data_and_no_error() -> None:
    result = OperationResult[dict[str, str]].success({"space_id": "space-1"})

    assert result.ok is True
    assert result.data == {"space_id": "space-1"}
    assert result.error is None


def test_failure_result_contains_stable_error_payload() -> None:
    result = OperationResult[object].failure(
        ErrorCode.CONFIGURATION_INVALID,
        "DOCMOST_BASE_URL must be configured.",
        retryable=False,
    )

    assert result.ok is False
    assert result.data is None
    assert result.error == OperationError(
        code=ErrorCode.CONFIGURATION_INVALID,
        message="DOCMOST_BASE_URL must be configured.",
        retryable=False,
    )


def test_result_rejects_mismatched_success_state() -> None:
    with pytest.raises(ValidationError, match="successful result"):
        OperationResult[dict[str, str]](
            ok=True,
            error=OperationError(
                code=ErrorCode.INTERNAL_ERROR,
                message="unexpected",
            ),
        )


def test_error_codes_are_stable_wire_values() -> None:
    assert ErrorCode.CONFIGURATION_INVALID.value == "configuration_invalid"
    assert ErrorCode.AUTH_REQUIRED.value == "auth_required"
    assert ErrorCode.PROFILE_BUSY.value == "profile_busy"
    assert ErrorCode.WRITE_COMPATIBILITY_BLOCKED.value == "write_compatibility_blocked"
    assert ErrorCode.FORBIDDEN.value == "forbidden"
    assert ErrorCode.PAGE_UNAVAILABLE.value == "page_unavailable"
    assert ErrorCode.CONFLICT.value == "conflict"
    assert ErrorCode.INVALID_PATCH.value == "invalid_patch"
    assert ErrorCode.OUTCOME_UNKNOWN.value == "outcome_unknown"
    assert ErrorCode.PARTIAL_SUCCESS.value == "partial_success"
    assert ErrorCode.INVALID_MARKDOWN.value == "invalid_markdown"
    assert ErrorCode.ATTACHMENT_UNAVAILABLE.value == "attachment_unavailable"
    assert ErrorCode.UNSUPPORTED_ATTACHMENT.value == "unsupported_attachment"
    assert ErrorCode.ATTACHMENT_TOO_LARGE.value == "attachment_too_large"
    assert ErrorCode.FORBIDDEN_PATH.value == "forbidden_path"
    assert ErrorCode.UPSTREAM_ERROR.value == "upstream_error"
    assert ErrorCode.INTERNAL_ERROR.value == "internal_error"


def test_pdf_attachment_result_enforces_verified_and_partial_states() -> None:
    verified = UploadedPdf(
        id="attachment-1",
        page_id="page-1",
        filename="report.pdf",
        size_bytes=42,
        sha256="a" * 64,
        checksum_verified=True,
        url="/api/files/attachment-1/report.pdf",
    )
    linked = PdfAttachmentResult(
        page=Page(id="page-1"),
        attachment=verified,
        link_status="linked",
        content_sha256="b" * 64,
    )

    assert linked.partial_success is False
    assert linked.attachment.media_type == "application/pdf"

    with pytest.raises(ValidationError, match="require verified"):
        PdfAttachmentResult(
            page=Page(id="page-1"),
            attachment=verified.model_copy(update={"checksum_verified": False}),
            link_status="already_linked",
            content_sha256="b" * 64,
        )
    with pytest.raises(ValidationError, match="matching page identities"):
        PdfAttachmentResult(
            page=Page(id="another-page"),
            attachment=verified,
            link_status="linked",
            content_sha256="b" * 64,
        )
    with pytest.raises(ValidationError, match="requires a partial-success warning"):
        PdfAttachmentResult(
            page=Page(id="page-1"),
            attachment=verified,
            link_status="uploaded_unlinked",
            content_sha256="b" * 64,
        )


def test_page_model_maps_v095_authoritative_slug_id() -> None:
    page = Page.model_validate({"id": "p1", "slugId": "authoritative"})

    assert page.slug_id == "authoritative"


def test_page_text_edit_result_exposes_only_summary_and_replacement_count() -> None:
    result = PageTextEditResult(page=Page(id="p1"))

    assert result.replacements == 1
    assert result.model_dump(mode="json") == {
        "page": {
            "id": "p1",
            "title": None,
            "slug_id": None,
            "space_id": None,
            "space_name": None,
            "space_slug": None,
            "parent": None,
            "position": None,
            "created_at": None,
            "updated_at": None,
            "url": None,
            "markdown": None,
            "truncated": False,
            "next_offset": None,
        },
        "replacements": 1,
    }

    with pytest.raises(ValidationError, match="must not include page content"):
        PageTextEditResult(page=Page(id="p1", markdown="private body"))


def test_page_content_models_expose_raw_reads_but_omit_write_response_bodies() -> None:
    content = cast(
        dict[str, JsonValue],
        {"type": "doc", "content": [{"type": "paragraph"}]},
    )
    digest = "a" * 64
    read_result = PageContentResult(
        page=Page(id="p1", updated_at="same"),
        content=content,
        content_sha256=digest,
    )
    patch_result = PageContentPatchResult(
        page=Page(id="p1", updated_at="newer"),
        content_sha256="b" * 64,
        operations_applied=2,
    )

    assert read_result.schema_version == "docmost.page-content.v1"
    assert read_result.content == content
    assert patch_result.operations_applied == 2
    assert "content" not in patch_result.model_dump(mode="json")

    with pytest.raises(ValidationError, match="must not include Markdown"):
        PageContentResult(
            page=Page(id="p1", markdown="private body"),
            content=content,
            content_sha256=digest,
        )
    with pytest.raises(ValidationError, match="must not include page content"):
        PageContentPatchResult(
            page=Page(id="p1", markdown="private body"),
            content_sha256=digest,
            operations_applied=1,
        )


def test_additive_upstream_fields_are_tolerated_but_not_returned_publicly() -> None:
    current = CurrentUser.model_validate(
        {
            "user": {"id": "u1", "futureSecret": "must-not-pass-through"},
            "workspace": {"id": "w1", "futureWorkspaceField": {"nested": True}},
            "futureEnvelopeField": ["unbounded", "payload"],
        }
    )

    assert current.model_dump(mode="json") == {
        "user": {"id": "u1", "name": None, "email": None},
        "workspace": {"id": "w1", "name": None, "slug": None},
    }
