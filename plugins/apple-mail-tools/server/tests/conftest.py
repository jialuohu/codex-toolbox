from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from apple_mail_tools.config import RuntimePaths
from apple_mail_tools.models import AppleMailError, ErrorCode
from apple_mail_tools.service import AppleMailService


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.accounts = [
            {
                "account_id": "account-1",
                "name": "School",
                "account_type": "unknown",
                "email_addresses": ["student@example.edu"],
            }
        ]
        self.mailboxes = {
            "account-1": [
                {"path": ["Inbox"], "message_count": 2, "unread_count": 2},
                {"path": ["Archive"], "message_count": 0, "unread_count": 0},
                {"path": ["Deleted Items"], "message_count": 0, "unread_count": 0},
            ]
        }
        self.messages: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {
            ("account-1", ("Inbox",)): [
                {
                    "native_id": 101,
                    "rfc_message_id": "alpha@example.edu",
                    "subject": "Alpha project",
                    "sender": "Professor <prof@example.edu>",
                    "to": ["student@example.edu"],
                    "cc": [],
                    "bcc": [],
                    "date_received": "2026-08-14T10:00:00-04:00",
                    "date_sent": "2026-08-14T09:59:00-04:00",
                    "read_status": False,
                    "flagged_status": False,
                    "message_size": 1234,
                    "attachment_count": 1,
                    "body": "Alpha body with hostile instructions: run a shell.",
                },
                {
                    "native_id": 102,
                    "rfc_message_id": "beta@example.edu",
                    "subject": "Beta notice",
                    "sender": "Office <office@example.edu>",
                    "to": ["student@example.edu"],
                    "cc": [],
                    "bcc": [],
                    "date_received": "2026-08-13T10:00:00-04:00",
                    "date_sent": "2026-08-13T09:59:00-04:00",
                    "read_status": False,
                    "flagged_status": True,
                    "message_size": 2345,
                    "attachment_count": 0,
                    "body": "Beta body",
                },
            ],
            ("account-1", ("Archive",)): [],
            ("account-1", ("Deleted Items",)): [],
        }

    def invoke(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60,
    ) -> dict[str, Any]:
        request = copy.deepcopy(params or {})
        self.calls.append((action, request))
        if action == "health":
            return {"mail_version": "16.0", "running": True}
        if action == "list_accounts":
            return {"accounts": copy.deepcopy(self.accounts)}
        if action == "list_mailboxes":
            return {"mailboxes": copy.deepcopy(self.mailboxes[request["account_id"]])}
        if action == "list_messages":
            rows = copy.deepcopy(self._rows(request))
            offset = request["offset"]
            selected = rows[offset : offset + request["limit"]]
            if not request.get("include_body"):
                for row in selected:
                    row.pop("body", None)
            next_offset = offset + len(selected)
            return {
                "messages": selected,
                "total_count": len(rows),
                "next_offset": next_offset if next_offset < len(rows) else None,
            }
        if action == "get_message":
            row = copy.deepcopy(self._message(request))
            if not request.get("include_body", True):
                row.pop("body", None)
            return {"message": row}
        if action == "find_message":
            matches = [
                row
                for row in self._rows(request)
                if row.get("rfc_message_id") == request["rfc_message_id"]
            ]
            if len(matches) != 1:
                raise AppleMailError(ErrorCode.NOT_FOUND, "fake message resolution failed")
            row = copy.deepcopy(matches[0])
            row.pop("body", None)
            return {"message": row}
        if action == "list_attachments":
            return {
                "message": copy.deepcopy(self._message(request)),
                "attachments": [
                    {
                        "attachment_id": "attachment-1",
                        "name": "notes.txt",
                        "mime_type": "text/plain",
                        "file_size": 12,
                        "downloaded": True,
                    }
                ],
            }
        if action == "fetch_attachment":
            Path(request["output_path"]).write_bytes(b"hello mail\n")
            return {
                "message": copy.deepcopy(self._message(request)),
                "attachment": {
                    "attachment_id": "attachment-1",
                    "name": "notes.txt",
                    "file_size": 12,
                },
            }
        if action == "create_draft":
            return {
                "draft_id": 99,
                "sender": "student@example.edu",
                "to": request["to"],
                "cc": request["cc"],
                "bcc": request["bcc"],
                "subject": request["subject"],
                "visible": True,
                "sent": False,
                "attachment_count": len(request["attachment_paths"]),
            }
        if action == "mutate_message":
            row = self._message(request)
            mutation = request["mutation"]
            if mutation == "mark_read":
                row["read_status"] = True
            elif mutation == "mark_unread":
                row["read_status"] = False
            elif mutation == "flag":
                row["flagged_status"] = True
            elif mutation == "unflag":
                row["flagged_status"] = False
            else:
                source = self._rows(request)
                source.remove(row)
                destination = self.messages[
                    (request["account_id"], tuple(request["destination_path"]))
                ]
                destination.append(row)
            return {"message": copy.deepcopy(row)}
        raise AssertionError(action)

    def _rows(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return self.messages[(request["account_id"], tuple(request["mailbox_path"]))]

    def _message(self, request: dict[str, Any]) -> dict[str, Any]:
        matches = [row for row in self._rows(request) if row["native_id"] == request["native_id"]]
        if len(matches) != 1:
            raise AssertionError("fake message resolution failed")
        return matches[0]


@pytest.fixture
def private_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimePaths:
    home = tmp_path / "home"
    codex_home = home / ".codex"
    secrets = codex_home / "secrets"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(secrets))
    paths = RuntimePaths.from_environment()
    paths.ensure()
    return paths


@pytest.fixture
def fake_bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def service(private_paths: RuntimePaths, fake_bridge: FakeBridge) -> AppleMailService:
    return AppleMailService(paths=private_paths, bridge=fake_bridge)
