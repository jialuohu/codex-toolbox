from __future__ import annotations

from pathlib import Path

import pytest

from apple_mail_tools.handles import HandleSigner, message_fingerprint
from apple_mail_tools.models import AppleMailError, ErrorCode


def test_handles_are_scoped_signed_and_tamper_evident(tmp_path: Path) -> None:
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    signer = HandleSigner(key)
    token = signer.sign("mailbox", {"account_id": "a", "mailbox_path": ["Inbox"]})

    assert signer.verify(token, "mailbox")["mailbox_path"] == ["Inbox"]
    with pytest.raises(AppleMailError) as wrong_kind:
        signer.verify(token, "message")
    assert wrong_kind.value.code is ErrorCode.INVALID_HANDLE
    replacement = "A" if token[-1] != "A" else "B"
    with pytest.raises(AppleMailError) as tampered:
        signer.verify(f"{token[:-1]}{replacement}", "mailbox")
    assert tampered.value.code is ErrorCode.INVALID_HANDLE


def test_message_fingerprint_ignores_mutable_read_and_flag_state() -> None:
    message = {
        "rfc_message_id": "id@example",
        "subject": "Subject",
        "sender": "sender@example",
        "date_received": "2026-01-01T00:00:00Z",
        "message_size": 10,
        "read_status": False,
        "flagged_status": False,
    }
    before = message_fingerprint(message)
    message.update(read_status=True, flagged_status=True)
    assert message_fingerprint(message) == before
    message["subject"] = "Changed"
    assert message_fingerprint(message) != before
