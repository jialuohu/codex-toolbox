"""Single-dispatch HTTP evaluation, with offline production billing gates."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Literal

import httpx

from .billing import MODEL, VERIFIED_BOUNDS, VERIFIED_PILOTS
from .config import ConfigStore, codex_home
from .errors import EvaluationError, unavailable
from .ledger import Ledger
from .schema import MAX_RESPONSE_BYTES, json_bytes, question_body, response_body, response_envelope

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEADLINE_SECONDS = 30


class Service:
    def __init__(self, config=None, ledger=None, bounds=None, transport=None, clock=None):
        self.config = config or ConfigStore()
        self.ledger = ledger or Ledger(codex_home() / "state" / "typesafe-tools")
        self.bounds = VERIFIED_BOUNDS if bounds is None else bounds
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def status(self) -> dict:
        reasons = []
        settings = None
        bound = None
        credential = False
        accounting = None
        try:
            settings = self.config.settings()
            bound = self.bounds.get(settings.billing_evidence_id)
        except EvaluationError as exc:
            reasons.append(exc.code)
        uncapped = settings is not None and settings.monthly_limit is None
        if not uncapped and (bound is None or not bound.valid(self.clock())):
            reasons.append("hard_cap_unverified")
        try:
            self.config.api_key()
            credential = True
        except EvaluationError as exc:
            reasons.append(exc.code)
        try:
            accounting = (self.ledger.unlimited_status(self.clock()) if uncapped
                          else self.ledger.status(self.clock()))
            if not uncapped and accounting.get("unpriced_requests_this_month", 0):
                reasons.append("accounting_unavailable")
            if (settings and settings.monthly_limit is not None
                    and bound and bound.valid(self.clock())
                    and accounting["used_nanousd"] + bound.reservation > settings.monthly_limit):
                reasons.append("budget_exhausted")
        except EvaluationError as exc:
            reasons.append(exc.code)
        return {
            "ok": True, "status": "blocked" if reasons else "ready", "model": MODEL,
            "credential_configured": credential, "block_reasons": list(dict.fromkeys(reasons)),
            "billing_status": ("uncapped" if uncapped else "blocked: hard cap unverified"
                               if "hard_cap_unverified" in reasons
                               else "verified bound configured"),
            "monthly_budget_usd": (None if uncapped else settings.monthly_limit / 1_000_000_000
                                   if settings and settings.monthly_limit is not None else 5),
            "budget_scope": "This installation's wrapper calls by UTC submission month only",
            "accounting": accounting,
            "automatic_research_enabled": bool(settings and settings.automatic_research
                and settings.pilot_evidence_id in VERIFIED_PILOTS and not reasons),
        }

    async def _dispatch(self, payload: bytes, key: str) -> bytes:
        transport = self.transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        async with httpx.AsyncClient(transport=transport, timeout=DEADLINE_SECONDS,
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
        started = time.monotonic()
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                return await self._evaluate(state, questions, classification, invocation, started)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except (TimeoutError, httpx.TimeoutException):
            return unavailable("deadline_exceeded")
        except httpx.HTTPError:
            return unavailable("provider_unavailable")
        except Exception:
            return unavailable("internal_error")

    async def _evaluate(self, state, questions, classification, invocation, started):
        if classification not in {"public", "synthetic"}:
            raise EvaluationError("data_ineligible")
        if invocation not in {"explicit", "automatic"}:
            raise EvaluationError("invalid_request")
        payload = question_body(state, questions)
        settings = await asyncio.to_thread(self.config.settings)
        uncapped = settings.monthly_limit is None
        bound = self.bounds.get(settings.billing_evidence_id)
        if not uncapped and (bound is None or not bound.valid(self.clock())):
            raise EvaluationError("hard_cap_unverified")
        if invocation == "automatic" and not (settings.automatic_research
                and settings.pilot_evidence_id in VERIFIED_PILOTS):
            raise EvaluationError("automatic_use_unverified")
        key = await asyncio.to_thread(self.config.api_key)
        protected_values = [key]
        if isinstance(self.config, ConfigStore):
            protected_values.append(str(self.config.secrets))
        if any(json_bytes(value)[1:-1] in payload for value in protected_values):
            raise EvaluationError("data_ineligible")
        # Workers may finish after cancellation; their reservation is never refunded.
        # The coroutine cannot dispatch until the committed reservation is returned.
        submitted = self.clock()
        metadata = {"classification": classification, "invocation": invocation,
                    "question_count": len(questions), "payload_bytes": len(payload)}
        if uncapped:
            reservation = await asyncio.to_thread(self.ledger.start_unlimited, submitted, metadata)
        else:
            if bound is None or settings.monthly_limit is None:
                raise EvaluationError("configuration_invalid")
            reservation = await asyncio.to_thread(
                self.ledger.reserve, bound, settings.monthly_limit, submitted, metadata)
        dispatch_time = self.clock()
        if not uncapped and (bound is None or not bound.valid(dispatch_time)):
            raise EvaluationError("hard_cap_unverified")
        if (submitted.astimezone(UTC).strftime("%Y-%m")
                != dispatch_time.astimezone(UTC).strftime("%Y-%m")):
            raise EvaluationError("submission_window_changed")
        raw = await self._dispatch(payload, key)
        envelope = response_envelope(raw)
        if uncapped:
            await asyncio.to_thread(self.ledger.finish_unlimited, reservation, **envelope["usage"])
            charged = None  # Token usage is known; no authoritative monetary charge was returned.
        else:
            charged = await asyncio.to_thread(self.ledger.settle, reservation, **envelope["usage"])
        accounting_result = {"charged_nanousd": charged, "request_id": reservation,
                             "billing_mode": "uncapped" if uncapped else "capped"}
        if not uncapped:
            accounting_result["reservation_id"] = reservation
        try:
            result = response_body(raw, questions)
        except EvaluationError as exc:
            return {**unavailable(exc.code), "usage": envelope["usage"], **accounting_result}
        return {"ok": True, "status": "evaluated", **result,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **accounting_result,
                "advisory_only": True}
