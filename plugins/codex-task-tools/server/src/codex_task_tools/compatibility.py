"""Exact App Server versions qualified against the broker's protocol contract."""

from __future__ import annotations

import re

SUPPORTED_APP_VERSIONS = frozenset({"0.156.1", "0.159.0"})

# Desktop supplies its own product name. The standalone App Server uses the
# initializing client's name; codex_cli is the original tested CLI form and
# codex_task_tools is the name sent by this package. Require a complete product
# token and either the bare form or the complete observed platform/client suffix.
_USER_AGENT = re.compile(
    r"(?:Codex Desktop|codex_cli|codex_task_tools)/(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"
    r"(?: \([^()\r\n]+\) [^\s()]+ \([A-Za-z0-9_.-]+; [A-Za-z0-9_.+-]+\))?"
)


def app_server_version(user_agent: object) -> str | None:
    """Return an exactly qualified release, never a matching embedded substring."""
    if not isinstance(user_agent, str) or len(user_agent) > 512:
        return None
    match = _USER_AGENT.fullmatch(user_agent)
    if match is None or match["version"] not in SUPPORTED_APP_VERSIONS:
        return None
    return match["version"]
