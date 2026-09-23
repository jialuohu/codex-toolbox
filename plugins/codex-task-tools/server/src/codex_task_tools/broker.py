"""Single-owner task broker: project validation, journaled mutations, and readback."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .app_server import (
    AppClient,
    AppServerClient,
    AppServerError,
    NotSent,
    OutcomeUnknown,
    RPCRejected,
    strict_json,
)
from .ledger import KeyConflict, Ledger, LedgerError, private_dir

APP_VERSION = "0.156.1"
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RESPONDABLE_REQUESTS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/tool/requestUserInput",
}


class TaskError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def state_directory() -> Path:
    home = Path(os.getenv("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return home / "state" / "codex-task-tools"


def project_ref(backend: str, project_id: str) -> str:
    return f"local:{backend[:20]}:{project_id}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


def _path(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise TaskError("invalid_cwd", "Working directory must be an existing absolute directory")
    return str(path.resolve(strict=True))


class TaskBroker:
    def __init__(
        self,
        state_dir: Path | None = None,
        app_factory: Callable[[], AppClient] | None = None,
    ) -> None:
        self.state_dir = state_dir or state_directory()
        self.ledger = Ledger(self.state_dir)
        self.app_factory = app_factory or AppServerClient
        self.app: AppClient | None = None
        self.connect_lock = asyncio.Lock()
        self.create_lock = asyncio.Lock()
        self.quiesced = False
        self.event_task: asyncio.Task[None] | None = None
        self.refresh_task: asyncio.Task[None] | None = None
        self.event_blocked = False
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        event_task = self.event_task
        if event_task is not None:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
        if self.refresh_task is not None:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        if self.app is not None:
            await self.app.close()
        self.ledger.close()

    async def ensure_connected(self) -> AppClient:
        if self.closed:
            raise TaskError("broker_closed", "Task broker is closed")
        async with self.connect_lock:
            if self.app is not None and self.app.version == APP_VERSION:
                return self.app
            candidate = self.app_factory()
            try:
                await candidate.connect()
                if candidate.version != APP_VERSION:
                    raise TaskError(
                        "unsupported_runtime",
                        f"App Server {candidate.version} is not certified for task creation",
                    )
                if not isinstance(candidate.backend_identity, str) or not candidate.backend_identity:
                    raise TaskError("invalid_backend", "App Server identity is unavailable")
                self.ledger.mark_inflight_unknown(candidate.backend_identity)
                self.app = candidate
                if self.event_task is None or self.event_task.done():
                    self.event_task = asyncio.create_task(self._event_loop(), name="task-events")
                return candidate
            except Exception:
                await candidate.close()
                raise

    async def _event_loop(self) -> None:
        reconnect_delay = 1
        while not self.closed:
            app = self.app
            if app is None:
                await asyncio.sleep(reconnect_delay)
                try:
                    app = await self.ensure_connected()
                    reconnect_delay = 1
                    await self._resume_tracked(app)
                except (AppServerError, TaskError, OSError):
                    reconnect_delay = min(reconnect_delay * 2, 30)
                continue
            try:
                event = await asyncio.wait_for(app.next_event(), timeout=30)
            except TimeoutError:
                if self.refresh_task is None or self.refresh_task.done():
                    self.refresh_task = asyncio.create_task(
                        self._refresh_active(app), name="task-readback"
                    )
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                self.event_blocked = True
                await asyncio.sleep(0.1)
                continue
            delay = 0.2
            while not self.closed:
                try:
                    await self._handle_event(app, event)
                    self.event_blocked = False
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Retain the exact event until its ledger transition succeeds.
                    # Dropping a server request here would hide a live approval.
                    self.event_blocked = True
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)

    async def _handle_event(self, app: AppClient, event: dict[str, Any]) -> None:
        method = event.get("method")
        params = event.get("params")
        if method == "_connection_lost":
            self.ledger.mark_inflight_unknown(app.backend_identity)
            await app.close()
            if self.app is app:
                self.app = None
            return
        if not isinstance(params, dict):
            return
        if method == "serverRequest/resolved":
            task_id, raw_request_id = params.get("threadId"), params.get("requestId")
            if isinstance(task_id, str) and isinstance(raw_request_id, str | int):
                request_id = json.dumps(raw_request_id, separators=(",", ":"))
                self.ledger.pending_state(
                    app.backend_identity, task_id, request_id, app.generation, "resolved"
                )
            return
        if "id" in event and isinstance(method, str):
            task_id = params.get("threadId")
            if not isinstance(task_id, str):
                return
            row = self.ledger.by_task(app.backend_identity, task_id)
            if row is None:
                return
            raw_id = event["id"]
            if not isinstance(raw_id, str | int):
                return
            request_id = json.dumps(raw_id, separators=(",", ":"))
            state = "pending" if method in RESPONDABLE_REQUESTS else "needs_attention"
            if len(json.dumps(params, separators=(",", ":")).encode()) > 128 * 1024:
                state = "needs_attention"
                params = {"threadId": task_id, "truncated": True}
            self.ledger.add_pending(
                app.backend_identity, task_id, request_id, app.generation, method,
                params, state,
            )
            return
        task_id = params.get("threadId")
        if not isinstance(task_id, str):
            return
        row = self.ledger.by_task(app.backend_identity, task_id)
        if row is None:
            return
        if method == "turn/completed":
            turn = params.get("turn")
            if isinstance(turn, dict) and turn.get("id") == row["turn_id"]:
                status = turn.get("status")
                if status in {"completed", "failed", "interrupted"}:
                    self.ledger.update(app.backend_identity, row["idempotency_key"], execution=status)
                    self.ledger.resolve_for_task(app.backend_identity, task_id)
                    asyncio.create_task(self._refresh(row["idempotency_key"]))

    async def _resume_tracked(self, app: AppClient) -> None:
        for row in self.ledger.tracked(app.backend_identity):
            if row["submission"] in {"unknown", "accepted"} or row["title_status"] == "unknown":
                row = await self._readback(app, row, verify_index=False)
            if row["submission"] == "accepted" and row["execution"] not in {
                "completed", "failed", "interrupted"
            }:
                try:
                    await app.request("thread/resume", {"threadId": row["task_id"]})
                except (AppServerError, TaskError):
                    # Status/readback remains available; never start another turn.
                    pass

    async def _refresh_active(self, app: AppClient) -> None:
        if self.app is not app:
            return
        for row in self.ledger.tracked(app.backend_identity):
            if self.app is not app:
                return
            if row["submission"] in {"accepted", "unknown"} and row["execution"] not in {
                "completed", "failed", "interrupted"
            }:
                await self._readback(app, row, verify_index=False)

    async def projects_find(self, query: str | None = None) -> dict[str, Any]:
        app = await self.ensure_connected()
        if query is not None and (not isinstance(query, str) or len(query) > 500):
            raise TaskError("invalid_query", "Project query is too long")
        projects = await self._projects(app)
        matches = [p for p in projects if query is None or query.casefold() in p["name"].casefold()]
        return {
            "backend": "local",
            "backendIdentity": app.backend_identity[:20],
            "appServerVersion": app.version,
            "capabilities": {"projectAssignment": True, "desktopMembership": "unverified"},
            "ambiguous": len(matches) > 1,
            "projects": [
                {
                    "projectRef": project_ref(app.backend_identity, p["id"]),
                    "id": p["id"], "name": p["name"],
                    "roots": [root["path"] for root in p["roots"]],
                }
                for p in matches
            ],
            "observedAt": _now(),
        }

    async def _projects(self, app: AppClient) -> list[dict[str, Any]]:
        cursor: str | None = None
        seen: set[str] = set()
        found: dict[str, dict[str, Any]] = {}
        for _ in range(100):
            page = await app.request("project/list", {"cursor": cursor, "limit": 100})
            data = page.get("data")
            if not isinstance(data, list):
                raise TaskError("invalid_project_response", "App Server project inventory is invalid")
            for item in data:
                if (
                    not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("roots"), list)
                    or any(
                        not isinstance(root, dict) or not isinstance(root.get("path"), str)
                        for root in item["roots"]
                    )
                    or item["id"] in found
                ):
                    raise TaskError("invalid_project_response", "App Server project inventory is invalid")
                found[item["id"]] = item
            cursor = page.get("nextCursor")
            if cursor is None:
                return list(found.values())
            if not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
        raise TaskError("incomplete_project_inventory", "Project inventory could not be completed")

    async def _resolve_project(
        self, app: AppClient, selected_ref: str, cwd: str | None
    ) -> tuple[dict[str, Any], str]:
        prefix = f"local:{app.backend_identity[:20]}:"
        if not isinstance(selected_ref, str) or not selected_ref.startswith(prefix):
            raise TaskError("wrong_backend", "Project reference does not belong to this Codex host")
        project_id = selected_ref[len(prefix):]
        if not project_id:
            raise TaskError("invalid_project_ref", "Project reference is incomplete")
        inventory = await self._projects(app)
        matches = [item for item in inventory if item["id"] == project_id]
        if len(matches) != 1:
            raise TaskError("stale_project_ref", "Selected project is absent from the backend")
        response = await app.request("project/read", {"projectId": project_id})
        project = response.get("project")
        if not isinstance(project, dict) or project.get("id") != project_id:
            raise TaskError("stale_project_ref", "Selected project could not be revalidated")
        roots = project.get("roots")
        if not isinstance(roots, list) or not roots:
            raise TaskError("project_has_no_roots", "Selected project has no local roots")
        canonical_roots: list[str] = []
        for root in roots:
            if not isinstance(root, dict) or not isinstance(root.get("path"), str):
                raise TaskError("invalid_project_roots", "Selected project roots are invalid")
            canonical_roots.append(_path(root["path"]))
        if cwd is None:
            if len(set(canonical_roots)) != 1:
                raise TaskError("cwd_required", "Select one working directory from this project's roots")
            resolved_cwd = canonical_roots[0]
        else:
            resolved_cwd = _path(cwd)
            if resolved_cwd not in canonical_roots:
                raise TaskError("cwd_not_project_root", "Working directory is not a root of this project")
        return project, resolved_cwd

    async def task_create(
        self, project_ref: str, title: str, prompt: str, idempotency_key: str,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise TaskError("invalid_title", "Task title must contain 1 to 200 characters")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 200_000:
            raise TaskError("invalid_prompt", "Initial prompt must contain 1 to 200,000 characters")
        if not isinstance(idempotency_key, str) or not KEY_PATTERN.fullmatch(idempotency_key):
            raise TaskError("invalid_idempotency_key", "Idempotency key has an invalid format")
        async with self.create_lock:
            if self.quiesced:
                raise TaskError("service_stopping", "Task broker is stopping; retry after it starts")
            app = await self.ensure_connected()
            existing = self.ledger.by_key(app.backend_identity, idempotency_key)
            if existing is not None:
                resolved_cwd = _path(cwd) if cwd is not None else existing["cwd"]
                requested_hash = _digest(json.dumps(
                    [project_ref, resolved_cwd, title, _digest(prompt)],
                    separators=(",", ":"), ensure_ascii=False,
                ))
                if existing["payload_hash"] != requested_hash:
                    raise TaskError(
                        "idempotency_conflict", "Idempotency key is bound to a different request"
                    )
                row = existing
                if row["stage"] == "needs_recovery" and row["task_id"]:
                    row = await self._readback(app, row)
                    row = await self._recover_project_assignment(app, row)
                if row["stage"] == "reserved":
                    await self._resolve_project(app, project_ref, resolved_cwd)
                elif row["stage"] == "submission_rejected":
                    if await self._prove_no_turn(app, row):
                        row = self.ledger.update(
                            app.backend_identity, idempotency_key,
                            stage="titled", submission="pending", reason=None,
                        )
            else:
                project, resolved_cwd = await self._resolve_project(app, project_ref, cwd)
                values = {
                    "backend_identity": app.backend_identity,
                    "idempotency_key": idempotency_key,
                    "project_ref": project_ref,
                    "project_id": project["id"],
                    "cwd": resolved_cwd,
                    "requested_title": title,
                    "prompt_hash": _digest(prompt),
                    "prompt_body": prompt,
                }
                values["payload_hash"] = _digest(json.dumps(
                    [project_ref, resolved_cwd, title, values["prompt_hash"]],
                    separators=(",", ":"), ensure_ascii=False,
                ))
                try:
                    row, _new = self.ledger.reserve(values)
                except KeyConflict as exc:
                    raise TaskError("idempotency_conflict", str(exc)) from exc
            if row["stage"] == "reserved":
                row = await self._create_thread(app, row)
            if row["stage"] == "created" and row["backend_membership"] != "verified":
                row = await self._assign_project(app, row)
            if row["stage"] == "created":
                row = await self._set_title(app, row)
            if row["stage"] == "titled":
                row = await self._submit_prompt(app, row)
            if row["task_id"]:
                row = await self._readback(app, row)
            return self._receipt(row)

    async def _prove_no_turn(self, app: AppClient, row: dict[str, Any]) -> bool:
        try:
            result = await app.request(
                "thread/read", {"threadId": row["task_id"], "includeTurns": True}
            )
        except AppServerError:
            return False
        thread = result.get("thread")
        return (
            isinstance(thread, dict) and thread.get("id") == row["task_id"]
            and thread.get("projectId") == row["project_id"]
            and thread.get("turns") == []
        )

    async def _create_thread(self, app: AppClient, row: dict[str, Any]) -> dict[str, Any]:
        backend, key = row["backend_identity"], row["idempotency_key"]
        row = self.ledger.update(backend, key, stage="create_sending", creation="sending")
        try:
            result = await app.request("thread/start", {
                "cwd": row["cwd"], "projectId": row["project_id"],
                "ephemeral": False, "serviceName": "codex-task-tools",
            })
        except NotSent:
            return self.ledger.update(backend, key, stage="reserved", creation="not_sent")
        except (OutcomeUnknown, RPCRejected, AppServerError):
            return self.ledger.update(
                backend, key, stage="needs_recovery", creation="unknown",
                reason="thread_start_outcome_unknown",
            )
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            return self.ledger.update(
                backend, key, stage="needs_recovery", creation="unknown",
                reason="invalid_thread_start_response",
            )
        task_id = thread["id"]
        if thread.get("ephemeral") is True or thread.get("projectId") not in (row["project_id"], None):
            return self.ledger.update(
                backend, key, task_id=task_id, stage="needs_recovery", creation="created",
                backend_membership="mismatch", reason="thread_start_project_mismatch",
            )
        effective = {
            name: result.get(name) for name in (
                "model", "modelProvider", "sandbox", "approvalPolicy", "approvalsReviewer",
                "activePermissionProfile", "runtimeWorkspaceRoots", "serviceTier",
            )
        }
        row = self.ledger.update(
            backend, key, task_id=task_id, stage="created", creation="created",
            effective_settings=json.dumps(effective, separators=(",", ":")),
            instruction_sources=json.dumps(result.get("instructionSources", [])),
        )
        return row

    async def _assign_project(self, app: AppClient, row: dict[str, Any]) -> dict[str, Any]:
        """Assign using the explicit metadata API; a start acknowledgement is insufficient."""
        backend, key = row["backend_identity"], row["idempotency_key"]
        row = self.ledger.update(
            backend, key, stage="assign_sending", backend_membership="assigning",
            reason=None,
        )
        try:
            result = await app.request("thread/metadata/update", {
                "threadId": row["task_id"], "projectId": row["project_id"],
            })
        except NotSent:
            return self.ledger.update(
                backend, key, stage="created", backend_membership="unverified",
                reason="project_assignment_not_sent",
            )
        except RPCRejected:
            return self.ledger.update(
                backend, key, stage="needs_recovery", backend_membership="unverified",
                reason="project_assignment_rejected",
            )
        except (OutcomeUnknown, AppServerError):
            return self.ledger.update(
                backend, key, stage="needs_recovery", backend_membership="unknown",
                reason="project_assignment_outcome_unknown",
            )
        thread = result.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != row["task_id"]:
            return self.ledger.update(
                backend, key, stage="needs_recovery", backend_membership="unknown",
                reason="invalid_project_assignment_response",
            )
        if thread.get("projectId") != row["project_id"]:
            return self.ledger.update(
                backend, key, stage="needs_recovery", backend_membership="mismatch",
                reason="project_assignment_ack_mismatch",
            )
        row = self.ledger.update(
            backend, key, stage="assign_acknowledged", backend_membership="acknowledged",
        )
        for attempt in range(3):
            row = await self._readback(app, row)
            if row["backend_membership"] == "verified":
                return self.ledger.update(backend, key, stage="created", reason=None)
            if attempt < 2:
                await asyncio.sleep(0.2 * (attempt + 1))
        return self.ledger.update(
            backend, key, stage="needs_recovery", reason="project_assignment_readback_unavailable",
        )

    async def _recover_project_assignment(
        self, app: AppClient, row: dict[str, Any]
    ) -> dict[str, Any]:
        """Continue only when readback proves the safe state of this same task."""
        if row["stage"] != "needs_recovery" or not row["task_id"]:
            return row
        reasons_after_attempt = {
            "project_assignment_outcome_unknown",
            "project_assignment_readback_unavailable",
            "invalid_project_assignment_response",
            "broker_restart_during_assignment",
        }
        safe_to_retry = {"backend_membership_unverified", "project_assignment_rejected"}
        if row["reason"] not in reasons_after_attempt | safe_to_retry:
            return row
        try:
            result = await app.request(
                "thread/read", {"threadId": row["task_id"], "includeTurns": True}
            )
        except AppServerError:
            return row
        thread = result.get("thread")
        if (
            not isinstance(thread, dict) or thread.get("id") != row["task_id"]
            or thread.get("cwd") != row["cwd"] or thread.get("ephemeral") is not False
            or thread.get("turns") != [] or thread.get("name") not in (None, "")
        ):
            return row
        if thread.get("projectId") == row["project_id"]:
            return self.ledger.update(
                row["backend_identity"], row["idempotency_key"],
                stage="created", backend_membership="verified", reason=None,
            )
        if row["reason"] in safe_to_retry and thread.get("projectId") is None:
            # The older broker never dispatched metadata/update; a definitive RPC
            # rejection is also safe to retry after readback proves no assignment.
            return self.ledger.update(
                row["backend_identity"], row["idempotency_key"],
                stage="created", backend_membership="unverified", reason=None,
            )
        return row

    async def _set_title(self, app: AppClient, row: dict[str, Any]) -> dict[str, Any]:
        backend, key = row["backend_identity"], row["idempotency_key"]
        row = self.ledger.update(backend, key, stage="title_sending", title_status="sending")
        try:
            await app.request("thread/name/set", {
                "threadId": row["task_id"], "name": row["requested_title"],
            })
        except NotSent:
            return self.ledger.update(backend, key, stage="created", title_status="not_sent")
        except (OutcomeUnknown, RPCRejected, AppServerError):
            return self.ledger.update(
                backend, key, stage="needs_recovery", title_status="unknown",
                reason="title_outcome_unknown",
            )
        try:
            read = await app.request("thread/read", {"threadId": row["task_id"], "includeTurns": False})
            thread = read.get("thread")
            if not isinstance(thread, dict) or thread.get("name") != row["requested_title"]:
                raise TaskError("title_unverified", "Task title could not be verified")
        except (AppServerError, TaskError):
            return self.ledger.update(
                backend, key, stage="needs_recovery", title_status="unverified",
                reason="title_readback_unavailable",
            )
        return self.ledger.update(backend, key, stage="titled", title_status="verified")

    async def _submit_prompt(self, app: AppClient, row: dict[str, Any]) -> dict[str, Any]:
        backend, key = row["backend_identity"], row["idempotency_key"]
        prompt = row["prompt_body"]
        if not isinstance(prompt, str) or _digest(prompt) != row["prompt_hash"]:
            return self.ledger.update(
                backend, key, stage="needs_recovery", submission="blocked",
                reason="private_prompt_unavailable",
            )
        row = self.ledger.update(backend, key, stage="turn_sending", submission="sending")
        try:
            result = await app.request("turn/start", {
                "threadId": row["task_id"], "input": [{"type": "text", "text": prompt}],
            })
        except NotSent:
            return self.ledger.update(backend, key, stage="titled", submission="not_sent")
        except RPCRejected:
            return self.ledger.update(
                backend, key, stage="submission_rejected", submission="rejected",
                reason="turn_start_rejected",
            )
        except (OutcomeUnknown, AppServerError):
            return self.ledger.update(
                backend, key, stage="needs_recovery", submission="unknown",
                reason="turn_start_outcome_unknown",
            )
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            return self.ledger.update(
                backend, key, stage="needs_recovery", submission="unknown",
                reason="invalid_turn_start_response",
            )
        return self.ledger.update(
            backend, key, turn_id=turn["id"], stage="submitted", submission="accepted",
            execution="in_progress", prompt_body=None, reason=None,
        )

    async def _readback(
        self, app: AppClient, row: dict[str, Any], *, verify_index: bool = True
    ) -> dict[str, Any]:
        task_id = row["task_id"]
        if not task_id:
            return row
        try:
            read = await app.request("thread/read", {"threadId": task_id, "includeTurns": True})
        except AppServerError:
            return row
        thread = read.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != task_id:
            return row
        updates: dict[str, Any] = {}
        if thread.get("projectId") == row["project_id"]:
            updates["backend_membership"] = "verified"
        elif "projectId" in thread:
            updates["backend_membership"] = "mismatch"
        turns = thread.get("turns")
        if (
            row["stage"] == "needs_recovery"
            and row["reason"] == "backend_membership_unverified"
            and thread.get("projectId") == row["project_id"]
            and thread.get("name") in (None, "") and turns == []
        ):
            updates.update(stage="created", reason=None)
        if thread.get("name") == row["requested_title"]:
            if row["title_status"] in {"verified", "drifted"}:
                updates["title_status"] = "verified"
            elif (
                row["title_status"] in {"unknown", "unverified"}
                and row["submission"] == "pending"
                and turns == [] and thread.get("projectId") == row["project_id"]
            ):
                updates["title_status"] = "verified"
                updates["stage"] = "titled"
                updates["reason"] = None
        elif row["title_status"] == "verified":
            updates["title_status"] = "drifted"
        if isinstance(turns, list) and row["submission"] == "unknown" and not row["turn_id"]:
            matches = [
                turn for turn in turns
                if isinstance(turn, dict) and isinstance(turn.get("id"), str)
                and self._prompt_count(turn, row["prompt_hash"]) > 0
            ]
            if len(matches) == 1 and self._prompt_count(matches[0], row["prompt_hash"]) == 1:
                updates.update(
                    turn_id=matches[0]["id"], submission="accepted",
                    prompt_delivery="verified_once", prompt_body=None, stage="submitted",
                    reason=None,
                )
                status = matches[0].get("status")
                if status in {"completed", "failed", "interrupted", "inProgress"}:
                    updates["execution"] = "in_progress" if status == "inProgress" else status
            elif matches:
                updates.update(prompt_delivery="duplicate", reason="duplicate_prompt_in_history")
        if isinstance(turns, list) and row["turn_id"]:
            for turn in turns:
                if isinstance(turn, dict) and turn.get("id") == row["turn_id"]:
                    status = turn.get("status")
                    if status in {"completed", "failed", "interrupted", "inProgress"}:
                        updates["execution"] = "in_progress" if status == "inProgress" else status
                    items = turn.get("items")
                    if isinstance(items, list):
                        delivered = self._prompt_count(turn, row["prompt_hash"])
                        if delivered == 1:
                            updates["prompt_delivery"] = "verified_once"
                        elif delivered > 1:
                            updates["prompt_delivery"] = "duplicate"
                    break
        if verify_index:
            try:
                if await self._indexed_task(app, task_id):
                    updates["persistence"] = "verified"
            except AppServerError:
                pass
        if updates:
            row = self.ledger.update(row["backend_identity"], row["idempotency_key"], **updates)
            if updates.get("execution") in {"completed", "failed", "interrupted"}:
                self.ledger.resolve_for_task(row["backend_identity"], task_id)
        return row

    @staticmethod
    def _prompt_count(turn: dict[str, Any], prompt_hash: str) -> int:
        items = turn.get("items")
        if not isinstance(items, list):
            return 0
        matches = 0
        for item in items:
            if not isinstance(item, dict) or item.get("type") != "userMessage":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict) and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                    and _digest(part["text"]) == prompt_hash
                ):
                    matches += 1
        return matches

    async def _indexed_task(self, app: AppClient, task_id: str) -> bool:
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(200):
            page = await app.request("thread/list", {
                "cursor": cursor, "limit": 100, "archived": False, "useStateDbOnly": True,
                "modelProviders": [],
                "sourceKinds": ["cli", "vscode", "exec", "appServer", "subAgent",
                                "subAgentReview", "subAgentCompact", "subAgentThreadSpawn",
                                "subAgentOther", "unknown"],
            })
            data = page.get("data")
            if not isinstance(data, list):
                return False
            if any(isinstance(item, dict) and item.get("id") == task_id for item in data):
                return True
            cursor = page.get("nextCursor")
            if cursor is None:
                return False
            if not isinstance(cursor, str) or cursor in seen:
                return False
            seen.add(cursor)
        return False

    def _receipt(self, row: dict[str, Any]) -> dict[str, Any]:
        pending = []
        if row["task_id"]:
            pending = [
                {
                    "requestId": item["request_id"], "method": item["method"],
                    "state": item["state"], "details": strict_json(item["params"]),
                    "observedAt": item["observed_at"],
                }
                for item in self.ledger.pending_for(row["backend_identity"], row["task_id"])
            ]
        return {
            "taskId": row["task_id"], "turnId": row["turn_id"],
            "idempotencyKey": row["idempotency_key"], "projectRef": row["project_ref"],
            "projectId": row["project_id"], "cwd": row["cwd"],
            "requestedTitle": row["requested_title"],
            "creation": row["creation"], "title": row["title_status"],
            "submission": row["submission"], "promptDelivery": row["prompt_delivery"],
            "execution": row["execution"],
            "persistence": row["persistence"], "backendMembership": row["backend_membership"],
            "desktopVerification": row["desktop_verification"],
            "effectiveSettings": strict_json(row["effective_settings"]) if row["effective_settings"] else None,
            "instructionSources": strict_json(row["instruction_sources"]) if row["instruction_sources"] else [],
            "pendingRequests": pending, "needsAttention": row["stage"] == "needs_recovery"
                or any(item["state"] != "pending" for item in pending),
            "reason": row["reason"], "observedAt": row["observed_at"],
        }

    async def task_status(
        self, task_id: str | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        if bool(task_id) == bool(idempotency_key):
            raise TaskError("invalid_lookup", "Provide exactly one task ID or idempotency key")
        app = await self.ensure_connected()
        row = (
            self.ledger.by_task(app.backend_identity, task_id) if task_id else
            self.ledger.by_key(app.backend_identity, idempotency_key or "")
        )
        if row is None:
            raise TaskError("unknown_task", "No tracked task matches this identifier")
        if row["task_id"]:
            row = await self._readback(app, row)
        return self._receipt(row)

    async def _refresh(self, key: str) -> None:
        try:
            await self.task_status(idempotency_key=key)
        except (AppServerError, TaskError):
            pass

    async def task_respond(
        self, task_id: str, request_id: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        app = await self.ensure_connected()
        row = self.ledger.by_task(app.backend_identity, task_id)
        if row is None:
            raise TaskError("unknown_task", "No tracked task matches this task ID")
        pending = self.ledger.pending_exact(app.backend_identity, task_id, request_id)
        if pending is None or pending["generation"] != app.generation:
            raise TaskError("stale_request", "Pending request is absent or belongs to a stale connection")
        self._validate_response(pending["method"], strict_json(pending["params"]), response)
        self.ledger.pending_state(
            app.backend_identity, task_id, request_id, app.generation, "responding"
        )
        try:
            await app.send_response(strict_json(request_id), response)
        except (OutcomeUnknown, AppServerError):
            self.ledger.pending_state(
                app.backend_identity, task_id, request_id, app.generation, "needs_attention",
                expected_state="responding",
            )
            raise TaskError("response_unknown", "Approval response outcome is unknown") from None
        self.ledger.pending_state(
            app.backend_identity, task_id, request_id, app.generation, "sent_unconfirmed",
            expected_state="responding",
        )
        return await self.task_status(task_id=task_id)

    @staticmethod
    def _validate_response(
        method: str, params: dict[str, Any], response: dict[str, Any]
    ) -> None:
        if not isinstance(response, dict):
            raise TaskError("invalid_response", "Response must be an object")
        if params.get("truncated"):
            raise TaskError("unsupported_request", "Request details exceeded the supported limit")
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            if (
                set(response) != {"decision"}
                or not isinstance(response["decision"], str)
                or response["decision"] not in {
                "accept", "decline", "cancel"
                }
            ):
                raise TaskError("invalid_response", "Use a single accept, decline, or cancel decision")
            if method == "item/commandExecution/requestApproval":
                available = params.get("availableDecisions")
                if available is not None and (
                    not isinstance(available, list) or response["decision"] not in available
                ):
                    raise TaskError("invalid_response", "Decision is not offered for this request")
            return
        if method == "item/tool/requestUserInput":
            answers = response.get("answers")
            if set(response) != {"answers"} or not isinstance(answers, dict) or any(
                not isinstance(k, str) or not isinstance(v, dict)
                or set(v) != {"answers"} or not isinstance(v["answers"], list)
                or any(not isinstance(x, str) for x in v["answers"])
                for k, v in answers.items()
            ):
                raise TaskError("invalid_response", "User-input answer shape is invalid")
            questions = params.get("questions")
            if (
                not isinstance(questions, list)
                or set(answers) != {
                    item.get("id") for item in questions if isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                }
            ):
                raise TaskError("invalid_response", "Answers must match the current question IDs")
            return
        raise TaskError("unsupported_request", "This request requires another supported client")

    async def recover_adopt(self, idempotency_key: str, task_id: str) -> dict[str, Any]:
        """Explicit operator adoption of an uncertain thread/start result."""
        async with self.create_lock:
            if self.quiesced:
                raise TaskError("service_stopping", "Task broker is stopping; retry after it starts")
            app = await self.ensure_connected()
            row = self.ledger.by_key(app.backend_identity, idempotency_key)
            if row is None or row["creation"] != "unknown" or row["task_id"] is not None:
                raise TaskError("not_adoptable", "This key has no uncertain creation to adopt")
            if self.ledger.by_task(app.backend_identity, task_id) is not None:
                raise TaskError("adoption_mismatch", "Task ID is already tracked by this broker")
            read = await app.request("thread/read", {"threadId": task_id, "includeTurns": True})
            thread = read.get("thread")
            if (
                not isinstance(thread, dict) or thread.get("id") != task_id
                or thread.get("projectId") not in (None, row["project_id"])
                or thread.get("ephemeral") is not False
                or thread.get("cwd") != row["cwd"]
                or thread.get("name") not in (None, "", row["requested_title"])
                or thread.get("turns") != []
            ):
                raise TaskError("adoption_mismatch", "Task does not match the reserved project and empty history")
            row = self.ledger.update(
                app.backend_identity, idempotency_key, task_id=task_id, stage="created",
                creation="adopted",
                backend_membership=(
                    "verified" if thread.get("projectId") == row["project_id"] else "unverified"
                ),
                reason=None,
            )
            if row["backend_membership"] != "verified":
                row = await self._assign_project(app, row)
            if row["stage"] == "created" and thread.get("name") == row["requested_title"]:
                row = self.ledger.update(
                    app.backend_identity, idempotency_key, stage="titled", title_status="verified"
                )
            elif row["stage"] == "created":
                row = await self._set_title(app, row)
            if row["stage"] == "titled":
                row = await self._submit_prompt(app, row)
            return self._receipt(await self._readback(app, row))

    async def service_quiesce(self, enabled: bool) -> dict[str, Any]:
        """Drain an in-progress create before allowing the service to stop."""
        if not isinstance(enabled, bool):
            raise TaskError("invalid_request", "Quiesce value must be a boolean")
        async with self.create_lock:
            self.quiesced = enabled
        return self.service_status()

    def service_status(self) -> dict[str, Any]:
        app = self.app
        if app is None:
            return {"running": True, "backendConnected": False,
                    "appServerVersion": None, "backendIdentity": None,
                    "activeTaskCount": None, "pendingApprovalCount": None,
                    "quiesced": self.quiesced, "eventProcessingError": self.event_blocked}
        if self.event_blocked:
            return {"running": True, "backendConnected": True,
                    "appServerVersion": app.version,
                    "backendIdentity": app.backend_identity[:20],
                    "activeTaskCount": None, "pendingApprovalCount": None,
                    "quiesced": self.quiesced, "eventProcessingError": True}
        tracked = self.ledger.tracked(app.backend_identity)
        active_stages = {
            "create_sending", "assign_sending", "assign_acknowledged", "created",
            "title_sending", "titled", "turn_sending",
        }
        active = sum(
            row["stage"] in active_stages or row["submission"] == "unknown"
            or (row["submission"] == "accepted" and row["execution"] not in
                {"completed", "failed", "interrupted"})
            for row in tracked
        )
        # A request may hold the lock before its first journal transition.
        if self.create_lock.locked() and active == 0:
            active = 1
        pending = sum(
            len(self.ledger.pending_for(app.backend_identity, row["task_id"]))
            for row in tracked
        )
        return {"running": True, "backendConnected": True,
                "appServerVersion": app.version,
                "backendIdentity": app.backend_identity[:20],
                "activeTaskCount": active, "pendingApprovalCount": pending,
                "quiesced": self.quiesced, "eventProcessingError": False}


def _claim_broker_lock(state_dir: Path) -> int:
    """Prevent two broker processes from dispatching the same journaled request."""
    state_dir = private_dir(state_dir)
    lock_path = state_dir / "broker.lock"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise LedgerError("Broker ownership lock is unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except (OSError, LedgerError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise LedgerError("Another broker owns the task journal or its lock is unsafe") from exc


async def _serve(state_dir: Path) -> None:
    state_dir = private_dir(state_dir)
    descriptor = _claim_broker_lock(state_dir)
    try:
        await _serve_locked(state_dir)
    finally:
        os.close(descriptor)


async def _serve_locked(state_dir: Path) -> None:
    socket_path = state_dir / "broker.sock"
    if socket_path.exists():
        if socket_path.is_symlink() or not socket_path.is_socket():
            raise LedgerError("Broker socket path is unsafe")
        try:
            probe = await asyncio.wait_for(asyncio.open_unix_connection(str(socket_path)), 1)
            probe[1].close()
            await probe[1].wait_closed()
            raise LedgerError("Another task broker is already listening")
        except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
            socket_path.unlink()
    broker = TaskBroker(state_dir)
    broker.event_task = asyncio.create_task(broker._event_loop(), name="task-events")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), 120)
            if len(raw) > 1024 * 1024:
                raise TaskError("oversize_request", "Broker request is too large")
            value = strict_json(raw)
            if not isinstance(value, dict):
                raise TaskError("invalid_request", "Broker request is invalid")
            operation, params = value.get("operation"), value.get("params", {})
            if not isinstance(params, dict):
                raise TaskError("invalid_request", "Broker request is invalid")
            if operation == "projects_find":
                result = await broker.projects_find(**params)
            elif operation == "task_create":
                result = await broker.task_create(**params)
            elif operation == "task_status":
                result = await broker.task_status(**params)
            elif operation == "task_respond":
                result = await broker.task_respond(**params)
            elif operation == "recover_adopt":
                result = await broker.recover_adopt(**params)
            elif operation == "service_status":
                result = broker.service_status()
            elif operation == "service_quiesce":
                result = await broker.service_quiesce(**params)
            else:
                raise TaskError("unknown_operation", "Unsupported broker operation")
            answer = {"ok": True, "result": result}
        except TaskError as exc:
            answer = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
        except (AppServerError, LedgerError, OSError, TypeError, ValueError):
            answer = {"ok": False, "error": {"code": "unavailable", "message":
                      "Task broker operation is unavailable; inspect service status"}}
        try:
            writer.write((json.dumps(answer, separators=(",", ":")) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, str(socket_path))
    os.chmod(socket_path, 0o600)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        await broker.close()
        socket_path.unlink(missing_ok=True)


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Run the private Codex task broker")
    parser.add_argument("--state-dir", type=Path, default=state_directory())
    args = parser.parse_args()
    asyncio.run(_serve(args.state_dir))
