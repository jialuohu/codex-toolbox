"""Guarded Mail operations, indexing, leases, drafts, and mutations."""

from __future__ import annotations

import platform
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from .bridge import AppleScriptRunner
from .config import RuntimePaths, Settings
from .handles import HandleSigner, message_fingerprint
from .index import MailIndex, decode_path
from .intents import IntentStore
from .leases import LeaseStore
from .models import AppleMailError, ErrorCode
from .path_security import MAX_ATTACHMENT_BYTES, validate_outgoing_attachments

MAX_PAGE = 100
MAX_BODY_CHARS = 100_000
MAX_MUTATION_TARGETS = 20
SYNC_MESSAGE_BUDGET = 500
SYNC_TIME_BUDGET_SECONDS = 10 * 60
INCREMENTAL_MAILBOX_OVERLAP = 200
INTENT_TTL_SECONDS = 10 * 60
_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


class Bridge(Protocol):
    def invoke(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60,
    ) -> dict[str, Any]: ...


@dataclass
class ServiceOutput:
    data: Any
    coverage: dict[str, Any] | None = None
    error: AppleMailError | None = None


class AppleMailService:
    def __init__(
        self,
        *,
        paths: RuntimePaths | None = None,
        bridge: Bridge | None = None,
    ) -> None:
        self.paths = paths or RuntimePaths.from_environment()
        self.paths.ensure()
        self.settings: Settings = self.paths.load_settings()
        self.signer = HandleSigner(self.paths.signing_key)
        self.bridge = bridge or AppleScriptRunner(self.paths)
        self.intents = IntentStore(self.paths.intent_file)
        self.leases = LeaseStore(self.paths.leases_root)
        self.index = MailIndex(self.paths.index_file)

    def health_check(self) -> ServiceOutput:
        mail = self.bridge.invoke("health", timeout=15)
        filevault = filevault_status()
        index_status = self._public_index_status(self.index.status())
        warnings: list[str] = []
        if filevault != "on" and not self.settings.allow_unencrypted_index:
            warnings.append(
                "Historical indexing is blocked until FileVault is on or the local "
                "override is enabled."
            )
        return ServiceOutput(
            {
                "platform": platform.system(),
                "mail": mail,
                "automation_access": "ready",
                "private_state_root": str(self.paths.state_root),
                "filevault": filevault,
                "index": index_status,
                "warnings": warnings,
            }
        )

    def list_accounts(self) -> ServiceOutput:
        rows: list[dict[str, Any]] = []
        for account in self._raw_accounts():
            rows.append(
                {
                    "account_handle": self._account_handle(account),
                    "name": _clean(account.get("name")),
                    "email_addresses": _string_list(account.get("email_addresses")),
                    "reported_type": _clean(account.get("account_type")) or "unknown",
                }
            )
        return ServiceOutput({"accounts": rows, "count": len(rows)})

    def list_mailboxes(self, account_handle: str) -> ServiceOutput:
        account_id = self._account_id(account_handle)
        rows: list[dict[str, Any]] = []
        for mailbox in self._raw_mailboxes(account_id):
            path = _mailbox_path(mailbox)
            rows.append(
                {
                    "mailbox_handle": self._mailbox_handle(account_id, path),
                    "path": path,
                    "name": path[-1],
                    "message_count": _nonnegative_int(mailbox.get("message_count")),
                    "unread_count": _nonnegative_int(mailbox.get("unread_count")),
                    "excluded_from_history": self._is_excluded(path),
                }
            )
        return ServiceOutput({"mailboxes": rows, "count": len(rows)})

    def list_messages(self, mailbox_handle: str, *, offset: int, limit: int) -> ServiceOutput:
        account_id, path = self._mailbox_scope(mailbox_handle)
        page = self._raw_message_page(
            account_id, path, offset=offset, limit=limit, include_body=False
        )
        rows = [self._public_message(account_id, path, message) for message in page["messages"]]
        return ServiceOutput(
            {
                "messages": rows,
                "next_offset": page.get("next_offset"),
                "total_count": _nonnegative_int(page.get("total_count")),
            },
            coverage={"source": "live_mail", "mailbox_path": path, "complete_page": True},
        )

    def search_recent(
        self,
        *,
        query: str | None,
        account_handle: str | None,
        mailbox_handle: str | None,
        sender: str | None,
        subject: str | None,
        received_after: str | None,
        received_before: str | None,
        read_status: bool | None,
        flagged_status: bool | None,
        limit: int,
    ) -> ServiceOutput:
        scopes: list[tuple[str, list[str]]] = []
        if mailbox_handle is not None:
            account_id, path = self._mailbox_scope(mailbox_handle)
            if account_handle is not None and self._account_id(account_handle) != account_id:
                raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Account and mailbox do not match")
            scopes.append((account_id, path))
        else:
            account_ids = (
                [self._account_id(account_handle)]
                if account_handle is not None
                else [str(account["account_id"]) for account in self._raw_accounts()]
            )
            for account_id in account_ids:
                for mailbox in self._raw_mailboxes(account_id):
                    path = _mailbox_path(mailbox)
                    if not self._is_excluded(path):
                        scopes.append((account_id, path))
        scope_cap = min(len(scopes), 100)
        scan_limit = min(MAX_PAGE, max(25, limit * 4))
        candidates: list[dict[str, Any]] = []
        scanned_messages = 0
        for account_id, path in scopes[:scope_cap]:
            page = self._raw_message_page(
                account_id, path, offset=0, limit=scan_limit, include_body=False
            )
            scanned_messages += len(page["messages"])
            for raw in page["messages"]:
                public = self._public_message(account_id, path, raw)
                if _matches_recent(
                    public,
                    query=query,
                    sender=sender,
                    subject=subject,
                    received_after=received_after,
                    received_before=received_before,
                    read_status=read_status,
                    flagged_status=flagged_status,
                ):
                    candidates.append(public)
        candidates.sort(key=lambda row: str(row.get("date_received") or ""), reverse=True)
        return ServiceOutput(
            {"messages": candidates[:limit], "count": min(len(candidates), limit)},
            coverage={
                "source": "live_mail",
                "scanned_mailboxes": scope_cap,
                "available_mailboxes": len(scopes),
                "scanned_messages": scanned_messages,
                "per_mailbox_scan_limit": scan_limit,
                "complete_scope": False,
            },
        )

    def get_message(self, message_handle: str, *, offset: int, max_chars: int) -> ServiceOutput:
        payload = self.signer.verify(message_handle, "message")
        raw = self._resolve_message(payload, include_body=True)
        body = _clean_body(raw.get("body"))
        window = body[offset : offset + max_chars]
        public = self._public_message(
            str(payload["account_id"]), list(payload["mailbox_path"]), raw
        )
        public.update(
            {
                "body": window,
                "body_offset": offset,
                "body_length": len(body),
                "truncated": offset + len(window) < len(body),
                "next_offset": offset + len(window) if offset + len(window) < len(body) else None,
            }
        )
        return ServiceOutput(public, coverage={"source": "live_mail", "revalidated": True})

    def list_attachments(self, message_handle: str) -> ServiceOutput:
        payload = self.signer.verify(message_handle, "message")
        self._resolve_message(payload, include_body=False)
        response = self.bridge.invoke(
            "list_attachments", self._message_bridge_params(payload), timeout=60
        )
        self._validate_live_message(payload, _dict(response.get("message")))
        attachments: list[dict[str, Any]] = []
        for raw in _dict_list(response.get("attachments")):
            attachment_id = _required_text(raw, "attachment_id")
            name = _clean(raw.get("name")) or "attachment"
            size = _nonnegative_int(raw.get("file_size"))
            handle = self.signer.sign(
                "attachment",
                {
                    **self._message_identity(payload),
                    "attachment_id": attachment_id,
                    "name": name,
                    "file_size": size,
                },
            )
            attachments.append(
                {
                    "attachment_handle": handle,
                    "name": name,
                    "mime_type": _clean(raw.get("mime_type")),
                    "file_size": size,
                    "downloaded": bool(raw.get("downloaded")),
                }
            )
        return ServiceOutput(
            {"attachments": attachments, "count": len(attachments)},
            coverage={"source": "live_mail", "revalidated": True},
        )

    def index_status(self) -> ServiceOutput:
        status = self._public_index_status(self.index.status())
        status.update(
            {
                "filevault": filevault_status(),
                "allow_unencrypted_index": self.settings.allow_unencrypted_index,
                "excluded_mailbox_names": list(self.settings.excluded_mailbox_names),
            }
        )
        return ServiceOutput(status, coverage=self._index_coverage(status))

    def prepare_index_sync(self, *, mode: Literal["auto", "full", "incremental"]) -> ServiceOutput:
        self._assert_index_allowed()
        status = self.index.status()
        actual_mode = (
            "full"
            if mode == "auto" and not status["complete_full_history"]
            else "incremental"
            if mode == "auto"
            else mode
        )
        scopes: list[dict[str, Any]] = []
        estimated = 0
        for account in self._raw_accounts():
            account_id = str(account["account_id"])
            for mailbox in self._raw_mailboxes(account_id):
                path = _mailbox_path(mailbox)
                if self._is_excluded(path):
                    continue
                count = _nonnegative_int(mailbox.get("message_count"))
                estimated += count
                scopes.append({"account_id": account_id, "mailbox_path": path})
        scopes.sort(key=lambda scope: (scope["account_id"], scope["mailbox_path"]))
        sync_id, scopes = self.index.choose_sync(actual_mode, scopes)
        token = self.intents.create(
            "index_sync",
            {"version": 1, "sync_id": sync_id, "mode": actual_mode, "scopes": scopes},
            ttl_seconds=INTENT_TTL_SECONDS,
        )
        return ServiceOutput(
            {
                "intent_token": token,
                "expires_in_seconds": INTENT_TTL_SECONDS,
                "mode": actual_mode,
                "mailbox_count": len(scopes),
                "estimated_message_locations": estimated,
                "excluded_mailbox_names": list(self.settings.excluded_mailbox_names),
            }
        )

    def commit_index_sync(self, intent_token: str) -> ServiceOutput:
        self._assert_index_allowed()
        intent = self.intents.consume(intent_token, "index_sync")
        sync_id = _required_text(intent, "sync_id")
        mode = _required_text(intent, "mode")
        if mode not in {"full", "incremental"}:
            raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Stored sync mode is invalid")
        scopes = _scope_list(intent.get("scopes"))
        self.index.activate_sync(sync_id, mode, scopes)
        deadline = time.monotonic() + SYNC_TIME_BUDGET_SECONDS
        processed = 0
        completed_mailboxes = 0
        for scope in scopes:
            if processed >= SYNC_MESSAGE_BUDGET or time.monotonic() >= deadline:
                break
            account_id = str(scope["account_id"])
            path = list(scope["mailbox_path"])
            offset, complete = self.index.checkpoint(sync_id, account_id, path)
            if complete:
                completed_mailboxes += 1
                continue
            while processed < SYNC_MESSAGE_BUDGET and time.monotonic() < deadline:
                if mode == "incremental" and offset >= INCREMENTAL_MAILBOX_OVERLAP:
                    self.index.index_page(
                        sync_id=sync_id,
                        mode=mode,
                        account_id=account_id,
                        mailbox_path=path,
                        messages=[],
                        next_offset=offset,
                        complete=True,
                    )
                    completed_mailboxes += 1
                    break
                page_limit = min(50, SYNC_MESSAGE_BUDGET - processed)
                if mode == "incremental":
                    page_limit = min(page_limit, INCREMENTAL_MAILBOX_OVERLAP - offset)
                page = self._raw_message_page(
                    account_id, path, offset=offset, limit=page_limit, include_body=True
                )
                messages = page["messages"]
                for message in messages:
                    message["fingerprint"] = message_fingerprint(message)
                    message["body"] = _clean_body(message.get("body"))
                processed += len(messages)
                next_value = page.get("next_offset")
                next_offset = offset + len(messages) if next_value is None else int(next_value)
                page_complete = next_value is None
                if mode == "incremental" and next_offset >= INCREMENTAL_MAILBOX_OVERLAP:
                    page_complete = True
                self.index.index_page(
                    sync_id=sync_id,
                    mode=mode,
                    account_id=account_id,
                    mailbox_path=path,
                    messages=messages,
                    next_offset=next_offset,
                    complete=page_complete,
                )
                offset = next_offset
                if page_complete:
                    completed_mailboxes += 1
                    break
                if not messages:
                    break
        sync_complete = self.index.finish_if_complete(sync_id, mode)
        status = self._public_index_status(self.index.status())
        return ServiceOutput(
            {
                "sync_id": sync_id,
                "mode": mode,
                "processed_message_locations": processed,
                "completed_mailboxes_seen": completed_mailboxes,
                "complete": sync_complete,
                "next_step": None
                if sync_complete
                else "Prepare and commit another index sync call to resume.",
                "status": status,
            },
            coverage=self._index_coverage(status),
        )

    def erase_index(self) -> ServiceOutput:
        removed = self.index.erase()
        return ServiceOutput({"erased": True, "removed_files": removed})

    def search_history(self, query: str, *, limit: int) -> ServiceOutput:
        rows = self.index.search(query, limit=limit)
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        for row in rows:
            account_id = str(row["account_id"])
            rfc_id = str(row.get("rfc_message_id") or "")
            key = (account_id, rfc_id or str(row["location_key"]))
            path = decode_path(str(row["mailbox_path"]))
            payload = {
                "account_id": account_id,
                "mailbox_path": path,
                "native_id": int(row["native_id"]),
                "rfc_message_id": rfc_id,
                "fingerprint": str(row["fingerprint"]),
            }
            location = {
                "mailbox_path": path,
                "mailbox_handle": self._mailbox_handle(account_id, path),
                "message_handle": self.signer.sign("message", payload),
                "live_status": "unvalidated",
            }
            if key not in grouped:
                order.append(key)
                grouped[key] = {
                    "subject": _clean(row.get("subject")),
                    "sender": _clean(row.get("sender")),
                    "date_received": _clean(row.get("date_received")),
                    "date_sent": _clean(row.get("date_sent")),
                    "read_status_at_index": bool(int(row.get("read_status") or 0)),
                    "flagged_status_at_index": bool(int(row.get("flagged_status") or 0)),
                    "rfc_message_id": rfc_id or None,
                    "indexed_at": float(row["indexed_at"]),
                    "locations": [],
                }
            grouped[key]["locations"].append(location)
        results = [grouped[key] for key in order[:limit]]
        status = self.index.status()
        return ServiceOutput(
            {"results": results, "count": len(results), "query_mode": "literal_terms"},
            coverage=self._index_coverage(status),
        )

    def fetch_attachment(self, attachment_handle: str) -> ServiceOutput:
        payload = self.signer.verify(attachment_handle, "attachment")
        self._resolve_message(payload, include_body=False)
        listed = self.bridge.invoke(
            "list_attachments", self._message_bridge_params(payload), timeout=60
        )
        self._validate_live_message(payload, _dict(listed.get("message")))
        attachment_id = _required_text(payload, "attachment_id")
        matches = [
            row
            for row in _dict_list(listed.get("attachments"))
            if str(row.get("attachment_id")) == attachment_id
        ]
        if len(matches) != 1:
            raise AppleMailError(
                ErrorCode.STALE_HANDLE, "Attachment no longer resolves uniquely in Mail"
            )
        raw = matches[0]
        size = _nonnegative_int(raw.get("file_size"))
        if size > MAX_ATTACHMENT_BYTES:
            raise AppleMailError(
                ErrorCode.ATTACHMENT_TOO_LARGE,
                f"Incoming attachments must be at most {MAX_ATTACHMENT_BYTES} bytes",
            )
        name = _clean(raw.get("name")) or "attachment"
        token, output_path, expires_at = self.leases.create_target(name)
        try:
            response = self.bridge.invoke(
                "fetch_attachment",
                {
                    **self._message_bridge_params(payload),
                    "attachment_id": attachment_id,
                    "output_path": str(output_path),
                },
                timeout=180,
            )
            self._validate_live_message(payload, _dict(response.get("message")))
            receipt = self.leases.finalize(
                token,
                output_path,
                expires_at,
                {"name": name, "mime_type": _clean(raw.get("mime_type"))},
            )
            if int(receipt["size"]) > MAX_ATTACHMENT_BYTES:
                self.leases.release(token)
                raise AppleMailError(
                    ErrorCode.ATTACHMENT_TOO_LARGE,
                    f"Incoming attachments must be at most {MAX_ATTACHMENT_BYTES} bytes",
                )
        except Exception:
            self.leases.release(token)
            raise
        return ServiceOutput(
            {
                "lease_token": token,
                "path": receipt["path"],
                "size": receipt["size"],
                "sha256": receipt["sha256"],
                "expires_at": receipt["expires_at"],
                "name": name,
                "mime_type": _clean(raw.get("mime_type")),
            }
        )

    def release_attachment(self, lease_token: str) -> ServiceOutput:
        removed = self.leases.release(lease_token)
        return ServiceOutput({"released": True, "previously_present": removed})

    def create_draft(
        self,
        *,
        account_handle: str,
        draft_type: Literal["new", "reply", "reply_all", "forward"],
        source_message_handle: str | None,
        to: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body: str,
        attachment_paths: list[str],
    ) -> ServiceOutput:
        account_id = self._account_id(account_handle)
        if len(subject) > 1_000 or len(body) > 500_000:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Draft subject or body is too long")
        recipients = {
            "to": _validated_addresses(to),
            "cc": _validated_addresses(cc),
            "bcc": _validated_addresses(bcc),
        }
        if sum(len(values) for values in recipients.values()) > 200:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Draft has too many recipients")
        request: dict[str, Any] = {
            "account_id": account_id,
            "draft_type": draft_type,
            "to": recipients["to"],
            "cc": recipients["cc"],
            "bcc": recipients["bcc"],
            "subject": subject,
            "body": body,
        }
        if draft_type == "new":
            if source_message_handle is not None:
                raise AppleMailError(
                    ErrorCode.VALIDATION_ERROR, "New drafts cannot have a source message"
                )
            if not recipients["to"]:
                raise AppleMailError(
                    ErrorCode.VALIDATION_ERROR, "A new draft requires a To recipient"
                )
        else:
            if source_message_handle is None:
                raise AppleMailError(
                    ErrorCode.VALIDATION_ERROR, "Reply and forward drafts require a source message"
                )
            source = self.signer.verify(source_message_handle, "message")
            if str(source["account_id"]) != account_id:
                raise AppleMailError(
                    ErrorCode.VALIDATION_ERROR, "Draft account and source message do not match"
                )
            self._resolve_message(source, include_body=False)
            request.update(self._message_bridge_params(source))
        attachments = validate_outgoing_attachments(
            attachment_paths, secrets_root=self.paths.secrets_root
        )
        request["attachment_paths"] = [str(item.path) for item in attachments]
        response = self.bridge.invoke("create_draft", request, timeout=180)
        account = next(
            row for row in self._raw_accounts_unchecked() if row.get("account_id") == account_id
        )
        verified = self._draft_readback_matches(
            response,
            account_addresses=_string_list(account.get("email_addresses")),
            requested_recipients=recipients,
            requested_subject=subject,
            attachment_count=len(attachments),
        )
        data = {
            **response,
            "draft_type": draft_type,
            "sent": False,
            "readback_verified": verified,
            "attachments": [
                {"path": str(item.path), "size": item.size, "sha256": item.sha256}
                for item in attachments
            ],
            "warning": (
                "Mail may apply quoted-text styling on this macOS version; "
                "inspect the visible draft before clicking Send."
            ),
        }
        if not verified:
            return ServiceOutput(
                data,
                error=AppleMailError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "Mail opened a draft but its fields could not be fully verified; "
                    "inspect it manually",
                ),
            )
        return ServiceOutput(data)

    def prepare_mutation(
        self,
        *,
        action: Literal["mark_read", "mark_unread", "flag", "unflag", "move", "trash"],
        message_handles: list[str],
        destination_mailbox_handle: str | None,
    ) -> ServiceOutput:
        if not 1 <= len(message_handles) <= MAX_MUTATION_TARGETS:
            raise AppleMailError(
                ErrorCode.VALIDATION_ERROR,
                f"Mutations require 1 to {MAX_MUTATION_TARGETS} exact message handles",
            )
        destination_scope = (
            self._mailbox_scope(destination_mailbox_handle)
            if destination_mailbox_handle is not None
            else None
        )
        if action == "move" and destination_scope is None:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Move requires a destination mailbox")
        if action != "move" and destination_scope is not None:
            raise AppleMailError(
                ErrorCode.VALIDATION_ERROR, "Only move accepts a destination mailbox"
            )
        targets: list[dict[str, Any]] = []
        previews: list[dict[str, Any]] = []
        for handle in message_handles:
            payload = self.signer.verify(handle, "message")
            raw = self._resolve_message(payload, include_body=False)
            account_id = str(payload["account_id"])
            if destination_scope is not None:
                if destination_scope[0] != account_id:
                    raise AppleMailError(
                        ErrorCode.VALIDATION_ERROR,
                        "Move targets and destination must share an account",
                    )
                destination_path = destination_scope[1]
            elif action == "trash":
                destination_path = self._trash_path(account_id)
            else:
                destination_path = None
            if destination_path == list(payload["mailbox_path"]):
                raise AppleMailError(
                    ErrorCode.VALIDATION_ERROR,
                    "Mutation destination is already the source mailbox",
                )
            preview: dict[str, Any] = {
                "account_handle": self.signer.sign("account", {"account_id": account_id}),
                "mailbox_path": list(payload["mailbox_path"]),
                "sender": _clean(raw.get("sender")),
                "subject": _clean(raw.get("subject")),
                "date_received": _clean(raw.get("date_received")),
                "action": action,
                "destination_path": destination_path,
            }
            target: dict[str, Any] = {
                **self._message_identity(payload),
                "destination_path": destination_path,
                "preview": preview,
            }
            targets.append(target)
            previews.append(preview)
        if (
            len(targets) > 1
            and action in {"move", "trash"}
            and any(not target.get("rfc_message_id") for target in targets)
        ):
            raise AppleMailError(
                ErrorCode.VALIDATION_ERROR,
                "Batch move or mutation requires an RFC Message-ID for every target",
            )
        token = self.intents.create(
            "mutation",
            {"version": 1, "action": action, "targets": targets},
            ttl_seconds=INTENT_TTL_SECONDS,
        )
        return ServiceOutput(
            {
                "intent_token": token,
                "expires_in_seconds": INTENT_TTL_SECONDS,
                "action": action,
                "target_count": len(targets),
                "targets": previews,
            }
        )

    def commit_mutation(self, intent_token: str) -> ServiceOutput:
        intent = self.intents.consume(intent_token, "mutation")
        action = _required_text(intent, "action")
        targets = _dict_list(intent.get("targets"))
        if action not in {"mark_read", "mark_unread", "flag", "unflag", "move", "trash"}:
            raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Stored mutation is invalid")
        # Validate every target before changing the first one.
        for target in targets:
            self._resolve_message(target, include_body=False)
            destination = target.get("destination_path")
            if destination is not None:
                self._assert_mailbox_exists(str(target["account_id"]), list(destination))
        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        unattempted: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            try:
                self._resolve_message(target, include_body=False)
                params: dict[str, Any] = {
                    **self._message_bridge_params(target),
                    "mutation": action,
                    "destination_path": target.get("destination_path") or [],
                }
                try:
                    response = self.bridge.invoke("mutate_message", params, timeout=90)
                except AppleMailError as error:
                    if error.code in {
                        ErrorCode.BRIDGE_ERROR,
                        ErrorCode.MAIL_UNAVAILABLE,
                        ErrorCode.TIMEOUT,
                    }:
                        raise AppleMailError(
                            ErrorCode.OUTCOME_UNKNOWN,
                            "Mail may have changed the target, but the mutation response was lost",
                        ) from error
                    raise
                updated = _dict(response.get("message"))
                try:
                    verified, new_path = self._verify_live_mutation_result(action, target, updated)
                except AppleMailError as error:
                    raise AppleMailError(
                        ErrorCode.OUTCOME_UNKNOWN,
                        "Mail accepted the mutation, but its live result could not be verified",
                    ) from error
                succeeded.append(
                    self._public_message(str(target["account_id"]), new_path, verified)
                )
            except AppleMailError as error:
                failed.append(
                    {
                        "target": target.get("preview"),
                        "code": error.code.value,
                        "message": error.message,
                    }
                )
                unattempted.extend(item.get("preview", {}) for item in targets[index + 1 :])
                break
        data = {
            "action": action,
            "succeeded": succeeded,
            "failed": failed,
            "unattempted": unattempted,
            "complete": not failed,
        }
        if failed:
            top_level_code = (
                ErrorCode.PARTIAL_SUCCESS if succeeded else ErrorCode(str(failed[0]["code"]))
            )
            return ServiceOutput(
                data,
                error=AppleMailError(
                    top_level_code,
                    "Mutation stopped after a target failed revalidation",
                ),
            )
        return ServiceOutput(data)

    def cancel_mutation(self, intent_token: str) -> ServiceOutput:
        cancelled = self.intents.cancel(intent_token, "mutation")
        return ServiceOutput({"cancelled": cancelled})

    def _raw_accounts(self) -> list[dict[str, Any]]:
        response = self.bridge.invoke("list_accounts", timeout=30)
        accounts = _dict_list(response.get("accounts"))
        for account in accounts:
            _required_text(account, "account_id")
        return accounts

    def _raw_mailboxes(self, account_id: str) -> list[dict[str, Any]]:
        self._assert_account_exists(account_id)
        response = self.bridge.invoke("list_mailboxes", {"account_id": account_id}, timeout=90)
        return _dict_list(response.get("mailboxes"))

    def _raw_message_page(
        self,
        account_id: str,
        path: list[str],
        *,
        offset: int,
        limit: int,
        include_body: bool,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= MAX_PAGE:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Message page bounds are invalid")
        response = self.bridge.invoke(
            "list_messages",
            {
                "account_id": account_id,
                "mailbox_path": path,
                "offset": offset,
                "limit": limit,
                "include_body": include_body,
            },
            timeout=180 if include_body else 90,
        )
        messages = _dict_list(response.get("messages"))
        for message in messages:
            _required_native_id(message)
        return {**response, "messages": messages}

    def _resolve_message(self, payload: dict[str, Any], *, include_body: bool) -> dict[str, Any]:
        params = self._message_bridge_params(payload)
        params["include_body"] = include_body
        response = self.bridge.invoke("get_message", params, timeout=90 if include_body else 60)
        raw = _dict(response.get("message"))
        self._validate_live_message(payload, raw)
        return raw

    def _validate_live_message(self, payload: dict[str, Any], raw: dict[str, Any]) -> None:
        if _required_native_id(raw) != int(payload["native_id"]):
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Message identity changed")
        expected_rfc = str(payload.get("rfc_message_id") or "")
        actual_rfc = str(raw.get("rfc_message_id") or "")
        if expected_rfc and actual_rfc != expected_rfc:
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Message-ID no longer matches")
        if message_fingerprint(raw) != str(payload["fingerprint"]):
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Message metadata no longer matches")

    def _public_message(
        self, account_id: str, path: list[str], raw: dict[str, Any]
    ) -> dict[str, Any]:
        fingerprint = message_fingerprint(raw)
        payload = {
            "account_id": account_id,
            "mailbox_path": path,
            "native_id": _required_native_id(raw),
            "rfc_message_id": str(raw.get("rfc_message_id") or ""),
            "fingerprint": fingerprint,
        }
        return {
            "message_handle": self.signer.sign("message", payload),
            "mailbox_path": path,
            "subject": _clean(raw.get("subject")),
            "sender": _clean(raw.get("sender")),
            "to": _string_list(raw.get("to")),
            "cc": _string_list(raw.get("cc")),
            "bcc": _string_list(raw.get("bcc")),
            "date_received": _clean(raw.get("date_received")),
            "date_sent": _clean(raw.get("date_sent")),
            "read_status": bool(raw.get("read_status")),
            "flagged_status": bool(raw.get("flagged_status")),
            "message_size": _nonnegative_int(raw.get("message_size")),
            "attachment_count": _nonnegative_int(raw.get("attachment_count")),
            "rfc_message_id_present": bool(raw.get("rfc_message_id")),
        }

    def _account_handle(self, account: dict[str, Any]) -> str:
        return self.signer.sign("account", {"account_id": _required_text(account, "account_id")})

    def _account_id(self, handle: str) -> str:
        payload = self.signer.verify(handle, "account")
        account_id = _required_text(payload, "account_id")
        self._assert_account_exists(account_id)
        return account_id

    def _mailbox_handle(self, account_id: str, path: list[str]) -> str:
        return self.signer.sign("mailbox", {"account_id": account_id, "mailbox_path": path})

    def _mailbox_scope(self, handle: str) -> tuple[str, list[str]]:
        payload = self.signer.verify(handle, "mailbox")
        account_id = _required_text(payload, "account_id")
        path = _path_value(payload.get("mailbox_path"))
        self._assert_mailbox_exists(account_id, path)
        return account_id, path

    def _assert_account_exists(self, account_id: str) -> None:
        matches = [
            row
            for row in self._raw_accounts_unchecked()
            if str(row.get("account_id")) == account_id
        ]
        if len(matches) == 0:
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Account is no longer enabled")
        if len(matches) != 1:
            raise AppleMailError(ErrorCode.AMBIGUOUS, "Account identity is ambiguous")

    def _raw_accounts_unchecked(self) -> list[dict[str, Any]]:
        response = self.bridge.invoke("list_accounts", timeout=30)
        return _dict_list(response.get("accounts"))

    def _assert_mailbox_exists(self, account_id: str, path: list[str]) -> None:
        matches = [row for row in self._raw_mailboxes(account_id) if _mailbox_path(row) == path]
        if len(matches) == 0:
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Mailbox is no longer available")
        if len(matches) != 1:
            raise AppleMailError(ErrorCode.AMBIGUOUS, "Mailbox identity is ambiguous")

    def _trash_path(self, account_id: str) -> list[str]:
        for configured_name in self.settings.trash_mailbox_names:
            matches = [
                _mailbox_path(row)
                for row in self._raw_mailboxes(account_id)
                if _mailbox_path(row)[-1].casefold() == configured_name.casefold()
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise AppleMailError(
                    ErrorCode.AMBIGUOUS,
                    "Trash mailbox name is ambiguous; update the private configuration",
                )
        raise AppleMailError(
            ErrorCode.NOT_FOUND, "No configured recoverable Trash mailbox is available"
        )

    def _is_excluded(self, path: list[str]) -> bool:
        excluded = {name.casefold() for name in self.settings.excluded_mailbox_names}
        return any(segment.casefold() in excluded for segment in path)

    def _assert_index_allowed(self) -> None:
        status = filevault_status()
        if status != "on" and not self.settings.allow_unencrypted_index:
            raise AppleMailError(
                ErrorCode.INDEX_DISABLED,
                "Historical indexing requires FileVault or allow_unencrypted_index=true "
                "in the private configuration",
            )

    def _index_coverage(self, status: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "private_sqlite_fts5",
            "complete_full_history": bool(status.get("complete_full_history")),
            "last_full_completed_at": status.get("last_full_completed_at"),
            "last_incremental_completed_at": status.get("last_incremental_completed_at"),
            "newest_indexed_at": status.get("newest_indexed_at"),
            "excluded_mailbox_names": list(self.settings.excluded_mailbox_names),
            "live_revalidation_required": True,
        }

    @staticmethod
    def _message_identity(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "account_id": _required_text(payload, "account_id"),
            "mailbox_path": _path_value(payload.get("mailbox_path")),
            "native_id": int(payload["native_id"]),
            "rfc_message_id": str(payload.get("rfc_message_id") or ""),
            "fingerprint": _required_text(payload, "fingerprint"),
        }

    @staticmethod
    def _message_bridge_params(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "account_id": _required_text(payload, "account_id"),
            "mailbox_path": _path_value(payload.get("mailbox_path")),
            "native_id": int(payload["native_id"]),
        }

    @staticmethod
    def _verify_mutation(action: str, updated: dict[str, Any]) -> None:
        if action == "mark_read" and not bool(updated.get("read_status")):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail did not mark the message read")
        if action == "mark_unread" and bool(updated.get("read_status")):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail did not mark the message unread")
        if action == "flag" and not bool(updated.get("flagged_status")):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail did not flag the message")
        if action == "unflag" and bool(updated.get("flagged_status")):
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail did not unflag the message")

    def _verify_live_mutation_result(
        self,
        action: str,
        target: dict[str, Any],
        updated: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        expected_fingerprint = _required_text(target, "fingerprint")
        if message_fingerprint(updated) != expected_fingerprint:
            raise AppleMailError(ErrorCode.STALE_HANDLE, "Message identity changed")
        account_id = _required_text(target, "account_id")
        if action in {"move", "trash"}:
            destination_path = _path_value(target.get("destination_path"))
            rfc_message_id = str(target.get("rfc_message_id") or "")
            if rfc_message_id:
                response = self.bridge.invoke(
                    "find_message",
                    {
                        "account_id": account_id,
                        "mailbox_path": destination_path,
                        "rfc_message_id": rfc_message_id,
                    },
                    timeout=90,
                )
                verified = _dict(response.get("message"))
                if str(verified.get("rfc_message_id") or "") != rfc_message_id:
                    raise AppleMailError(ErrorCode.STALE_HANDLE, "Message-ID no longer matches")
                if message_fingerprint(verified) != expected_fingerprint:
                    raise AppleMailError(ErrorCode.STALE_HANDLE, "Message identity changed")
            else:
                verified = self._resolve_message(
                    {
                        "account_id": account_id,
                        "mailbox_path": destination_path,
                        "native_id": _required_native_id(updated),
                        "rfc_message_id": "",
                        "fingerprint": expected_fingerprint,
                    },
                    include_body=False,
                )
            return verified, destination_path
        verified = self._resolve_message(target, include_body=False)
        self._verify_mutation(action, verified)
        return verified, _path_value(target.get("mailbox_path"))

    @staticmethod
    def _draft_readback_matches(
        response: dict[str, Any],
        *,
        account_addresses: list[str],
        requested_recipients: dict[str, list[str]],
        requested_subject: str,
        attachment_count: int,
    ) -> bool:
        if response.get("visible") is not True or response.get("sent") is not False:
            return False
        if requested_subject and response.get("subject") != requested_subject:
            return False
        sender = str(response.get("sender") or "").casefold()
        if account_addresses and not any(
            sender == address.casefold() or sender.endswith(f"<{address.casefold()}>")
            for address in account_addresses
        ):
            return False
        for field, requested in requested_recipients.items():
            actual = {address.casefold() for address in _string_list(response.get(field))}
            if not {address.casefold() for address in requested}.issubset(actual):
                return False
        return response.get("attachment_count") == attachment_count

    def _public_index_status(self, raw_status: dict[str, Any]) -> dict[str, Any]:
        status = dict(raw_status)
        scopes = cast(list[dict[str, Any]], status.pop("indexed_scopes", []))
        indexed_mailboxes: list[dict[str, Any]] = []
        for scope in scopes:
            account_id = str(scope["account_id"])
            path = decode_path(str(scope["mailbox_path"]))
            indexed_mailboxes.append(
                {
                    "account_handle": self.signer.sign("account", {"account_id": account_id}),
                    "mailbox_handle": self._mailbox_handle(account_id, path),
                    "mailbox_path": path,
                    "message_locations": int(scope["message_locations"]),
                    "newest_indexed_at": float(scope["newest_indexed_at"]),
                }
            )
        status["indexed_mailboxes"] = indexed_mailboxes
        status["indexed_accounts"] = len({scope["account_handle"] for scope in indexed_mailboxes})
        return status


def filevault_status() -> str:
    if platform.system() != "Darwin":
        return "unsupported"
    try:
        result = subprocess.run(
            ["/usr/bin/fdesetup", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "indeterminate"
    text = f"{result.stdout}\n{result.stderr}".casefold()
    if "filevault is on" in text:
        return "on"
    if "filevault is off" in text:
        return "off"
    return "indeterminate"


def _matches_recent(
    message: dict[str, Any],
    *,
    query: str | None,
    sender: str | None,
    subject: str | None,
    received_after: str | None,
    received_before: str | None,
    read_status: bool | None,
    flagged_status: bool | None,
) -> bool:
    if query:
        haystack = " ".join(
            str(value)
            for key in ("subject", "sender", "to", "cc")
            for value in _values(message.get(key))
            if value is not None
        ).casefold()
        if query.casefold() not in haystack:
            return False
    if sender and sender.casefold() not in str(message.get("sender") or "").casefold():
        return False
    if subject and subject.casefold() not in str(message.get("subject") or "").casefold():
        return False
    received = str(message.get("date_received") or "")
    if received_after and received < received_after:
        return False
    if received_before and received > received_before:
        return False
    if read_status is not None and bool(message.get("read_status")) != read_status:
        return False
    return flagged_status is None or bool(message.get("flagged_status")) == flagged_status


def _validated_addresses(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if len(cleaned) > 320 or _EMAIL.fullmatch(cleaned) is None:
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Recipient address is invalid")
        result.append(cleaned)
    return list(dict.fromkeys(result))


def _values(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else [value]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "")
    return "".join(character for character in text if ord(character) >= 32 or character in "\t\n\r")


def _clean_body(value: Any) -> str:
    return _clean(value) or ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        cleaned
        for item in cast(list[Any], value)
        if (cleaned := _clean(item)) is not None
    ]


def _dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
    return cast(dict[str, Any], value)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
    items = cast(list[Any], value)
    if not all(isinstance(item, dict) for item in items):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
    return [cast(dict[str, Any], item) for item in items]


def _scope_list(value: Any) -> list[dict[str, Any]]:
    scopes = _dict_list(value)
    for scope in scopes:
        _required_text(scope, "account_id")
        _path_value(scope.get("mailbox_path"))
    return scopes


def _required_text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if (
        not isinstance(result, str)
        or not result
        or len(result) > 10_000
        or any(ord(character) < 32 for character in result)
    ):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
    return result


def _required_native_id(value: dict[str, Any]) -> int:
    raw = value.get("native_id")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mail returned malformed data")
    return raw


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _path_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mailbox path is invalid")
    items = cast(list[Any], value)
    if (
        not items
        or len(items) > 100
        or any(not isinstance(item, str) or not item or len(item) > 500 for item in items)
    ):
        raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Mailbox path is invalid")
    return [cast(str, item) for item in items]


def _mailbox_path(value: dict[str, Any]) -> list[str]:
    return _path_value(value.get("path"))
