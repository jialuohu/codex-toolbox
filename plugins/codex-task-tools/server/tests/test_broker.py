"""Deterministic task creation tests. No real Codex daemon or task is used."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from codex_task_tools.app_server import AppServerError, OutcomeUnknown, RPCRejected
from codex_task_tools.broker import TaskBroker, _claim_broker_lock
from codex_task_tools.ledger import LedgerError

ROOT = str(Path(__file__).resolve().parents[4])
PROMPT = "Reply exactly: TOOLBOX_TASK_OK. Do not use tools or change files."


class FakeAppServer:
    """An in-memory App Server with injectable post-commit transport loss."""

    def __init__(
        self,
        *,
        projects: list[dict[str, Any]] | None = None,
        backend_identity: str = "a" * 64,
        version: str = "0.156.1",
    ) -> None:
        self.projects = projects or [
            {"id": "project-1", "name": "codex-toolbox", "roots": [{"path": ROOT}]}
        ]
        self.backend_identity = backend_identity
        self.version = version
        self.generation = "generation-1"
        self.threads: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.lost_after_commit: Counter[str] = Counter()
        self.reject_before_commit: Counter[str] = Counter()
        self.read_absent: Counter[str] = Counter()
        self.connect_failures = 0
        self.null_project_on_start = False
        self.metadata_stays_null = False
        self.duplicate_user_messages = False
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.responses: list[tuple[Any, Any]] = []
        self.connected = False

    async def connect(self) -> None:
        if self.connect_failures:
            self.connect_failures -= 1
            raise AppServerError("fixture connection unavailable")
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def next_event(self) -> dict[str, Any]:
        return await self.events.get()

    async def send_response(self, request_id: Any, result: Any) -> None:
        self.responses.append((request_id, copy.deepcopy(result)))

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, copy.deepcopy(params)))
        if self.reject_before_commit[method]:
            self.reject_before_commit[method] -= 1
            raise RPCRejected(method, -32000)

        if method == "project/list":
            result = {"data": copy.deepcopy(self.projects), "nextCursor": None}
        elif method == "project/read":
            project = next(item for item in self.projects if item["id"] == params["projectId"])
            result = {"project": copy.deepcopy(project)}
        elif method == "thread/start":
            task_id = f"task-{len(self.threads) + 1}"
            thread = {
                "id": task_id,
                "name": None,
                "cwd": params.get("cwd"),
                "projectId": None if self.null_project_on_start else params.get("projectId"),
                "ephemeral": params.get("ephemeral"),
                "turns": [],
                "status": {"type": "notLoaded"},
            }
            self.threads[task_id] = thread
            self.turns[task_id] = []
            result = {"thread": copy.deepcopy(thread)}
        elif method == "thread/metadata/update":
            thread = self.threads[params["threadId"]]
            if not self.metadata_stays_null:
                thread["projectId"] = params["projectId"]
            result = {"thread": copy.deepcopy(thread)}
        elif method == "thread/name/set":
            thread = self.threads[params["threadId"]]
            thread["name"] = params["name"]
            result = {}
        elif method == "thread/read":
            if self.read_absent[method]:
                self.read_absent[method] -= 1
                return {}
            thread = self.threads[params["threadId"]]
            result = {"thread": copy.deepcopy(thread)}
        elif method == "thread/list":
            if self.read_absent[method]:
                self.read_absent[method] -= 1
                result = {"data": [], "nextCursor": None}
            else:
                result = {"data": copy.deepcopy(list(self.threads.values())), "nextCursor": None}
        elif method == "thread/resume":
            result = {"thread": copy.deepcopy(self.threads[params["threadId"]])}
        elif method == "turn/start":
            task_id = params["threadId"]
            turn_id = f"turn-{len(self.turns[task_id]) + 1}"
            user_message = {"type": "userMessage", "content": copy.deepcopy(params["input"])}
            items = [user_message]
            if self.duplicate_user_messages:
                items.append(copy.deepcopy(user_message))
            turn = {"id": turn_id, "status": "inProgress", "items": items}
            self.turns[task_id].append(turn)
            self.threads[task_id]["turns"] = copy.deepcopy(self.turns[task_id])
            result = {"turn": copy.deepcopy(turn)}
        else:
            raise AssertionError(f"Unexpected App Server method: {method}")

        if self.lost_after_commit[method]:
            self.lost_after_commit[method] -= 1
            raise OutcomeUnknown(f"fixture lost {method} response after commit")
        return result

    def count(self, method: str) -> int:
        return sum(candidate == method for candidate, _ in self.calls)


def project_ref(found: dict[str, Any]) -> str:
    """Take the canonical reference returned by the public project lookup."""
    projects = found.get("projects") or found.get("data")
    assert isinstance(projects, list) and len(projects) == 1, found
    ref = projects[0].get("projectRef") or projects[0].get("ref")
    assert isinstance(ref, str) and ref, found
    return ref


async def create(
    broker: TaskBroker,
    ref: str,
    *,
    key: str = "smoke-1",
    title: str = "Codex Toolbox task-creation smoke test",
    prompt: str = PROMPT,
    cwd: str | None = ROOT,
) -> dict[str, Any]:
    return await broker.task_create(
        project_ref=ref,
        title=title,
        prompt=prompt,
        idempotency_key=key,
        cwd=cwd,
    )


def assert_no_forbidden_mutations(app: FakeAppServer) -> None:
    methods = {method for method, _ in app.calls}
    assert methods <= {
        "project/list",
        "project/read",
        "thread/start",
        "thread/metadata/update",
        "thread/name/set",
        "turn/start",
        "thread/read",
        "thread/list",
        "thread/resume",
        "thread/loaded/list",
    }


def test_create_assigns_explicit_project_and_submits_one_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        result = await create(broker, ref)

        assert result["taskId"] == "task-1"
        assert app.count("thread/start") == 1
        assert app.count("thread/name/set") == 1
        assert app.count("turn/start") == 1
        start = next(params for method, params in app.calls if method == "thread/start")
        assert start["projectId"] == "project-1"
        assert start["ephemeral"] is False
        assert start["cwd"] == ROOT
        sent = next(params for method, params in app.calls if method == "turn/start")
        assert [item["text"] for item in sent["input"] if item.get("type") == "text"] == [PROMPT]
        assert app.threads["task-1"]["name"] == "Codex Toolbox task-creation smoke test"
        assert_no_forbidden_mutations(app)

    asyncio.run(exercise())


def test_unsupported_runtime_cannot_create(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer(version="0.999.0")
        broker = TaskBroker(tmp_path, lambda: app)
        with pytest.raises(Exception, match="(?i)(unsupported|certified)"):
            await broker.projects_find()
        assert app.calls == []

    asyncio.run(exercise())


def test_exact_retry_and_restart_never_duplicate_task_or_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        first = await create(broker, ref)
        same = await create(broker, ref)
        restarted = await create(TaskBroker(tmp_path, lambda: app), ref)

        assert first["taskId"] == same["taskId"] == restarted["taskId"]
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1
        assert_no_forbidden_mutations(app)

    asyncio.run(exercise())


def test_exact_retry_returns_existing_receipt_after_project_disappears(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        first = await create(broker, ref)
        app.projects = []
        same = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert same["taskId"] == first["taskId"]
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_initial_read_and_index_delay_do_not_strand_created_task(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.read_absent["thread/read"] = 1
        app.read_absent["thread/list"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        result = await create(broker, ref)
        assert result["creation"] == "created"
        assert result["backendMembership"] == "verified"
        assert result["submission"] == "accepted"
        assert result["persistence"] == "verified"
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_concurrent_same_key_creates_one_task(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        first, second = await asyncio.gather(create(broker, ref), create(broker, ref))
        assert first["taskId"] == second["taskId"]
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_key_cannot_be_reused_with_changed_payload(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        await create(broker, ref)
        with pytest.raises(Exception, match="(?i)(conflict|different|idempotency)"):
            await create(broker, ref, prompt="Different prompt")
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_private_state_does_not_store_prompt_and_uses_restrictive_modes(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("codex-toolbox"))
        await create(broker, ref)

        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        files = [path for path in tmp_path.rglob("*") if path.is_file()]
        assert files
        for path in files:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            raw = path.read_bytes()
            assert PROMPT.encode() not in raw
            assert b"Authorization" not in raw
        assert_no_forbidden_mutations(app)

    asyncio.run(exercise())


def test_lookup_exposes_ambiguous_names_without_selecting_one(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer(
            projects=[
                {"id": "project-1", "name": "same-name", "roots": [{"path": ROOT}]},
                {"id": "project-2", "name": "same-name", "roots": [{"path": "/fixture/other"}]},
            ]
        )
        broker = TaskBroker(tmp_path, lambda: app)
        found = await broker.projects_find("same-name")
        projects = found.get("projects") or found.get("data")
        assert isinstance(projects, list) and len(projects) == 2
        assert app.count("thread/start") == 0

    asyncio.run(exercise())


def test_multi_root_project_needs_explicit_directory(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer(
            projects=[
                {
                    "id": "project-1",
                    "name": "multi-root",
                    "roots": [{"path": ROOT}, {"path": "/fixture/second-root"}],
                }
            ]
        )
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find("multi-root"))
        with pytest.raises(Exception, match="(?i)(cwd|directory|root|ambiguous)"):
            await create(broker, ref, cwd=None)
        assert app.count("thread/start") == 0

    asyncio.run(exercise())


def test_wrong_backend_project_reference_cannot_create(tmp_path: Path) -> None:
    async def exercise() -> None:
        source = FakeAppServer(backend_identity="a" * 64)
        foreign_ref = project_ref(await TaskBroker(tmp_path / "a", lambda: source).projects_find())
        destination = FakeAppServer(backend_identity="b" * 64)
        broker = TaskBroker(tmp_path / "b", lambda: destination)
        with pytest.raises(Exception, match="(?i)(backend|host|project|reference)"):
            await create(broker, foreign_ref)
        assert destination.count("thread/start") == 0

    asyncio.run(exercise())


def test_lost_creation_response_never_causes_blind_duplicate(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.lost_after_commit["thread/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        try:
            await create(broker, ref)
        except Exception:
            pass
        try:
            await create(TaskBroker(tmp_path, lambda: app), ref)
        except Exception:
            pass
        assert app.count("thread/start") == 1
        assert len(app.threads) == 1
        assert app.count("turn/start") == 0

    asyncio.run(exercise())


def test_null_start_project_is_explicitly_assigned_before_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.null_project_on_start = True
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        result = await create(broker, ref)
        assert result["taskId"] == "task-1"
        assert result["backendMembership"] == "verified"
        assert result["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("thread/metadata/update") == 1
        assert app.count("turn/start") == 1
        mutations = [method for method, _ in app.calls]
        assert mutations.index("thread/metadata/update") < mutations.index("thread/name/set")
        assert mutations.index("thread/metadata/update") < mutations.index("turn/start")
        assert app.threads["task-1"]["projectId"] == "project-1"

    asyncio.run(exercise())


def test_lost_assignment_response_reconciles_same_task_before_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.null_project_on_start = True
        app.lost_after_commit["thread/metadata/update"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        held = await create(broker, ref)
        assert held["taskId"] == "task-1"
        assert held["submission"] != "accepted"
        assert app.count("turn/start") == 0
        recovered = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert recovered["taskId"] == "task-1"
        assert recovered["backendMembership"] == "verified"
        assert recovered["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("thread/metadata/update") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_held_unassigned_task_recovers_on_existing_key_without_new_start(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        app.threads["task-1"] = {
            "id": "task-1", "name": None, "cwd": ROOT, "projectId": None,
            "ephemeral": False, "turns": [], "status": {"type": "notLoaded"},
        }
        app.turns["task-1"] = []
        title = "Codex Toolbox task-creation smoke test"
        prompt_hash = hashlib.sha256(PROMPT.encode()).hexdigest()
        payload_hash = hashlib.sha256(json.dumps(
            [ref, ROOT, title, prompt_hash], separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
        broker.ledger.reserve({
            "backend_identity": app.backend_identity, "idempotency_key": "smoke-1",
            "payload_hash": payload_hash, "project_ref": ref, "project_id": "project-1",
            "cwd": ROOT, "requested_title": title, "prompt_hash": prompt_hash,
            "prompt_body": PROMPT,
        })
        # A previous broker held this task after thread/start returned null projectId.
        broker.ledger.update(
            app.backend_identity, "smoke-1", task_id="task-1", creation="created",
            stage="needs_recovery",
            backend_membership="unverified", reason="backend_membership_unverified",
        )
        recovered = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert recovered["taskId"] == "task-1"
        assert recovered["backendMembership"] == "verified"
        assert recovered["submission"] == "accepted"
        assert app.count("thread/start") == 0
        assert app.count("thread/metadata/update") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_unverified_assignment_blocks_title_and_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.null_project_on_start = True
        app.metadata_stays_null = True
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        held = await create(broker, ref)
        assert held["taskId"] == "task-1"
        assert held["backendMembership"] != "verified"
        assert app.count("thread/name/set") == 0
        assert app.count("turn/start") == 0
        assert app.count("thread/start") == 1

    asyncio.run(exercise())


def test_explicit_adoption_of_lost_creation_validates_and_continues_once(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.lost_after_commit["thread/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        uncertain = await create(broker, ref)
        assert uncertain["creation"] == "unknown"
        assert uncertain["taskId"] is None
        adopted = await broker.recover_adopt("smoke-1", "task-1")
        assert adopted["taskId"] == "task-1"
        assert adopted["creation"] == "adopted"
        assert adopted["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_adoption_assigns_null_project_on_same_task(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.null_project_on_start = True
        app.lost_after_commit["thread/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        assert (await create(broker, ref))["creation"] == "unknown"
        adopted = await broker.recover_adopt("smoke-1", "task-1")
        assert adopted["taskId"] == "task-1"
        assert adopted["backendMembership"] == "verified"
        assert adopted["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("thread/metadata/update") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_adoption_requires_proven_empty_history(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.lost_after_commit["thread/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        assert (await create(broker, ref))["creation"] == "unknown"
        app.threads["task-1"].pop("turns")
        with pytest.raises(Exception, match="(?i)(adoption|history)"):
            await broker.recover_adopt("smoke-1", "task-1")
        assert app.count("turn/start") == 0

    asyncio.run(exercise())


def test_lost_name_response_holds_or_recovers_before_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.lost_after_commit["thread/name/set"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        first = await create(broker, ref)
        assert first["taskId"] == "task-1"
        assert first["title"] == "verified"
        assert app.count("turn/start") == 0
        recovered = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert recovered["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("thread/name/set") == 1
        assert app.count("turn/start") == 1
        assert app.threads["task-1"]["name"] == "Codex Toolbox task-creation smoke test"

    asyncio.run(exercise())


def test_lost_prompt_response_never_resends_accepted_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.lost_after_commit["turn/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        first = await create(broker, ref)
        assert first["submission"] == "accepted"
        assert first["promptDelivery"] == "verified_once"
        recovered = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert recovered["submission"] == "accepted"
        assert recovered["promptDelivery"] == "verified_once"
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1
        assert len(app.turns["task-1"]) == 1

    asyncio.run(exercise())


def test_duplicate_user_message_after_lost_response_is_reported_without_replay(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.duplicate_user_messages = True
        app.lost_after_commit["turn/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        first = await create(broker, ref)
        assert first["submission"] == "unknown"
        assert first["promptDelivery"] == "duplicate"
        again = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert again["taskId"] == "task-1"
        assert again["promptDelivery"] == "duplicate"
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_rejected_prompt_retries_only_after_empty_history_is_proven(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        app.reject_before_commit["turn/start"] = 1
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        rejected = await create(broker, ref)
        assert rejected["taskId"] == "task-1"
        assert rejected["submission"] == "rejected"
        assert rejected["turnId"] is None
        again = await create(TaskBroker(tmp_path, lambda: app), ref)
        assert again["taskId"] == "task-1"
        assert again["submission"] == "accepted"
        assert app.count("thread/start") == 1
        assert app.count("turn/start") == 2
        assert len(app.turns["task-1"]) == 1

    asyncio.run(exercise())


def test_pending_approval_requires_exact_live_request_and_explicit_response(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        created = await create(broker, ref)
        await app.events.put(
            {
                "id": "approval-17",
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": created["taskId"], "turnId": created["turnId"]},
            }
        )
        pending = []
        for _ in range(100):
            pending = (await broker.task_status(task_id="task-1"))["pendingRequests"]
            if pending:
                break
            await asyncio.sleep(0.01)
        assert len(pending) == 1
        request_id = pending[0]["requestId"]
        with pytest.raises(Exception, match="(?i)(invalid|decision)"):
            await broker.task_respond("task-1", request_id, {"decision": "acceptForSession"})
        assert app.responses == []
        answered = await broker.task_respond("task-1", request_id, {"decision": "decline"})
        assert answered["taskId"] == "task-1"
        assert answered["pendingRequests"][0]["state"] == "sent_unconfirmed"
        assert app.responses == [("approval-17", {"decision": "decline"})]
        with pytest.raises(Exception, match="(?i)(stale|absent)"):
            await broker.task_respond("task-1", request_id, {"decision": "decline"})
        await broker._handle_event(  # noqa: SLF001 - exercise server confirmation
            app,
            {"method": "serverRequest/resolved", "params": {
                "threadId": "task-1", "requestId": "approval-17"
            }},
        )
        assert (await broker.task_status(task_id="task-1"))["pendingRequests"] == []

    asyncio.run(exercise())


def test_approval_decision_must_be_offered(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        await broker._handle_event(  # noqa: SLF001 - exercise server request contract
            app,
            {"id": "approval-18", "method": "item/commandExecution/requestApproval",
             "params": {"threadId": "task-1", "availableDecisions": ["decline"]}},
        )
        request_id = (await broker.task_status(task_id="task-1"))["pendingRequests"][0][
            "requestId"
        ]
        with pytest.raises(Exception, match="(?i)(decision|offered)"):
            await broker.task_respond("task-1", request_id, {"decision": "accept"})
        assert app.responses == []

    asyncio.run(exercise())


def test_quiesce_waits_for_creation_lock_and_blocks_new_mutations(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        async with broker.create_lock:
            assert broker.service_status()["activeTaskCount"] == 1
            barrier = asyncio.create_task(broker.service_quiesce(True))
            await asyncio.sleep(0)
            assert not barrier.done()
        assert (await barrier)["quiesced"] is True
        with pytest.raises(Exception, match="(?i)(stopping|retry)"):
            await create(broker, ref)
        await broker.service_quiesce(False)
        assert (await create(broker, ref))["submission"] == "accepted"

    asyncio.run(exercise())


def test_only_one_process_can_own_broker_journal(tmp_path: Path) -> None:
    descriptor = _claim_broker_lock(tmp_path)
    try:
        with pytest.raises(LedgerError, match="(?i)(owns|lock)"):
            _claim_broker_lock(tmp_path)
    finally:
        os.close(descriptor)
    recovered = _claim_broker_lock(tmp_path)
    os.close(recovered)


def test_failed_approval_persistence_retries_same_event_and_blocks_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        original = broker.ledger.add_pending
        fail = True
        attempts = 0

        def flaky(*args: Any, **kwargs: Any) -> None:
            nonlocal attempts
            attempts += 1
            if fail:
                raise LedgerError("fixture disk failure")
            original(*args, **kwargs)

        monkeypatch.setattr(broker.ledger, "add_pending", flaky)
        await app.events.put({
            "id": "approval-19", "method": "item/commandExecution/requestApproval",
            "params": {"threadId": "task-1"},
        })
        for _ in range(100):
            if broker.event_blocked:
                break
            await asyncio.sleep(0.01)
        assert broker.event_blocked is True
        assert broker.service_status()["pendingApprovalCount"] is None
        fail = False
        for _ in range(100):
            if (await broker.task_status(task_id="task-1"))["pendingRequests"]:
                break
            await asyncio.sleep(0.01)
        status = await broker.task_status(task_id="task-1")
        assert len(status["pendingRequests"]) == 1
        assert broker.event_blocked is False
        assert attempts >= 2

    asyncio.run(exercise())


def test_unsupported_server_request_is_visible_and_never_answered(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        await broker._handle_event(  # noqa: SLF001 - exercise the recorded event contract
            app,
            {"id": "unsupported-1", "method": "unsupported/request", "params": {
                "threadId": "task-1"
            }},
        )
        status = await broker.task_status(task_id="task-1")
        assert status["pendingRequests"][0]["state"] == "needs_attention"
        assert status["needsAttention"] is True
        with pytest.raises(Exception, match="(?i)(stale|absent|unsupported)"):
            await broker.task_respond(
                "task-1", status["pendingRequests"][0]["requestId"], {"decision": "accept"}
            )
        assert app.responses == []

    asyncio.run(exercise())


def test_server_resolved_event_clears_pending_approval_without_response(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        await broker._handle_event(  # noqa: SLF001 - exercise server event contract
            app,
            {
                "id": "approval-17",
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "task-1"},
            },
        )
        assert len((await broker.task_status(task_id="task-1"))["pendingRequests"]) == 1
        await broker._handle_event(  # noqa: SLF001 - exercise server event contract
            app,
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "task-1", "requestId": "approval-17"},
            },
        )
        status = await broker.task_status(task_id="task-1")
        assert status["pendingRequests"] == []
        with pytest.raises(Exception, match="(?i)(stale|absent)"):
            await broker.task_respond("task-1", '"approval-17"', {"decision": "accept"})
        assert app.responses == []

    asyncio.run(exercise())


def test_reconnect_retries_service_connection_without_resending_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        initial = FakeAppServer()
        unavailable = FakeAppServer()
        unavailable.connect_failures = 1
        recovered = FakeAppServer()
        recovered.generation = "generation-3"
        apps = iter([initial, unavailable, recovered])
        broker = TaskBroker(tmp_path, lambda: next(apps))
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        for app in (unavailable, recovered):
            app.threads = initial.threads
            app.turns = initial.turns

        original_sleep = asyncio.sleep

        async def immediate_sleep(_delay: float) -> None:
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
        await initial.events.put({"method": "_connection_lost", "params": {}})
        for _ in range(100):
            if broker.app is recovered:
                break
            await original_sleep(0.01)
        assert broker.app is recovered
        assert recovered.count("thread/resume") == 1
        assert initial.count("turn/start") == 1
        assert recovered.count("turn/start") == 0
        assert (await broker.task_status(task_id="task-1"))["taskId"] == "task-1"

    asyncio.run(exercise())


def test_reconnect_readback_clears_stale_active_status(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        assert broker.service_status()["activeTaskCount"] == 1
        app.threads["task-1"]["turns"][0]["status"] = "completed"
        await broker._resume_tracked(app)  # noqa: SLF001 - reconnect reconciliation
        assert broker.service_status()["activeTaskCount"] == 0
        assert app.count("thread/resume") == 0
        assert app.count("turn/start") == 1

    asyncio.run(exercise())


def test_stale_connection_generation_blocks_approval_response(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = FakeAppServer()
        broker = TaskBroker(tmp_path, lambda: app)
        ref = project_ref(await broker.projects_find())
        await create(broker, ref)
        await broker._handle_event(  # noqa: SLF001 - exercise the recorded event contract
            app,
            {
                "id": "approval-17",
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "task-1"},
            },
        )
        request_id = (await broker.task_status(task_id="task-1"))["pendingRequests"][0][
            "requestId"
        ]
        app.generation = "generation-2"
        with pytest.raises(Exception, match="(?i)(stale|connection)"):
            await broker.task_respond("task-1", request_id, {"decision": "accept"})
        assert app.responses == []

    asyncio.run(exercise())
