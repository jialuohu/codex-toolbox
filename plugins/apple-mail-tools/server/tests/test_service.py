from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import FakeBridge

from apple_mail_tools.config import RuntimePaths
from apple_mail_tools.models import AppleMailError, ErrorCode
from apple_mail_tools.service import AppleMailService


def _first_handles(service: AppleMailService) -> tuple[str, str, list[str]]:
    account = service.list_accounts().data["accounts"][0]
    mailbox = service.list_mailboxes(account["account_handle"]).data["mailboxes"][0]
    messages = service.list_messages(mailbox["mailbox_handle"], offset=0, limit=25).data["messages"]
    return (
        account["account_handle"],
        mailbox["mailbox_handle"],
        [message["message_handle"] for message in messages],
    )


def test_live_reads_use_signed_handles_and_body_windows(service: AppleMailService) -> None:
    account_handle, mailbox_handle, message_handles = _first_handles(service)
    assert "account-1" not in account_handle
    assert service.list_mailboxes(account_handle).data["count"] == 3
    listed = service.list_messages(mailbox_handle, offset=0, limit=1)
    assert listed.coverage is not None
    assert listed.coverage["source"] == "live_mail"
    body = service.get_message(message_handles[0], offset=0, max_chars=10).data
    assert body["body"] == "Alpha body"
    assert body["truncated"] is True
    with pytest.raises(AppleMailError) as tampered:
        service.get_message(f"{message_handles[0][:-1]}A", offset=0, max_chars=10)
    assert tampered.value.code is ErrorCode.INVALID_HANDLE


def test_live_resolution_rejects_stale_and_ambiguous_identities(
    private_paths: RuntimePaths, fake_bridge: FakeBridge
) -> None:
    service = AppleMailService(paths=private_paths, bridge=fake_bridge)
    account_handle, _, message_handles = _first_handles(service)
    fake_bridge.messages[("account-1", ("Inbox",))][0]["subject"] = "Changed elsewhere"
    with pytest.raises(AppleMailError) as stale:
        service.get_message(message_handles[0], offset=0, max_chars=100)
    assert stale.value.code is ErrorCode.STALE_HANDLE

    fake_bridge.accounts.append(dict(fake_bridge.accounts[0]))
    with pytest.raises(AppleMailError) as ambiguous:
        service.list_mailboxes(account_handle)
    assert ambiguous.value.code is ErrorCode.AMBIGUOUS


def test_history_sync_is_resumable_complete_and_excludes_trash(
    service: AppleMailService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apple_mail_tools.service.filevault_status", lambda: "on")
    prepared = service.prepare_index_sync(mode="auto").data
    assert prepared["mode"] == "full"
    assert prepared["mailbox_count"] == 2
    committed = service.commit_index_sync(prepared["intent_token"])
    assert committed.data["complete"] is True
    assert committed.coverage is not None
    assert committed.coverage["complete_full_history"] is True
    results = service.search_history("Alpha", limit=25)
    assert results.data["count"] == 1
    assert results.data["results"][0]["locations"][0]["live_status"] == "unvalidated"
    assert results.coverage is not None
    assert results.coverage["live_revalidation_required"] is True
    with pytest.raises(AppleMailError) as replay:
        service.commit_index_sync(prepared["intent_token"])
    assert replay.value.code is ErrorCode.INTENT_USED


def test_history_sync_stops_at_500_and_resumes(
    service: AppleMailService,
    fake_bridge: FakeBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apple_mail_tools.service.filevault_status", lambda: "on")
    template = fake_bridge.messages[("account-1", ("Inbox",))][0]
    rows = []
    for native_id in range(1, 521):
        row = dict(template)
        row.update(
            native_id=native_id,
            rfc_message_id=f"message-{native_id}@example.edu",
            subject=f"History message {native_id}",
            body=f"history body {native_id}",
        )
        rows.append(row)
    fake_bridge.messages[("account-1", ("Inbox",))] = rows
    fake_bridge.mailboxes["account-1"][0]["message_count"] = len(rows)

    first_intent = service.prepare_index_sync(mode="full").data["intent_token"]
    first = service.commit_index_sync(first_intent).data
    assert first["processed_message_locations"] == 500
    assert first["complete"] is False
    second_intent = service.prepare_index_sync(mode="full").data["intent_token"]
    second = service.commit_index_sync(second_intent).data
    assert second["processed_message_locations"] == 20
    assert second["complete"] is True
    assert service.index_status().data["message_locations"] == 520


def test_history_search_deduplicates_message_id_and_keeps_locations(
    service: AppleMailService,
    fake_bridge: FakeBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apple_mail_tools.service.filevault_status", lambda: "on")
    duplicate = dict(fake_bridge.messages[("account-1", ("Inbox",))][0])
    duplicate["native_id"] = 201
    fake_bridge.messages[("account-1", ("Archive",))].append(duplicate)
    fake_bridge.mailboxes["account-1"][1]["message_count"] = 1
    prepared = service.prepare_index_sync(mode="full").data
    assert service.commit_index_sync(prepared["intent_token"]).data["complete"] is True
    results = service.search_history("Alpha", limit=25).data["results"]
    assert len(results) == 1
    assert len(results[0]["locations"]) == 2


def test_index_is_blocked_without_filevault(
    service: AppleMailService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apple_mail_tools.service.filevault_status", lambda: "off")
    with pytest.raises(AppleMailError) as blocked:
        service.prepare_index_sync(mode="full")
    assert blocked.value.code is ErrorCode.INDEX_DISABLED


def test_attachment_lease_and_visible_draft(
    service: AppleMailService,
    private_paths: RuntimePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_handle, _, message_handles = _first_handles(service)
    attachments = service.list_attachments(message_handles[0]).data["attachments"]
    fetched = service.fetch_attachment(attachments[0]["attachment_handle"]).data
    assert Path(fetched["path"]).read_bytes() == b"hello mail\n"
    assert service.release_attachment(fetched["lease_token"]).data["released"] is True
    assert not Path(fetched["path"]).exists()

    home = Path.home()
    document = home / "Documents" / "draft.txt"
    document.parent.mkdir(parents=True)
    document.write_text("attachment")
    draft = service.create_draft(
        account_handle=account_handle,
        draft_type="new",
        source_message_handle=None,
        to=["teacher@example.edu"],
        cc=[],
        bcc=[],
        subject="Draft subject",
        body="Draft body",
        attachment_paths=[str(document)],
    ).data
    assert draft["visible"] is True
    assert draft["sent"] is False
    assert draft["attachment_count"] == 1


def test_mutations_preview_commit_replay_and_batch_message_id_guard(
    service: AppleMailService, fake_bridge: FakeBridge
) -> None:
    _, _, handles = _first_handles(service)
    prepared = service.prepare_mutation(
        action="mark_read", message_handles=[handles[0]], destination_mailbox_handle=None
    ).data
    assert prepared["target_count"] == 1
    committed = service.commit_mutation(prepared["intent_token"])
    assert committed.data["complete"] is True
    assert committed.data["succeeded"][0]["read_status"] is True
    with pytest.raises(AppleMailError) as replay:
        service.commit_mutation(prepared["intent_token"])
    assert replay.value.code is ErrorCode.INTENT_USED

    fake_bridge.messages[("account-1", ("Inbox",))][1]["rfc_message_id"] = None
    _, _, refreshed = _first_handles(service)
    with pytest.raises(AppleMailError) as missing_id:
        service.prepare_mutation(
            action="trash", message_handles=refreshed, destination_mailbox_handle=None
        )
    assert missing_id.value.code is ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppleMailError) as oversized_batch:
        service.prepare_mutation(
            action="flag",
            message_handles=[refreshed[0]] * 21,
            destination_mailbox_handle=None,
        )
    assert oversized_batch.value.code is ErrorCode.VALIDATION_ERROR


def test_batch_mutation_reports_exact_partial_state(
    private_paths: RuntimePaths,
) -> None:
    class RacingBridge(FakeBridge):
        def invoke(
            self,
            action: str,
            params: dict[str, Any] | None = None,
            *,
            timeout: float = 60,
        ) -> dict[str, Any]:
            result = super().invoke(action, params, timeout=timeout)
            if action == "mutate_message" and params is not None and params["native_id"] == 101:
                self.messages[("account-1", ("Inbox",))][1]["subject"] = "Changed elsewhere"
            return result

    bridge = RacingBridge()
    template = dict(bridge.messages[("account-1", ("Inbox",))][1])
    template.update(native_id=103, rfc_message_id="third@example.edu", subject="Third")
    bridge.messages[("account-1", ("Inbox",))].append(template)
    service = AppleMailService(paths=private_paths, bridge=bridge)
    _, _, handles = _first_handles(service)
    prepared = service.prepare_mutation(
        action="mark_read", message_handles=handles, destination_mailbox_handle=None
    ).data
    result = service.commit_mutation(prepared["intent_token"])
    assert result.error is not None
    assert result.error.code is ErrorCode.PARTIAL_SUCCESS
    assert len(result.data["succeeded"]) == 1
    assert len(result.data["failed"]) == 1
    assert len(result.data["unattempted"]) == 1


def test_trash_is_a_recoverable_move_not_delete(
    service: AppleMailService, fake_bridge: FakeBridge
) -> None:
    _, _, handles = _first_handles(service)
    prepared = service.prepare_mutation(
        action="trash", message_handles=[handles[0]], destination_mailbox_handle=None
    ).data
    assert prepared["targets"][0]["destination_path"] == ["Deleted Items"]
    committed = service.commit_mutation(prepared["intent_token"])
    assert committed.data["complete"] is True
    assert len(fake_bridge.messages[("account-1", ("Deleted Items",))]) == 1
    assert any(action == "find_message" for action, _ in fake_bridge.calls)
    moved_handle = committed.data["succeeded"][0]["message_handle"]
    moved = service.get_message(moved_handle, offset=0, max_chars=100).data
    assert moved["subject"] == "Alpha project"


def test_unverifiable_move_reports_unknown_outcome(private_paths: RuntimePaths) -> None:
    class UnverifiableMoveBridge(FakeBridge):
        def invoke(
            self,
            action: str,
            params: dict[str, Any] | None = None,
            *,
            timeout: float = 60,
        ) -> dict[str, Any]:
            if action == "find_message":
                raise AppleMailError(ErrorCode.NOT_FOUND, "moved message is unavailable")
            return super().invoke(action, params, timeout=timeout)

    service = AppleMailService(paths=private_paths, bridge=UnverifiableMoveBridge())
    _, _, handles = _first_handles(service)
    prepared = service.prepare_mutation(
        action="trash", message_handles=[handles[0]], destination_mailbox_handle=None
    ).data
    result = service.commit_mutation(prepared["intent_token"])
    assert result.error is not None
    assert result.error.code is ErrorCode.OUTCOME_UNKNOWN
    assert result.data["succeeded"] == []
    assert result.data["failed"][0]["code"] == ErrorCode.OUTCOME_UNKNOWN.value
