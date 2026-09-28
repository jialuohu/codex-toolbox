"""Stdio MCP for bounded Jev advice. Startup and status perform no network calls."""

import json
import logging
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .errors import EvaluationError, unavailable
from .service import Service


def create_server(service: Service | None = None) -> FastMCP:
    mcp = FastMCP("typesafe-tools", log_level="ERROR")
    instance = service

    def get_service() -> Service:
        nonlocal instance
        if instance is None:
            instance = Service()
        return instance

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                          idempotentHint=True, openWorldHint=False))
    def typesafe_status() -> dict[str, Any]:
        """Offline credential, routing, and accounting readiness for the fixed Jev model."""
        try:
            return get_service().status()
        except EvaluationError as exc:
            return unavailable(exc.code)
        except Exception:
            return unavailable("internal_error")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                          idempotentHint=False, openWorldHint=True))
    async def typesafe_evaluate(state: str | dict | list, questions: dict,
                               classification: Literal["public", "synthetic", "private"],
                               invocation: Literal["explicit", "automatic"] = "explicit"
                               ) -> dict[str, Any]:
        """Evaluate at most 16 typed questions in a complete 24 KiB payload.

        Codex must review EVERY outgoing field. Public and synthetic content are
        eligible; task-scoped private content requires protected allow_private_data
        opt-in and authority to send it to TypeSafe. Exclude credentials and unknown
        origin content. Classification records review, not technical proof.
        Questions map IDs to objects
        with type, instructions and criteria: choice uses an option-to-description
        map; score uses an ordered description list; noul uses optional true/false
        descriptions. No retries. Automatic research use requires a separately
        reviewed pilot. Returned judgments
        never authorize actions or replace source and numerical verification.
        """
        try:
            return await get_service().evaluate(state, questions, classification, invocation)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except Exception:
            return unavailable("internal_error")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                          idempotentHint=False, openWorldHint=True))
    async def typesafe_route(task: str, candidates: list[dict], catalog_digest: str,
                             classification: Literal["public", "synthetic", "private"],
                             session_id: str | None = None, turn_id: str | None = None,
                             invocation: Literal["pilot", "automatic"] = "automatic"
                             ) -> dict[str, Any]:
        """Advisory capability ranking for eligible tasks with material tool choice.

        Review every outgoing field. Private content requires protected
        allow_private_data opt-in and authority to send it to TypeSafe; exclude
        credentials and unknown origin content. Supply only available,
        eligible candidates from the current installed catalog. A ranking never
        authorizes a tool call. Session and turn IDs are optional correlation
        fields; the server generates opaque IDs when omitted and never sends
        them to Jev. Use automatic invocation for default routing; pilot
        invocation remains separately gated.
        """
        try:
            return await get_service().route(
                task, candidates, catalog_digest, classification,
                session_id=session_id, turn_id=turn_id, invocation=invocation)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except Exception:
            return unavailable("internal_error")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                          idempotentHint=False, openWorldHint=True))
    async def typesafe_choose_action(surface: Literal["browser", "native"], objective: str,
                                     observation: str, snapshot_id: str, task_scope_id: str,
                                     candidates: list[dict],
                                     classification: Literal["public", "synthetic", "private"],
                                     invocation: Literal["explicit", "automatic"]
                                     ) -> dict[str, Any]:
        """Recommend one semantic computer-use action or abstain; never execute it.

        Codex must review every outgoing field. Private content requires protected
        allow_private_data opt-in and authority to send it to TypeSafe; exclude
        credentials and unknown origin content. Supply
        one to 15 candidates with id, target, operation, arguments,
        preconditions, and intended_result string fields. Keep executable UI
        bindings local. Task scope and snapshot IDs are opaque local values;
        reuse the task scope only within one Codex task. Echoed snapshot IDs
        help Codex correlate advice; it must reacquire and check the target
        before acting. The caller must identify explicit user-requested or
        enabled automatic use. Automatic use requires that surface's protected
        user opt-in or separately reviewed evidence.
        """
        try:
            return await get_service().choose_action(
                surface, objective, observation, snapshot_id, task_scope_id, candidates,
                classification, invocation)
        except EvaluationError as exc:
            return unavailable(exc.code)
        except Exception:
            return unavailable("internal_error")

    return mcp


def main() -> None:
    # Third-party debug/error records can contain malformed requests or URL details.
    # Readiness and failures are exposed only through the sanitized tool results.
    logging.disable(logging.CRITICAL)
    create_server().run(transport="stdio")


def status_main() -> None:
    try:
        result = Service().status()
    except EvaluationError as exc:
        result = unavailable(exc.code)
    except Exception:
        result = unavailable("internal_error")
    print(json.dumps(result, sort_keys=True))
