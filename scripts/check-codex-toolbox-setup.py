#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-codex-toolbox.sh"
SYNC_AGENTS_SCRIPT = ROOT / "scripts" / "sync-agents.sh"
SYNC_PETS_SCRIPT = ROOT / "scripts" / "sync-codex-pets.py"
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
README = ROOT / "README.md"
STINKY_PENGUIN_DIR = ROOT / "config" / "codex" / "pets" / "stinky-penguin"
STINKY_PENGUIN_MANIFEST = STINKY_PENGUIN_DIR / "pet.json"
STINKY_PENGUIN_SPRITESHEET = STINKY_PENGUIN_DIR / "spritesheet.webp"
MINERU_SETUP = ROOT / "scripts" / "setup-mineru.sh"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
GAME_ASSET_PLUGIN = ROOT / "plugins" / "game-asset-tools" / ".codex-plugin" / "plugin.json"
GAME_ASSET_MCP = ROOT / "plugins" / "game-asset-tools" / ".mcp.json"
TRADING_MCP = ROOT / "plugins" / "trading-tools" / ".mcp.json"
RESEARCH_PLUGIN = ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json"
RESEARCH_MCP = ROOT / "plugins" / "research-tools" / ".mcp.json"
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
MINERU_DOCUMENT_SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "mineru-document-extraction"
    / "SKILL.md"
)
MINERU_WRAPPER = MINERU_DOCUMENT_SKILL.parent / "scripts" / "run_mineru.py"
PAPER_LIBRARY_INTAKE_SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "paper-library-intake"
    / "SKILL.md"
)
PAPER_LIBRARY_INTAKE_OPENAI = PAPER_LIBRARY_INTAKE_SKILL.parent / "agents" / "openai.yaml"
PAPER_LIBRARY_ATTACHMENT = (
    PAPER_LIBRARY_INTAKE_SKILL.parent / "scripts" / "zotero_attachment.py"
)
PAPER_READ_DRAFT_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "paper-read-draft" / "SKILL.md"
)
PAPER_READ_DRAFT_OPENAI = PAPER_READ_DRAFT_SKILL.parent / "agents" / "openai.yaml"
PAPER_READ_DRAFT_TEMPLATE = PAPER_READ_DRAFT_SKILL.parent / "references" / "paper-read-template.md"
WORKFLOW_PLUGIN = ROOT / "plugins" / "workflow-tools" / ".codex-plugin" / "plugin.json"
DEEP_PLANNING_SKILL = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "deep-planning" / "SKILL.md"
)
DEEP_PLANNING_OPENAI = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "deep-planning" / "agents" / "openai.yaml"
)
PAPER_FIGURE_PLUGIN = ROOT / "plugins" / "paper-figure-tools" / ".codex-plugin" / "plugin.json"
PAPER_FIGURE_SKILL = (
    ROOT / "plugins" / "paper-figure-tools" / "skills" / "paper-figure-workflow" / "SKILL.md"
)
PAPER_FIGURE_OPENAI = (
    ROOT / "plugins" / "paper-figure-tools" / "skills" / "paper-figure-workflow" / "agents" / "openai.yaml"
)
PAPER_FIGURE_REFERENCE = (
    ROOT
    / "plugins"
    / "paper-figure-tools"
    / "skills"
    / "paper-figure-workflow"
    / "references"
    / "templates.md"
)
PRODUCTIVITY_PLUGIN = ROOT / "plugins" / "productivity-tools" / ".codex-plugin" / "plugin.json"
PRODUCTIVITY_MCP = ROOT / "plugins" / "productivity-tools" / ".mcp.json"
TODOIST_TASK_PLANNING_SKILL = (
    ROOT
    / "plugins"
    / "productivity-tools"
    / "skills"
    / "todoist-task-planning"
    / "SKILL.md"
)
TODOIST_TASK_PLANNING_OPENAI = (
    TODOIST_TASK_PLANNING_SKILL.parent / "agents" / "openai.yaml"
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
    readme_text = README.read_text()
    readme_normalized = " ".join(readme_text.split())
    require(GLOBAL_AGENTS.exists(), "canonical global AGENTS file must exist")
    require(
        GLOBAL_AGENTS.read_text().startswith("## Orchestration routing\n"),
        "canonical global AGENTS file must start with orchestration routing",
    )
    global_agents_text = GLOBAL_AGENTS.read_text()
    global_agents_normalized = " ".join(global_agents_text.split())
    for expected in (
        "native Codex subagents",
        "independent, testable subtasks",
        "Superpowers planning and subagent-driven-development workflow",
        "durable requirements, acceptance criteria",
        "Plan mode",
        "Do not implement changes or mutate external systems in Plan mode",
        "bootstrap serially until the shared foundation is stable",
    ):
        require(expected in global_agents_text, f"global AGENTS routing must mention {expected}")
    for expected in (
        "paper-figure-tools",
        "$paper-figure-workflow",
        "draw.io",
        "SciencePlots",
        "Inkscape",
        "figures_src/",
        "make figures",
    ):
        require(expected in global_agents_text, f"global AGENTS figure routing must mention {expected}")
    for expected in (
        "$mineru-document-extraction",
        "complex, scanned, OCR-heavy, or layout-sensitive local documents",
        "`pdf` or `documents` skill",
        "Zotero",
        "Defuddle or Firecrawl",
        "obsidian_files",
        "scripts/setup-mineru.sh --check",
        "not an MCP server",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS MinerU routing must mention {expected}",
        )
    for expected in (
        "$paper-library-intake",
        "Zotero first",
        "Firecrawl first",
        "Paper Search",
        "Research/ReadLater",
        "explicit `add`, `save`, or `import`",
        "use_scihub=false",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS paper intake routing must mention {expected}",
        )
    for expected in (
        "Todoist MCP",
        "$todoist-task-planning",
        "Prefer the connected Todoist app",
        "authoritative personal task store",
        "Deadline-only tasks stay in Todoist",
        "Google Calendar only for explicit meetings or time blocks",
        "confirm before calendar writes or invitations",
        "do not create meeting follow-up tasks unless",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS Todoist routing must mention {expected}",
        )
    for expected in (
        "$deep-planning",
        "adversarial critique protocol",
        "If `$deep-planning` is unavailable",
        "draft the strongest plan",
        "OpenSpec",
        "must not write files",
        "docs/superpowers/",
    ):
        require(expected in global_agents_text, f"global AGENTS deep planning must mention {expected}")
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
    require(SYNC_PETS_SCRIPT.exists(), "setup must include a Codex pet sync script")
    require(
        'python3 "$ROOT/scripts/sync-codex-pets.py" --install' in script,
        "setup script must install repository-managed Codex pets",
    )
    require(STINKY_PENGUIN_MANIFEST.exists(), "managed stinky-penguin manifest must exist")
    require(STINKY_PENGUIN_SPRITESHEET.exists(), "managed stinky-penguin atlas must exist")
    stinky_penguin_manifest = json.loads(STINKY_PENGUIN_MANIFEST.read_text())
    require(
        stinky_penguin_manifest
        == {
            "id": "stinky-penguin",
            "displayName": "臭企鹅 stinky penguin",
            "description": "you are a stinky penguin.",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
        },
        "managed stinky-penguin manifest must match the validated v2 package",
    )
    require(MINERU_SETUP.exists(), "toolbox must include the optional MinerU setup helper")
    require(GAME_ASSET_PLUGIN.exists(), "game-asset-tools plugin manifest must exist")
    require(GAME_ASSET_MCP.exists(), "game-asset-tools must define an MCP config")
    require(RESEARCH_PLUGIN.exists(), "research-tools plugin manifest must exist")
    require(RESEARCH_MCP.exists(), "research-tools must define an MCP config")
    require(RESEARCH_LLM_WIKI_SKILL.exists(), "research-tools must include research-llm-wiki skill")
    require(
        RESEARCH_LLM_WIKI_LINT.exists(),
        "research-llm-wiki must include a deterministic lint helper",
    )
    require(
        MINERU_DOCUMENT_SKILL.exists(),
        "research-tools must include the mineru-document-extraction skill",
    )
    require(MINERU_WRAPPER.exists(), "MinerU document skill must include its local wrapper")
    require(
        PAPER_LIBRARY_INTAKE_SKILL.exists(),
        "research-tools must include paper-library-intake skill",
    )
    require(
        PAPER_LIBRARY_INTAKE_OPENAI.exists(),
        "paper-library-intake must include OpenAI agent metadata",
    )
    require(
        PAPER_LIBRARY_ATTACHMENT.exists(),
        "paper-library-intake must include the WebDAV attachment helper",
    )
    require(
        PAPER_READ_DRAFT_SKILL.exists(),
        "research-tools must include paper-read-draft skill",
    )
    require(
        PAPER_READ_DRAFT_OPENAI.exists(),
        "paper-read-draft must include OpenAI agent metadata",
    )
    require(
        PAPER_READ_DRAFT_TEMPLATE.exists(),
        "paper-read-draft must include its compact note template",
    )
    require(WORKFLOW_PLUGIN.exists(), "workflow-tools plugin manifest must exist")
    require(DEEP_PLANNING_SKILL.exists(), "workflow-tools must include deep-planning skill")
    require(DEEP_PLANNING_OPENAI.exists(), "deep-planning must include OpenAI agent metadata")
    require(PAPER_FIGURE_PLUGIN.exists(), "paper-figure-tools plugin manifest must exist")
    require(
        PAPER_FIGURE_SKILL.exists(),
        "paper-figure-tools must include paper-figure-workflow skill",
    )
    require(
        PAPER_FIGURE_OPENAI.exists(),
        "paper-figure-workflow must include OpenAI agent metadata",
    )
    require(
        PAPER_FIGURE_REFERENCE.exists(),
        "paper-figure-workflow must include figure templates reference",
    )
    require(PRODUCTIVITY_PLUGIN.exists(), "productivity-tools plugin manifest must exist")
    require(PRODUCTIVITY_MCP.exists(), "productivity-tools must define an MCP config")
    require(
        TODOIST_TASK_PLANNING_SKILL.exists(),
        "productivity-tools must include todoist-task-planning skill",
    )
    require(
        TODOIST_TASK_PLANNING_OPENAI.exists(),
        "todoist-task-planning must include OpenAI agent metadata",
    )
    marketplace = json.loads(MARKETPLACE.read_text())
    game_asset_plugin = json.loads(GAME_ASSET_PLUGIN.read_text())
    game_asset_mcp = json.loads(GAME_ASSET_MCP.read_text())
    research_plugin = json.loads(RESEARCH_PLUGIN.read_text())
    research_mcp = json.loads(RESEARCH_MCP.read_text())
    workflow_plugin = json.loads(WORKFLOW_PLUGIN.read_text())
    paper_figure_plugin = json.loads(PAPER_FIGURE_PLUGIN.read_text())
    productivity_plugin = json.loads(PRODUCTIVITY_PLUGIN.read_text())
    productivity_mcp = json.loads(PRODUCTIVITY_MCP.read_text())
    trading_mcp = json.loads(TRADING_MCP.read_text())
    default_plugins = array_body(script, "DEFAULT_PLUGINS")
    retired_plugins = array_body(script, "RETIRED_PLUGINS")
    managed_mcp_servers = array_body(script, "MANAGED_MCP_SERVERS")
    retired_mcp_servers = array_body(script, "RETIRED_MCP_SERVERS")
    pixellab_server = game_asset_mcp.get("mcpServers", {}).get("pixellab")
    robinhood_server = trading_mcp.get("mcpServers", {}).get("robinhood-trading")
    todoist_server = productivity_mcp.get("mcpServers", {}).get("todoist")

    retired_orchestrator = "sym" + "phony"
    retired_plugin_name = retired_orchestrator + "-tools"
    require(
        not (ROOT / "plugins" / retired_plugin_name).exists(),
        "retired orchestration plugin directory must be absent",
    )
    retired_mentions = []
    retired_tracker_mentions = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.resolve() == Path(__file__).resolve():
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if retired_orchestrator in line.lower():
                retired_mentions.append((str(path.relative_to(ROOT)), line_number, line.strip()))
            if re.search(r"\b" + ("lin" + "ear") + r"\b", line, re.IGNORECASE):
                retired_tracker_mentions.append(
                    (str(path.relative_to(ROOT)), line_number, line.strip())
                )
    allowed_retired_mentions = {
        ("scripts/setup-codex-toolbox.sh", f'"{retired_plugin_name}"'),
        ("scripts/setup-codex-toolbox.sh", f'"{retired_orchestrator}"'),
    }
    require(
        len(retired_mentions) == 2
        and {(path, line) for path, _, line in retired_mentions} == allowed_retired_mentions,
        "retired orchestration references must be limited to the plugin and MCP migration tombstones",
    )
    require(
        not retired_tracker_mentions,
        "retired issue-tracker routing references must be absent",
    )

    require(
        marketplace.get("name") == "jialuo-codex-toolbox",
        "marketplace must be named jialuo-codex-toolbox",
    )
    for expected in (
        "$mineru-document-extraction",
        "complex, scanned, OCR-heavy, or layout-sensitive local documents",
        "`pdf` or `documents` skill",
        "Zotero",
        "Defuddle or Firecrawl",
        "obsidian_files",
        "scripts/setup-mineru.sh --check",
        "scripts/setup-mineru.sh --install",
        "scripts/setup-mineru.sh --download-models",
        "not an MCP server",
    ):
        require(
            expected in readme_normalized,
            f"README MinerU routing must mention {expected}",
        )
    for expected in (
        "$paper-library-intake find",
        "$paper-library-intake add",
        "PAPER_SEARCH_MCP_ROOT",
        "Koofr/WebDAV",
        "metadata-only",
        "use_scihub=false",
    ):
        require(expected in readme_text, f"README paper intake must mention {expected}")
    for expected in (
        "Todoist Task Planning",
        "$todoist-task-planning",
        "connected Todoist app",
        "Codex CLI fallback",
        "https://ai.todoist.net/mcp",
        "codex mcp login todoist",
        "Deadline-only tasks stay in Todoist",
    ):
        require(
            expected in readme_normalized,
            f"README Todoist workflow must mention {expected}",
        )
    for expected in (
        "Managed Codex Pet",
        "config/codex/pets/stinky-penguin/",
        "python3 scripts/sync-codex-pets.py --install",
        "python3 scripts/sync-codex-pets.py --check",
        "installs the pet without selecting it",
        "Rerun the toolbox setup",
    ):
        require(
            expected in readme_normalized,
            f"README managed pet workflow must mention {expected}",
        )
    for forbidden in (
        "/Users/",
        "/home/",
        "MacBook",
        "WRX90",
        "RTX 5090",
        "RTX 6000",
    ):
        require(
            forbidden not in readme_text and forbidden not in global_agents_text,
            f"public routing docs must not contain private path or hardware identifier: {forbidden}",
        )
    require(
        marketplace.get("interface", {}).get("displayName") == "Jialuo's Codex Toolbox",
        "marketplace display name must be Jialuo's Codex Toolbox",
    )
    require(
        'MARKETPLACE_NAME="jialuo-codex-toolbox"' in script,
        "setup script must register the jialuo-codex-toolbox marketplace",
    )
    for expected in (
        "Git-backed",
        "marketplace source `jialuohu/codex-toolbox`",
        "Upgrade",
        "codex plugin marketplace upgrade jialuo-codex-toolbox",
        "CODEX_TOOLBOX_MARKETPLACE_MODE=local",
    ):
        require(expected in readme_text, f"README must document upgradeable toolbox marketplace: {expected}")
    for expected in (
        'TOOLBOX_MARKETPLACE_SOURCE="${CODEX_TOOLBOX_MARKETPLACE_SOURCE:-jialuohu/codex-toolbox}"',
        'TOOLBOX_MARKETPLACE_GIT_URL="https://github.com/jialuohu/codex-toolbox.git"',
        'TOOLBOX_MARKETPLACE_REF="${CODEX_TOOLBOX_MARKETPLACE_REF:-main}"',
        'TOOLBOX_MARKETPLACE_MODE="${CODEX_TOOLBOX_MARKETPLACE_MODE:-git}"',
        'plugin marketplace upgrade "$MARKETPLACE_NAME"',
        'plugin marketplace add "$TOOLBOX_MARKETPLACE_SOURCE" --ref "$TOOLBOX_MARKETPLACE_REF"',
        "remove_toolbox_marketplace_config_blocks",
        "TOOLBOX_MARKETPLACE_SOURCE_TO_REMOVE",
        "local)",
        "Registering local toolbox marketplace for development",
    ):
        require(expected in script, f"setup script must support upgradeable toolbox marketplace: {expected}")
    require(
        "declare -a OLD_MARKETPLACE_NAMES=()" in script,
        "setup script must not publish retired personal marketplace aliases",
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
        '  "symphony-tools"' not in default_plugins,
        "setup script must not install the retired symphony-tools plugin",
    )
    require(
        '  "symphony-tools"' in retired_plugins,
        "setup script must retain the symphony-tools migration tombstone",
    )
    require(
        '  "workflow-tools"' in default_plugins,
        "setup script must install the workflow-tools plugin",
    )
    require(
        '  "paper-figure-tools"' in default_plugins,
        "setup script must install the paper-figure-tools plugin",
    )
    require(
        '  "productivity-tools"' in default_plugins,
        "setup script must install the productivity-tools plugin",
    )
    require(
        '  "pixellab"' in managed_mcp_servers,
        "setup script must manage the pixellab MCP server cleanup list",
    )
    require(
        '  "symphony"' not in managed_mcp_servers,
        "setup script must not treat the retired symphony MCP server as active",
    )
    require(
        '  "symphony"' in retired_mcp_servers,
        "setup script must retain the symphony MCP migration tombstone",
    )
    require(
        'for server in "${RETIRED_MCP_SERVERS[@]}"; do' in script
        and 'Removed retired direct MCP config: ${server}' in script,
        "setup script must clean up retired direct MCP config overrides",
    )
    require(
        '  "todoist"' in managed_mcp_servers,
        "setup script must manage the todoist MCP server cleanup list",
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
        not any(
            plugin.get("name") == "symphony-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must not include the retired symphony-tools plugin",
    )
    require(
        any(
            plugin.get("name") == "workflow-tools"
            and plugin.get("source", {}).get("path") == "./plugins/workflow-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include workflow-tools",
    )
    require(
        any(
            plugin.get("name") == "paper-figure-tools"
            and plugin.get("source", {}).get("path") == "./plugins/paper-figure-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include paper-figure-tools",
    )
    require(
        any(
            plugin.get("name") == "productivity-tools"
            and plugin.get("source", {}).get("path") == "./plugins/productivity-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include productivity-tools",
    )
    require(
        productivity_plugin.get("skills") == "./skills/",
        "productivity-tools must expose its Todoist workflow skill",
    )
    require(
        productivity_plugin.get("mcpServers") == "./.mcp.json",
        "productivity-tools must expose its MCP config",
    )
    productivity_interface = productivity_plugin.get("interface", {})
    require(
        "Todoist" in productivity_interface.get("longDescription", ""),
        "productivity-tools description must mention Todoist",
    )
    require(
        any(
            "todoist-task-planning" in prompt
            for prompt in productivity_interface.get("defaultPrompt", [])
        ),
        "productivity-tools prompts must surface todoist-task-planning",
    )
    require(
        todoist_server is not None,
        "productivity-tools must define the todoist MCP server",
    )
    require(
        todoist_server.get("type") == "http",
        "todoist must use the Streamable HTTP plugin MCP shape",
    )
    require(
        todoist_server.get("url") == "https://ai.todoist.net/mcp",
        "todoist must point to Todoist's official MCP endpoint",
    )
    require(
        todoist_server.get("default_tools_approval_mode") == "prompt",
        "todoist tools must prompt by default until their mutation semantics are reviewed",
    )
    todoist_skill_text = TODOIST_TASK_PLANNING_SKILL.read_text()
    todoist_skill_normalized = " ".join(todoist_skill_text.split())
    for expected in (
        "name: todoist-task-planning",
        "Todoist is the source of truth",
        "Deadline-only tasks",
        "Do not create a Google Calendar event",
        "calendar time block",
        "remote meeting",
        "Do not create a Todoist follow-up task unless",
        "Search for an existing matching record",
        "attendee-visible",
        "Confirm before",
        "conversation history is not a task database",
        "Prefer the connected Todoist app",
        "Never write the same operation through both",
    ):
        require(
            expected in todoist_skill_normalized,
            f"todoist-task-planning must mention {expected}",
        )
    todoist_openai = TODOIST_TASK_PLANNING_OPENAI.read_text()
    for expected in (
        'display_name: "Todoist Task Planning"',
        'short_description: "Manage Todoist tasks and calendar work blocks."',
        'default_prompt: "Use $todoist-task-planning to capture this task and schedule time only when appropriate."',
        'value: "todoist"',
        'url: "https://ai.todoist.net/mcp"',
    ):
        require(
            expected in todoist_openai,
            f"todoist-task-planning OpenAI metadata must mention {expected}",
        )
    require(
        workflow_plugin.get("skills") == "./skills/",
        "workflow-tools must expose bundled planning skills",
    )
    require(
        workflow_plugin.get("version") == "0.1.1",
        "workflow-tools plugin version must reflect the routing update",
    )
    require(
        "mcpServers" not in workflow_plugin,
        "workflow-tools must not expose an MCP server",
    )
    workflow_interface = workflow_plugin.get("interface", {})
    require(
        "Plan Mode" in workflow_interface.get("longDescription", ""),
        "workflow-tools plugin description must mention Plan Mode",
    )
    require(
        any("deep-planning" in prompt for prompt in workflow_interface.get("defaultPrompt", [])),
        "workflow-tools default prompts must surface deep-planning usage",
    )
    deep_planning_text = DEEP_PLANNING_SKILL.read_text()
    for expected in (
        "name: deep-planning",
        "Plan Mode",
        "adversarial critique",
        "Observed Facts",
        "Assumptions / Unknowns",
        "Strongest Plan",
        "Adversarial Review",
        "Revised Plan / Routing",
        "Do not edit or write files",
        "docs/superpowers/",
        "Codex-only",
        "Native Codex subagents",
        "Superpowers",
        "OpenSpec",
    ):
        require(expected in deep_planning_text, f"deep-planning skill must mention {expected}")
    deep_planning_openai = DEEP_PLANNING_OPENAI.read_text()
    for expected in (
        'display_name: "Deep Planning"',
        'short_description: "Adversarial Plan Mode critique before implementation."',
        'default_prompt: "Use $deep-planning to critique this plan before implementation."',
    ):
        require(expected in deep_planning_openai, f"deep-planning OpenAI metadata must mention {expected}")
    require(
        paper_figure_plugin.get("skills") == "./skills/",
        "paper-figure-tools must expose bundled figure workflow skills",
    )
    require(
        "mcpServers" not in paper_figure_plugin,
        "paper-figure-tools must not expose an MCP server",
    )
    paper_figure_interface = paper_figure_plugin.get("interface", {})
    require(
        "AI/systems paper" in paper_figure_interface.get("longDescription", ""),
        "paper-figure-tools plugin description must mention AI/systems paper figures",
    )
    require(
        any("paper-figure-workflow" in prompt for prompt in paper_figure_interface.get("defaultPrompt", [])),
        "paper-figure-tools default prompts must surface paper-figure-workflow usage",
    )
    paper_figure_skill_text = PAPER_FIGURE_SKILL.read_text()
    for expected in (
        "name: paper-figure-workflow",
        "AI/systems paper",
        "draw.io",
        "diagrams.net",
        "figures_src/",
        "figures/",
        "SVG",
        "PDF",
        "Matplotlib",
        "SciencePlots",
        "import scienceplots",
        "['science', 'no-latex']",
        "Inkscape",
        "make figures",
        "no hard-coded absolute paths",
        "Do not rasterize",
        "Check that the generated figures build successfully",
        "references/templates.md",
    ):
        require(expected in paper_figure_skill_text, f"paper-figure-workflow skill must mention {expected}")
    paper_figure_openai = PAPER_FIGURE_OPENAI.read_text()
    for expected in (
        'display_name: "Paper Figure Workflow"',
        'short_description: "Reproducible paper figure workflows."',
        'default_prompt: "Use $paper-figure-workflow to set up editable diagrams and publication plots."',
    ):
        require(expected in paper_figure_openai, f"paper-figure OpenAI metadata must mention {expected}")
    paper_figure_reference_text = PAPER_FIGURE_REFERENCE.read_text()
    for expected in (
        "make figures",
        "python -m pip install matplotlib scienceplots pandas",
        "fig.savefig",
        "figure.svg",
        "figure.pdf",
        "inkscape",
        "--export-type=pdf",
        "drawio",
        "--export",
    ):
        require(expected in paper_figure_reference_text, f"paper-figure reference must mention {expected}")
    require(
        research_plugin.get("skills") == "./skills/",
        "research-tools must expose bundled research skills",
    )
    paper_search_server = research_mcp.get("mcpServers", {}).get("paper_search_mcp")
    require(paper_search_server is not None, "research-tools must define paper_search_mcp")
    paper_search_args = paper_search_server.get("args", [])
    require(
        len(paper_search_args) == 2 and paper_search_args[0] == "-lc",
        "paper_search_mcp must run through zsh -lc",
    )
    paper_search_launch = paper_search_args[1] if len(paper_search_args) == 2 else ""
    source_position = paper_search_launch.find('source "$SECRET_FILE"')
    root_position = paper_search_launch.find("PAPER_SEARCH_MCP_ROOT")
    require(
        source_position >= 0 and root_position > source_position,
        "paper_search_mcp must load its environment before validating PAPER_SEARCH_MCP_ROOT",
    )
    disabled_paper_downloads = set(paper_search_server.get("disabled_tools", []))
    require(
        {"download_scihub", "download_with_fallback"} <= disabled_paper_downloads,
        "paper_search_mcp must disable direct and default-enabled Sci-Hub paths",
    )
    paper_intake_text = PAPER_LIBRARY_INTAKE_SKILL.read_text()
    for expected in (
        "name: paper-library-intake",
        "$paper-library-intake find",
        "$paper-library-intake add",
        "Search Zotero first",
        "Use Firecrawl first",
        "Use Paper Search",
        "Research/ReadLater",
        'if_exists="file"',
        "create_missing_collections=false",
        'attach_mode="none"',
        'attach_mode="auto"',
        "attach-cloud",
        "use_scihub=false",
        "zotero_read_pdf_pages",
        "metadata-only",
        "reachable: true",
        "authoritative auto-detection signal",
        "Sync > File Syncing",
    ):
        require(expected in paper_intake_text, f"paper-library-intake must mention {expected}")
    require(
        "$paper-library-intake" in PAPER_LIBRARY_INTAKE_OPENAI.read_text(),
        "paper-library-intake agent metadata must expose the skill trigger",
    )
    attachment_text = PAPER_LIBRARY_ATTACHMENT.read_text()
    for expected in (
        "incomplete_webdav_configuration",
        "webdav_backend_required",
        "ambiguous_attachment_children",
        "attachment_checksum_conflict",
        "AttachmentMutationError",
        "_attachment_lock",
        "_create_attachment_with_recovery",
        "correlation_title",
        "secrets.token_hex",
        "attachment_metadata_create_outcome_unknown",
        "concurrent_attachment_conflict",
        "upload_attachment_to_webdav",
        "attach_zotero_cloud",
        "extract_bounded_webdav_zip",
        "_download_webdav_attachment_bounded",
        "webdav_checksum_mismatch",
        "webdav_preflight_failed",
        "invalid_webdav_preflight_response",
        "PROPFIND",
        "symlink_not_allowed",
        "attachment_operation_failed",
    ):
        require(expected in attachment_text, f"paper attachment helper must mention {expected}")
    require(
        research_plugin.get("version") == "0.3.0",
        "research-tools must use the PaperRead draft minor version",
    )
    mineru_skill_text = MINERU_DOCUMENT_SKILL.read_text()
    for expected in (
        "name: mineru-document-extraction",
        "one local document",
        "complex, scanned, OCR-heavy, table/formula-rich, or layout-sensitive documents",
        "mineru-run.json",
        "Use Zotero tools instead",
        "outside any Obsidian vault",
        "setup-mineru.sh --check",
        "Extraction is local-only",
    ):
        require(expected in mineru_skill_text, f"MinerU document skill must mention {expected}")
    mineru_setup_text = MINERU_SETUP.read_text()
    for expected in (
        "scripts/setup-mineru.sh --check|--install|--download-models",
        "MINERU_MODEL_CACHE_DIR",
        "outside every Git checkout and Obsidian vault",
        "Model downloads remain opt-in",
        'get_vlm_engine("auto")',
        "umask 077",
        'chmod 600 "$CONFIG_FILE"',
    ):
        require(expected in mineru_setup_text, f"MinerU setup helper must mention {expected}")
    mineru_wrapper_text = MINERU_WRAPPER.read_text()
    for expected in (
        'default="hybrid-engine"',
        'default="high"',
        '"observed_device_engine"',
        '"duration_seconds"',
        '"content_list_v2"',
        '"MINERU_API_MAX_CONCURRENT_REQUESTS"',
        '"MINERU_MODEL_SOURCE"',
        '"HF_HUB_OFFLINE"',
        '"local_only"',
        "outside every Git checkout",
        "configured Obsidian vault",
        '"staged_copy_used"',
        "model_configuration_error",
        "CONTENT_LIST_V2_TYPES",
        "CONTENT_LIST_V2_REQUIRED_VALUE_TYPES",
        "TemporaryDirectory",
        "llm-aided-config",
        '"NO_PROXY"',
        '"TORCH_HOME"',
        '"FTLANG_CACHE"',
        "dir=output",
        "artifact_tree_error",
        '"PYTHONUNBUFFERED"',
    ):
        require(expected in mineru_wrapper_text, f"MinerU wrapper must mention {expected}")
    for mcp_file in ROOT.glob("plugins/*/.mcp.json"):
        mcp_config = json.loads(mcp_file.read_text())
        for server_name in mcp_config.get("mcpServers", {}):
            require(
                "mineru" not in server_name.lower(),
                f"MinerU must remain a local skill, not an MCP server ({mcp_file})",
            )
    require(
        '  "mineru"' not in managed_mcp_servers.lower(),
        "setup script must not manage a MinerU MCP server",
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
    require(
        any("$paper-library-intake" in prompt for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface paper-library-intake",
    )
    require(
        any("mineru" in prompt.lower() for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must retain MinerU extraction coverage",
    )
    require(
        "PaperRead" in research_interface.get("shortDescription", "")
        and "PaperRead" in research_interface.get("longDescription", ""),
        "research-tools plugin descriptions must surface the PaperRead draft workflow",
    )
    require(
        any("$paper-read-draft" in prompt for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface paper-read-draft",
    )
    require(
        len(research_interface.get("defaultPrompt", [])) <= 3,
        "research-tools default prompts must respect Codex's three-prompt limit",
    )
    paper_read_draft_text = PAPER_READ_DRAFT_SKILL.read_text()
    for expected in (
        "name: paper-read-draft",
        "metadata-only",
        "do not guess",
        "Do not add or update Zotero",
        "do not ingest the LLM Wiki",
        "Fill a metadata field only when the user supplied it or current-task source/tool output actually observed it.",
        "Never claim a Zotero or canonical lookup occurred without actual returned evidence.",
        "Missing evidence means blank optional fields.",
    ):
        require(expected in paper_read_draft_text, f"paper-read-draft skill must mention {expected}")
    for expected, message in (
        (
            "Use the vault template at `PaperRead/_Paper Read Template.md` when it exists and satisfies the contract.",
            "paper-read-draft must require the exact PaperRead vault template path",
        ),
        (
            "If that exact vault template is missing or malformed, never silently rewrite the vault template; use the bundled fallback at `references/paper-read-template.md` for note creation.",
            "paper-read-draft must use its bundled fallback only when the vault template is missing or malformed",
        ),
        (
            "A standard create-draft request authorizes only one new note.",
            "paper-read-draft must limit create authority to one new note",
        ),
        (
            "Resolve the configured vault through `CODEX_OBSIDIAN_VAULT` and `obsidian_files`. Write only beneath `PaperRead/`; never use the current working directory as the vault.",
            "paper-read-draft must use the configured vault, only write under PaperRead, and never use the current directory as the vault",
        ),
        (
            "Before any write, perform an exact-path check. If the note already exists, return its path without modifying it.",
            "paper-read-draft must return an exact-path existing note without modification",
        ),
        (
            "If a normalized filename collision represents a distinct paper, ask before choosing a disambiguated filename.",
            "paper-read-draft must ask about distinct normalized filename collisions",
        ),
        (
            "Do not fill personal sections by default; each is hidden-prompt-only.",
            "paper-read-draft must leave personal sections hidden-prompt-only by default",
        ),
    ):
        require(expected in paper_read_draft_text, message)
    paper_read_draft_openai = PAPER_READ_DRAFT_OPENAI.read_text()
    for expected in (
        'display_name: "PaperRead Draft"',
        'default_prompt: "Use $paper-read-draft',
        "allow_implicit_invocation: true",
    ):
        require(expected in paper_read_draft_openai, f"paper-read-draft metadata must mention {expected}")
    paper_read_draft_template = PAPER_READ_DRAFT_TEMPLATE.read_text()
    for expected in (
        "tags: [paper-read]",
        "## Takeaway",
        "## Summary in my own words",
        "## My thoughts",
        "## Questions",
    ):
        require(expected in paper_read_draft_template, f"paper-read-draft template must mention {expected}")
    for expected in (
        "## PaperRead Draft",
        "$paper-read-draft",
        "create a compact Obsidian PaperRead draft",
        "fills factual metadata only",
        "four personal sections",
    ):
        require(expected in readme_text, f"README PaperRead draft section must mention {expected}")
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
        "$paper-library-intake",
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
        "CODEX_SECRETS_DIR",
        'source "$SECRET_FILE"',
        "mcp-remote@latest",
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
