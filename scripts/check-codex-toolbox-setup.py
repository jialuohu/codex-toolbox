#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-codex-toolbox.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def array_body(script: str, name: str) -> str:
    match = re.search(rf"^{name}=\(\n(?P<body>.*?)\n\)", script, re.MULTILINE | re.DOTALL)
    require(match is not None, f"setup script must define {name}")
    return match.group("body")


def main() -> None:
    script = SETUP_SCRIPT.read_text()
    managed_mcp_servers = array_body(script, "MANAGED_MCP_SERVERS")

    require(
        'UI_UX_MARKETPLACE_NAME="ui-ux-pro-max-skill"' in script,
        "setup script must define the UI/UX Pro Max marketplace name",
    )
    require(
        'UI_UX_MARKETPLACE_SOURCE="nextlevelbuilder/ui-ux-pro-max-skill"' in script,
        "setup script must define the upstream UI/UX Pro Max marketplace source",
    )
    require(
        'UI_UX_MARKETPLACE_REF="v2.10.0"' in script,
        "setup script must pin UI/UX Pro Max to v2.10.0",
    )
    require(
        'CONTEXT7_MARKETPLACE_NAME="context7-marketplace"' in script,
        "setup script must define the official Context7 marketplace name",
    )
    require(
        'CONTEXT7_MARKETPLACE_SOURCE="upstash/context7"' in script,
        "setup script must define the upstream Context7 marketplace source",
    )

    for sparse_path in (
        ".claude/skills/ui-ux-pro-max",
        ".claude-plugin",
        "LICENSE",
    ):
        require(
            f'"{sparse_path}"' in script,
            f"setup script must sparse-checkout {sparse_path}",
        )

    require(
        '"ui-ux-pro-max"' in script,
        "setup script must install the ui-ux-pro-max plugin",
    )
    require(
        '"context7"' in script,
        "setup script must install the context7 plugin",
    )
    require(
        'install_or_refresh_plugin "$plugin" "$CONTEXT7_MARKETPLACE_NAME"' in script,
        "setup script must install Context7 from the official marketplace",
    )
    require(
        '  "context7"' in managed_mcp_servers,
        "setup script must manage the context7 MCP server cleanup list",
    )
    require(
        'plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null 2>&1 || true'
        in script,
        "setup script must remove retired toolbox plugins unconditionally",
    )


if __name__ == "__main__":
    main()
