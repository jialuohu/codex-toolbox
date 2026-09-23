"""Single-dispatch HTTP evaluation with private usage accounting."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx

from .billing import MODEL, VERIFIED_PILOTS
from .config import ConfigStore, codex_home
from .errors import EvaluationError, unavailable
from .ledger import Ledger
from .routing import ROUTING_DEADLINE_SECONDS, prepare, rank
from .schema import MAX_RESPONSE_BYTES, json_bytes, question_body, response_body, response_envelope

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEADLINE_SECONDS = 30


class Service:
    def __init__(self, config=None, ledger=None, transport=None, clock=None):
        self.config = config or ConfigStore()
        self.ledger = ledger or Ledger(codex_home() / "state" / "typesafe-tools")
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self._routing_session_id = uuid.uuid4().hex
        self.routing_failures = 0

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
        return {
            "ok": True, "status": "blocked" if reasons else "ready", "model": MODEL,
            "credential_configured": credential, "block_reasons": list(dict.fromkeys(reasons)),
            "accounting": accounting,
            "automatic_research_enabled": bool(settings and settings.automatic_research
                and settings.pilot_evidence_id in VERIFIED_PILOTS and not reasons),
            "routing_pilot_enabled": bool(settings and settings.routing_pilot and not reasons),
            "automatic_routing_enabled": bool(settings and settings.automatic_routing
                and not reasons),
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

    async def _evaluate_with_deadline(self, state, questions, classification,
                                      invocation, deadline, purpose) -> dict:
        started = time.monotonic()
        try:
            async with asyncio.timeout(deadline):
                return await self._evaluate(
                    state, questions, classification, invocation, started, deadline, purpose)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except (TimeoutError, httpx.TimeoutException):
            return unavailable("deadline_exceeded")
        except httpx.HTTPError:
            return unavailable("provider_unavailable")
        except Exception:
            return unavailable("internal_error")

    async def _evaluate(self, state, questions, classification, invocation,
                        started, deadline=DEADLINE_SECONDS, purpose="research"):
        if classification not in {"public", "synthetic"}:
            raise EvaluationError("data_ineligible")
        if ((purpose == "research" and invocation not in {"explicit", "automatic"})
                or (purpose == "routing" and invocation not in {"pilot", "automatic"})
                or purpose not in {"research", "routing"}):
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
        key = await asyncio.to_thread(self.config.api_key)
        protected_values = [key]
        if isinstance(self.config, ConfigStore):
            protected_values.append(str(self.config.secrets))
        if any(json_bytes(value)[1:-1] in payload for value in protected_values):
            raise EvaluationError("data_ineligible")
        # Workers may finish after cancellation; their usage record stays unresolved.
        # The coroutine cannot dispatch until the record is committed.
        submitted = self.clock()
        metadata = {"classification": classification,
                    "invocation": invocation if purpose == "research" else "routing_" + invocation,
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
