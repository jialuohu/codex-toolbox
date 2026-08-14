from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apple_mail_tools.index import MailIndex, literal_fts_query
from apple_mail_tools.intents import IntentStore
from apple_mail_tools.models import AppleMailError, ErrorCode


def _message(native_id: int, subject: str, body: str) -> dict[str, object]:
    return {
        "native_id": native_id,
        "rfc_message_id": f"{native_id}@example",
        "fingerprint": f"fingerprint-{native_id}",
        "subject": subject,
        "sender": "sender@example",
        "to": ["to@example"],
        "cc": [],
        "bcc": [],
        "body": body,
        "date_received": "2026-01-01T00:00:00Z",
        "date_sent": "2026-01-01T00:00:00Z",
        "read_status": False,
        "flagged_status": False,
        "message_size": 10,
    }


def test_index_resumes_searches_literal_terms_and_reconciles(tmp_path: Path) -> None:
    index = MailIndex(tmp_path / "index.sqlite3")
    scopes = [{"account_id": "a", "mailbox_path": ["Inbox"]}]
    sync_id, _ = index.choose_sync("full", scopes)
    index.activate_sync(sync_id, "full", scopes)
    index.index_page(
        sync_id=sync_id,
        mode="full",
        account_id="a",
        mailbox_path=["Inbox"],
        messages=[_message(1, "Alpha", "literal OR syntax")],
        next_offset=1,
        complete=False,
    )
    assert index.checkpoint(sync_id, "a", ["Inbox"]) == (1, False)
    index.index_page(
        sync_id=sync_id,
        mode="full",
        account_id="a",
        mailbox_path=["Inbox"],
        messages=[_message(2, "Beta", "more literal text")],
        next_offset=2,
        complete=True,
    )
    assert index.finish_if_complete(sync_id, "full") is True
    assert index.status()["complete_full_history"] is True
    assert [row["native_id"] for row in index.search("Alpha", limit=10)] == [1]
    assert index.search("Alpha OR missing", limit=10) == []
    assert literal_fts_query('Alpha " OR *') == '"Alpha" AND "OR"'

    next_sync, _ = index.choose_sync("full", scopes)
    index.activate_sync(next_sync, "full", scopes)
    index.index_page(
        sync_id=next_sync,
        mode="full",
        account_id="a",
        mailbox_path=["Inbox"],
        messages=[_message(2, "Beta", "still present")],
        next_offset=1,
        complete=True,
    )
    assert index.finish_if_complete(next_sync, "full") is True
    assert index.search("Alpha", limit=10) == []
    assert index.erase()
    assert not index.exists()


def test_intents_expire_replay_and_cancel(tmp_path: Path) -> None:
    store = IntentStore(tmp_path / "intents.sqlite3")
    token = store.create("mutation", {"action": "flag"}, ttl_seconds=60)
    assert store.consume(token, "mutation") == {"action": "flag"}
    with pytest.raises(AppleMailError) as replay:
        store.consume(token, "mutation")
    assert replay.value.code is ErrorCode.INTENT_USED

    cancelled = store.create("mutation", {"action": "flag"}, ttl_seconds=60)
    assert store.cancel(cancelled, "mutation") is True
    with pytest.raises(AppleMailError) as used:
        store.consume(cancelled, "mutation")
    assert used.value.code is ErrorCode.INTENT_USED

    expired = store.create("index_sync", {"mode": "full"}, ttl_seconds=60)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE intents SET expires_at=0 WHERE token_hash<>''")
    with pytest.raises(AppleMailError) as expiry:
        store.consume(expired, "index_sync")
    assert expiry.value.code is ErrorCode.INTENT_EXPIRED
