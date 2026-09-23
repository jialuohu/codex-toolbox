"""Fixed, content-free errors suitable for MCP responses."""

MESSAGES = {
    "hard_cap_unverified": "blocked: hard cap unverified",
    "configuration_invalid": "Private configuration is invalid or not protected.",
    "credential_missing": "The protected TypeSafe API key is unavailable.",
    "invalid_request": "Request does not meet the documented question or payload limits.",
    "data_ineligible": "Only reviewed public or synthetic payloads are eligible.",
    "automatic_use_unverified": "Automatic research use has not passed its pilot.",
    "routing_disabled": "Capability routing is disabled; no provider request was sent.",
    "routing_suspended": (
        "Capability routing is suspended after repeated provider failures."
    ),
    "computer_use_disabled": "Automatic computer-use advice is disabled for this surface.",
    "computer_use_unverified": "Automatic computer-use advice lacks reviewed evidence.",
    "duplicate_decision": "This unchanged computer-use decision was already evaluated.",
    "budget_exhausted": "The monthly wrapper budget has insufficient unreserved funds.",
    "accounting_unavailable": (
        "Private usage accounting is unavailable; no further calls are allowed."
    ),
    "billing_bound_exceeded": "Reported usage exceeded the verified bound; paid calls halted.",
    "provider_unavailable": "Provider request failed; no automatic retry was made.",
    "invalid_response": "Response validation failed; unresolved usage remains recorded.",
    "deadline_exceeded": "Request deadline expired; unresolved dispatches remain recorded.",
    "submission_window_changed": "UTC month changed before dispatch; request record retained.",
    "internal_error": "Evaluation unavailable; continue without TypeSafe.",
}


class EvaluationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES[code])


def unavailable(code: str) -> dict:
    return {"ok": False, "status": "unavailable", "error": {
        "code": code, "message": MESSAGES[code], "retryable": False,
    }}
