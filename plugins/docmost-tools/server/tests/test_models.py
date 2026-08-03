from __future__ import annotations

import pytest
from pydantic import ValidationError

from docmost_tools.models import CurrentUser, ErrorCode, OperationError, OperationResult, Page


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
    assert ErrorCode.OUTCOME_UNKNOWN.value == "outcome_unknown"
    assert ErrorCode.PARTIAL_SUCCESS.value == "partial_success"
    assert ErrorCode.INVALID_MARKDOWN.value == "invalid_markdown"
    assert ErrorCode.UPSTREAM_ERROR.value == "upstream_error"
    assert ErrorCode.INTERNAL_ERROR.value == "internal_error"


def test_page_model_maps_v095_authoritative_slug_id() -> None:
    page = Page.model_validate({"id": "p1", "slugId": "authoritative"})

    assert page.slug_id == "authoritative"


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
