"""Two-tool stdio MCP. Startup and status perform no network calls."""

import json
import logging
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .errors import EvaluationError, unavailable
from .service import Service


def create_server(service: Service | None = None) -> FastMCP:
    mcp = FastMCP("typesafe-tools", log_level="ERROR")

    def get_service() -> Service:
        return service if service is not None else Service()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                          idempotentHint=True, openWorldHint=False))
    def typesafe_status() -> dict[str, Any]:
        """Offline readiness, fixed model, budget status, and reasons paid calls are blocked."""
        try:
            return get_service().status()
        except EvaluationError as exc:
            return unavailable(exc.code)
        except Exception:
            return unavailable("internal_error")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                          idempotentHint=False, openWorldHint=True))
    async def typesafe_evaluate(state: str | dict | list, questions: dict,
                               classification: Literal["public", "synthetic"],
                               invocation: Literal["explicit", "automatic"] = "explicit"
                               ) -> dict[str, Any]:
        """Evaluate at most 16 typed questions in a complete 24 KiB payload.

        Codex must review EVERY outgoing field as public or synthetic. Classification
        records this review; it is not technical proof. Questions map IDs to objects
        with type, instructions and criteria: choice uses an option-to-description
        map; score uses an ordered description list; noul uses optional true/false
        descriptions. Capped mode requires an audited billing bound; an explicit
        null monthly budget disables the cap and that billing-bound gate. No retries.
        Automatic use also requires a separately reviewed pilot. Returned judgments
        never authorize actions or replace source and numerical verification.
        """
        try:
            return await get_service().evaluate(state, questions, classification, invocation)
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
