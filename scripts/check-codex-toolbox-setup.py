#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-codex-toolbox.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    script = SETUP_SCRIPT.read_text()

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
        'plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null 2>&1 || true'
        in script,
        "setup script must remove retired toolbox plugins unconditionally",
    )


if __name__ == "__main__":
    main()
