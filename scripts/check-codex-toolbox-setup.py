#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-codex-toolbox.sh"
SYNC_AGENTS_SCRIPT = ROOT / "scripts" / "sync-agents.sh"
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
GAME_ASSET_PLUGIN = ROOT / "plugins" / "game-asset-tools" / ".codex-plugin" / "plugin.json"
GAME_ASSET_MCP = ROOT / "plugins" / "game-asset-tools" / ".mcp.json"
SYMPHONY_PLUGIN = ROOT / "plugins" / "symphony-tools" / ".codex-plugin" / "plugin.json"
SYMPHONY_MCP = ROOT / "plugins" / "symphony-tools" / ".mcp.json"
SYMPHONY_SKILL = (
    ROOT / "plugins" / "symphony-tools" / "skills" / "symphony-orchestration" / "SKILL.md"
)
TRADING_MCP = ROOT / "plugins" / "trading-tools" / ".mcp.json"
RESEARCH_PLUGIN = ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json"
RESEARCH_LLM_WIKI_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "research-llm-wiki" / "SKILL.md"
)
RESEARCH_LLM_WIKI_LINT = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "research-llm-wiki"
    / "scripts"
    / "lint_research_llm_wiki.py"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def array_body(script: str, name: str) -> str:
    match = re.search(rf"^{name}=\(\n(?P<body>.*?)\n\)", script, re.MULTILINE | re.DOTALL)
    require(match is not None, f"setup script must define {name}")
    return match.group("body")


def main() -> None:
    script = SETUP_SCRIPT.read_text()
    require(GLOBAL_AGENTS.exists(), "canonical global AGENTS file must exist")
    require(
        GLOBAL_AGENTS.read_text().startswith("## Orchestration routing\n"),
        "canonical global AGENTS file must start with orchestration routing",
    )
    global_agents_text = GLOBAL_AGENTS.read_text()
    for expected in (
        "3 or more independent, testable implementation tasks",
        "Codex + Symphony + Linear",
        "Plan mode",
        "project-specific Symphony workflow",
        "route to the Codex + Symphony + Linear lane by default",
        "Do not present Codex-only as an equal execution option",
        "reviewed preflight Linear payloads",
        "do not stop at dry-runs",
        "start or refresh Symphony",
    ):
        require(expected in global_agents_text, f"global AGENTS routing must mention {expected}")
    require(
        "## Superpowers workflow" in global_agents_text,
        "canonical global AGENTS file must preserve the Superpowers workflow section",
    )
    require(SYNC_AGENTS_SCRIPT.exists(), "setup must include an AGENTS sync script")
    sync_agents_script = SYNC_AGENTS_SCRIPT.read_text()
    require(
        '"${CODEX_HOME:-$HOME/.codex}"' in sync_agents_script,
        "AGENTS sync script must respect CODEX_HOME with ~/.codex fallback",
    )
    require(
        "AGENTS.override.md" in sync_agents_script,
        "AGENTS sync script must warn about AGENTS.override.md precedence",
    )
    require(
        ".codex-toolbox" in sync_agents_script,
        "AGENTS sync script must write a local toolbox sync marker",
    )
    require(
        '"$ROOT/scripts/sync-agents.sh" --install' in script,
        "setup script must install global AGENTS instructions",
    )
    require(GAME_ASSET_PLUGIN.exists(), "game-asset-tools plugin manifest must exist")
    require(GAME_ASSET_MCP.exists(), "game-asset-tools must define an MCP config")
    require(SYMPHONY_PLUGIN.exists(), "symphony-tools plugin manifest must exist")
    require(SYMPHONY_MCP.exists(), "symphony-tools must define an MCP config")
    require(SYMPHONY_SKILL.exists(), "symphony-tools must bundle the symphony-orchestration skill")
    require(RESEARCH_PLUGIN.exists(), "research-tools plugin manifest must exist")
    require(RESEARCH_LLM_WIKI_SKILL.exists(), "research-tools must include research-llm-wiki skill")
    require(
        RESEARCH_LLM_WIKI_LINT.exists(),
        "research-llm-wiki must include a deterministic lint helper",
    )
    marketplace = json.loads(MARKETPLACE.read_text())
    game_asset_plugin = json.loads(GAME_ASSET_PLUGIN.read_text())
    game_asset_mcp = json.loads(GAME_ASSET_MCP.read_text())
    symphony_plugin = json.loads(SYMPHONY_PLUGIN.read_text())
    symphony_mcp = json.loads(SYMPHONY_MCP.read_text())
    research_plugin = json.loads(RESEARCH_PLUGIN.read_text())
    trading_mcp = json.loads(TRADING_MCP.read_text())
    default_plugins = array_body(script, "DEFAULT_PLUGINS")
    managed_mcp_servers = array_body(script, "MANAGED_MCP_SERVERS")
    pixellab_server = game_asset_mcp.get("mcpServers", {}).get("pixellab")
    symphony_server = symphony_mcp.get("mcpServers", {}).get("symphony")
    robinhood_server = trading_mcp.get("mcpServers", {}).get("robinhood-trading")

    require(
        marketplace.get("name") == "jialuo-codex-toolbox",
        "marketplace must be named jialuo-codex-toolbox",
    )
    require(
        'MARKETPLACE_NAME="jialuo-codex-toolbox"' in script,
        "setup script must register the jialuo-codex-toolbox marketplace",
    )
    require(
        "OLD_MARKETPLACE_NAMES=(" in script and '"jialuo-codex-toolbox"' in script,
        "setup script must track retired toolbox marketplace names",
    )
    require(
        "remove_stale_plugin_config_blocks" in script,
        "setup script must remove stale retired-marketplace plugin config blocks",
    )
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
        '  "game-asset-tools"' in default_plugins,
        "setup script must install the game-asset-tools plugin",
    )
    require(
        '  "symphony-tools"' in default_plugins,
        "setup script must install the symphony-tools plugin",
    )
    require(
        '  "pixellab"' in managed_mcp_servers,
        "setup script must manage the pixellab MCP server cleanup list",
    )
    require(
        '  "symphony"' in managed_mcp_servers,
        "setup script must manage the symphony MCP server cleanup list",
    )
    require(
        any(
            plugin.get("name") == "game-asset-tools"
            and plugin.get("source", {}).get("path") == "./plugins/game-asset-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include game-asset-tools",
    )
    require(
        game_asset_plugin.get("skills") == "./skills/",
        "game-asset-tools must expose its PixelLab routing skill",
    )
    require(
        game_asset_plugin.get("mcpServers") == "./.mcp.json",
        "game-asset-tools must expose its MCP config",
    )
    require(
        any(
            plugin.get("name") == "symphony-tools"
            and plugin.get("source", {}).get("path") == "./plugins/symphony-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include symphony-tools",
    )
    require(
        symphony_plugin.get("skills") == "./skills/",
        "symphony-tools must expose its orchestration skill",
    )
    require(
        symphony_plugin.get("mcpServers") == "./.mcp.json",
        "symphony-tools must expose its MCP config",
    )
    require(
        symphony_server is not None,
        "symphony-tools must define the symphony MCP server",
    )
    require(
        symphony_server.get("command") == "/bin/zsh",
        "symphony MCP must use the zsh secret-loading wrapper",
    )
    symphony_args = symphony_server.get("args", [])
    require(
        len(symphony_args) == 2 and symphony_args[0] == "-lc",
        "symphony MCP must run through zsh -lc",
    )
    symphony_launch = symphony_args[1] if len(symphony_args) == 2 else ""
    for expected in (
        'source "$CODEX_SECRETS_DIR/symphony-linear.env"',
        'command -v symphony',
        '"CODEX_LOCAL_BIN_DIR/symphony"',
        'exec "$SYMPHONY" mcp',
    ):
        require(expected in symphony_launch, f"symphony launch must include {expected}")
    require(
        symphony_server.get("default_tools_approval_mode") == "prompt",
        "symphony MCP must prompt by default",
    )
    for tool_name in ("symphony_state", "symphony_handoff_summary"):
        require(
            symphony_server.get("tools", {}).get(tool_name, {}).get("approval_mode") == "auto",
            f"symphony read/review tool {tool_name} must be auto-approved",
        )
    for tool_name in (
        "symphony_create_issue",
        "symphony_create_issue_batch",
        "symphony_workflow_init",
        "symphony_refresh",
        "symphony_add_linear_comment",
        "symphony_move_linear_issue",
    ):
        require(
            symphony_server.get("tools", {}).get(tool_name, {}).get("approval_mode") == "prompt",
            f"symphony mutating/dispatch tool {tool_name} must stay prompt-gated",
        )
    symphony_skill_text = SYMPHONY_SKILL.read_text()
    for expected in (
        "name: symphony-orchestration",
        "MCP Tool Preference",
        "symphony_create_issue",
        "symphony_workflow_init",
        "symphony_handoff_summary",
        "symphony_add_linear_comment",
        "symphony_move_linear_issue",
        "symphony service",
        "large decomposable app/site/project builds",
        "Workflow Selection",
        "--concurrency 4",
        "route to the Symphony lane by default",
        "Do not offer Codex-only as an equal lane",
        "preflight",
        "do not stop at dry-runs",
        "Build a polished business website",
        "Never let a worker use these tools",
    ):
        require(expected in symphony_skill_text, f"symphony skill must mention {expected}")
    require(
        research_plugin.get("skills") == "./skills/",
        "research-tools must expose bundled research skills",
    )
    research_interface = research_plugin.get("interface", {})
    require(
        "LLM Wiki" in research_interface.get("longDescription", ""),
        "research-tools plugin description must mention the Research LLM Wiki workflow",
    )
    require(
        any("wiki" in prompt.lower() for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface wiki usage",
    )
    research_skill_text = RESEARCH_LLM_WIKI_SKILL.read_text()
    for expected in (
        "name: research-llm-wiki",
        "Research/LLM Wiki",
        "$research-llm-wiki ingest",
        "$research-llm-wiki query",
        "$research-llm-wiki lint",
        "lint_research_llm_wiki.py",
        "Do not rewrite raw source notes",
        "index.md",
        "log.md",
    ):
        require(expected in research_skill_text, f"research-llm-wiki skill must mention {expected}")
    lint_script_text = RESEARCH_LLM_WIKI_LINT.read_text()
    for expected in (
        "Missing required wiki path",
        "missing source identity",
        "citation",
        "orphan concept page",
    ):
        require(expected in lint_script_text, f"research-llm-wiki lint helper must check {expected}")
    require(
        pixellab_server is not None,
        "game-asset-tools must define the pixellab MCP server",
    )
    require(
        pixellab_server.get("command") == "/bin/zsh",
        "pixellab must use the zsh secret-loading wrapper",
    )
    pixellab_args = pixellab_server.get("args", [])
    require(
        len(pixellab_args) == 2 and pixellab_args[0] == "-lc",
        "pixellab must run through zsh -lc",
    )
    pixellab_launch = pixellab_args[1] if len(pixellab_args) == 2 else ""
    for expected in (
        'source "$CODEX_SECRETS_DIR/pixellab.env"',
        "npx -y mcp-remote@latest",
        "https://api.pixellab.ai/mcp",
        "--transport http-only",
        "--header 'Authorization:${AUTH_HEADER}'",
    ):
        require(expected in pixellab_launch, f"pixellab launch must include {expected}")
    require(
        pixellab_server.get("default_tools_approval_mode") == "prompt",
        "pixellab must prompt by default to avoid accidental credit spend",
    )
    disabled_pixellab_tools = set(pixellab_server.get("disabled_tools", []))
    for tool_name in (
        "chat_list_conversations",
        "chat_get_messages",
        "chat_send_message",
        "sandbox_create_session",
        "sandbox_destroy_session",
        "sandbox_bash",
        "sandbox_run",
        "sandbox_read",
        "sandbox_write",
        "sandbox_edit",
    ):
        require(tool_name in disabled_pixellab_tools, f"pixellab must disable {tool_name}")
    for tool_name in (
        "get_character",
        "list_characters",
        "get_topdown_tileset",
        "list_topdown_tilesets",
        "get_sidescroller_tileset",
        "list_sidescroller_tilesets",
        "get_isometric_tile",
        "list_isometric_tiles",
        "get_map_object",
        "get_object",
        "list_objects",
    ):
        require(
            pixellab_server.get("tools", {}).get(tool_name, {}).get("approval_mode") == "auto",
            f"pixellab read/status tool {tool_name} must be auto-approved",
        )
    require(
        '  "context7"' in managed_mcp_servers,
        "setup script must manage the context7 MCP server cleanup list",
    )
    require(
        '  "robinhood-trading"' in managed_mcp_servers,
        "setup script must manage the robinhood-trading MCP server cleanup list",
    )
    require(
        robinhood_server is not None,
        "trading-tools must define the robinhood-trading MCP server",
    )
    require(
        robinhood_server.get("type") == "http",
        "robinhood-trading must use the Streamable HTTP plugin MCP shape",
    )
    require(
        robinhood_server.get("url") == "https://agent.robinhood.com/mcp/trading",
        "robinhood-trading must point to Robinhood's official Trading MCP endpoint",
    )
    require(
        robinhood_server.get("default_tools_approval_mode") == "auto",
        "robinhood-trading must use the requested auto approval policy",
    )
    require(
        'plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null 2>&1 || true'
        in script,
        "setup script must remove retired toolbox plugins unconditionally",
    )


if __name__ == "__main__":
    main()
