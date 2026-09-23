"""Single-dispatch HTTP evaluation with private usage accounting."""

import asyncio
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Literal

import httpx

from .billing import MODEL, VERIFIED_PILOTS
from .computer_use import (
    COMPUTER_USE_DEADLINE_SECONDS,
    VERIFIED_COMPUTER_USE_EVIDENCE,
)
from .computer_use import (
    prepare as prepare_computer_use,
)
from .computer_use import (
    select as select_computer_use,
)
from .config import ConfigStore, Settings, codex_home
from .errors import EvaluationError, unavailable
from .ledger import Ledger
from .routing import ROUTING_DEADLINE_SECONDS, prepare, rank
from .schema import MAX_RESPONSE_BYTES, json_bytes, question_body, response_body, response_envelope

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEADLINE_SECONDS = 30


def computer_use_activation_basis(settings: Settings, surface: Literal["browser", "native"]
                                  ) -> Literal["measured_benefit", "user_opt_in"] | None:
    if surface == "browser":
        enabled = settings.automatic_browser_use
        evidence_id = settings.browser_evidence_id
        user_opt_in = settings.browser_user_opt_in
    else:
        enabled = settings.automatic_native_use
        evidence_id = settings.native_evidence_id
        user_opt_in = settings.native_user_opt_in
    if not enabled:
        return None
    if evidence_id in VERIFIED_COMPUTER_USE_EVIDENCE[surface]:
        return "measured_benefit"
    if user_opt_in:
        return "user_opt_in"
    return None


class Service:
    def __init__(self, config=None, ledger=None, transport=None, clock=None):
        self.config = config or ConfigStore()
        self.ledger = ledger or Ledger(codex_home() / "state" / "typesafe-tools")
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self._routing_session_id = uuid.uuid4().hex
        self.routing_failures = 0
        self._computer_use_decisions: set[str] = set()
        self._computer_use_order: deque[str] = deque()

    def status(self) -> dict:
        reasons = []
        settings = None
        credential = False
        accounting = None
        try:
            settings = self.config.settings()
        except EvaluationError as exc:
            reasons.append(exc.code)
        try:
            self.config.api_key()
            credential = True
        except EvaluationError as exc:
            reasons.append(exc.code)
        try:
            accounting = self.ledger.unlimited_status(self.clock())
        except EvaluationError as exc:
            reasons.append(exc.code)
        browser_basis = (computer_use_activation_basis(settings, "browser")
                         if settings and not reasons else None)
        native_basis = (computer_use_activation_basis(settings, "native")
                        if settings and not reasons else None)
        return {
            "ok": True, "status": "blocked" if reasons else "ready", "model": MODEL,
            "credential_configured": credential, "block_reasons": list(dict.fromkeys(reasons)),
            "accounting": accounting,
            "automatic_research_enabled": bool(settings and settings.automatic_research
                and settings.pilot_evidence_id in VERIFIED_PILOTS and not reasons),
            "routing_pilot_enabled": bool(settings and settings.routing_pilot and not reasons),
            "automatic_routing_enabled": bool(settings and settings.automatic_routing
                and not reasons),
            "automatic_browser_use_enabled": browser_basis is not None,
            "automatic_browser_use_basis": browser_basis,
            "automatic_native_use_enabled": native_basis is not None,
            "automatic_native_use_basis": native_basis,
        }

    async def _dispatch(self, payload: bytes, key: str,
                        deadline: float = DEADLINE_SECONDS) -> bytes:
        transport = self.transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        async with httpx.AsyncClient(transport=transport, timeout=deadline,
                                    follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", ENDPOINT, content=payload, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "Accept": "application/json", "Accept-Encoding": "identity",
            }) as response:
                if response.status_code != 200:
                    raise EvaluationError("provider_unavailable")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise EvaluationError("invalid_response")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise EvaluationError("invalid_response")
                    data.extend(chunk)
                return bytes(data)

    async def evaluate(self, state: object, questions: dict,
                       classification: Literal["public", "synthetic"],
                       invocation: Literal["explicit", "automatic"] = "explicit") -> dict:
        return await self._evaluate_with_deadline(
            state, questions, classification, invocation, DEADLINE_SECONDS, "research")

    async def route(self, task: str, candidates: list[dict], catalog_digest: str,
                    classification: Literal["public", "synthetic"],
                    session_id: str | None = None, turn_id: str | None = None,
                    invocation: Literal["pilot", "automatic"] = "automatic") -> dict:
        # Correlation IDs stay local. They are not trusted as circuit-breaker keys.
        session_id = self._routing_session_id if session_id is None else session_id
        turn_id = uuid.uuid4().hex if turn_id is None else turn_id
        try:
            state, questions = prepare(task, candidates, catalog_digest, session_id, turn_id)
        except EvaluationError as exc:
            return unavailable(exc.code)
        if self.routing_failures >= 3:
            return unavailable("routing_suspended")
        evaluation = await self._evaluate_with_deadline(
            state, questions, classification, invocation, ROUTING_DEADLINE_SECONDS, "routing")
        if not evaluation.get("ok"):
            if evaluation.get("error", {}).get("code") in {
                    "provider_unavailable", "deadline_exceeded", "invalid_response"}:
                self.routing_failures += 1
            return evaluation
        try:
            result = rank(candidates, evaluation, catalog_digest, session_id, turn_id, task)
            self.routing_failures = 0
            return result
        except (EvaluationError, KeyError, TypeError):
            self.routing_failures += 1
            return unavailable("invalid_response")

    async def choose_action(self, surface: Literal["browser", "native"], objective: str,
                            observation: str, snapshot_id: str, task_scope_id: str,
                            candidates: list[dict],
                            classification: Literal["public", "synthetic"],
                            invocation: Literal["explicit", "automatic"]) -> dict:
        try:
            state, questions, decision_digest = prepare_computer_use(
                surface, objective, observation, snapshot_id, task_scope_id, candidates)
        except EvaluationError as exc:
            return unavailable(exc.code)
        evaluation = await self._evaluate_with_deadline(
            state, questions, classification, invocation,
            COMPUTER_USE_DEADLINE_SECONDS, "computer_use",
            surface=surface, decision_digest=decision_digest)
        if not evaluation.get("ok"):
            return {**evaluation, "surface": surface, "snapshot_id": snapshot_id}
        try:
            return select_computer_use(evaluation, surface, snapshot_id)
        except EvaluationError as exc:
            return {**unavailable(exc.code), "surface": surface,
                    "snapshot_id": snapshot_id}

    def _remember_computer_use_decision(self, digest: str) -> None:
        # No await occurs between checking and recording this key in one event loop.
        if digest in self._computer_use_decisions:
            raise EvaluationError("duplicate_decision")
        self._computer_use_decisions.add(digest)
        self._computer_use_order.append(digest)
        if len(self._computer_use_order) > 256:
            self._computer_use_decisions.remove(self._computer_use_order.popleft())

    async def _evaluate_with_deadline(self, state, questions, classification,
                                      invocation, deadline, purpose, *, surface=None,
                                      decision_digest=None) -> dict:
        started = time.monotonic()
        try:
            async with asyncio.timeout(deadline):
                return await self._evaluate(
                    state, questions, classification, invocation, started, deadline, purpose,
                    surface=surface, decision_digest=decision_digest)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except (TimeoutError, httpx.TimeoutException):
            return unavailable("deadline_exceeded")
        except httpx.HTTPError:
            return unavailable("provider_unavailable")
        except Exception:
            return unavailable("internal_error")

    async def _evaluate(self, state, questions, classification, invocation,
                        started, deadline=DEADLINE_SECONDS, purpose="research", *,
                        surface=None, decision_digest=None):
        if classification not in {"public", "synthetic"}:
            raise EvaluationError("data_ineligible")
        if ((purpose == "research" and invocation not in {"explicit", "automatic"})
                or (purpose == "routing" and invocation not in {"pilot", "automatic"})
                or (purpose == "computer_use" and invocation not in {
                    "explicit", "automatic"})
                or purpose not in {"research", "routing", "computer_use"}):
            raise EvaluationError("invalid_request")
        if purpose == "computer_use":
            if (not isinstance(surface, str) or surface not in {"browser", "native"}
                    or not isinstance(decision_digest, str)):
                raise EvaluationError("invalid_request")
        payload = question_body(state, questions)
        settings = await asyncio.to_thread(self.config.settings)
        if purpose == "routing" and invocation == "pilot" and not settings.routing_pilot:
            raise EvaluationError("routing_disabled")
        if purpose == "routing" and invocation == "automatic" and not settings.automatic_routing:
            raise EvaluationError("routing_disabled")
        if purpose == "research" and invocation == "automatic" and not (
                settings.automatic_research and settings.pilot_evidence_id in VERIFIED_PILOTS):
            raise EvaluationError("automatic_use_unverified")
        if purpose == "computer_use" and invocation == "automatic":
            assert surface in ("browser", "native")
            enabled = (settings.automatic_browser_use if surface == "browser"
                       else settings.automatic_native_use)
            if not enabled:
                raise EvaluationError("computer_use_disabled")
            if computer_use_activation_basis(settings, surface) is None:
                raise EvaluationError("computer_use_unverified")
        key = await asyncio.to_thread(self.config.api_key)
        protected_values = [key]
        if isinstance(self.config, ConfigStore):
            protected_values.append(str(self.config.secrets))
        if any(json_bytes(value)[1:-1] in payload for value in protected_values):
            raise EvaluationError("data_ineligible")
        if purpose == "computer_use":
            assert isinstance(decision_digest, str)
            self._remember_computer_use_decision(decision_digest)
        # Workers may finish after cancellation; their usage record stays unresolved.
        # The coroutine cannot dispatch until the record is committed.
        submitted = self.clock()
        metadata = {"classification": classification,
                    "invocation": (
                        invocation if purpose == "research" else
                        "routing_" + invocation if purpose == "routing" else
                        f"computer_use_{surface}_{invocation}"),
                    "question_count": len(questions), "payload_bytes": len(payload)}
        request_id = await asyncio.to_thread(self.ledger.start_unlimited, submitted, metadata)
        dispatch_time = self.clock()
        if (submitted.astimezone(UTC).strftime("%Y-%m")
                != dispatch_time.astimezone(UTC).strftime("%Y-%m")):
            raise EvaluationError("submission_window_changed")
        raw = await self._dispatch(payload, key, deadline)
        envelope = response_envelope(raw)
        await asyncio.to_thread(self.ledger.finish_unlimited, request_id, **envelope["usage"])
        accounting_result = {"request_id": request_id}
        try:
            result = response_body(raw, questions)
        except EvaluationError as exc:
            return {**unavailable(exc.code), "usage": envelope["usage"], **accounting_result}
        return {"ok": True, "status": "evaluated", **result,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **accounting_result,
                "advisory_only": True}
