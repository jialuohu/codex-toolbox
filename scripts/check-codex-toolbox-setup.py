#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

import hashlib
import json
import re
import shlex
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-codex-toolbox.sh"
SETUP_PREREQUISITES = ROOT / "scripts" / "setup-codex-prerequisites.py"
SYNC_AGENTS_SCRIPT = ROOT / "scripts" / "sync-agents.sh"
SYNC_PETS_SCRIPT = ROOT / "scripts" / "sync-codex-pets.py"
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
REPO_AGENTS = ROOT / "AGENTS.md"
README = ROOT / "README.md"
STINKY_PENGUIN_DIR = ROOT / "config" / "codex" / "pets" / "stinky-penguin"
STINKY_PENGUIN_MANIFEST = STINKY_PENGUIN_DIR / "pet.json"
STINKY_PENGUIN_SPRITESHEET = STINKY_PENGUIN_DIR / "spritesheet.webp"
MINERU_SETUP = ROOT / "scripts" / "setup-mineru.sh"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
WEB_DATA_DIR = ROOT / "plugins" / "web-data-tools"
WEB_DATA_PLUGIN = WEB_DATA_DIR / ".codex-plugin" / "plugin.json"
WEB_DATA_MCP = WEB_DATA_DIR / ".mcp.json"
FIRECRAWL_LAUNCHER = WEB_DATA_DIR / "scripts" / "run-firecrawl-mcp.sh"
FIRECRAWL_PROXY = WEB_DATA_DIR / "scripts" / "firecrawl_budget_proxy.py"
COMMUNITY_RESEARCH_SKILL = (
    WEB_DATA_DIR / "skills" / "community-research" / "SKILL.md"
)
COMMUNITY_RESEARCH_OPENAI = (
    COMMUNITY_RESEARCH_SKILL.parent / "agents" / "openai.yaml"
)
OBSIDIAN_MCP = ROOT / "plugins" / "obsidian-tools" / ".mcp.json"
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
DOCMOST_LAB_WIKI_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "docmost-lab-wiki" / "SKILL.md"
)
DOCMOST_LAB_WIKI_OPENAI = DOCMOST_LAB_WIKI_SKILL.parent / "agents" / "openai.yaml"
DOCMOST_LAB_WIKI_COMMANDS = DOCMOST_LAB_WIKI_SKILL.parent / "references" / "commands.md"
DOCMOST_LAB_WIKI_RUNTIME = (
    ROOT / "plugins" / "research-tools" / "runtime" / "docmost-lab-wiki"
)
DOCMOST_LAB_WIKI_PYPROJECT = DOCMOST_LAB_WIKI_RUNTIME / "pyproject.toml"
DOCMOST_LAB_WIKI_LOCK = DOCMOST_LAB_WIKI_RUNTIME / "uv.lock"
DOCMOST_LAB_WIKI_CONSTANTS = (
    DOCMOST_LAB_WIKI_RUNTIME / "src" / "docmost_lab_wiki" / "constants.py"
)
DOCMOST_LAB_WIKI_CLI = (
    DOCMOST_LAB_WIKI_RUNTIME / "src" / "docmost_lab_wiki" / "cli.py"
)
DOCMOST_LAB_WIKI_WIKI = (
    DOCMOST_LAB_WIKI_RUNTIME / "src" / "docmost_lab_wiki" / "wiki.py"
)
DOCMOST_LAB_WIKI_INDEX = (
    DOCMOST_LAB_WIKI_RUNTIME / "src" / "docmost_lab_wiki" / "index.py"
)
DOCMOST_LAB_WIKI_TEST = DOCMOST_LAB_WIKI_RUNTIME / "tests" / "test_lab_wiki.py"
DOCMOST_LAB_WIKI_SETUP = ROOT / "scripts" / "setup-docmost-lab-wiki.sh"
DOCMOST_LAB_WIKI_RUNNER = (
    ROOT / "plugins" / "research-tools" / "scripts" / "docmost-lab-wiki.sh"
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
PAPER_REVIEW_LIBRARY_INTAKE_SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "paper-review-library-intake"
    / "SKILL.md"
)
PAPER_REVIEW_LIBRARY_INTAKE_OPENAI = (
    PAPER_REVIEW_LIBRARY_INTAKE_SKILL.parent / "agents" / "openai.yaml"
)
PAPER_REVIEW_PAGE_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "paper-review-page" / "SKILL.md"
)
PAPER_REVIEW_PAGE_OPENAI = PAPER_REVIEW_PAGE_SKILL.parent / "agents" / "openai.yaml"
PAPER_REVIEW_CONFERENCE_TEMPLATE = (
    PAPER_REVIEW_PAGE_SKILL.parent / "assets" / "conference-review-template.md"
)
PAPER_REVIEW_JOURNAL_TEMPLATE = (
    PAPER_REVIEW_PAGE_SKILL.parent / "assets" / "journal-review-template.md"
)
PAPER_REVIEW_PAGE_STRUCTURE = (
    PAPER_REVIEW_PAGE_SKILL.parent / "scripts" / "template_structure.py"
)
PAPER_REVIEW_SYNC_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "paper-review-sync" / "SKILL.md"
)
PAPER_REVIEW_SYNC_OPENAI = PAPER_REVIEW_SYNC_SKILL.parent / "agents" / "openai.yaml"
PAPER_REVIEW_SYNC_CONTRACT = (
    PAPER_REVIEW_SYNC_SKILL.parent / "scripts" / "paper_review_contract.py"
)
ZOTERO_TODOIST_READING_TASKS_SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "zotero-todoist-reading-tasks"
    / "SKILL.md"
)
ZOTERO_TODOIST_READING_TASKS_OPENAI = (
    ZOTERO_TODOIST_READING_TASKS_SKILL.parent / "agents" / "openai.yaml"
)
PAPER_READ_DRAFT_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "paper-read-draft" / "SKILL.md"
)
PAPER_READ_DRAFT_OPENAI = PAPER_READ_DRAFT_SKILL.parent / "agents" / "openai.yaml"
PAPER_READ_DRAFT_TEMPLATE = PAPER_READ_DRAFT_SKILL.parent / "references" / "paper-read-template.md"
PAPER_READ_DRAFT_FILENAME = (
    PAPER_READ_DRAFT_SKILL.parent / "scripts" / "paper_read_filename.py"
)
PAPER_READ_REVIEW_SKILL = (
    ROOT / "plugins" / "research-tools" / "skills" / "paper-read-review" / "SKILL.md"
)
PAPER_READ_REVIEW_OPENAI = PAPER_READ_REVIEW_SKILL.parent / "agents" / "openai.yaml"
WORKFLOW_PLUGIN = ROOT / "plugins" / "workflow-tools" / ".codex-plugin" / "plugin.json"
CODER_PLUGIN = ROOT / "plugins" / "coder-tools" / ".codex-plugin" / "plugin.json"
CODER_MCP = ROOT / "plugins" / "coder-tools" / ".mcp.json"
DEEP_PLANNING_SKILL = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "deep-planning" / "SKILL.md"
)
DEEP_PLANNING_OPENAI = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "deep-planning" / "agents" / "openai.yaml"
)
EXPLAIN_CLEARLY_SKILL = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "explain-clearly" / "SKILL.md"
)
EXPLAIN_CLEARLY_OPENAI = EXPLAIN_CLEARLY_SKILL.parent / "agents" / "openai.yaml"
SHIP_TOOLBOX_SKILL = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "ship-toolbox" / "SKILL.md"
)
SHIP_TOOLBOX_OPENAI = SHIP_TOOLBOX_SKILL.parent / "agents" / "openai.yaml"
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
DIAGRAM_TOOLS_DIR = ROOT / "plugins" / "diagram-tools"
DIAGRAM_TOOLS_PLUGIN = DIAGRAM_TOOLS_DIR / ".codex-plugin" / "plugin.json"
PRETTY_MERMAID_DIR = DIAGRAM_TOOLS_DIR / "skills" / "pretty-mermaid"
PRETTY_MERMAID_SKILL = PRETTY_MERMAID_DIR / "SKILL.md"
PRETTY_MERMAID_OPENAI = PRETTY_MERMAID_DIR / "agents" / "openai.yaml"
PRETTY_MERMAID_CLI = PRETTY_MERMAID_DIR / "scripts" / "pretty-mermaid.mjs"
PRETTY_MERMAID_FIXTURES = PRETTY_MERMAID_DIR / "assets" / "fixtures"
DIAGRAM_BOOTSTRAP = DIAGRAM_TOOLS_DIR / "runtime" / "bootstrap"
DIAGRAM_SETUP = ROOT / "scripts" / "setup-diagram-tools.sh"
DIAGRAM_WORKFLOW = ROOT / ".github" / "workflows" / "diagram-tools.yml"
DRAWIO_TOOLS_DIR = ROOT / "plugins" / "drawio-tools"
DRAWIO_TOOLS_PLUGIN = DRAWIO_TOOLS_DIR / ".codex-plugin" / "plugin.json"
DRAWIO_TOOLS_MCP = DRAWIO_TOOLS_DIR / ".mcp.json"
DRAWIO_SKILL_DIR = DRAWIO_TOOLS_DIR / "skills" / "drawio"
DRAWIO_SKILL = DRAWIO_SKILL_DIR / "SKILL.md"
DRAWIO_OPENAI = DRAWIO_SKILL_DIR / "agents" / "openai.yaml"
DRAWIO_BOOTSTRAP = DRAWIO_TOOLS_DIR / "runtime" / "bootstrap"
DRAWIO_LAUNCHER = DRAWIO_TOOLS_DIR / "scripts" / "run-drawio-mcp.sh"
DRAWIO_VERIFIER = DRAWIO_TOOLS_DIR / "scripts" / "verify-drawio-runtime.mjs"
DRAWIO_DESKTOP = DRAWIO_TOOLS_DIR / "scripts" / "drawio-desktop.sh"
DRAWIO_FIXTURE = DRAWIO_TOOLS_DIR / "assets" / "fixtures" / "basic.drawio"
DRAWIO_MCP_SMOKE = DRAWIO_TOOLS_DIR / "tests" / "mcp-smoke.mjs"
DRAWIO_SETUP = ROOT / "scripts" / "setup-drawio-tools.sh"
DRAWIO_WORKFLOW = ROOT / ".github" / "workflows" / "drawio-tools.yml"
DRAWIO_TEST = ROOT / "tests" / "test_drawio_tools.py"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
PRODUCTIVITY_PLUGIN = ROOT / "plugins" / "productivity-tools" / ".codex-plugin" / "plugin.json"
PRODUCTIVITY_MCP = ROOT / "plugins" / "productivity-tools" / ".mcp.json"
DOCMOST_DIR = ROOT / "plugins" / "docmost-tools"
DOCMOST_PLUGIN = DOCMOST_DIR / ".codex-plugin" / "plugin.json"
DOCMOST_MCP = DOCMOST_DIR / ".mcp.json"
DOCMOST_APPROVED_LAUNCHER_SHA256 = (
    "9d67581f0bf57fd92ba4cf1cf8d8612dde1a82c3ec09bc4d3dddeaea8ad05125"
)
DOCMOST_SETUP = ROOT / "scripts" / "setup-docmost-tools.sh"
DOCMOST_SMOKE = DOCMOST_DIR / "server" / "src" / "docmost_tools" / "smoke_cli.py"
DOCMOST_AUTH_WRAPPER = DOCMOST_DIR / "server" / "scripts" / "docmost-auth"
DOCMOST_MCP_WRAPPER = DOCMOST_DIR / "server" / "scripts" / "docmost-mcp"
DOCMOST_RUNTIME_LOCK = (
    DOCMOST_DIR / "server" / "src" / "docmost_tools" / "runtime_lock.py"
)
DOCMOST_RUNTIME_STAMP = (
    DOCMOST_DIR / "server" / "src" / "docmost_tools" / "runtime_stamp.py"
)
APPLE_MAIL_DIR = ROOT / "plugins" / "apple-mail-tools"
APPLE_MAIL_PLUGIN = APPLE_MAIL_DIR / ".codex-plugin" / "plugin.json"
APPLE_MAIL_MCP = APPLE_MAIL_DIR / ".mcp.json"
APPLE_MAIL_SKILL = APPLE_MAIL_DIR / "skills" / "apple-mail" / "SKILL.md"
APPLE_MAIL_SERVER = APPLE_MAIL_DIR / "server"
APPLE_MAIL_BRIDGE = APPLE_MAIL_SERVER / "scripts" / "mail_bridge.applescript"
APPLE_MAIL_SERVER_SOURCE = APPLE_MAIL_SERVER / "src" / "apple_mail_tools" / "server.py"
APPLE_MAIL_SETUP = ROOT / "scripts" / "setup-apple-mail-tools.sh"
APPLE_MAIL_APPROVED_LAUNCHER_SHA256 = (
    "41cd449f224e6f12614b53bf15f2f9e1f180787e7518b68cb5f29e29cf1e71f5"
)
DESIGN_ENGINEERING_DIR = ROOT / "plugins" / "design-engineering-tools"
DESIGN_ENGINEERING_PLUGIN = DESIGN_ENGINEERING_DIR / ".codex-plugin" / "plugin.json"
DESIGN_ENGINEERING_PROVENANCE = DESIGN_ENGINEERING_DIR / "PROVENANCE.md"
DESIGN_ENGINEERING_BOUNDARIES = DESIGN_ENGINEERING_DIR / "SHARED-BOUNDARIES.md"
DESIGN_ENGINEERING_SKILLS_DIR = DESIGN_ENGINEERING_DIR / "skills"
STEVENS_PRESENTATION_DIR = ROOT / "plugins" / "stevens-presentation-tools"
STEVENS_PRESENTATION_PLUGIN = (
    STEVENS_PRESENTATION_DIR / ".codex-plugin" / "plugin.json"
)
STEVENS_SLIDES_DIR = STEVENS_PRESENTATION_DIR / "skills" / "stevens-slides"
STEVENS_TEMPLATE_MANIFEST = STEVENS_SLIDES_DIR / "references" / "template-manifest.json"
STEVENS_ASSET_CHECKSUMS = STEVENS_SLIDES_DIR / "references" / "asset-checksums.json"
STEVENS_TEMPLATE_CHECKER = STEVENS_SLIDES_DIR / "scripts" / "check_templates.py"
STEVENS_SKILL_NAMES = (
    "stevens-slides",
    "stevens-slides-white",
    "stevens-slides-dark",
)
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
DAILY_COMMAND_CENTER_SKILL = (
    ROOT
    / "plugins"
    / "productivity-tools"
    / "skills"
    / "daily-command-center"
    / "SKILL.md"
)
DAILY_COMMAND_CENTER_OPENAI = DAILY_COMMAND_CENTER_SKILL.parent / "agents" / "openai.yaml"
GWS_SETUP = ROOT / "scripts" / "setup-gws.sh"
GOOGLE_WORKSPACE_DIR = ROOT / "plugins" / "google-workspace-tools"
GOOGLE_WORKSPACE_PLUGIN = GOOGLE_WORKSPACE_DIR / ".codex-plugin" / "plugin.json"
GOOGLE_WORKSPACE_PROVENANCE = GOOGLE_WORKSPACE_DIR / "PROVENANCE.md"
GOOGLE_WORKSPACE_LICENSE = GOOGLE_WORKSPACE_DIR / "LICENSE"
GOOGLE_WORKSPACE_SKILLS_DIR = GOOGLE_WORKSPACE_DIR / "skills"
GWS_SHARED_SKILL = GOOGLE_WORKSPACE_SKILLS_DIR / "gws-shared" / "SKILL.md"
GWS_GMAIL_SKILL = GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail" / "SKILL.md"
GWS_GMAIL_SEND_SKILL = GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-send" / "SKILL.md"
GWS_GMAIL_REPLY_SKILL = GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-reply" / "SKILL.md"
GWS_GMAIL_REPLY_ALL_SKILL = (
    GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-reply-all" / "SKILL.md"
)
GWS_GMAIL_FORWARD_SKILL = (
    GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-forward" / "SKILL.md"
)
GWS_GMAIL_READ_SKILL = GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-read" / "SKILL.md"
GWS_GMAIL_TRIAGE_SKILL = (
    GOOGLE_WORKSPACE_SKILLS_DIR / "gws-gmail-triage" / "SKILL.md"
)
GOOGLE_WORKSPACE_LICENSE_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
)
GWS_SHARED_SKILL_SHA256 = (
    "0bd1debf74c8161591394d4bf3a3a470150b351f0807088de1602f0285b8128a"
)
GWS_GMAIL_SKILL_SHA256 = (
    "5dec2f19457737a4611fe073c9cb943c0e2337af12b7bb7cdd9e3b8571216ef3"
)
GWS_GMAIL_SEND_SKILL_SHA256 = (
    "58e25295e204e414d429aa0fa80cc349eafaaea2816d6e64a25e2182367a9e42"
)
GWS_GMAIL_REPLY_SKILL_SHA256 = (
    "0f8debeb36280fa48d1fd2767544dab45999925519b2a754f69c35736b6bc303"
)
GWS_GMAIL_REPLY_ALL_SKILL_SHA256 = (
    "d1cfe8753e1cb151e7d93b679a0013fec29371311694c6f2d76a96f9d62f4648"
)
GWS_GMAIL_FORWARD_SKILL_SHA256 = (
    "f03e8693bb59705edd17379f9c745e57b9d40f5b89edfff994f7719781f3a7a1"
)
GWS_GMAIL_READ_SKILL_SHA256 = (
    "b5712fccedc4a706652633d8fa10c68c36c8b436da7a64a6c634f628c8feb60f"
)
GWS_GMAIL_TRIAGE_SKILL_SHA256 = (
    "9ce72c66fbe1afe34d4183404c3e82be6ae89a4752334b2d11e6f8c20c6778d7"
)
GOOGLE_WORKSPACE_PROVENANCE_SHA256 = (
    "aff66c1f8bacb72b7a28d74a9718a9dafe54a66d457c7cc54245f4767493970c"
)
GWS_INSTALL_FUNCTION_SHA256 = (
    "6583f835538eaa503fd0118f48beccf97ea0af36930f24956e6f93ede8657198"
)
GWS_RUNTIME_READY_FUNCTION_SHA256 = (
    "20967ce89c5fc49eb56cffb7f325e2f124e9aeca14c6072530c48eb77a8e54b4"
)
GWS_RUNTIME_TRUST_FUNCTION_SHA256 = (
    "0502a0a4e0167e199f25e5d1767a46a42c73a99a474088dd60dedacbf7d3c5f4"
)
GWS_ENSURE_RUNTIME_FUNCTION_SHA256 = (
    "2ab4dacc442950d52d571e8acdabc6209635e2596c4d84ad204b5f71069ea366"
)
GWS_SETUP_SHA256 = (
    "37c2181cd84236f9e7ab706b28990f39c27545abc150a93fe44921329cb85d40"
)
GLOBAL_GMAIL_ROUTING_PARAGRAPH = (
    "Keep the official Gmail connector available for ordinary connected Gmail requests. "
    "Use `$gws-gmail` from `google-workspace-tools` only when the user explicitly requests "
    "direct `gws` or multi-account Gmail and supplies an explicit account alias. Never infer "
    "or default an alias; ask for one when it is missing. Use exactly one Gmail surface per "
    "request: do not mix the official Gmail connector and direct `gws` in the same request. "
    "Direct `gws` work must apply `$gws-shared` and fail closed if its isolated profile or "
    "live identity preflight fails."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def array_body(script: str, name: str) -> str:
    match = re.search(rf"^{name}=\(\n(?P<body>.*?)\n\)", script, re.MULTILINE | re.DOTALL)
    require(match is not None, f"setup script must define {name}")
    return match.group("body")


def shell_array_entries(script: str, name: str) -> list[str]:
    """Parse the literal entries in a simple shell array, excluding comments."""
    entries = []
    for line in array_body(script, name).splitlines():
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as error:
            raise SystemExit(f"setup script {name} has invalid shell syntax: {error}") from error
        require(
            len(tokens) <= 1,
            f"setup script {name} must contain one literal entry per line",
        )
        if tokens:
            entries.append(tokens[0])
    return entries


def normalized(text: str) -> str:
    return " ".join(text.split())


def shell_assignment_values(script: str, name: str) -> list[str]:
    """Return every active whole-line assignment for one shell variable."""
    return re.findall(
        rf"^[ \t]*{re.escape(name)}=(?P<value>[^\r\n]*)$",
        script,
        re.MULTILINE,
    )


def shell_function_blocks(script: str, name: str) -> list[str]:
    """Return every whole top-level shell function definition with this name."""
    return re.findall(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        script,
        re.MULTILINE | re.DOTALL,
    )


def scan_retired_tracker_mentions(
    root: Path,
    checker_path: Path,
) -> list[tuple[str, int, str]]:
    """Return retired issue-tracker integration mentions outside ignored paths."""
    retired_tracker_mentions = []
    ignored_scan_parts = {".git", ".worktrees", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules"}
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        if (
            not path.is_file()
            or ignored_scan_parts.intersection(relative_path.parts)
            or path.resolve() == checker_path.resolve()
        ):
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if re.search(
                r"(?:https?://(?:www\.)?linear\.app\b|\bLINEAR_[A-Z0-9_]+\b|"
                r"\blinear\s+(?:issue|issues|ticket|tickets|project|projects|team|teams|"
                r"workspace|workspaces|integration|integrations|api|mcp|connector|connectors)\b)",
                line,
                re.IGNORECASE,
            ) or re.search(
                r"\bLinear(?:\s+(?:client|app)\b|\s+to\s+(?:track|manage)\b)",
                line,
            ):
                retired_tracker_mentions.append((str(relative_path), line_number, line.strip()))
    return retired_tracker_mentions


def daily_skill_frontmatter(skill_text: str) -> str:
    match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n", skill_text, re.DOTALL)
    require(match is not None, "daily-command-center must start with YAML frontmatter")
    return match.group("frontmatter")


def markdown_section(skill_text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        skill_text,
        re.MULTILINE | re.DOTALL,
    )
    require(match is not None, f"daily-command-center must include a {heading} section")
    return match.group("body")


def plain_normalized(text: str) -> str:
    return re.sub(r"[`*_]", "", normalized(text)).lower()


def validate_stevens_presentation_tools_contract(
    marketplace: dict,
    readme_text: str,
    default_plugins: str,
) -> None:
    """Validate the public Stevens presentation plugin and template contract."""
    entry = next(
        (
            plugin
            for plugin in marketplace.get("plugins", [])
            if plugin.get("name") == "stevens-presentation-tools"
        ),
        None,
    )
    require(entry is not None, "marketplace must include stevens-presentation-tools")
    require(
        entry.get("source")
        == {"source": "local", "path": "./plugins/stevens-presentation-tools"},
        "stevens-presentation-tools marketplace source must be local",
    )
    require(
        entry.get("policy")
        == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "stevens-presentation-tools marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require(
        default_plugins.count('  "stevens-presentation-tools"') == 1,
        "setup script must default-install stevens-presentation-tools exactly once",
    )

    for path, message in (
        (STEVENS_PRESENTATION_PLUGIN, "Stevens plugin manifest must exist"),
        (STEVENS_TEMPLATE_MANIFEST, "Stevens template manifest must exist"),
        (STEVENS_ASSET_CHECKSUMS, "Stevens asset checksum inventory must exist"),
        (STEVENS_TEMPLATE_CHECKER, "Stevens template checker must exist"),
        (STEVENS_PRESENTATION_DIR / "PROVENANCE.md", "Stevens provenance must exist"),
        (
            STEVENS_PRESENTATION_DIR / "THIRD_PARTY_NOTICES.md",
            "Stevens third-party notices must exist",
        ),
    ):
        require(path.exists(), message)

    plugin = json.loads(STEVENS_PRESENTATION_PLUGIN.read_text())
    require(
        plugin.get("name") == "stevens-presentation-tools",
        "Stevens plugin name must be exact",
    )
    require(plugin.get("version") == "0.2.0", "Stevens plugin version must be 0.2.0")
    require(plugin.get("skills") == "./skills/", "Stevens plugin must expose its skills")
    require("mcpServers" not in plugin, "Stevens plugin must not declare an MCP server")
    require(
        plugin.get("interface", {}).get("capabilities") == ["Read", "Write"],
        "Stevens plugin must declare Read and Write capabilities",
    )

    for skill_name in STEVENS_SKILL_NAMES:
        skill_dir = STEVENS_PRESENTATION_DIR / "skills" / skill_name
        require(skill_dir.joinpath("SKILL.md").exists(), f"{skill_name} skill must exist")
        require(
            skill_dir.joinpath("agents", "openai.yaml").exists(),
            f"{skill_name} must include OpenAI agent metadata",
        )

    manifest = json.loads(STEVENS_TEMPLATE_MANIFEST.read_text())
    require(manifest.get("version") == "2.0.0", "Stevens template manifest version must be 2.0.0")
    require(manifest.get("defaultTheme") == "white", "Stevens White must be the default theme")
    require(
        set(manifest.get("themes", {})) == {"white", "dark"},
        "Stevens manifest must define White and Dark themes",
    )
    require(
        manifest.get("templateStructure", {}).get("theme")
        == {"slides": 18, "masters": 2, "layouts": 39, "notesSlides": 18, "indexSlide": 1},
        "Stevens manifest must record the theme template structure",
    )
    require(
        manifest.get("templateStructure", {}).get("gallery")
        == {"slides": 4, "masters": 2, "layouts": 22, "notesSlides": 4},
        "Stevens manifest must record the gallery structure",
    )
    archetypes = manifest.get("archetypes", [])
    require(len(archetypes) == 17, "Stevens manifest must define 17 archetypes")
    require(
        [item.get("slideNumber") for item in archetypes] == list(range(2, 19)),
        "Stevens archetypes must map exemplar slides 2 through 18",
    )
    require(
        len({item.get("layoutName") for item in archetypes}) == 17,
        "Stevens layout names must be unique",
    )
    asset_paths = [manifest.get("sourceAsset"), manifest.get("galleryAsset")]
    asset_paths.extend(
        theme.get("assetPath") for theme in manifest.get("themes", {}).values()
    )
    for asset_path in asset_paths:
        require(
            isinstance(asset_path, str) and STEVENS_SLIDES_DIR.joinpath(asset_path).is_file(),
            f"Stevens manifest asset must exist: {asset_path}",
        )

    checksums = json.loads(STEVENS_ASSET_CHECKSUMS.read_text())
    require(checksums.get("algorithm") == "sha256", "Stevens assets must use SHA-256 checksums")
    require(
        len(checksums.get("files", [])) == 22,
        "Stevens checksum inventory must contain the 22 distributable assets",
    )
    require(
        not list(STEVENS_SLIDES_DIR.rglob("*.inspect.ndjson")),
        "Stevens generated inspect sidecars must not be distributed",
    )

    for expected in (
        "## Stevens Presentation Tools",
        "`stevens-presentation-tools`",
        "$stevens-slides-white",
        "$stevens-slides-dark",
        "17 named layouts",
        "`[Sources]`",
    ):
        require(expected in readme_text, f"README must document Stevens presentations: {expected}")


def validate_design_engineering_tools_contract(
    marketplace: dict,
    global_agents_text: str,
    readme_text: str,
    default_plugins: str,
    managed_mcp_servers: str,
) -> None:
    """Validate the installed design-engineering plugin and its routing boundary."""
    require(
        DESIGN_ENGINEERING_PLUGIN.exists(),
        "design-engineering-tools plugin manifest must exist",
    )
    require(
        DESIGN_ENGINEERING_PROVENANCE.exists(),
        "design-engineering-tools provenance must exist",
    )
    require(
        DESIGN_ENGINEERING_BOUNDARIES.exists(),
        "design-engineering-tools shared authority boundaries must exist",
    )
    require(
        DESIGN_ENGINEERING_SKILLS_DIR.exists(),
        "design-engineering-tools skills directory must exist",
    )
    design_plugin = json.loads(DESIGN_ENGINEERING_PLUGIN.read_text())
    expected_skills = {
        "animation-vocabulary",
        "apple-design",
        "emil-design-eng",
        "find-animation-opportunities",
        "improve-animations",
        "pick-ui-library",
        "prototype",
        "review-animations",
    }
    actual_skills = {
        path.name
        for path in DESIGN_ENGINEERING_SKILLS_DIR.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    }
    require(
        actual_skills == expected_skills,
        "design-engineering-tools skills inventory must be exactly eight expected skills",
    )
    require(
        design_plugin.get("name") == "design-engineering-tools",
        "design-engineering-tools manifest name must be exact",
    )
    require(
        design_plugin.get("version") == "0.1.0",
        "design-engineering-tools manifest version must be 0.1.0",
    )
    require(
        design_plugin.get("skills") == "./skills/",
        "design-engineering-tools manifest must expose ./skills/",
    )
    require(
        design_plugin.get("interface", {}).get("capabilities")
        == ["Read", "Write", "Interactive"],
        "design-engineering-tools manifest capabilities must be Read, Write, and Interactive",
    )
    require(
        "mcpServers" not in design_plugin,
        "design-engineering-tools manifest must not declare MCP servers",
    )
    require(
        not (DESIGN_ENGINEERING_DIR / ".mcp.json").exists(),
        "design-engineering-tools must not define an MCP config file",
    )
    design_entry = next(
        (
            plugin
            for plugin in marketplace.get("plugins", [])
            if plugin.get("name") == "design-engineering-tools"
        ),
        None,
    )
    require(design_entry is not None, "marketplace must include design-engineering-tools")
    source = design_entry.get("source", {})
    require(
        source.get("source") == "local",
        "design-engineering-tools marketplace source must be local",
    )
    require(
        source.get("path") == "./plugins/design-engineering-tools",
        "design-engineering-tools marketplace path must be ./plugins/design-engineering-tools",
    )
    policy = design_entry.get("policy", {})
    require(
        policy.get("installation") == "AVAILABLE",
        "design-engineering-tools marketplace installation policy must be AVAILABLE",
    )
    require(
        policy.get("authentication") == "ON_INSTALL",
        "design-engineering-tools marketplace authentication policy must be ON_INSTALL",
    )
    require(
        default_plugins.count("design-engineering-tools") == 1,
        "setup script must install design-engineering-tools as an active default plugin",
    )
    require(
        "design-engineering-tools" not in managed_mcp_servers,
        "design-engineering-tools must not be a managed MCP server",
    )
    provenance_text = DESIGN_ENGINEERING_PROVENANCE.read_text()
    require(
        "https://github.com/emilkowalski/skills" in provenance_text,
        "design-engineering-tools provenance must cite the upstream URL",
    )
    require(
        "70744e3816f1d93eafb697161a8b880a7384c5ff" in provenance_text,
        "design-engineering-tools provenance must cite the upstream commit",
    )
    require(
        "MIT" in provenance_text,
        "design-engineering-tools provenance must cite the MIT license",
    )
    boundaries_text = DESIGN_ENGINEERING_BOUNDARIES.read_text()
    boundary_order = (
        ("Explicit user direction", "explicit user direction"),
        ("Target project conventions and design system", "the project design system"),
        ("Accessibility requirements", "accessibility requirements"),
        ("Current official documentation", "current official documentation"),
        ("Imported opinions are advisory", "imported opinions as advisory"),
    )
    boundary_positions = []
    for expected, description in boundary_order:
        require(
            expected in boundaries_text,
            f"design-engineering-tools shared authority boundary must preserve {description}",
        )
        boundary_positions.append(boundaries_text.index(expected))
    require(
        boundary_positions == sorted(boundary_positions),
        "design-engineering-tools shared authority boundary must preserve priority order",
    )
    for skill in expected_skills:
        metadata = DESIGN_ENGINEERING_SKILLS_DIR / skill / "agents" / "openai.yaml"
        policy_match = re.search(
            r"^  allow_implicit_invocation: (?P<value>true|false)$",
            metadata.read_text(),
            re.MULTILINE,
        ) if metadata.exists() else None
        expected_value = skill not in {"pick-ui-library", "prototype", "review-animations"}
        require(
            policy_match is not None
            and (policy_match.group("value") == "true") == expected_value,
            "design-engineering-tools skill invocation policies must preserve explicit-only skills",
        )
    routing_requirements = (
        (
            "Use `ui-ux-pro-max` for broad UI/UX",
            "global AGENTS design-engineering routing must keep ui-ux-pro-max broad",
        ),
        (
            "$animation-vocabulary",
            "global AGENTS design-engineering routing must map vague motion naming to animation-vocabulary",
        ),
        (
            "`$apple-design` for explicitly Apple-like physical interaction",
            "global AGENTS design-engineering routing must map Apple-like interactions to apple-design",
        ),
        (
            "layout, typography, color, accessibility, and visual polish",
            "global AGENTS design-engineering routing must keep generic typography, accessibility, and reduced motion with ui-ux-pro-max",
        ),
        (
            "`$emil-design-eng` for explicit Emil Kowalski-style motion craft",
            "global AGENTS design-engineering routing must reserve emil-design-eng for explicit Emil or animations.dev requests",
        ),
        (
            "read-only animation audit skills for their named purposes",
            "global AGENTS design-engineering routing must map motion discovery and audits to their skills",
        ),
        (
            "Project design systems and accessibility requirements override imported advice",
            "global AGENTS design-engineering routing must preserve the authority override order",
        ),
    )
    for expected, message in routing_requirements:
        require(expected in global_agents_text, message)
    design_readme_match = re.search(
        r"^## Design Engineering Tools\n(?P<body>.*?)(?=^## |\Z)",
        readme_text,
        re.MULTILINE | re.DOTALL,
    )
    require(
        design_readme_match is not None,
        "README must include a Design Engineering Tools section",
    )
    design_readme_text = design_readme_match.group("body")
    readme_requirements = (
        (
            "motion vocabulary",
            "README design-engineering section must describe motion vocabulary scope",
        ),
        (
            "https://github.com/emilkowalski/skills",
            "README design-engineering section must cite the upstream URL",
        ),
        (
            "70744e3816f1d93eafb697161a8b880a7384c5ff",
            "README design-engineering section must cite the upstream commit",
        ),
        (
            "`review-animations`, `pick-ui-library`, and\n`prototype` are explicit-only skills",
            "README design-engineering section must identify explicit-only skills",
        ),
        (
            "fresh Codex task",
            "README design-engineering section must require a fresh Codex task",
        ),
    )
    for expected, message in readme_requirements:
        require(expected in design_readme_text, message)


def validate_google_workspace_tools_contract(
    marketplace: dict,
    global_agents_text: str,
    readme_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Validate the pinned, skill-only, isolated-profile Gmail integration."""
    require(
        GOOGLE_WORKSPACE_PLUGIN.exists(),
        "google-workspace-tools plugin manifest must exist",
    )
    google_workspace_plugin = json.loads(GOOGLE_WORKSPACE_PLUGIN.read_text())
    require(
        google_workspace_plugin.get("name") == "google-workspace-tools",
        "google-workspace-tools manifest name must be exact",
    )
    require(
        google_workspace_plugin.get("version") == "0.1.0",
        "google-workspace-tools manifest version must be 0.1.0",
    )
    require(
        google_workspace_plugin.get("license") == "Apache-2.0",
        "google-workspace-tools manifest license must be Apache-2.0",
    )
    require(
        google_workspace_plugin.get("skills") == "./skills/",
        "google-workspace-tools manifest must expose ./skills/",
    )
    require(
        "mcpServers" not in google_workspace_plugin,
        "google-workspace-tools manifest must not declare MCP servers",
    )
    require(
        not any(GOOGLE_WORKSPACE_DIR.rglob(".mcp.json")),
        "google-workspace-tools must not define an MCP config file",
    )

    expected_skills = {
        "gws-shared",
        "gws-gmail",
        "gws-gmail-read",
        "gws-gmail-triage",
        "gws-gmail-send",
        "gws-gmail-reply",
        "gws-gmail-reply-all",
        "gws-gmail-forward",
    }
    require(
        GOOGLE_WORKSPACE_SKILLS_DIR.is_dir(),
        "google-workspace-tools skills inventory must be exactly the eight Gmail skills",
    )
    actual_skill_directories = {
        path.name
        for path in GOOGLE_WORKSPACE_SKILLS_DIR.iterdir()
        if path.is_dir()
    }
    require(
        actual_skill_directories == expected_skills
        and all(
            (GOOGLE_WORKSPACE_SKILLS_DIR / skill / "SKILL.md").is_file()
            for skill in expected_skills
        ),
        "google-workspace-tools skills inventory must be exactly the eight Gmail skills",
    )

    google_workspace_entry = next(
        (
            plugin
            for plugin in marketplace.get("plugins", [])
            if plugin.get("name") == "google-workspace-tools"
        ),
        None,
    )
    require(
        google_workspace_entry is not None,
        "marketplace must include google-workspace-tools",
    )
    source = google_workspace_entry.get("source", {})
    require(
        source.get("source") == "local"
        and source.get("path") == "./plugins/google-workspace-tools",
        "google-workspace-tools marketplace source must be the local plugin",
    )
    policy = google_workspace_entry.get("policy", {})
    require(
        policy.get("installation") == "AVAILABLE"
        and policy.get("authentication") == "ON_INSTALL",
        "google-workspace-tools marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require(
        default_plugins.count("google-workspace-tools") == 1,
        "setup script must install google-workspace-tools as an active default plugin",
    )
    require(
        "gws" not in managed_mcp_servers
        and "google-workspace-tools" not in managed_mcp_servers,
        "gws must not be a managed MCP server",
    )

    require(
        GOOGLE_WORKSPACE_PROVENANCE.exists(),
        "google-workspace-tools provenance must exist",
    )
    provenance_text = GOOGLE_WORKSPACE_PROVENANCE.read_text()
    for expected, message in (
        (
            "https://github.com/googleworkspace/cli",
            "google-workspace-tools provenance must cite the upstream URL",
        ),
        (
            "`v0.22.5`",
            "google-workspace-tools provenance must cite release v0.22.5",
        ),
        (
            "`705fb0ecac6f4249679958f6325b809b63fdde17`",
            "google-workspace-tools provenance must cite the pinned upstream commit",
        ),
    ):
        require(expected in provenance_text, message)
    expected_imported_skills = {
        f"skills/{skill}/SKILL.md" for skill in expected_skills
    }
    imported_skill_paths = re.findall(
        r"^- `(?P<path>skills/[^`\r\n]+/SKILL\.md)`$",
        provenance_text,
        re.MULTILINE,
    )
    require(
        len(imported_skill_paths) == len(expected_imported_skills)
        and set(imported_skill_paths) == expected_imported_skills,
        "google-workspace-tools provenance imported skill inventory must be exact",
    )
    require(
        hashlib.sha256(GOOGLE_WORKSPACE_PROVENANCE.read_bytes()).hexdigest()
        == GOOGLE_WORKSPACE_PROVENANCE_SHA256,
        "google-workspace-tools provenance must match the canonical reviewed text",
    )
    require(
        GOOGLE_WORKSPACE_LICENSE.exists(),
        "google-workspace-tools Apache-2.0 license must exist",
    )
    require(
        hashlib.sha256(GOOGLE_WORKSPACE_LICENSE.read_bytes()).hexdigest()
        == GOOGLE_WORKSPACE_LICENSE_SHA256,
        "google-workspace-tools license must match the canonical Apache-2.0 text",
    )

    require(GWS_SETUP.exists(), "toolbox must include the opt-in setup-gws helper")
    gws_setup_text = GWS_SETUP.read_text()
    for name, expected_value, message in (
        (
            "VERSION",
            '"0.22.5"',
            "setup-gws must pin gws version 0.22.5 exactly once",
        ),
        (
            "ASSET",
            '"google-workspace-cli-aarch64-apple-darwin.tar.gz"',
            "setup-gws must pin the macOS arm64 release asset exactly once",
        ),
        (
            "SHA256",
            '"1d2a9ffd5bc9b2c2c4b48630daf082fad13d9e57d741988a2c248eed562f7dac"',
            "setup-gws must pin the expected release checksum exactly once",
        ),
        (
            "BINARY_SHA256",
            '"0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e"',
            "setup-gws must pin the expected binary checksum exactly once",
        ),
        (
            "RELEASE_URL",
            '"https://github.com/googleworkspace/cli/releases/download/v${VERSION}/${ASSET}"',
            "setup-gws must pin the exact upstream release URL",
        ),
    ):
        require(
            shell_assignment_values(gws_setup_text, name) == [expected_value],
            message,
        )
    require(
        gws_setup_text.splitlines().count(
            '  [ "$actual" = "$SHA256" ] || die "checksum mismatch for pinned gws release"'
        )
        == 1,
        "setup-gws must actively compare the downloaded archive checksum",
    )
    runtime_ready_blocks = shell_function_blocks(gws_setup_text, "runtime_ready")
    require(
        len(runtime_ready_blocks) == 1
        and "  runtime_path_is_trusted 0 || return 1\n" in runtime_ready_blocks[0]
        and hashlib.sha256(runtime_ready_blocks[0].encode()).hexdigest()
        == GWS_RUNTIME_READY_FUNCTION_SHA256,
        "setup-gws must validate the complete managed runtime trust path",
    )
    runtime_trust_blocks = shell_function_blocks(
        gws_setup_text,
        "runtime_path_is_trusted",
    )
    require(
        len(runtime_trust_blocks) == 1
        and all(
            expected in runtime_trust_blocks[0]
            for expected in (
                "not os.path.isabs(runtime_dir)",
                "os.path.normpath(runtime_dir) != runtime_dir",
                'binary != os.path.join(runtime_dir, "gws")',
                "components = [current]",
                "metadata = os.lstat(component)",
                "stat.S_ISLNK(metadata.st_mode)",
                "not stat.S_ISDIR(metadata.st_mode)",
            )
        ),
        "setup-gws must validate every managed runtime path component",
    )
    require(
        len(runtime_trust_blocks) == 1
        and (
            "            or not stat.S_ISDIR(metadata.st_mode)\n"
            "            or metadata.st_uid not in trusted_owners\n"
            "            or mode & (stat.S_IWGRP | stat.S_IWOTH)\n"
        )
        in runtime_trust_blocks[0],
        "setup-gws must reject untrusted or writable runtime directories",
    )
    require(
        len(runtime_trust_blocks) == 1
        and (
            "            stat.S_ISLNK(metadata.st_mode)\n"
            "            or not stat.S_ISREG(metadata.st_mode)\n"
            "            or metadata.st_uid not in trusted_owners\n"
            "            or mode & (stat.S_IWGRP | stat.S_IWOTH)\n"
        )
        in runtime_trust_blocks[0]
        and hashlib.sha256(runtime_trust_blocks[0].encode()).hexdigest()
        == GWS_RUNTIME_TRUST_FUNCTION_SHA256,
        "setup-gws must reject an untrusted or writable runtime binary",
    )
    ensure_runtime_blocks = shell_function_blocks(gws_setup_text, "ensure_runtime_dir")
    install_gws_blocks = shell_function_blocks(gws_setup_text, "install_gws")
    require(
        len(ensure_runtime_blocks) == 1
        and ensure_runtime_blocks[0].count("runtime_path_is_trusted 1") == 2
        and 'mkdir -p "$RUNTIME_DIR"' in ensure_runtime_blocks[0]
        and 'chmod 755 "$RUNTIME_DIR"' in ensure_runtime_blocks[0]
        and hashlib.sha256(ensure_runtime_blocks[0].encode()).hexdigest()
        == GWS_ENSURE_RUNTIME_FUNCTION_SHA256
        and len(install_gws_blocks) == 1
        and "  ensure_runtime_dir\n" in install_gws_blocks[0],
        "setup-gws installer must reject unsafe preexisting runtime paths",
    )
    require(
        len(install_gws_blocks) == 1
        and hashlib.sha256(install_gws_blocks[0].encode()).hexdigest()
        == GWS_INSTALL_FUNCTION_SHA256,
        "setup-gws install_gws function must match the canonical reviewed text",
    )
    setup_requirements = (
        (
            'GMAIL_SCOPE="https://www.googleapis.com/auth/gmail.modify"',
            "setup-gws must request only gmail.modify",
        ),
        (
            'SECRETS_BASE="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"',
            "setup-gws must use the toolbox secrets root",
        ),
        (
            'ACCOUNTS_ROOT="${SECRETS_ROOT}/accounts"',
            "setup-gws must isolate profiles below the accounts root",
        ),
        (
            '[[ "$1" =~ ^[a-z0-9][a-z0-9._-]{0,62}$ ]]',
            "setup-gws must validate account aliases",
        ),
        (
            "cd / || return 1",
            "setup-gws must run gws from the filesystem root",
        ),
        (
            'GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile"',
            "setup-gws must select an isolated profile directory",
        ),
        (
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file",
            "setup-gws must force the file keyring backend",
        ),
        (
            'GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json"',
            "setup-gws must block ambient ADC with a missing profile-local sentinel",
        ),
        (
            'status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()',
            "setup-gws must verify the exact live account identity",
        ),
        (
            '        "openid",',
            "setup-gws must require the openid identity scope",
        ),
        (
            '        "https://www.googleapis.com/auth/gmail.modify",',
            "setup-gws must require gmail.modify",
        ),
        (
            '        "https://www.googleapis.com/auth/userinfo.email",',
            "setup-gws must require the userinfo.email identity scope",
        ),
        (
            '        "https://www.googleapis.com/auth/userinfo.profile",',
            "setup-gws must require the userinfo.profile identity scope",
        ),
        (
            "and len(scopes) == len(scope_set)",
            "setup-gws must reject duplicate scopes",
        ),
        (
            "and any(scope_set == accepted for accepted in accepted_scope_sets)",
            "setup-gws must require one exact accepted scope set",
        ),
        (
            "chmod 700",
            "setup-gws must protect profile directories with mode 700",
        ),
        (
            "chmod 600",
            "setup-gws must protect profile files with mode 600",
        ),
    )
    for expected, message in setup_requirements:
        require(expected in gws_setup_text, message)
    for variable in (
        "GOOGLE_WORKSPACE_CLI_TOKEN",
        "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
        "GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE",
        "GOOGLE_WORKSPACE_CLI_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_CLI_LOG",
        "GOOGLE_WORKSPACE_CLI_LOG_FILE",
        "GOOGLE_WORKSPACE_PROJECT_ID",
        "GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE",
        "GOOGLE_WORKSPACE_CLI_SANITIZE_MODE",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        require(
            f"    -u {variable} \\" in gws_setup_text,
            f"setup-gws must clear ambient {variable}",
        )
    require(
        all(
            expected in gws_setup_text
            for expected in (
                'SECRETS_ROOT="${SECRETS_BASE}/gws"',
                'ACCOUNTS_ROOT="${SECRETS_ROOT}/accounts"',
                'profile_state_is_private_shallow "$SECRETS_BASE" || return 1',
                'profile_state_is_private_shallow "$SECRETS_ROOT" || return 1',
                'profile_state_is_private_shallow "$ACCOUNTS_ROOT" || return 1',
                '[ "$base" = "$SECRETS_BASE" ]',
                '[ "$root" = "$SECRETS_ROOT" ]',
                '[ "$root" = "$SECRETS_ROOT/accounts" ] && [ "$root" = "$ACCOUNTS_ROOT" ]',
                "and stat.S_IMODE(metadata.st_mode) == 0o700",
            )
        ),
        "setup-gws must enforce the canonical private secrets hierarchy",
    )
    require(
        all(
            expected in gws_setup_text
            for expected in (
                'required = ("client_id", "client_secret", "project_id", "auth_uri", "token_uri")',
                'installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"',
                'installed["token_uri"] == "https://oauth2.googleapis.com/token"',
                'validate_client_json "$1" || die "invalid Desktop OAuth client JSON"',
                'validate_client_json "$candidate" || die "copied OAuth client candidate is invalid"',
                'private_regular_file "$candidate" || die "copied OAuth client candidate is unsafe"',
            )
        ),
        "setup-gws must validate the complete Desktop OAuth client contract",
    )
    client_no_clobber = (
        '[ ! -e "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || '
        'die "OAuth client already registered; refusing replacement"'
    )
    require(
        gws_setup_text.count(client_no_clobber) == 2
        and all(
            expected in gws_setup_text
            for expected in (
                'candidate="$(mktemp "$SECRETS_ROOT/.client_secret.json.XXXXXX")"',
                'TX_CLIENT_CANDIDATE="$candidate"',
                '/bin/ln "$candidate" "$CLIENT_PATH"',
                'unlink_destination_if_same_file "$candidate" "$CLIENT_PATH"',
                '/bin/rm -- "$candidate" || die "unable to clean OAuth client candidate"',
                'TX_CLIENT_CANDIDATE=""',
            )
        ),
        "setup-gws must register the OAuth client transactionally without clobbering",
    )
    require(
        gws_setup_text.count('acquire_alias_lock "$alias"') == 2
        and gws_setup_text.count('release_alias_lock') == 3
        and gws_setup_text.count('if ! check_account "$alias"; then') == 2
        and all(
            expected in gws_setup_text
            for expected in (
                '/bin/mkdir "$profile" || die "unable to reserve account profile path"',
                'TX_RESERVATION="$profile"',
                'rename_path "$candidate" "$profile" || die "unable to activate candidate account profile"',
                'rename_path "$profile" "$backup"',
                'rename_path "$candidate" "$profile"',
            )
        ),
        "setup-gws must serialize and reserve account activation",
    )
    require(
        gws_setup_text.count("shopt -s dotglob nullglob") == 2
        and gws_setup_text.count("secrets_root_inventory_is_clean") == 3
        and gws_setup_text.count('elif check_account "$alias"; then') == 2
        and all(
            expected in gws_setup_text
            for expected in (
                'PROFILE_ENTRIES=("$ACCOUNTS_ROOT"/*)',
                'SECRETS_ROOT_ENTRIES=("$SECRETS_ROOT"/*)',
                "client_secret.json|accounts) ;;",
                "*) return 1 ;;",
            )
        ),
        "setup-gws must inspect hidden and broken profile entries fail closed",
    )
    credential_state_blocks = shell_function_blocks(
        gws_setup_text,
        "credential_state_is_complete",
    )
    health_check_blocks = shell_function_blocks(gws_setup_text, "check_profile_health")
    require(
        len(credential_state_blocks) == 1
        and all(
            expected in credential_state_blocks[0]
            for expected in (
                'private_regular_file "$profile/profile.json" || return 1',
                'private_regular_file "$profile/client_secret.json" || return 1',
                'private_regular_file "$profile/credentials.enc" || return 1',
                'private_regular_file "$profile/.encryption_key" || return 1',
            )
        )
        and len(health_check_blocks) == 1
        and health_check_blocks[0].index("credential_state_is_complete")
        < health_check_blocks[0].index('status="$(run_isolated'),
        "setup-gws must require encrypted credential files before auth status",
    )
    require(
        len(credential_state_blocks) == 1
        and '[ ! -e "$profile/credentials.json" ] && [ ! -L "$profile/credentials.json" ]'
        in credential_state_blocks[0]
        and 'status.get("plain_credentials_exists") is False' in gws_setup_text,
        "setup-gws must reject plaintext credential state",
    )
    require(
        hashlib.sha256(GWS_SETUP.read_bytes()).hexdigest() == GWS_SETUP_SHA256,
        "setup-gws profile manager must match the canonical reviewed text",
    )

    require(GWS_SHARED_SKILL.exists(), "gws-shared skill must exist")
    gws_shared_text = GWS_SHARED_SKILL.read_text()
    require(
        "Require an **explicit alias**" in gws_shared_text,
        "gws shared contract must require an explicit alias",
    )
    require(
        "never infer one from a likely" in gws_shared_text
        and "If it is absent, stop and\nask." in gws_shared_text,
        "gws shared contract must reject default account inference",
    )
    shared_runtime_requirements = (
        (
            "  cd / || exit 1\n",
            "gws shared runtime must run from the filesystem root",
        ),
        (
            'gws_runtime_path="${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws"\n',
            "gws shared runtime must use the pinned absolute managed binary",
        ),
        (
            "        metadata = os.lstat(component)\n",
            "gws shared runtime must validate every managed runtime path component",
        ),
        (
            "            or not stat.S_ISDIR(metadata.st_mode)\n"
            "            or metadata.st_uid not in trusted_owners\n"
            "            or mode & (stat.S_IWGRP | stat.S_IWOTH)\n",
            "gws shared runtime must reject untrusted or writable runtime directories",
        ),
        (
            "        or not stat.S_ISREG(metadata.st_mode)\n"
            "        or metadata.st_uid not in trusted_owners\n"
            "        or mode & (stat.S_IWGRP | stat.S_IWOTH)\n",
            "gws shared runtime must reject an untrusted or writable runtime binary",
        ),
        (
            'gws_sha_output="$(/usr/bin/shasum -a 256 "$gws_bin" 2>/dev/null)" || exit 1\n',
            "gws shared runtime must hash the managed binary with /usr/bin/shasum",
        ),
        (
            '[ "$gws_sha256" = "0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e" ] || exit 1\n',
            "gws shared runtime must verify the pinned binary checksum",
        ),
        (
            '[ "$first_line" = "gws 0.22.5" ] || exit 1\n',
            "gws shared runtime must verify the pinned binary version",
        ),
        (
            "  /usr/bin/env -u GOOGLE_WORKSPACE_CLI_TOKEN \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_TOKEN",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_CLIENT_ID \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CLIENT_ID",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_CLIENT_SECRET \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_CLIENT_SECRET",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_LOG \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_LOG",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_LOG_FILE \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_LOG_FILE",
        ),
        (
            "    -u GOOGLE_WORKSPACE_PROJECT_ID \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_PROJECT_ID",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE",
        ),
        (
            "    -u GOOGLE_WORKSPACE_CLI_SANITIZE_MODE \\\n",
            "gws shared runtime must clear ambient GOOGLE_WORKSPACE_CLI_SANITIZE_MODE",
        ),
        (
            "    -u GOOGLE_APPLICATION_CREDENTIALS \\\n",
            "gws shared runtime must unset ambient GOOGLE_APPLICATION_CREDENTIALS",
        ),
        (
            '    GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile" \\\n',
            "gws shared runtime must select the isolated profile directory",
        ),
        (
            "    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \\\n",
            "gws shared runtime must force the file keyring backend",
        ),
        (
            '    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \\\n',
            "gws shared runtime must set the missing profile-local ADC sentinel",
        ),
        (
            'and status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()\n',
            "gws shared runtime must verify the exact live identity",
        ),
        (
            'and status.get("token_valid") is True\n',
            "gws shared runtime must require a valid token",
        ),
        (
            'and status.get("storage") == "encrypted"\n',
            "gws shared runtime must require encrypted credential storage",
        ),
        (
            'and status.get("keyring_backend") == "file"\n',
            "gws shared runtime must verify the file keyring backend",
        ),
        (
            'and status.get("encrypted_credentials_exists") is True\n',
            "gws shared runtime must require encrypted credentials",
        ),
        (
            'and status.get("encryption_valid") is True\n',
            "gws shared runtime must require decryptable credentials",
        ),
        (
            "and isinstance(scopes, list)\n",
            "gws shared runtime must validate the scope collection",
        ),
        (
            '        "openid",\n',
            "gws shared runtime must require the openid identity scope",
        ),
        (
            '        "https://www.googleapis.com/auth/gmail.modify",\n',
            "gws shared runtime must require gmail.modify",
        ),
        (
            '        "https://www.googleapis.com/auth/userinfo.email",\n',
            "gws shared runtime must require the userinfo.email identity scope",
        ),
        (
            '        "https://www.googleapis.com/auth/userinfo.profile",\n',
            "gws shared runtime must require the userinfo.profile identity scope",
        ),
        (
            "and len(scopes) == len(scope_set)\n",
            "gws shared runtime must reject duplicate scopes",
        ),
        (
            "and any(scope_set == accepted for accepted in accepted_scope_sets)\n",
            "gws shared runtime must require one exact accepted scope set",
        ),
        (
            "There is no same-request Gmail connector fallback. Fail closed.\n",
            "gws shared runtime must forbid same-request connector fallback",
        ),
    )
    for expected, message in shared_runtime_requirements:
        require(expected in gws_shared_text, message)
    require(
        "    -u GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE \\" in gws_shared_text,
        "gws shared contract must clear ambient GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE",
    )
    require(
        all(
            expected in gws_shared_text
            for expected in (
                'secrets_root_path="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"',
                '[ "$secrets_root" = "$secrets_root_path" ] || exit 1',
                'gws_root_path="$secrets_root/gws"',
                '[ "$gws_root" = "$gws_root_path" ] || exit 1',
                'accounts_root_path="$gws_root/accounts"',
                '[ "$accounts_root" = "$accounts_root_path" ] || exit 1',
                "check(secrets_root, stat.S_ISDIR, 0o700)",
                "check(gws_root, stat.S_ISDIR, 0o700)",
                "check(root, stat.S_ISDIR, 0o700)",
                "check(profile, stat.S_ISDIR, 0o700)",
            )
        ),
        "gws shared contract must enforce the full canonical private secrets hierarchy",
    )
    require(
        all(
            expected in gws_shared_text
            for expected in (
                '        "profile.json",',
                '        "client_secret.json",',
                '        "credentials.enc",',
                '        ".encryption_key",',
            )
        )
        and gws_shared_text.index('        "credentials.enc",')
        < gws_shared_text.index('status_json="$('),
        "gws shared contract must require encrypted credential files before status",
    )
    require(
        'if os.path.lexists(os.path.join(profile, "credentials.json")):'
        in gws_shared_text
        and 'status.get("plain_credentials_exists") is False' in gws_shared_text,
        "gws shared contract must reject plaintext credential state",
    )
    require(
        all(
            expected in gws_shared_text
            for expected in (
                "Create a private temporary directory with mode `700`",
                "one mode-`700` child directory",
                "mode-`600` staged file",
                "cleanup for\n   every success and failure path",
            )
        ),
        "gws shared contract must stage attachments as private immutable copies",
    )
    require(
        "After the copy, perform a post-copy original restat and rehash"
        in gws_shared_text
        and "same non-symlink regular object, canonical target, device/inode, byte size,\n"
        "   and digest recorded initially" in gws_shared_text,
        "gws shared contract must restat and rehash the original after staging",
    )
    require(
        "require its staged\n   digest and size to match the original record"
        in gws_shared_text,
        "gws shared contract must verify staged size and digest",
    )
    require(
        "Require the final staged digest and identity to match the\n"
        "   staged record. Invoke gws with only the staged copy; never pass the mutable\n"
        "   original path." in gws_shared_text,
        "gws shared contract must verify the final staged copy and never pass the original path",
    )
    require(
        hashlib.sha256(GWS_SHARED_SKILL.read_bytes()).hexdigest()
        == GWS_SHARED_SKILL_SHA256,
        "gws-shared security contract must match the canonical reviewed text",
    )
    require(
        GWS_GMAIL_SKILL.exists(),
        "gws-gmail skill must exist",
    )
    gws_gmail_text = GWS_GMAIL_SKILL.read_text()
    gws_gmail_normalized = normalized(gws_gmail_text)
    require(
        "Do not invoke `users.messages.delete`,\n"
        "`users.messages.batchDelete`" in gws_gmail_text,
        "gws Gmail contract must keep permanent deletion unavailable",
    )
    require(
        all(
            expected in gws_gmail_normalized
            for expected in (
                "Raw Gmail resource access is read-only",
                "Raw `users.messages.send` is unavailable",
                "for the exact newly created server-side draft",
                "immediate unchanged readback",
                "unavailable for an existing, user-selected, guessed, or modified draft",
            )
        ),
        "gws Gmail contract must keep raw send inside the exact new-draft helper boundary",
    )
    require(
        hashlib.sha256(GWS_GMAIL_SKILL.read_bytes()).hexdigest()
        == GWS_GMAIL_SKILL_SHA256,
        "gws-gmail security contract must match the canonical reviewed text",
    )
    compose_skills = {
        "gws-gmail-send": (
            GWS_GMAIL_SEND_SKILL,
            GWS_GMAIL_SEND_SKILL_SHA256,
            r"\+send",
        ),
        "gws-gmail-reply": (
            GWS_GMAIL_REPLY_SKILL,
            GWS_GMAIL_REPLY_SKILL_SHA256,
            r"\+reply",
        ),
        "gws-gmail-reply-all": (
            GWS_GMAIL_REPLY_ALL_SKILL,
            GWS_GMAIL_REPLY_ALL_SKILL_SHA256,
            r"\+reply-all",
        ),
        "gws-gmail-forward": (
            GWS_GMAIL_FORWARD_SKILL,
            GWS_GMAIL_FORWARD_SKILL_SHA256,
            r"\+forward",
        ),
    }
    for skill_name, (skill_path, expected_sha256, helper_pattern) in compose_skills.items():
        require(skill_path.exists(), f"{skill_name} skill must exist")
        skill_text = skill_path.read_text()
        skill_normalized = normalized(skill_text)
        helper_prefix = rf'`"\$gws_bin" gmail {helper_pattern} [^`\r\n]*'
        require(
            re.search(
                helper_prefix + r'--from "\$expected_email"',
                skill_text,
            )
            is not None,
            f"{skill_name} must bind the helper draft to the verified From identity",
        )
        require(
            "Always create a server-side draft first" in skill_normalized
            or "always create a server-side draft first" in skill_normalized,
            f"{skill_name} must always create a server-side draft first",
        )
        require(
            re.search(helper_prefix + r"--draft`", skill_text) is not None,
            f"{skill_name} must always create a server-side draft first",
        )
        require(
            all(
                expected in skill_text
                for expected in (
                    '"userId": "me",',
                    '"id": os.environ["DRAFT_ID"],',
                    '"format": "full",',
                    'draft_json="$(isolated_gws gmail users drafts get --params "$draft_get_params")" || exit 1',
                )
            ),
            f"{skill_name} must fetch the exact new draft in full",
        )
        require(
            all(
                expected in skill_normalized
                for expected in (
                    "Validate the actual From",
                    "case-insensitively against `$expected_email`",
                    "actual To/CC/BCC",
                    "subject",
                    "thread context",
                    "attachment names and count",
                )
            ),
            f"{skill_name} must validate authoritative draft envelope and attachment fields",
        )
        require(
            all(
                expected in skill_normalized
                for expected in (
                    "Recursively base64url-decode every inline",
                    "`text/plain` and `text/html` MIME leaf",
                    "Validate decoded body content against the requested body",
                    "Missing or undecodable body bytes fail",
                )
            ),
            f"{skill_name} must validate decoded draft body content",
        )
        require(
            all(
                expected in skill_normalized
                for expected in (
                    "canonical MIME content digest from each part path",
                    "decoded byte length, and SHA-256 of its decoded bytes",
                    "decoded body bytes and canonical MIME content digest",
                )
            ),
            f"{skill_name} must validate the canonical MIME content digest",
        )
        require(
            'draft_json_again="$(isolated_gws gmail users drafts get '
            '--params "$draft_get_params")" || exit 1' in skill_text,
            f"{skill_name} must immediately reread the exact new draft before send",
        )
        require(
            skill_text.count('"id": os.environ["DRAFT_ID"]') == 2
            and 'print(json.dumps({"id": os.environ["DRAFT_ID"]}, separators=(",", ":")))'
            in skill_text,
            f"{skill_name} must send only the exact newly created draft ID",
        )
        require(
            'isolated_gws gmail users drafts send --params \'{"userId":"me"}\' '
            '--json "$draft_send_body" || exit 1' in skill_text
            and "never rebuild or send with `users.messages.send`"
            in skill_normalized,
            f"{skill_name} must use the narrow exact raw drafts.send command",
        )
        require(
            all(
                expected in skill_normalized
                for expected in (
                    "shared attachment safety contract",
                    "private temporary directory",
                    "initial lstat",
                    "device/inode",
                    "SHA-256",
                    "byte size",
                    "copy the exact bytes",
                    "post-copy original restat",
                    "staged digest",
                    "final staged digest check",
                    "pass only the staged copy to gws",
                    "Never pass the mutable user-supplied path",
                    "cleanup on every exit",
                )
            ),
            f"{skill_name} must enforce staged attachment integrity",
        )
        require(
            hashlib.sha256(skill_path.read_bytes()).hexdigest() == expected_sha256,
            f"{skill_name} security contract must match the canonical reviewed text",
        )
    for skill_name, skill_path, expected_sha256 in (
        ("gws-gmail-read", GWS_GMAIL_READ_SKILL, GWS_GMAIL_READ_SKILL_SHA256),
        (
            "gws-gmail-triage",
            GWS_GMAIL_TRIAGE_SKILL,
            GWS_GMAIL_TRIAGE_SKILL_SHA256,
        ),
    ):
        require(skill_path.exists(), f"{skill_name} skill must exist")
        require(
            hashlib.sha256(skill_path.read_bytes()).hexdigest() == expected_sha256,
            f"{skill_name} security contract must match the canonical reviewed text",
        )

    global_agents_requirements = (
        (
            "Use the official Gmail connector for ordinary Gmail",
            "global AGENTS must retain the official Gmail connector",
        ),
        (
            "explicitly requested direct-`gws` or multi-account workflow",
            "global AGENTS must route direct or multi-account Gmail to google-workspace-tools",
        ),
        (
            "explicit account alias",
            "global AGENTS direct gws routing must require an explicit account alias",
        ),
        (
            "never mix Gmail surfaces",
            "global AGENTS Gmail routing must select exactly one surface per request",
        ),
        (
            "`$gws-gmail` plus `$gws-shared`",
            "global AGENTS direct gws routing must require the shared preflight",
        ),
    )
    for expected, message in global_agents_requirements:
        require(expected in global_agents_text, message)
    require(
        re.search(
            r"official (?:gmail )?connector.{0,48}direct `?gws`? together",
            global_agents_text,
            re.IGNORECASE,
        )
        is None,
        "global AGENTS Gmail routing policy must reject additive surface-mixing contradictions",
    )

    readme_section_match = re.search(
        r"^## Isolated Multi-Account Gmail with gws\n"
        r"(?P<body>.*?)(?=^## |\Z)",
        readme_text,
        re.MULTILINE | re.DOTALL,
    )
    require(
        readme_section_match is not None,
        "README must document isolated multi-account Gmail with gws",
    )
    gws_readme_text = readme_section_match.group("body")
    gws_readme_normalized = normalized(gws_readme_text)
    readme_requirements = (
        (
            "https://github.com/googleworkspace/cli",
            "README must cite the Google Workspace CLI project",
        ),
        (
            "not an officially supported Google product",
            "README must state that gws is not an officially supported Google product",
        ),
        (
            "pre-v1",
            "README must state the pre-v1 stability status",
        ),
        (
            "no current `gws mcp`",
            "README must state that gws has no current MCP command",
        ),
        (
            "no native multi-account selector",
            "README must state that gws has no native multi-account selector",
        ),
        (
            "scripts/setup-gws.sh --check",
            "README must document the gws setup check",
        ),
        (
            "scripts/setup-gws.sh --install",
            "README must document the explicit gws installation",
        ),
        (
            "manual",
            "README must require manual Cloud Console OAuth setup",
        ),
        (
            "enable the Gmail API",
            "README OAuth setup must enable the Gmail API",
        ),
        (
            "External",
            "README OAuth setup must use an External audience",
        ),
        (
            "personal-use",
            "README OAuth setup must identify the personal-use app",
        ),
        (
            "In Production",
            "README OAuth setup must publish In Production before final logins",
        ),
        (
            "seven days",
            "README OAuth setup must explain Testing-mode token expiry",
        ),
        (
            "Desktop app",
            "README OAuth setup must use a Desktop client",
        ),
        (
            "unverified warning",
            "README OAuth setup must explain the unverified warning",
        ),
        (
            "https://www.googleapis.com/auth/gmail.modify",
            "README must require only the gmail.modify OAuth scope",
        ),
        (
            "The only Gmail permission requested is "
            "`https://www.googleapis.com/auth/gmail.modify`",
            "README must distinguish gmail.modify as the only Gmail permission",
        ),
        (
            "`gws` v0.22.5 automatically adds the three identity scopes "
            "`openid`, `userinfo.email`, and `userinfo.profile`",
            "README must document the three identity scopes added by gws v0.22.5",
        ),
        (
            "Never request `https://mail.google.com/`",
            "README must forbid the broad Gmail mail scope",
        ),
        (
            "scripts/setup-gws.sh --register-client /absolute/path/to/client_secret.json",
            "README must use an executable neutral OAuth client path",
        ),
        (
            "scripts/setup-gws.sh --add-account account-one@example.com --alias account-one",
            "README must document per-account onboarding with neutral placeholders",
        ),
        (
            "scripts/setup-gws.sh --reauth-account account-one",
            "README must document account reauthentication",
        ),
        (
            "Reauthenticate an existing profile, including one with an expired or "
            "revoked token, without changing its expected identity",
            "README must document repair reauthentication for unhealthy tokens",
        ),
        (
            "scripts/setup-gws.sh --check-account account-one",
            "README must document per-account health checks",
        ),
        (
            "scripts/setup-gws.sh --list-accounts",
            "README must document redacted account listing",
        ),
        (
            "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/gws/accounts/<alias>",
            "README must document the isolated profile root",
        ),
        (
            "plugin only",
            "README must keep binary installation and OAuth out of normal toolbox setup",
        ),
        (
            "There is no default gws account",
            "README must not define a default gws account",
        ),
    )
    for expected, message in readme_requirements:
        require(expected in gws_readme_normalized, message)


def validate_apple_mail_tools_contract(
    marketplace: dict,
    script: str,
    readme_text: str,
    global_agents_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Keep local Mail automation explicit, private, and unable to send."""
    for path, message in (
        (APPLE_MAIL_PLUGIN, "apple-mail-tools plugin manifest must exist"),
        (APPLE_MAIL_MCP, "apple-mail-tools must define an MCP config"),
        (APPLE_MAIL_SKILL, "apple-mail-tools must include its owning skill"),
        (APPLE_MAIL_BRIDGE, "apple-mail-tools must include its fixed bridge"),
        (APPLE_MAIL_SERVER_SOURCE, "apple-mail-tools must include its FastMCP server"),
        (APPLE_MAIL_SETUP, "toolbox must include the Apple Mail setup helper"),
    ):
        require(path.exists(), message)
    plugin = json.loads(APPLE_MAIL_PLUGIN.read_text())
    mcp = json.loads(APPLE_MAIL_MCP.read_text())
    require(plugin.get("name") == "apple-mail-tools", "Apple Mail plugin name must be exact")
    require(plugin.get("version") == "0.1.0", "apple-mail-tools must use version 0.1.0")
    require(
        plugin.get("author", {}).get("name") == "Codex Toolbox Contributors",
        "Apple Mail manifest must use neutral publisher metadata",
    )
    require(plugin.get("skills") == "./skills/", "Apple Mail manifest must expose its skill")
    require(
        plugin.get("mcpServers") == "./.mcp.json",
        "Apple Mail manifest must register its MCP config",
    )
    require(
        plugin.get("interface", {}).get("capabilities") == ["Read", "Write", "Interactive"],
        "Apple Mail manifest must keep read, write, and interactive capabilities",
    )
    servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    require(
        isinstance(servers, dict) and set(servers) == {"apple_mail"},
        "apple-mail-tools must define exactly one MCP server named apple_mail",
    )
    server = servers["apple_mail"]
    require(isinstance(server, dict), "Apple Mail MCP definition must be an object")
    require(server.get("command") == "/bin/zsh", "Apple Mail MCP must use its strict launcher")
    arguments = server.get("args")
    require(
        isinstance(arguments, list)
        and len(arguments) == 2
        and arguments[0] == "-lc"
        and isinstance(arguments[1], str)
        and bool(arguments[1]),
        "Apple Mail MCP must use exactly one nonempty zsh launcher",
    )
    launcher = arguments[1]
    require(
        hashlib.sha256(launcher.encode()).hexdigest()
        == APPLE_MAIL_APPROVED_LAUNCHER_SHA256,
        "Apple Mail MCP launcher must match the approved fingerprint",
    )
    require(server.get("cwd") == ".", "Apple Mail MCP must use plugin-root cwd")
    require(
        server.get("env_vars") == ["CODEX_HOME", "CODEX_SECRETS_DIR"],
        "Apple Mail MCP must forward only private-state root variables",
    )
    require(
        server.get("default_tools_approval_mode") == "auto",
        "Apple Mail MCP reads must default to automatic approval",
    )
    required_prompts = {
        "apple_mail_commit_index_sync",
        "apple_mail_erase_index",
        "apple_mail_fetch_attachment",
        "apple_mail_create_draft",
        "apple_mail_commit_mutation",
    }
    tools = server.get("tools")
    require(
        isinstance(tools, dict) and set(tools) == required_prompts,
        "Apple Mail MCP must prompt exactly its body-index, file, draft, and mutation writes",
    )
    require(
        all(tools[name] == {"approval_mode": "prompt"} for name in required_prompts),
        "Every Apple Mail write boundary must require approval",
    )
    for expected in (
        'APPLE_MAIL_RUNTIME_PARENT="$APPLE_MAIL_CODEX_ROOT/runtime"',
        'APPLE_MAIL_RUNTIME="$APPLE_MAIL_RUNTIME_PARENT/apple-mail-tools"',
        'APPLE_MAIL_PROJECT="$PWD/server"',
        'APPLE_MAIL_LOCK="$APPLE_MAIL_RUNTIME/libexec/runtime_lock.py"',
        "--mode shared",
        "--validate-fd --mode shared",
        "apple-mail-runtime-stamp\" check",
        'exec "$APPLE_MAIL_RUNTIME/bin/apple-mail-mcp"',
    ):
        require(expected in launcher, f"Apple Mail MCP launcher must include {expected}")
    marketplace_entry = next(
        (entry for entry in marketplace.get("plugins", []) if entry.get("name") == "apple-mail-tools"),
        None,
    )
    require(marketplace_entry is not None, "marketplace must include apple-mail-tools")
    require(
        marketplace_entry.get("source")
        == {"source": "local", "path": "./plugins/apple-mail-tools"},
        "Apple Mail marketplace source must be local",
    )
    require(
        marketplace_entry.get("policy")
        == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "Apple Mail marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require(
        "apple-mail-tools" in default_plugins,
        "setup must install apple-mail-tools by default",
    )
    require("apple_mail" in managed_mcp_servers, "setup must manage apple_mail MCP migration")
    helper = APPLE_MAIL_SETUP.read_text()
    require(APPLE_MAIL_SETUP.stat().st_mode & 0o111, "Apple Mail setup helper must be executable")
    for expected in (
        "--check", "--install", "--status", "--init-config",
        "--reinstall-package apple-mail-tools", "uv sync --python 3.12 --frozen",
        "run_locked exclusive --install-locked", "run_locked shared --check-locked",
        "run_locked shared --status-locked", "RuntimePaths.from_environment().ensure()",
        "apple-mail-runtime-stamp", "mail_bridge.applescript",
    ):
        require(expected in helper, f"Apple Mail setup helper must include {expected}")
    installed_blocks = shell_function_blocks(script, "installed_apple_mail_server_dir")
    require(
        len(installed_blocks) == 1
        and all(
            expected in installed_blocks[0]
            for expected in (
                '"$CODEX_BIN" mcp get apple_mail --json',
                '("plugins", "cache", marketplace_name, "apple-mail-tools")',
                'server / "scripts" / "mail_bridge.applescript"',
                f'approved_launcher_sha256 = "{APPLE_MAIL_APPROVED_LAUNCHER_SHA256}"',
                "hashlib.sha256(configured_args[1].encode()).hexdigest()",
                "transport.get(\"args\") != configured_args",
            )
        ),
        "toolbox setup must validate the exact installed Apple Mail distribution",
    )
    require(
        script.index('APPLE_MAIL_INSTALLED_SERVER_DIR="$(installed_apple_mail_server_dir)"')
        > script.index('for plugin in "${DEFAULT_PLUGINS[@]}"')
        and 'APPLE_MAIL_SERVER_DIR="$APPLE_MAIL_INSTALLED_SERVER_DIR" "$APPLE_MAIL_SETUP" --install'
        in script
        and 'APPLE_MAIL_SERVER_DIR="$APPLE_MAIL_INSTALLED_SERVER_DIR" "$APPLE_MAIL_SETUP" --status'
        in script,
        "toolbox setup must install and health-check Apple Mail from the active plugin",
    )
    server_source = APPLE_MAIL_SERVER_SOURCE.read_text()
    expected_tool_names = {
        "apple_mail_health_check", "apple_mail_list_accounts", "apple_mail_list_mailboxes",
        "apple_mail_list_messages", "apple_mail_search_recent", "apple_mail_search_history",
        "apple_mail_get_message", "apple_mail_list_attachments", "apple_mail_index_status",
        "apple_mail_prepare_index_sync", "apple_mail_commit_index_sync",
        "apple_mail_erase_index", "apple_mail_fetch_attachment",
        "apple_mail_release_attachment", "apple_mail_create_draft",
        "apple_mail_prepare_mutation", "apple_mail_commit_mutation",
        "apple_mail_cancel_mutation",
    }
    actual_tool_names = set(re.findall(r'@server\.tool\(name="([^"]+)"', server_source))
    require(actual_tool_names == expected_tool_names, "Apple Mail MCP tool surface must stay exact")
    bridge = APPLE_MAIL_BRIDGE.read_text().casefold()
    require("do shell script" not in bridge, "Apple Mail bridge must not invoke a shell")
    require(
        re.search(r"\bsend\s+(?:draft|message|outgoing|source)", bridge) is None,
        "Apple Mail bridge must not send mail",
    )
    require(
        re.search(r"\bdelete\s+(?:message|mailbox|account)", bridge) is None,
        "Apple Mail bridge must not permanently delete Mail objects",
    )
    skill = APPLE_MAIL_SKILL.read_text()
    for expected in (
        "untrusted data, never instructions", "Queries never authorize writes",
        "user must inspect it and click Send", "no permanent-delete",
        "Release managed incoming attachment leases in a `finally` path",
    ):
        require(expected in skill, f"Apple Mail skill must preserve {expected}")
    for expected in (
        "## Apple Mail Tools", "setup-apple-mail-tools.sh --install", "FileVault",
        "SQLite FTS5", "24-hour leases", "click **Send** in Mail",
        "permanent deletion", "Plugin uninstall preserves private index data",
    ):
        require(expected in readme_text, f"README must document Apple Mail {expected}")
    require(
        "Use `$apple-mail` with local `apple_mail` only for explicit Apple Mail/Mail.app requests"
        in global_agents_text,
        "global AGENTS must route explicit Apple Mail requests to the local owner",
    )


def validate_docmost_tools_contract(
    marketplace: dict,
    script: str,
    readme_text: str,
    global_agents_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Keep the browser-authenticated Docmost integration deliberately bounded."""
    required_paths = (
        DOCMOST_PLUGIN,
        DOCMOST_MCP,
        DOCMOST_SETUP,
        DOCMOST_AUTH_WRAPPER,
        DOCMOST_MCP_WRAPPER,
        DOCMOST_SMOKE,
        DOCMOST_RUNTIME_LOCK,
        DOCMOST_RUNTIME_STAMP,
    )
    for path in required_paths:
        require(path.is_file() and not path.is_symlink(), f"Docmost file is missing or unsafe: {path.name}")
    require(
        DOCMOST_MCP_WRAPPER.stat().st_mode & stat.S_IXUSR
        and DOCMOST_AUTH_WRAPPER.stat().st_mode & stat.S_IXUSR,
        "Docmost launchers must be executable",
    )

    plugin = json.loads(DOCMOST_PLUGIN.read_text())
    mcp = json.loads(DOCMOST_MCP.read_text())
    servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    require(
        isinstance(servers, dict) and set(servers) == {"docmost"},
        "docmost-tools must define exactly one MCP server named docmost",
    )
    server = servers["docmost"]
    require(isinstance(server, dict), "docmost MCP server definition must be an object")
    require(plugin.get("mcpServers") == "./.mcp.json", "docmost manifest must register its MCP config")
    require(
        plugin.get("author", {}).get("name") == "Codex Toolbox Contributors",
        "docmost manifest must use neutral publisher metadata",
    )
    require(plugin.get("version") == "0.5.0", "docmost-tools must use version 0.5.0")
    require(
        plugin.get("interface", {}).get("capabilities") == ["Read", "Write", "Interactive"],
        "docmost manifest must keep Read, Write, and Interactive capabilities",
    )
    require(
        server.get("command") == "/bin/bash"
        and server.get("args") == ["server/scripts/docmost-mcp"]
        and server.get("cwd") == "."
        and server.get("env_vars") == ["CODEX_SECRETS_DIR", "CODEX_HOME"],
        "docmost MCP must use only the checked-in generation bootstrap",
    )
    require(
        server.get("startup_timeout_sec") == 120
        and server.get("tool_timeout_sec") == 900,
        "docmost MCP must retain its startup and snapshot timeouts",
    )
    require(
        server.get("default_tools_approval_mode") == "auto",
        "docmost MCP reads must default to automatic approval",
    )
    required_writes = {
        "docmost_create_page",
        "docmost_update_page_title",
        "docmost_create_comment",
    }
    tools = server.get("tools")
    require(
        isinstance(tools, dict)
        and set(tools) == required_writes
        and all(tools[name] == {"approval_mode": "prompt"} for name in required_writes),
        "docmost MCP must prompt-gate exactly the approved write tools",
    )

    launcher = DOCMOST_MCP_WRAPPER.read_text()
    require(
        hashlib.sha256(DOCMOST_MCP_WRAPPER.read_bytes()).hexdigest()
        == DOCMOST_APPROVED_LAUNCHER_SHA256,
        "Docmost MCP bootstrap hash must be intentionally approved",
    )
    for expected in (
        'GENERATION_ROOT="$RUNTIME_PARENT/docmost-tools-generations"',
        'GENERATION_ENVS="$GENERATION_ROOT/envs"',
        'SECRET_FILE="$DOCMOST_SECRETS_ROOT/docmost.env"',
        'source_fingerprint',
        '--kind session --mode shared --root "$RUNTIME_PARENT"',
        '--kind generation --mode shared --root "$GENERATION_ROOT"',
        '--validate-fd',
        '"$STAMP_SOURCE" check "$SERVER_DIR" "$RUNTIME_STAMP"',
        'source "$SECRET_FILE"',
        'exec "$MCP_EXECUTABLE"',
    ):
        require(expected in launcher, f"Docmost MCP bootstrap must include {expected}")
    require(
        launcher.index('--kind session --mode shared --root "$RUNTIME_PARENT"')
        < launcher.index('--kind generation --mode shared --root "$GENERATION_ROOT"')
        < launcher.index('"$STAMP_SOURCE" check "$SERVER_DIR" "$RUNTIME_STAMP"')
        < launcher.index('source "$SECRET_FILE"')
        < launcher.index('exec "$MCP_EXECUTABLE"'),
        "Docmost MCP bootstrap must lock, validate, load configuration, then exec",
    )
    require(
        "uv run" not in launcher
        and "playwright" not in launcher
        and "docmost-auth" not in launcher
        and "setup-docmost-tools.sh" not in launcher,
        "Docmost MCP bootstrap must not install, authenticate, or retain uv",
    )

    runtime_recovery_text = "rerun the full codex-toolbox setup from its checkout"
    auth_login_command = (
        'CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" '
        '"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
    )
    auth_required_sentence = (
        "Authentication required. Close the active task, run "
        f"`{auth_login_command}`, then start a fresh task or reconnect Docmost."
    )
    helper = DOCMOST_SETUP.read_text()
    for expected in (
        "--check|--install|--login|--status|--logout|--prune",
        'GENERATION_ROOT="$RUNTIME_PARENT/docmost-tools-generations"',
        'GENERATION_ENVS="$GENERATION_ROOT/envs"',
        'GENERATION_LOCKS="$GENERATION_ROOT/locks"',
        'LEGACY_RUNTIME="$RUNTIME_PARENT/docmost-tools"',
        'run_setup_locked --install-setup-locked',
        'run_generation_locked exclusive --install-generation-locked',
        'run_generation_locked shared --check-locked',
        'run_session_generation_locked shared --status-locked',
        'run_session_generation_locked exclusive --login-locked',
        'run_session_generation_locked exclusive --logout-locked',
        'UV_PROJECT_ENVIRONMENT="$GENERATION_RUNTIME" run_uv sync',
        "--frozen --no-dev --no-editable --reinstall-package docmost-tools",
        '"$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" write',
        'protected_generation_ids',
        'plugins/cache/*/docmost-tools/*/server',
        'legacy_retained=',
        "playwright install chromium",
        "DocmostSettings.model_validate",
        "docmost-smoke",
        runtime_recovery_text,
    ):
        require(expected in helper, f"Docmost setup helper must include {expected}")
    require(f"LOGIN_COMMAND='{auth_login_command}'" in helper, "Docmost setup must preserve the auth recovery command")
    require(f"AUTH_REQUIRED_SENTENCE='{auth_required_sentence}'" in helper, "Docmost setup must preserve AUTH_REQUIRED wording")
    install_blocks = shell_function_blocks(helper, "install_generation_locked")
    require(len(install_blocks) == 1, "Docmost setup must define one generation installer")
    install_block = install_blocks[0]
    require(
        install_block.index("require_fresh_dependency_lock")
        < install_block.index('UV_PROJECT_ENVIRONMENT="$GENERATION_RUNTIME" run_uv sync')
        < install_block.index("install_runtime_support")
        < install_block.index("install_chromium")
        < install_block.index('"$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" write'),
        "Docmost generation installation must publish the verified stamp last",
    )
    require(
        "run_session_generation_locked" not in install_block
        and 'mv -f -- "$GENERATION_RUNTIME"' not in helper,
        "Docmost generation installation must avoid session locks and environment renames",
    )

    runtime_lock = DOCMOST_RUNTIME_LOCK.read_text()
    for expected in (
        'LOCK_NAME = ".docmost-tools-runtime.lock"',
        'SETUP_LOCK_NAME = ".setup.lock"',
        'LockKind = Literal["session", "setup", "generation"]',
        'def open_generation_lock',
        'def open_setup_lock',
        'environment[GENERATION_ID_ENV]',
        'os.set_inheritable(descriptor, True)',
        'os.execvpe(',
        '"Docmost runtime setup is busy',
        '"Docmost runtime generation is busy',
        'descriptor <= 2',
        'metadata.st_uid != os.geteuid()',
        'inherited.st_uid != os.geteuid()',
        'inherited.st_nlink != 1',
    ):
        require(expected in runtime_lock, f"Docmost runtime lock must include {expected}")
    stamp = DOCMOST_RUNTIME_STAMP.read_text()
    require(
        '"scripts/docmost-auth"' in stamp
        and '"scripts/docmost-mcp"' in stamp
        and 'getattr(os, "O_NOFOLLOW", 0)' in stamp
        and 'metadata.st_uid != os.geteuid()' in stamp
        and 'metadata.st_nlink != 1' in stamp
        and 'stat.S_IMODE(metadata.st_mode) != 0o600' in stamp
        and "temporary.replace(stamp)" in stamp,
        "Docmost runtime fingerprint must cover both launchers and publish atomically",
    )

    auth_wrapper = DOCMOST_AUTH_WRAPPER.read_text()
    for expected in (
        'GENERATION_ROOT="$(cd "$GENERATION_ENVS/.." && pwd)"',
        'DOCMOST_RUNTIME_LOCK="$RUNTIME_ROOT/bin/docmost-runtime-lock"',
        'REQUIRED_SESSION_MODE=shared',
        'REQUIRED_SESSION_MODE=exclusive',
        '--kind session --mode "$REQUIRED_SESSION_MODE"',
        '--kind generation --mode shared',
        '--validate-fd',
        'exec "$DOCMOST_AUTH_INTERNAL" "$@"',
    ):
        require(expected in auth_wrapper, f"Docmost auth wrapper must include {expected}")
    require(
        "uv run" not in auth_wrapper and "setup-docmost-tools.sh" not in auth_wrapper,
        "Docmost auth wrapper must execute its immutable generation directly",
    )
    server_source = (DOCMOST_DIR / "server" / "src" / "docmost_tools" / "server.py").read_text()
    require(
        "signal.SIGTERM" in server_source
        and "_GracefulTermination" in server_source
        and "runtime.close()" in server_source,
        "Docmost server must unwind runtime cleanup on SIGTERM",
    )

    marketplace_entry = next(
        (entry for entry in marketplace.get("plugins", []) if entry.get("name") == "docmost-tools"),
        None,
    )
    require(marketplace_entry is not None, "marketplace must include docmost-tools")
    require(
        marketplace_entry.get("source") == {"source": "local", "path": "./plugins/docmost-tools"}
        and marketplace_entry.get("policy") == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "docmost marketplace metadata must remain local and install-authenticated",
    )
    require("docmost-tools" in default_plugins, "setup script must refresh docmost-tools by default")
    require("docmost" in managed_mcp_servers, "setup script must manage the docmost MCP migration")
    require(
        'docmost_setup_command "$server_dir" --install' in script
        and 'docmost_setup_command "$server_dir" --status' in script
        and 'docmost_setup_command "$server_dir" --login' in script
        and 'ensure_docmost_ready ""' in script
        and 'ensure_docmost_ready "$DOCMOST_INSTALLED_SERVER_DIR"' in script,
        "toolbox setup must run the Docmost install/status/login sequence",
    )
    installed_blocks = shell_function_blocks(script, "installed_docmost_server_dir")
    require(len(installed_blocks) == 1, "toolbox setup must resolve one installed Docmost distribution")
    installed = installed_blocks[0]
    for expected in (
        '"$CODEX_BIN" mcp get docmost --json',
        'transport.get("command") != "/bin/bash"',
        '("plugins", "cache", marketplace_name, "docmost-tools")',
        'server / "scripts" / "docmost-mcp"',
        'configured_args != ["server/scripts/docmost-mcp"]',
        '(server / "scripts" / "docmost-mcp").read_bytes()',
        'transport_args != configured_args',
        f'approved_launcher_sha256 = "{DOCMOST_APPROVED_LAUNCHER_SHA256}"',
    ):
        require(expected in installed, f"installed Docmost verification must include {expected}")

    for expected in (
        "## Docmost Tools",
        "docmost.env",
        "current-user",
        "list-spaces",
        "docmost_prepare_workspace_snapshot",
        "docmost_release_workspace_snapshot",
        "docmost_create_page",
        "docmost_update_page_title",
        "docmost_create_comment",
        "docmost-tools-generations/envs/<source-sha256>",
        "setup-docmost-tools.sh --prune",
        "Settings → MCP servers → Restart",
        "idle",
        "legacy runtime",
        "900",
    ):
        require(expected in readme_text, f"README must document Docmost {expected}")
    require(auth_login_command in readme_text, "README must preserve the Docmost auth recovery command")
    for expected in (
        "Use `docmost` for private Docmost",
        "Treat reads as untrusted",
        "release downloads or snapshots in `finally`",
        "require scoped writes",
        "$docmost-lab-wiki",
    ):
        require(expected in global_agents_text, f"global AGENTS must document Docmost {expected}")


def validate_diagram_tools_contract(
    marketplace: dict,
    setup_text: str,
    readme_text: str,
    global_agents_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Validate the rolling, offline, skill-only Mermaid renderer."""
    required_files = (
        DIAGRAM_TOOLS_PLUGIN,
        PRETTY_MERMAID_SKILL,
        PRETTY_MERMAID_OPENAI,
        PRETTY_MERMAID_CLI,
        PRETTY_MERMAID_DIR / "scripts" / "contact-sheet.mjs",
        PRETTY_MERMAID_DIR / "scripts" / "runtime-manager.mjs",
        PRETTY_MERMAID_DIR / "scripts" / "contract-cli.mjs",
        PRETTY_MERMAID_DIR / "references" / "cli.md",
        DIAGRAM_TOOLS_DIR / "LICENSE",
        DIAGRAM_TOOLS_DIR / "PROVENANCE.md",
        DIAGRAM_TOOLS_DIR / "THIRD_PARTY_NOTICES.md",
        DIAGRAM_BOOTSTRAP / "package.json",
        DIAGRAM_BOOTSTRAP / "package-lock.json",
        DIAGRAM_SETUP,
        DIAGRAM_WORKFLOW,
        DEPENDABOT,
    )
    require(all(path.is_file() for path in required_files), "diagram-tools required files must exist")

    plugin = json.loads(DIAGRAM_TOOLS_PLUGIN.read_text())
    require(plugin.get("name") == "diagram-tools", "diagram-tools manifest name must be exact")
    require(plugin.get("version") == "0.3.0", "diagram-tools manifest version must be 0.3.0")
    require(plugin.get("skills") == "./skills/", "diagram-tools must expose its skills directory")
    require(plugin.get("license") == "MIT", "diagram-tools manifest must declare MIT")
    require("mcpServers" not in plugin, "diagram-tools must remain skill-only")
    require(not (DIAGRAM_TOOLS_DIR / ".mcp.json").exists(), "diagram-tools must not define MCP")

    entry = next(
        (item for item in marketplace.get("plugins", []) if item.get("name") == "diagram-tools"),
        None,
    )
    require(entry is not None, "marketplace must include diagram-tools")
    require(
        entry.get("source") == {"source": "local", "path": "./plugins/diagram-tools"},
        "diagram-tools marketplace source must be local",
    )
    require(
        entry.get("policy") == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "diagram-tools marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require(default_plugins.count("diagram-tools") == 1, "setup must install diagram-tools once")
    require(
        "diagram-tools" not in managed_mcp_servers,
        "diagram-tools must not be a managed MCP server",
    )
    require(
        '"$ROOT/scripts/setup-diagram-tools.sh" --update' in setup_text,
        "full toolbox setup must update the contract-gated diagram runtime",
    )
    require(DIAGRAM_SETUP.stat().st_mode & 0o111, "diagram setup helper must be executable")
    diagram_setup_text = DIAGRAM_SETUP.read_text()
    for expected in (
        "CODEX_LOCAL_BIN_DIR",
        "PRETTY_MERMAID_LAUNCHER",
        "Refusing to replace non-symlink launcher",
        "NODE_MAJOR",
    ):
        require(expected in diagram_setup_text, f"diagram setup launcher must preserve {expected}")

    skill_text = PRETTY_MERMAID_SKILL.read_text()
    require("[TODO:" not in skill_text, "pretty-mermaid skill must not contain placeholders")
    for expected in (
        "name: pretty-mermaid",
        "self-contained SVG",
        "genuine PNG",
        "Use this skill by default whenever Mermaid is selected",
        "task-scoped temporary directory with `mktemp -d`",
        "native inline Mermaid only",
        "reuse the exact source",
        "Do not install packages during an ordinary render",
        "$drawio",
        "$paper-figure-workflow",
        "references/cli.md",
    ):
        require(expected in skill_text, f"pretty-mermaid skill must mention {expected}")
    openai_text = PRETTY_MERMAID_OPENAI.read_text()
    require(
        'display_name: "Pretty Mermaid"' in openai_text
        and "Use $pretty-mermaid by default" in openai_text,
        "pretty-mermaid OpenAI metadata must match the skill",
    )

    fixture_manifest = json.loads((PRETTY_MERMAID_FIXTURES / "manifest.json").read_text())
    expected_fixtures = {"flowchart.mmd", "state.mmd", "sequence.mmd", "class.mmd", "er.mmd", "xy.mmd"}
    actual_fixtures = {item.get("file") for item in fixture_manifest.get("fixtures", [])}
    require(actual_fixtures == expected_fixtures, "pretty-mermaid core fixture inventory must be exact")
    require(
        all((PRETTY_MERMAID_FIXTURES / name).is_file() for name in expected_fixtures),
        "pretty-mermaid fixture files must exist",
    )

    bootstrap_package = json.loads((DIAGRAM_BOOTSTRAP / "package.json").read_text())
    bootstrap_lock = json.loads((DIAGRAM_BOOTSTRAP / "package-lock.json").read_text())
    dependencies = bootstrap_package.get("dependencies", {})
    fallback_version = dependencies.get("beautiful-mermaid")
    locked_fallback = bootstrap_lock.get("packages", {}).get("node_modules/beautiful-mermaid", {})
    require(
        re.fullmatch(r"\d+\.\d+\.\d+", fallback_version or "") is not None,
        "diagram fallback must be one exact stable release",
    )
    require(
        locked_fallback.get("version") == fallback_version
        and str(locked_fallback.get("integrity", "")).startswith("sha512-"),
        "diagram fallback lock must match its approved version and integrity",
    )
    require(
        all(
            isinstance(value, str)
            and not any(marker in value for marker in ("^", "~", "*", "latest"))
            for value in dependencies.values()
        ),
        "diagram bootstrap dependencies must be exact installation receipts",
    )
    script_text = "\n".join(
        path.read_text()
        for path in (PRETTY_MERMAID_DIR / "scripts").rglob("*.mjs")
    )
    require(
        fallback_version not in script_text,
        "Beautiful Mermaid fallback version must not appear in adapter or runtime logic",
    )
    for expected in (
        "renderMermaidSVG",
        "renderMermaidSVGAsync",
        "renderMermaidASCII",
        "renderMermaidAscii",
        "THEMES",
        "color-mix",
        "@import",
        "active.json",
        "previous.json",
        "--ignore-scripts",
        "--audit-level=high",
    ):
        require(expected in script_text, f"diagram runtime must preserve {expected} handling")

    for expected in (
        "## Diagram Tools",
        "the default renderer",
        "task-scoped temporary directory",
        "contract-gated rolling runtime",
        "Normal rendering is offline",
    ):
        require(expected in readme_text, f"README Diagram Tools section must mention {expected}")
    for expected in (
        "$pretty-mermaid` by default whenever Mermaid is the chosen format",
        "task-scoped temporary directory",
        "native inline Mermaid only",
        "$drawio",
        "$paper-figure-workflow",
    ):
        require(expected in global_agents_text, f"global AGENTS diagram routing must mention {expected}")
    for retired in (
        "Use native Mermaid for quick response diagrams",
        "Static relationships, hierarchy, or sequence: inline Mermaid",
    ):
        require(retired not in global_agents_text, f"global AGENTS must remove retired routing: {retired}")
    require(
        "Do not install packages during an ordinary render" in PRETTY_MERMAID_SKILL.read_text(),
        "pretty-mermaid skill must own the offline runtime contract",
    )
    require(
        "beautiful-mermaid" in DEPENDABOT.read_text()
        and "plugins/diagram-tools/runtime/bootstrap" in DEPENDABOT.read_text(),
        "Dependabot must advance only the approved diagram fallback",
    )
    workflow_text = DIAGRAM_WORKFLOW.read_text()
    for expected in (
        "ubuntu-latest",
        "macos-latest",
        "test:contract",
        "--update --strict",
        "contact-sheet.mjs",
        "SVG and PNG contact sheets",
        "upload-artifact",
    ):
        require(expected in workflow_text, f"diagram CI must include {expected}")


def validate_drawio_tools_contract(
    marketplace: dict,
    setup_text: str,
    readme_text: str,
    global_agents_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Validate the pinned official Draw.io MCP and optional Desktop lane."""
    required_files = (
        DRAWIO_TOOLS_PLUGIN,
        DRAWIO_TOOLS_MCP,
        DRAWIO_SKILL,
        DRAWIO_OPENAI,
        DRAWIO_SKILL_DIR / "references" / "cli.md",
        DRAWIO_LAUNCHER,
        DRAWIO_VERIFIER,
        DRAWIO_DESKTOP,
        DRAWIO_FIXTURE,
        DRAWIO_MCP_SMOKE,
        DRAWIO_BOOTSTRAP / "package.json",
        DRAWIO_BOOTSTRAP / "package-lock.json",
        DRAWIO_TOOLS_DIR / "LICENSE",
        DRAWIO_TOOLS_DIR / "PROVENANCE.md",
        DRAWIO_TOOLS_DIR / "THIRD_PARTY_NOTICES.md",
        DRAWIO_SETUP,
        DRAWIO_WORKFLOW,
        DRAWIO_TEST,
    )
    require(all(path.is_file() for path in required_files), "drawio-tools required files must exist")
    for executable in (DRAWIO_LAUNCHER, DRAWIO_VERIFIER, DRAWIO_DESKTOP, DRAWIO_MCP_SMOKE, DRAWIO_SETUP):
        require(executable.stat().st_mode & 0o111, f"{executable.name} must be executable")

    plugin = json.loads(DRAWIO_TOOLS_PLUGIN.read_text())
    require(plugin.get("name") == "drawio-tools", "drawio-tools manifest name must be exact")
    require(plugin.get("version") == "0.1.0", "drawio-tools manifest version must be 0.1.0")
    require(plugin.get("skills") == "./skills/", "drawio-tools must expose its skill")
    require(plugin.get("mcpServers") == "./.mcp.json", "drawio-tools must expose its MCP config")
    require(plugin.get("license") == "MIT", "drawio-tools must declare its toolbox license")
    require(
        set(plugin.get("interface", {}).get("capabilities", [])) == {"Read", "Write", "Interactive"},
        "drawio-tools capabilities must reflect local reads, writes, and browser interaction",
    )

    entry = next(
        (item for item in marketplace.get("plugins", []) if item.get("name") == "drawio-tools"),
        None,
    )
    require(entry is not None, "marketplace must include drawio-tools")
    require(
        entry.get("source") == {"source": "local", "path": "./plugins/drawio-tools"},
        "drawio-tools marketplace source must be local",
    )
    require(
        entry.get("policy") == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "drawio-tools marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require(default_plugins.count("drawio-tools") == 1, "setup must install drawio-tools once")
    require(managed_mcp_servers.count("drawio") == 1, "setup must remove one stale direct drawio MCP override")

    mcp = json.loads(DRAWIO_TOOLS_MCP.read_text())
    servers = mcp.get("mcpServers", {})
    require(set(servers) == {"drawio"}, "drawio-tools must expose only the drawio MCP server")
    server = servers.get("drawio", {})
    expected_tools = [
        "open_drawio_xml",
        "open_drawio_csv",
        "open_drawio_mermaid",
        "search_shapes",
        "list_pages",
        "get_page",
        "set_page",
    ]
    require(
        server.get("enabled") is True
        and server.get("command") == "/bin/zsh"
        and server.get("args") == ["scripts/run-drawio-mcp.sh"]
        and server.get("cwd") == ".",
        "drawio MCP must launch the bundled verified runtime wrapper",
    )
    require(server.get("enabled_tools") == expected_tools, "drawio MCP tool allowlist must be exact")
    require(
        server.get("env_vars") == ["CODEX_HOME", "CODEX_LOCAL_BIN_DIR", "DRAWIO_BASE_URL"],
        "drawio MCP must forward only its approved runtime and editor settings",
    )
    require(
        server.get("default_tools_approval_mode") == "auto"
        and server.get("tools") == {"set_page": {"approval_mode": "prompt"}},
        "drawio MCP must prompt only for set_page",
    )
    require("disabled_tools" not in server, "drawio MCP must use one positive tool allowlist")

    bootstrap = json.loads((DRAWIO_BOOTSTRAP / "package.json").read_text())
    lock = json.loads((DRAWIO_BOOTSTRAP / "package-lock.json").read_text())
    dependencies = bootstrap.get("dependencies", {})
    locked_package = lock.get("packages", {}).get("node_modules/@drawio/mcp", {})
    expected_integrity = (
        "sha512-DRg8oveMZSN5rgH6TAtkfaGSm364GzJV53uqJE9ug4EYCORjCgEpapFr0XLi037kq2OXdM2Z/"
        "vgAyj7N6vbjiA=="
    )
    require(dependencies == {"@drawio/mcp": "1.4.0"}, "Draw.io runtime must pin one exact direct dependency")
    require(
        lock.get("packages", {}).get("", {}).get("dependencies") == dependencies,
        "Draw.io bootstrap lock root must match package.json",
    )
    require(
        locked_package.get("version") == "1.4.0"
        and locked_package.get("integrity") == expected_integrity,
        "Draw.io runtime lock must preserve the audited 1.4.0 package integrity",
    )

    setup_helper = DRAWIO_SETUP.read_text()
    for expected in (
        'PACKAGE_VERSION="1.4.0"',
        expected_integrity,
        'PACKAGE_TREE_SHA256="9b8fed587fd1bc61041c4a57ec536ad653673e8f413141d7ff6ef0b03754ac6d"',
        'SHAPE_INDEX_COMMIT="9ce8dc19caa8861315337ec91f3ac7c0df8e0978"',
        'SHAPE_INDEX_SHA256="09b84516025e46238e5dd47465cc96ecfd96134ea853ace1063e1ca19dd34601"',
        'SHAPE_INDEX_BYTES="4776086"',
        'SHAPE_INDEX_ENTRIES="10446"',
        "--ignore-scripts",
        "--audit-level=high",
        "--with-desktop",
        "install --cask drawio",
        "mktemp -d",
        "mv \"$candidate\" \"$ACTIVE_DIR\"",
    ):
        require(expected in setup_helper, f"Draw.io setup must preserve {expected}")
    for expected in (
        '  "drawio-tools"',
        '  "drawio"',
        'CODEX_TOOLBOX_INSTALL_DRAWIO_DESKTOP',
        '"$ROOT/scripts/setup-drawio-tools.sh" "${DRAWIO_SETUP_ARGS[@]}"',
    ):
        require(expected in setup_text, f"full setup must integrate Draw.io via {expected}")

    launcher_text = DRAWIO_LAUNCHER.read_text()
    for expected in (
        "verify-drawio-runtime.mjs",
        "DRAWIO_SHAPE_INDEX_URL",
        "invalid.invalid/drawio-tools-offline-index",
        "node_modules/@drawio/mcp/src/index.js",
    ):
        require(expected in launcher_text, f"Draw.io MCP launcher must preserve {expected}")
    verifier_text = DRAWIO_VERIFIER.read_text()
    for expected in (
        "packageIntegrity",
        "packageTreeSha256",
        "lockSha256",
        "shapeIndexSha256",
        "shapeIndexEntries",
        "routing-core-cache.js",
        "libavoid.wasm",
        "postinstall",
    ):
        require(expected in verifier_text, f"Draw.io runtime verifier must preserve {expected}")
    desktop_text = DRAWIO_DESKTOP.read_text()
    for expected in (
        "DRAWIO_DESKTOP_BIN",
        "/Applications/draw.io.app/Contents/MacOS/draw.io",
        "-x -f",
        '"$drawio_bin" -x -f "$format" -e -b 10 -o "$output" "$input"',
        "png|svg|pdf",
    ):
        require(expected in desktop_text, f"Draw.io Desktop helper must preserve {expected}")

    skill_text = DRAWIO_SKILL.read_text()
    for expected in (
        "name: drawio",
        "editable .drawio source",
        "list_pages",
        "get_page",
        "set_page",
        "search_shapes",
        "task-scoped temporary directory with `mktemp -d`",
        "retain the `.drawio` source",
        "Do not send diagram contents to a cloud rasterization service",
        "DRAWIO_DESKTOP_BIN",
        "$paper-figure-workflow",
        "references/cli.md",
    ):
        require(expected in skill_text, f"drawio skill must mention {expected}")
    openai_text = DRAWIO_OPENAI.read_text()
    for expected in (
        'display_name: "Draw.io"',
        "Use $drawio",
        'allow_implicit_invocation: true',
        'value: "drawio"',
    ):
        require(expected in openai_text, f"drawio OpenAI metadata must mention {expected}")

    pretty_text = PRETTY_MERMAID_SKILL.read_text()
    paper_text = PAPER_FIGURE_SKILL.read_text()
    require(
        "$drawio" in pretty_text and "Pretty Mermaid" in skill_text,
        "Pretty Mermaid and Draw.io skills must preserve their routing boundary",
    )
    require(
        "$drawio" in paper_text and "publication" in paper_text,
        "paper-figure-workflow must delegate Draw.io execution without giving up pipeline ownership",
    )
    require(
        json.loads(DIAGRAM_TOOLS_PLUGIN.read_text()).get("version") == "0.3.0",
        "diagram-tools version must reflect the Draw.io routing boundary",
    )
    require(
        json.loads(PAPER_FIGURE_PLUGIN.read_text()).get("version") == "0.2.0",
        "paper-figure-tools version must reflect Draw.io execution delegation",
    )

    for expected in (
        "## Draw.io Tools",
        "@drawio/mcp@1.4.0",
        "CODEX_TOOLBOX_INSTALL_DRAWIO_DESKTOP=1",
        "DRAWIO_BASE_URL",
        "DRAWIO_DESKTOP_BIN",
        "cloud rasterization",
        "task-scoped temporary directory",
    ):
        require(expected in readme_text, f"README Draw.io section must mention {expected}")
    for expected in (
        "Use `$drawio` for explicit editable, multi-page, browser, or exported draw.io work",
        "`$paper-figure-workflow` owns publication pipelines",
    ):
        require(expected in global_agents_text, f"global AGENTS Draw.io routing must mention {expected}")

    workflow_text = DRAWIO_WORKFLOW.read_text()
    for expected in (
        "ubuntu-latest",
        "macos-latest",
        "scripts/setup-drawio-tools.sh --install",
        "scripts/setup-drawio-tools.sh --check",
        "mcp-smoke.mjs",
        "test_drawio_tools",
    ):
        require(expected in workflow_text, f"Draw.io CI must include {expected}")
    dependabot_text = DEPENDABOT.read_text()
    require(
        "/plugins/drawio-tools/runtime/bootstrap" in dependabot_text
        and 'dependency-name: "@drawio/mcp"' in dependabot_text,
        "Dependabot must track only the approved Draw.io direct dependency",
    )


def main() -> None:
    script = SETUP_SCRIPT.read_text()
    readme_text = README.read_text()
    readme_normalized = " ".join(readme_text.split())
    require(
        DAILY_COMMAND_CENTER_SKILL.exists(),
        "productivity-tools must include daily-command-center skill",
    )
    require(
        DAILY_COMMAND_CENTER_OPENAI.exists(),
        "daily-command-center must include OpenAI agent metadata",
    )
    require(GLOBAL_AGENTS.exists(), "canonical global AGENTS file must exist")
    require(
        GLOBAL_AGENTS.read_text().startswith("## Response style\n"),
        "canonical global AGENTS file must start with response style",
    )
    require(REPO_AGENTS.exists(), "toolbox repository must include repository-level AGENTS.md")
    global_agents_text = GLOBAL_AGENTS.read_text()
    global_agents_normalized = " ".join(global_agents_text.split())
    repo_agents_text = REPO_AGENTS.read_text()
    require(
        len(GLOBAL_AGENTS.read_bytes()) <= 8_192,
        "canonical global AGENTS file must fit within the 8 KiB budget",
    )
    require(
        len(GLOBAL_AGENTS.read_bytes()) + len(REPO_AGENTS.read_bytes()) <= 16_384,
        "combined global and toolbox AGENTS files must fit within the 16 KiB budget",
    )
    require(
        "Lead with the result. Write in a concise, factual, newspaper style"
        in global_agents_text,
        "global AGENTS must preserve the configured response style",
    )
    for expected in (
        "native subagents for independent testable subtasks",
        "OpenSpec when durable requirements",
        "Plan mode",
        "without implementing it",
    ):
        require(expected in global_agents_text, f"global AGENTS routing must mention {expected}")
    for expected in (
        "One conclusion or simple procedure",
        "Three or more comparable entities",
        "`$pretty-mermaid` by default",
        "native inline Mermaid only",
        "bundled Visualize",
        "standalone or hosted application",
        "A visual is presentation, not evidence",
        "side to move",
        "move legality",
        "report ambiguity instead of inventing pieces",
        "Do not use generative image models for exact factual diagrams",
        "CLI or IDE surfaces",
    ):
        require(expected in global_agents_text, f"global AGENTS visual routing must mention {expected}")
    require(COMMUNITY_RESEARCH_SKILL.exists(), "web-data-tools must include community-research")
    require(
        COMMUNITY_RESEARCH_OPENAI.exists(),
        "community-research must include OpenAI agent metadata",
    )
    community_research_text = COMMUNITY_RESEARCH_SKILL.read_text()
    community_research_normalized = " ".join(community_research_text.split())
    for expected in (
        "built-in Codex web search for ordinary public discovery",
        "`$community-research`",
        "public community or forum discussions",
        "user reports",
        "sentiment",
        "community troubleshooting",
        "official or canonical corroboration",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS community dispatch must mention {expected}",
        )
    for expected in (
        "known public thread URL",
        "exactly one web source",
        "highlights",
        "no `scrapeOptions`",
        "result limit of 5 or less",
        "no more than two selected threads",
        "fixed 900-credit billing-period cap",
        "`firecrawl_budget_status`",
        "Markdown-only `firecrawl_scrape`",
        "community coverage is degraded",
        "separate connected Firecrawl app",
        "private local files",
        "FIRECRAWL_BUDGET_EXHAUSTED",
        "FIRECRAWL_BUDGET_UNAVAILABLE",
        "FIRECRAWL_REQUEST_NOT_BOUNDED",
    ):
        require(
            expected in community_research_normalized,
            f"community-research must own bounded routing detail {expected}",
        )
    community_openai_text = COMMUNITY_RESEARCH_OPENAI.read_text()
    require(
        "allow_implicit_invocation: true" in community_openai_text,
        "community-research must allow implicit invocation",
    )
    for retired_promise in (
        "Every map or crawl must have an explicit page limit",
        "Use Firecrawl Interact or Agent",
        "After using `firecrawl_search`, call the Firecrawl feedback tool",
    ):
        require(
            retired_promise not in global_agents_text
            and retired_promise not in community_research_text,
            f"routing contracts must remove retired Firecrawl promise {retired_promise}",
        )
    for expected in (
        "$mineru-document-extraction",
        "$paper-library-intake",
        "$paper-review-sync",
        "$paper-review-library-intake",
        "$paper-review-page",
        "$zotero-todoist-reading-tasks",
        "$todoist-task-planning",
        "$daily-command-center",
        "$paper-figure-workflow",
        "$pretty-mermaid",
        "$drawio",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS must dispatch to owning skill {expected}",
        )
    for expected in (
        "$deep-planning",
        "adversarial, architectural, or high-risk planning",
        "OpenSpec",
    ):
        require(expected in global_agents_text, f"global AGENTS deep planning must mention {expected}")
    for expected in (
        "$explain-clearly",
        "why/how",
        "code walkthrough",
        "execution-only",
    ):
        require(
            expected in global_agents_text,
            f"global AGENTS explanation routing must mention {expected}",
        )
    require("Superpowers" not in global_agents_text, "global AGENTS must not route through Superpowers")
    require("superpowers:" not in global_agents_text, "global AGENTS must not invoke Superpowers skills")
    require("Superpowers" not in readme_text, "README must not document Superpowers routing")
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
    require(SETUP_PREREQUISITES.exists(), "setup must include the prerequisite helper")
    prerequisites_text = SETUP_PREREQUISITES.read_text()
    for expected in (
        "legacy-skills --install",
        "ensure-rg --install",
        "resolve-codex",
    ):
        require(expected in script, f"setup script must run prerequisite step {expected}")
    for expected in (
        '"chronicle"',
        '"defuddle"',
        '"json-canvas"',
        '"obsidian-bases"',
        '"obsidian-cli"',
        '"obsidian-markdown"',
        '"playwright"',
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        "/Applications/Codex.app/Contents/Resources/codex",
        '"install", "ripgrep"',
        "CODEX_LOCAL_BIN_DIR",
        "Refusing to modify legacy skills",
    ):
        require(expected in prerequisites_text, f"setup prerequisites must preserve {expected}")
    require(
        '"hatch-pet"' not in prerequisites_text.split("CHATGPT_CODEX", 1)[0],
        "setup prerequisite migration must not manage hatch-pet",
    )
    for expected in (
        "seven known duplicate user-skill links",
        ".cc-switch/skills",
        "preserves their targets and `hatch-pet`",
        "working `rg` through Homebrew",
        "`PATH`, the current ChatGPT app, then the legacy",
        "setup-codex-prerequisites.py legacy-skills --check",
        "setup-codex-prerequisites.py ensure-rg --check",
        "setup-codex-prerequisites.py resolve-codex",
    ):
        require(expected in readme_normalized, f"README setup prerequisites must mention {expected}")
    for expected in (
        "8 KiB budget",
        "below 16 KiB",
        "owning skills",
    ):
        require(expected in readme_normalized, f"README AGENTS ownership must mention {expected}")
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
    for path in (
        DOCMOST_LAB_WIKI_SKILL,
        DOCMOST_LAB_WIKI_OPENAI,
        DOCMOST_LAB_WIKI_COMMANDS,
        DOCMOST_LAB_WIKI_PYPROJECT,
        DOCMOST_LAB_WIKI_LOCK,
        DOCMOST_LAB_WIKI_CONSTANTS,
        DOCMOST_LAB_WIKI_CLI,
        DOCMOST_LAB_WIKI_WIKI,
        DOCMOST_LAB_WIKI_INDEX,
        DOCMOST_LAB_WIKI_TEST,
        DOCMOST_LAB_WIKI_SETUP,
        DOCMOST_LAB_WIKI_RUNNER,
    ):
        require(path.is_file(), f"Docmost Lab Wiki required file is missing: {path.name}")
    for executable in (DOCMOST_LAB_WIKI_SETUP, DOCMOST_LAB_WIKI_RUNNER):
        require(executable.stat().st_mode & 0o111, f"{executable.name} must be executable")
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
        ZOTERO_TODOIST_READING_TASKS_SKILL.exists(),
        "research-tools must include zotero-todoist-reading-tasks skill",
    )
    require(
        ZOTERO_TODOIST_READING_TASKS_OPENAI.exists(),
        "zotero-todoist-reading-tasks must include OpenAI agent metadata",
    )
    require(
        PAPER_LIBRARY_ATTACHMENT.exists(),
        "paper-library-intake must include the WebDAV attachment helper",
    )
    for path, message in (
        (PAPER_REVIEW_LIBRARY_INTAKE_SKILL, "research-tools must include paper-review-library-intake"),
        (PAPER_REVIEW_LIBRARY_INTAKE_OPENAI, "paper-review-library-intake must include OpenAI metadata"),
        (PAPER_REVIEW_PAGE_SKILL, "research-tools must include paper-review-page"),
        (PAPER_REVIEW_PAGE_OPENAI, "paper-review-page must include OpenAI metadata"),
        (PAPER_REVIEW_CONFERENCE_TEMPLATE, "paper-review-page must include a conference fallback"),
        (PAPER_REVIEW_JOURNAL_TEMPLATE, "paper-review-page must include a journal fallback"),
        (PAPER_REVIEW_PAGE_STRUCTURE, "paper-review-page must include its structure helper"),
        (PAPER_REVIEW_SYNC_SKILL, "research-tools must include paper-review-sync"),
        (PAPER_REVIEW_SYNC_OPENAI, "paper-review-sync must include OpenAI metadata"),
        (PAPER_REVIEW_SYNC_CONTRACT, "paper-review-sync must include its contract helper"),
    ):
        require(path.exists(), message)
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
    require(
        PAPER_READ_DRAFT_FILENAME.exists(),
        "paper-read-draft must include its deterministic filename helper",
    )
    require(
        PAPER_READ_REVIEW_SKILL.exists(),
        "research-tools must include paper-read-review skill",
    )
    require(
        PAPER_READ_REVIEW_OPENAI.exists(),
        "paper-read-review must include OpenAI agent metadata",
    )
    require(WEB_DATA_PLUGIN.exists(), "web-data-tools plugin manifest must exist")
    require(WEB_DATA_MCP.exists(), "web-data-tools must define an MCP config")
    require(FIRECRAWL_LAUNCHER.exists(), "web-data-tools must include the Firecrawl launcher")
    require(FIRECRAWL_PROXY.exists(), "web-data-tools must include the Firecrawl budget proxy")
    require(OBSIDIAN_MCP.exists(), "obsidian-tools must define an MCP config")
    require(CODER_PLUGIN.exists(), "coder-tools plugin manifest must exist")
    require(CODER_MCP.exists(), "coder-tools must define an MCP config")
    require(WORKFLOW_PLUGIN.exists(), "workflow-tools plugin manifest must exist")
    require(DEEP_PLANNING_SKILL.exists(), "workflow-tools must include deep-planning skill")
    require(DEEP_PLANNING_OPENAI.exists(), "deep-planning must include OpenAI agent metadata")
    require(EXPLAIN_CLEARLY_SKILL.exists(), "workflow-tools must include explain-clearly skill")
    require(
        EXPLAIN_CLEARLY_OPENAI.exists(),
        "explain-clearly must include OpenAI agent metadata",
    )
    require(SHIP_TOOLBOX_SKILL.exists(), "workflow-tools must include ship-toolbox skill")
    require(
        SHIP_TOOLBOX_OPENAI.exists(),
        "ship-toolbox must include OpenAI agent metadata",
    )
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
    web_data_plugin = json.loads(WEB_DATA_PLUGIN.read_text())
    web_data_mcp = json.loads(WEB_DATA_MCP.read_text())
    obsidian_mcp = json.loads(OBSIDIAN_MCP.read_text())
    game_asset_plugin = json.loads(GAME_ASSET_PLUGIN.read_text())
    game_asset_mcp = json.loads(GAME_ASSET_MCP.read_text())
    research_plugin = json.loads(RESEARCH_PLUGIN.read_text())
    research_mcp = json.loads(RESEARCH_MCP.read_text())
    coder_plugin = json.loads(CODER_PLUGIN.read_text())
    coder_mcp = json.loads(CODER_MCP.read_text())
    workflow_plugin = json.loads(WORKFLOW_PLUGIN.read_text())
    paper_figure_plugin = json.loads(PAPER_FIGURE_PLUGIN.read_text())
    productivity_plugin = json.loads(PRODUCTIVITY_PLUGIN.read_text())
    productivity_mcp = json.loads(PRODUCTIVITY_MCP.read_text())
    trading_mcp = json.loads(TRADING_MCP.read_text())
    default_plugins = array_body(script, "DEFAULT_PLUGINS")
    default_plugin_entries = shell_array_entries(script, "DEFAULT_PLUGINS")
    managed_mcp_servers = array_body(script, "MANAGED_MCP_SERVERS")
    managed_mcp_server_entries = shell_array_entries(script, "MANAGED_MCP_SERVERS")
    pixellab_server = game_asset_mcp.get("mcpServers", {}).get("pixellab")
    robinhood_server = trading_mcp.get("mcpServers", {}).get("robinhood-trading")
    todoist_server = productivity_mcp.get("mcpServers", {}).get("todoist")
    coder_server = coder_mcp.get("mcpServers", {}).get("coder")
    obsidian_files_server = obsidian_mcp.get("mcpServers", {}).get("obsidian_files")

    require(web_data_plugin.get("name") == "web-data-tools", "web-data-tools name must be exact")
    require(web_data_plugin.get("version") == "0.5.0", "web-data-tools must use version 0.5.0")
    require(
        web_data_plugin.get("skills") == "./skills/",
        "web-data-tools manifest must expose its community-research skill",
    )
    require(
        web_data_plugin.get("mcpServers") == "./.mcp.json",
        "web-data-tools manifest must register its MCP config",
    )
    firecrawl_servers = web_data_mcp.get("mcpServers", {})
    require(
        set(firecrawl_servers) == {"firecrawl"},
        "web-data-tools MCP config must expose only the Firecrawl server",
    )
    firecrawl_server = firecrawl_servers.get("firecrawl", {})
    require(
        firecrawl_server.get("command") == "/bin/sh"
        and firecrawl_server.get("args") == ["scripts/run-firecrawl-mcp.sh", "serve"]
        and firecrawl_server.get("cwd") == ".",
        "Firecrawl MCP must launch the bundled metering proxy from the plugin root",
    )
    require(
        {"CODEX_HOME", "CODEX_SECRETS_DIR"}.issubset(
            set(firecrawl_server.get("env_vars", []))
        ),
        "Firecrawl MCP must forward only the paths needed for private state and secrets",
    )
    firecrawl_mcp_text = WEB_DATA_MCP.read_text()
    for forbidden in ("disabled_tools", "firecrawl_search_feedback", "firecrawl_feedback"):
        require(
            forbidden not in firecrawl_mcp_text,
            f"Firecrawl MCP config must not rely on the legacy direct surface: {forbidden}",
        )
    require(
        FIRECRAWL_LAUNCHER.stat().st_mode & 0o111,
        "Firecrawl launcher must be executable",
    )
    firecrawl_launcher_text = FIRECRAWL_LAUNCHER.read_text()
    for expected in (
        "firecrawl.env",
        "firecrawl_budget_proxy.py",
        "serve",
        "status",
        "600",
    ):
        require(expected in firecrawl_launcher_text, f"Firecrawl launcher must preserve {expected}")
    firecrawl_proxy_text = FIRECRAWL_PROXY.read_text()
    for expected in (
        "BUDGET_CAP_CREDITS = 900",
        'STATE_FILENAME = "firecrawl-budget.json"',
        "firecrawl_search",
        "firecrawl_scrape",
        "firecrawl_budget_status",
        "FIRECRAWL_BUDGET_EXHAUSTED",
        "FIRECRAWL_BUDGET_UNAVAILABLE",
        "FIRECRAWL_REQUEST_NOT_BOUNDED",
        "BOUNDED_SERVER_INSTRUCTIONS",
        "sanitize_initialize_result",
        "/v2/team/credit-usage",
    ):
        require(expected in firecrawl_proxy_text, f"Firecrawl budget proxy must preserve {expected}")

    validate_docmost_tools_contract(
        marketplace,
        script,
        readme_text,
        global_agents_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )
    validate_apple_mail_tools_contract(
        marketplace,
        script,
        readme_text,
        global_agents_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )

    validate_stevens_presentation_tools_contract(
        marketplace,
        readme_text,
        default_plugins,
    )
    validate_design_engineering_tools_contract(
        marketplace,
        global_agents_text,
        readme_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )
    validate_google_workspace_tools_contract(
        marketplace,
        global_agents_text,
        readme_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )
    validate_diagram_tools_contract(
        marketplace,
        script,
        readme_text,
        global_agents_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )
    validate_drawio_tools_contract(
        marketplace,
        script,
        readme_text,
        global_agents_text,
        default_plugin_entries,
        managed_mcp_server_entries,
    )

    require(obsidian_files_server is not None, "obsidian-tools must define obsidian_files")
    require(
        "CODEX_OBSIDIAN_VAULT" in obsidian_files_server.get("env_vars", []),
        "obsidian_files must forward CODEX_OBSIDIAN_VAULT to its STDIO server",
    )

    retired_tracker_mentions = scan_retired_tracker_mentions(
        ROOT,
        Path(__file__),
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
        "## Firecrawl Routing and Budget",
        "$community-research",
        "`firecrawl_search`",
        "Markdown-only `firecrawl_scrape`",
        "`firecrawl_budget_status`",
        "fixed 900-credit cap",
        "Search reserves 2 credits",
        "basic Scrape reserves 1 credit",
        "not refunded",
        "fail closed",
        "FIRECRAWL_BUDGET_EXHAUSTED",
        "FIRECRAWL_BUDGET_UNAVAILABLE",
        "FIRECRAWL_REQUEST_NOT_BOUNDED",
        "degraded-coverage notice",
        "separate connected Firecrawl app",
        "${CODEX_HOME:-~/.codex}/state/firecrawl-budget.json",
        "plugins/web-data-tools/scripts/run-firecrawl-mcp.sh status",
        "never reports Firecrawl credentials",
    ):
        require(expected in readme_text, f"README Firecrawl budget contract must mention {expected}")
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
        "Paper Search first",
        "Firecrawl only",
    ):
        require(expected in readme_text, f"README paper intake must mention {expected}")
    for expected in (
        "## Zotero-linked Todoist Reading Tasks",
        "$zotero-todoist-reading-tasks",
        "parent-item link",
        "attachment-key link",
        "`deadlineDate`",
        "not continuous",
    ):
        require(
            expected in readme_text,
            f"README Zotero-Todoist workflow must mention {expected}",
        )
    for expected in (
        "## Private Paper Review Sync",
        "$paper-review-sync check",
        "$paper-review-sync sync",
        "$paper-review-sync repair",
        "$paper-review-library-intake",
        "$paper-review-page",
        "Research/PaperReview",
        "Paper Reviews/Assigned",
        "not continuous monitoring",
    ):
        require(expected in readme_text, f"README paper-review workflow must mention {expected}")
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
        "Coder MCP",
        "coder-tools",
        "coder login <deployment-url>",
        "coder exp mcp server",
        "read-only",
        "fresh Codex task",
    ):
        require(
            expected in readme_normalized,
            f"README Coder MCP guidance must mention {expected}",
        )
    for expected in (
        "Daily Command Center",
        "$daily-command-center",
        "read-only daily brief",
        "Gmail",
        "Google Calendar",
        "Todoist",
        "scheduled task",
        "preferred local time",
    ):
        require(
            expected in readme_normalized,
            f"README daily command center guidance must mention {expected}",
        )
    for expected in (
        "Explain Clearly",
        "$explain-clearly",
        "mental model",
        "concrete example",
        "smallest useful format",
        "bundled Visualize",
        "ambiguous chess positions",
    ):
        require(
            expected in readme_normalized,
            f"README explanation workflow must mention {expected}",
        )
    for expected in (
        "Ship Toolbox",
        "$ship-toolbox",
        "synchronized `main`",
        "explicit paths and hunks",
        "Git-backed local marketplace",
        "does not create branches",
    ):
        require(
            expected in readme_text,
            f"README shipping workflow must mention {expected}",
        )
    for expected in (
        "$ship-toolbox",
        "only when the user explicitly invokes it",
        "never make `$ship-toolbox` implicitly invocable",
        "synchronized-`main`",
    ):
        require(
            expected in repo_agents_text,
            f"repository AGENTS shipping routing must mention {expected}",
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
        '  "workflow-tools"' in default_plugins,
        "setup script must install the workflow-tools plugin",
    )
    require(
        '  "coder-tools"' in default_plugins,
        "setup script must install the coder-tools plugin",
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
        '  "todoist"' in managed_mcp_servers,
        "setup script must manage the todoist MCP server cleanup list",
    )
    require(
        '  "coder"' in managed_mcp_servers,
        "setup script must manage the coder MCP server cleanup list",
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
            plugin.get("name") == "workflow-tools"
            and plugin.get("source", {}).get("path") == "./plugins/workflow-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include workflow-tools",
    )
    require(
        any(
            plugin.get("name") == "coder-tools"
            and plugin.get("source", {}).get("path") == "./plugins/coder-tools"
            for plugin in marketplace.get("plugins", [])
        ),
        "marketplace must include coder-tools",
    )
    require(
        coder_plugin.get("mcpServers") == "./.mcp.json",
        "coder-tools must expose its MCP config",
    )
    require(
        coder_plugin.get("version") == "0.1.0",
        "coder-tools plugin version must start at 0.1.0",
    )
    require(coder_server is not None, "coder-tools must define the coder MCP server")
    require(
        coder_server.get("command") == "/bin/zsh",
        "coder MCP must use the portable zsh launcher",
    )
    coder_args = coder_server.get("args", [])
    require(
        len(coder_args) == 2
        and coder_args[0] == "-lc"
        and 'exec "$CODER_BIN" exp mcp server' in coder_args[1],
        "coder MCP must launch the local Coder CLI MCP server",
    )
    require(
        "--allowed-tools" in coder_args[1],
        "coder MCP must restrict the exposed tool set",
    )
    for allowed_tool in (
        "coder_get_authenticated_user",
        "coder_get_workspace",
        "coder_get_workspace_agent_logs",
        "coder_get_workspace_build_logs",
        "coder_list_templates",
        "coder_list_workspaces",
        "coder_workspace_ls",
        "coder_workspace_read_file",
        "fetch",
        "search",
    ):
        require(
            allowed_tool in coder_args[1],
            f"coder MCP read-only allowlist must include {allowed_tool}",
        )
    for forbidden_tool in (
        "coder_create_workspace",
        "coder_delete_workspace",
        "coder_workspace_bash",
        "coder_workspace_edit_file",
        "coder_workspace_write_file",
    ):
        require(
            forbidden_tool not in coder_args[1],
            f"coder MCP allowlist must exclude mutating tool {forbidden_tool}",
        )
    require(
        coder_server.get("default_tools_approval_mode") == "auto",
        "coder MCP may auto-approve only its process-level read-only allowlist",
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
        "productivity-tools must expose its productivity workflow skills",
    )
    require(
        productivity_plugin.get("mcpServers") == "./.mcp.json",
        "productivity-tools must expose its MCP config",
    )
    productivity_interface = productivity_plugin.get("interface", {})
    require(
        productivity_plugin.get("version") == "0.2.0",
        "productivity-tools plugin version must reflect daily-command-center",
    )
    require(
        "Todoist" in productivity_interface.get("longDescription", ""),
        "productivity-tools description must mention Todoist",
    )
    description_surfaces = {
        "description": productivity_plugin.get("description", ""),
        "shortDescription": productivity_interface.get("shortDescription", ""),
        "longDescription": productivity_interface.get("longDescription", ""),
    }
    for field, description_text in description_surfaces.items():
        description_lower = description_text.lower()
        require(
            all(
                expected in description_lower
                for expected in ("read-only", "daily", "gmail", "calendar", "todoist")
            ),
            f"productivity-tools {field} must surface the read-only Gmail, Calendar, and Todoist daily brief",
        )
    require(
        any(
            "todoist-task-planning" in prompt
            for prompt in productivity_interface.get("defaultPrompt", [])
        ),
        "productivity-tools prompts must surface todoist-task-planning",
    )
    require(
        any(
            "daily-command-center" in prompt
            for prompt in productivity_interface.get("defaultPrompt", [])
        ),
        "productivity-tools prompts must surface daily-command-center",
    )
    require(
        len(productivity_interface.get("defaultPrompt", [])) <= 3,
        "productivity-tools must stay within Codex's three default-prompt limit",
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
    daily_skill_text = DAILY_COMMAND_CENTER_SKILL.read_text()
    daily_skill_normalized = normalized(daily_skill_text)
    daily_skill_lower = daily_skill_normalized.lower()
    read_only_text = daily_skill_text.split("## Source ownership and tool choice", maxsplit=1)[0]
    source_choice_text = markdown_section(daily_skill_text, "Source ownership and tool choice")
    read_sources_text = markdown_section(daily_skill_text, "Read the bounded sources")
    brief_text = markdown_section(daily_skill_text, "Write the brief")
    frontmatter = daily_skill_frontmatter(daily_skill_text)
    frontmatter_lines = frontmatter.splitlines()
    require(
        len(frontmatter_lines) == 2
        and frontmatter_lines[0] == "name: daily-command-center"
        and frontmatter_lines[1].startswith("description: ")
        and bool(frontmatter_lines[1].removeprefix("description: ").strip()),
        "daily-command-center frontmatter must contain exactly the required name and description",
    )
    description = frontmatter_lines[1].removeprefix("description: ").lower()
    for expected in (
        "daily or morning briefs",
        "daily planning",
        "scheduled command-center runs",
        "gmail, google calendar, and todoist",
    ):
        require(
            expected in description,
            f"daily-command-center frontmatter description must trigger for {expected}",
        )
    for expected in (
        "daily or morning briefs",
        "daily planning",
        "scheduled command-center runs",
        "Gmail, Google Calendar, and Todoist",
        "strictly read-only",
        "conversation history is not a task database",
        "Gmail is incoming context",
        "Todoist is the durable source of truth for actionable tasks",
        "Google Calendar is the source of truth for time commitments",
        "Prefer connected apps",
        "official hosted MCP as a fallback",
        "one Todoist surface per run",
        "overdue, today, and seven-day upcoming tasks",
        "verification codes",
        "direct verification",
        "partial brief",
        "do not substitute web search",
        "$todoist-task-planning",
    ):
        require(
            expected.lower() in daily_skill_lower,
            f"daily-command-center must mention {expected}",
        )
    for service, operations in (
        ("Gmail", r"send\s*,\s*draft\s*,\s*label\s*,\s*archive\s*,\s*trash\s*,\s*or\s+delete\s+email"),
        ("Calendar", r"create\s*,\s*update\s*,\s*delete\s*,\s*or\s+respond\s+to\s+calendar\s+events"),
        ("Todoist", r"create\s*,\s*update\s*,\s*complete\s*,\s*delete\s*,\s*or\s+reschedule\s+todoist\s+records"),
    ):
        require(
            re.search(operations, plain_normalized(read_only_text)) is not None,
            f"daily-command-center must list every prohibited {service} mutation",
        )
    timezone_contract = plain_normalized(source_choice_text)
    require(
        re.search(
            r"connected profiles.*?profiles disagree materially.*?report the mismatch.*?calendar timezone.*?schedule rendering",
            timezone_contract,
        )
        is not None,
        "daily-command-center must report profile timezone mismatches and render schedules in the Calendar timezone",
    )
    gmail_query = (
        "newer_than:2d in:inbox -category:promotions "
        "-category:social -in:spam -in:trash"
    )
    require(
        gmail_query in read_sources_text,
        "daily-command-center must use the exact bounded Gmail query",
    )
    require(
        re.search(
            r"initial search at 30 messages.*?group results by thread.*?at most five likely-action threads",
            plain_normalized(read_sources_text),
        )
        is not None,
        "daily-command-center must retain the exact Gmail message and thread expansion bounds",
    )
    require(
        re.search(
            r"calendar.*?explicit timezone-aware bounds.*?start of today.*?next seven days",
            plain_normalized(read_sources_text),
        )
        is not None,
        "daily-command-center must retain the bounded timezone-aware Calendar window",
    )
    output_labels = (
        "Today at a glance",
        "Attention now",
        "Calendar",
        "Tasks",
        "FYI",
        "Suggested actions",
        "Coverage and caveats",
    )
    brief_lines = [plain_normalized(line) for line in brief_text.splitlines()]
    output_positions = []
    for label in output_labels:
        label_pattern = rf"(?:(?:\d+[.)]|[-+])\s+)?{re.escape(label.lower())}"
        matching_lines = [
            index
            for index, line in enumerate(brief_lines)
            if re.fullmatch(label_pattern, line)
        ]
        require(
            len(matching_lines) == 1,
            f"daily-command-center must list the {label} output section exactly once",
        )
        output_positions.append(matching_lines[0])
    require(
        output_positions == sorted(output_positions),
        "daily-command-center output labels must appear in the required stable order",
    )
    require(
        re.search(
            r"(?:limit|cap)\s+attention now\s+to\s+five(?:\s+items)?\s+and\s+fyi\s+to\s+three(?:\s+items)?",
            plain_normalized(brief_text),
        )
        is not None,
        "daily-command-center must cap Attention now at five items and FYI at three",
    )
    require(
        re.search(
            r"every attention item.*?source.*?time (?:or|/) date.*?why it matters.*?known deadline.*?recommended next step",
            plain_normalized(brief_text),
        )
        is not None,
        "daily-command-center attention items must include source, time/date, rationale, deadline, and next step",
    )
    daily_openai = DAILY_COMMAND_CENTER_OPENAI.read_text()
    for expected in (
        'display_name: "Daily Command Center"',
        'short_description: "Summarize email, calendar, and priority tasks."',
        'default_prompt: "Use $daily-command-center to prepare my read-only daily brief."',
    ):
        require(
            expected in daily_openai,
            f"daily-command-center OpenAI metadata must mention {expected}",
        )
    require(
        "todoist" not in daily_openai.lower(),
        "daily-command-center OpenAI metadata must not require Todoist MCP",
    )
    require(
        workflow_plugin.get("skills") == "./skills/",
        "workflow-tools must expose bundled planning skills",
    )
    require(
        workflow_plugin.get("version") == "0.5.0",
        "workflow-tools plugin version must reflect default Pretty Mermaid routing",
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
    require(
        any("explain-clearly" in prompt for prompt in workflow_interface.get("defaultPrompt", [])),
        "workflow-tools default prompts must surface explain-clearly usage",
    )
    require(
        "explanation" in workflow_interface.get("longDescription", "").lower(),
        "workflow-tools plugin description must mention explanations",
    )
    require(
        "Ship Toolbox" in workflow_interface.get("longDescription", ""),
        "workflow-tools plugin description must mention Ship Toolbox",
    )
    require(
        {"Read", "Write"}.issubset(set(workflow_interface.get("capabilities", []))),
        "workflow-tools must expose Read and Write capabilities",
    )
    require(
        any("ship-toolbox" in prompt for prompt in workflow_interface.get("defaultPrompt", [])),
        "workflow-tools default prompts must surface ship-toolbox usage",
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
        "ordinary multi-step work",
        "Codex-only",
        "Native Codex subagents",
        "OpenSpec",
    ):
        require(expected in deep_planning_text, f"deep-planning skill must mention {expected}")
    require(
        "Superpowers" not in deep_planning_text and "superpowers:" not in deep_planning_text,
        "deep-planning skill must not route through Superpowers",
    )
    deep_planning_openai = DEEP_PLANNING_OPENAI.read_text()
    for expected in (
        'display_name: "Deep Planning"',
        'short_description: "Adversarial Plan Mode critique before implementation."',
        'default_prompt: "Use $deep-planning to critique this plan before implementation."',
    ):
        require(expected in deep_planning_openai, f"deep-planning OpenAI metadata must mention {expected}")
    explain_clearly_text = EXPLAIN_CLEARLY_SKILL.read_text()
    for expected in (
        "name: explain-clearly",
        "Use when",
        "Direct answer",
        "Mental model",
        "Concrete example",
        "exactly one worked",
        "Mechanism and limits",
        "input",
        "state",
        "output",
        "analogy",
        "terse factual query",
        "explicit user instructions",
        "Choose the Smallest Useful Format",
        "`$pretty-mermaid` by default",
        "native inline Mermaid only",
        "editable `.mmd` source",
        "bundled Visualize",
        "A visual is presentation, not evidence",
        "For chess",
        "responsive and accessible",
        "CLI or IDE",
    ):
        require(expected in explain_clearly_text, f"explain-clearly skill must mention {expected}")
    explain_clearly_openai = EXPLAIN_CLEARLY_OPENAI.read_text()
    for expected in (
        'display_name: "Explain Clearly"',
        'short_description: "Clear mental models and concrete examples."',
        'default_prompt: "Use $explain-clearly to lead with the answer, choose the smallest useful format, use Pretty Mermaid by default for diagrams, and give one accurate mental model and concrete example."',
        "allow_implicit_invocation: true",
    ):
        require(
            expected in explain_clearly_openai,
            f"explain-clearly OpenAI metadata must mention {expected}",
        )
    ship_toolbox_files = {
        path.relative_to(SHIP_TOOLBOX_SKILL.parent).as_posix()
        for path in SHIP_TOOLBOX_SKILL.parent.rglob("*")
        if path.is_file()
    }
    require(
        ship_toolbox_files == {"SKILL.md", "agents/openai.yaml"},
        "ship-toolbox must remain instruction-only with SKILL.md and agents/openai.yaml",
    )
    ship_toolbox_text = SHIP_TOOLBOX_SKILL.read_text()
    for expected in (
        "name: ship-toolbox",
        "Use only when explicitly invoked as $ship-toolbox",
        "jialuohu/codex-toolbox",
        "origin/main",
        "git rev-list --left-right --count",
        "git add .",
        "git add -A",
        "git diff --cached --name-status",
        "python3 scripts/check-codex-toolbox-setup.py",
        "scripts/privacy-audit.sh current",
        "python3 -m unittest discover -s tests",
        "git push origin main",
        "git ls-remote origin",
        "GitHub Actions",
        "scripts/setup-codex-toolbox.sh",
        "sourceType",
        "codex mcp list",
        "Wrong branch",
        "Behind or diverged",
        "Ambiguous mixed changes",
        "No-change refresh",
        "Push failed",
        "CI failed",
        "Post-push setup failed",
        "Privacy or test gate failed",
        "empty commit",
        "force-push",
        "rebase",
        "reset",
        "revert automatically",
    ):
        require(expected in ship_toolbox_text, f"ship-toolbox skill must mention {expected}")
    ship_toolbox_openai = SHIP_TOOLBOX_OPENAI.read_text()
    for expected in (
        'display_name: "Ship Toolbox"',
        'short_description: "Validate, publish, and refresh toolbox changes."',
        'default_prompt: "Use $ship-toolbox to validate, commit, push, refresh, and verify the current toolbox changes."',
        "allow_implicit_invocation: false",
    ):
        require(
            expected in ship_toolbox_openai,
            f"ship-toolbox OpenAI metadata must mention {expected}",
        )
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
        "Use Paper Search first",
        "normal Codex web search",
        "Use Firecrawl only",
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
    zotero_todoist_text = ZOTERO_TODOIST_READING_TASKS_SKILL.read_text()
    zotero_todoist_normalized = " ".join(zotero_todoist_text.split())
    for expected in (
        "name: zotero-todoist-reading-tasks",
        "Do not mutate Zotero",
        "zotero_get_collection_items",
        "zotero_get_items_children",
        "Choose exactly one Todoist tool surface",
        "zotero://select/library/items/<PARENT_KEY>",
        "zotero://open-pdf/library/items/<ATTACHMENT_KEY>",
        "zotero://select/groups/<GROUP_ID>/items/<PARENT_KEY>",
        "zotero://open-pdf/groups/<GROUP_ID>/items/<ATTACHMENT_KEY>",
        "unique one-to-one match",
        "exactly one managed `Zotero:` line",
        "`deadlineDate`",
        "`reschedule-tasks`",
        "continuous synchronization",
        "$paper-library-intake",
        "`$paper-read-draft` exactly once per uniquely resolved Zotero parent",
        "without Obsidian notes",
        "Do not independently infer a note filename or URI",
        "`note-missing`",
    ):
        require(
            expected in zotero_todoist_normalized,
            f"zotero-todoist-reading-tasks must mention {expected}",
        )
    zotero_todoist_openai = ZOTERO_TODOIST_READING_TASKS_OPENAI.read_text()
    for expected in (
        'display_name: "Zotero Todoist Reading Tasks"',
        'default_prompt: "Use $zotero-todoist-reading-tasks',
        'value: "zotero"',
        'value: "todoist"',
        'value: "obsidian_files"',
        'url: "https://ai.todoist.net/mcp"',
    ):
        require(
            expected in zotero_todoist_openai,
            f"zotero-todoist-reading-tasks metadata must mention {expected}",
        )
    require(
        'value: "obsidian_files"' in zotero_todoist_openai,
        "research-tools must declare obsidian_files as a dependency",
    )
    require(
        "todoist" not in research_mcp.get("mcpServers", {}),
        "research-tools must not duplicate the Todoist MCP server",
    )
    require(
        "obsidian_files" not in research_mcp.get("mcpServers", {}),
        "research-tools must not duplicate the Obsidian MCP server",
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

    paper_review_library_text = PAPER_REVIEW_LIBRARY_INTAKE_SKILL.read_text()
    for expected in (
        "name: paper-review-library-intake",
        "Research/PaperReview",
        "Paper Review ID:",
        "docmost_download_attachment",
        "docmost_release_attachment_download",
        "in a `finally` path",
        "Never send a private title",
        "Do not invoke `$paper-library-intake`",
        "zotero_attachment.py attach",
        "zotero_read_pdf_pages",
        "zotero://select/library/items/<PARENT_KEY>",
        "zotero://open-pdf/library/items/<ATTACHMENT_KEY>",
    ):
        require(
            expected in paper_review_library_text,
            f"paper-review-library-intake must mention {expected}",
        )
    require(
        "$paper-review-library-intake" in PAPER_REVIEW_LIBRARY_INTAKE_OPENAI.read_text(),
        "paper-review-library-intake metadata must expose the skill trigger",
    )

    paper_review_page_text = PAPER_REVIEW_PAGE_SKILL.read_text()
    for expected in (
        "name: paper-review-page",
        "Jialuo Hu/Paper Review",
        "Paper Number exactly",
        "Assignment form",
        "Same venue and year",
        "Fallback asset",
        "template_structure.py",
        "Remove names, paper-specific summaries",
        "Never copy an entire peer page",
        "Paper Review ID:",
        "docmost_create_page",
    ):
        require(expected in paper_review_page_text, f"paper-review-page must mention {expected}")
    require(
        paper_review_page_text.index("**Assignment form:**")
        < paper_review_page_text.index("**Same venue and year:**")
        < paper_review_page_text.index("**Fallback asset:**"),
        "paper-review-page must prefer assignment form, then venue structure, then fallback",
    )
    require(
        "$paper-review-page" in PAPER_REVIEW_PAGE_OPENAI.read_text(),
        "paper-review-page metadata must expose the skill trigger",
    )

    paper_review_sync_text = PAPER_REVIEW_SYNC_SKILL.read_text()
    for expected in (
        "name: paper-review-sync",
        "$paper-review-sync check",
        "$paper-review-sync sync",
        "$paper-review-sync repair",
        "strictly read-only",
        "Assigned To",
        "Reviewer",
        "Jialuo Hu",
        "Review Comments",
        "paper-review",
        "deep-work",
        "Paper Reviews",
        "Assigned",
        "Paper Review ID:",
        "Review page: repair-needed",
        "Zotero: repair-needed",
        "$paper-review-library-intake",
        "$paper-review-page",
        "not continuous synchronization",
        "paper_review_contract.py",
    ):
        require(expected in paper_review_sync_text, f"paper-review-sync must mention {expected}")
    require(
        "$paper-review-sync" in PAPER_REVIEW_SYNC_OPENAI.read_text(),
        "paper-review-sync metadata must expose the skill trigger",
    )

    require(
        research_plugin.get("version") == "0.8.0",
        "research-tools must use the current Lab Wiki workflow version",
    )
    lab_skill = DOCMOST_LAB_WIKI_SKILL.read_text()
    for expected in (
        "name: docmost-lab-wiki",
        "docmost_prepare_workspace_snapshot",
        "docmost_release_workspace_snapshot",
        "finally",
        "Never call page creation",
        "Never open, print, parse, summarize",
        "Research/LLM Wiki",
        "older than 36 hours",
        "There is no override",
        "Warning-level outcomes are nonzero",
        "references/commands.md",
    ):
        require(expected in lab_skill, f"docmost-lab-wiki skill must mention {expected}")
    require(
        "docmost_create_page" not in lab_skill
        and "docmost_update_page_title" not in lab_skill
        and "docmost_create_comment" not in lab_skill,
        "docmost-lab-wiki skill must not make Docmost write tools reachable",
    )
    lab_openai = DOCMOST_LAB_WIKI_OPENAI.read_text()
    for expected in (
        "$docmost-lab-wiki",
        'value: "docmost"',
        "allow_implicit_invocation: true",
    ):
        require(expected in lab_openai, f"docmost-lab-wiki metadata must mention {expected}")
    lab_project = DOCMOST_LAB_WIKI_PYPROJECT.read_text()
    lab_lock = DOCMOST_LAB_WIKI_LOCK.read_text()
    for expected in (
        'version = "0.8.0"',
        'requires-python = ">=3.12,<3.13"',
        '"fastembed==0.8.0"',
        'docmost-lab-wiki = "docmost_lab_wiki.cli:main"',
    ):
        require(expected in lab_project, f"Docmost Lab Wiki runtime must pin {expected}")
    require(
        'name = "fastembed"' in lab_lock
        and 'version = "0.8.0"' in lab_lock
        and 'name = "docmost-lab-wiki"' in lab_lock,
        "Docmost Lab Wiki dependency lock must pin FastEmbed 0.8.0 and the local package",
    )
    lab_constants = DOCMOST_LAB_WIKI_CONSTANTS.read_text()
    for expected in (
        'MODEL_REVISION = "c32e6154d1bb7a0e47c5e745fd895e7700f44385"',
        'MODEL_FILE_SHA256 = "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"',
        "MODEL_DIMENSIONS = 384",
        "MODEL_MAX_TOKENS = 512",
        "CHUNK_TARGET_TOKENS = 420",
        "CHUNK_OVERLAP_TOKENS = 60",
        "RETRIEVAL_CANDIDATES = 50",
        "FINAL_CONTEXT_CHUNKS = 12",
        "MAX_CHUNKS_PER_PAGE = 2",
    ):
        require(expected in lab_constants, f"Docmost Lab Wiki constants must pin {expected}")
    lab_setup = DOCMOST_LAB_WIKI_SETUP.read_text()
    for expected in (
        'MODEL_REPOSITORY="Qdrant/bge-small-en-v1.5-onnx-Q"',
        'MODEL_REVISION="c32e6154d1bb7a0e47c5e745fd895e7700f44385"',
        'MODEL_FILE_SHA256="51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"',
        "snapshot_download(",
        "--frozen --no-dev --no-editable --reinstall-package docmost-lab-wiki",
        "DOCMOST_LAB_WIKI_ROOT=Research/Lab Wiki",
        "mktemp -d",
    ):
        require(expected in lab_setup, f"Docmost Lab Wiki setup must preserve {expected}")
    lab_runner = DOCMOST_LAB_WIKI_RUNNER.read_text()
    for expected in (
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
        "docmost-lab-wiki.env",
        "mode 600",
        'exec "$LAB_WIKI_RUNTIME/bin/docmost-lab-wiki"',
    ):
        require(expected in lab_runner, f"Docmost Lab Wiki runner must include {expected}")
    lab_runtime_text = "\n".join(
        path.read_text()
        for path in sorted(
            (DOCMOST_LAB_WIKI_RUNTIME / "src" / "docmost_lab_wiki").glob("*.py")
        )
    )
    for expected in (
        "specific_model_path=str(model_path)",
        "local_files_only=True",
        "CREATE VIRTUAL TABLE chunks_fts USING fts5",
        "mode=ro&immutable=1",
        "scan_for_secrets",
        "quarantined_managed_body",
        "deleted_managed_body",
        "fail_after_replacements",
    ):
        require(expected in lab_runtime_text, f"Docmost Lab Wiki runtime must include {expected}")
    for expected in (
        "## Read-only Docmost Lab Wiki",
        "$docmost-lab-wiki",
        "Sources/Docmost/<space-id>/<page-id>.md",
        "FastEmbed 0.8.0",
        "scripts/setup-docmost-lab-wiki.sh --install",
    ):
        require(expected in readme_text, f"README must document Docmost Lab Wiki {expected}")
    require(
        "$docmost-lab-wiki" in global_agents_text
        and "read-only Obsidian mirror" in global_agents_text,
        "global AGENTS must route the read-only Docmost Lab Wiki",
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
        any(
            "$zotero-todoist-reading-tasks" in prompt
            for prompt in research_interface.get("defaultPrompt", [])
        ),
        "research-tools default prompts must surface zotero-todoist-reading-tasks",
    )
    require(
        any("$paper-review-sync" in prompt for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface paper-review-sync",
    )
    require(
        any("mineru" in prompt.lower() for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must retain MinerU extraction coverage",
    )
    require(
        "Todoist" in research_plugin.get("description", "")
        and "Todoist" in research_interface.get("longDescription", ""),
        "research-tools descriptions must surface Zotero-linked Todoist reading tasks",
    )
    require(
        "PaperRead" in research_interface.get("shortDescription", "")
        and "review" in research_interface.get("shortDescription", "").lower()
        and "PaperRead" in research_interface.get("longDescription", "")
        and "review" in research_interface.get("longDescription", "").lower(),
        "research-tools plugin descriptions must surface the PaperRead draft and review workflows",
    )
    require(
        any("$paper-read-draft" in prompt for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface paper-read-draft",
    )
    require(
        any("$paper-read-review" in prompt for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must surface paper-read-review",
    )
    require(
        len(research_interface.get("defaultPrompt", [])) <= 3,
        "research-tools default prompts must respect Codex's three-prompt limit",
    )
    require(
        all(len(prompt) <= 128 for prompt in research_interface.get("defaultPrompt", [])),
        "research-tools default prompts must respect Codex's 128-character limit",
    )
    paper_read_draft_text = PAPER_READ_DRAFT_SKILL.read_text()
    paper_read_draft_normalized = " ".join(paper_read_draft_text.split())
    for expected in (
        "name: paper-read-draft",
        "metadata-only",
        "do not guess",
        "Do not add or update Zotero",
        "do not ingest the LLM Wiki",
        "Fill a metadata field only when the user supplied it or current-task source/tool output actually observed it.",
        "Never claim a Zotero or canonical lookup occurred without actual returned evidence.",
        "Missing evidence means blank optional fields.",
        "For `year`, prefer the official venue publication year",
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
            "A bounded call from `$zotero-todoist-reading-tasks` authorizes at most one create-or-reuse action per uniquely resolved parent.",
            "paper-read-draft must bound delegated create-or-reuse authority per resolved parent",
        ),
        (
            "Resolve the configured vault through `CODEX_OBSIDIAN_VAULT` and `obsidian_files`. Write only beneath `PaperRead/`; never use the current working directory as the vault.",
            "paper-read-draft must use the configured vault, only write under PaperRead, and never use the current directory as the vault",
        ),
        (
            "PaperRead/<first-author-family-name><YY>-<short-method-name>.md",
            "paper-read-draft must use the author-year-method filename contract",
        ),
        (
            "Before any write, search `PaperRead/` for the same DOI, arXiv identifier, canonical URL, or exact normalized title.",
            "paper-read-draft must deduplicate paper identity before creation",
        ),
        (
            "Perform an exact target-path check. If it contains the same paper, return it unchanged.",
            "paper-read-draft must return an exact-path existing note without modification",
        ),
        (
            "Never migrate legacy title-based filenames automatically.",
            "paper-read-draft must not rename legacy notes without explicit authority",
        ),
        (
            "Do not fill personal sections by default; each is hidden-prompt-only.",
            "paper-read-draft must leave personal sections hidden-prompt-only by default",
        ),
        (
            "Return `reused` for an existing exact or identity-deduplicated note, `created` for a new note, or `skipped` when no note was written.",
            "paper-read-draft must return a created, reused, or skipped note status",
        ),
        (
            "For `created` or `reused`, return the vault-relative path and the resulting clickable Obsidian URI.",
            "paper-read-draft must return its resolved path and URI",
        ),
    ):
        require(expected in paper_read_draft_normalized, message)
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
        "## One-sentence summary",
        "## Summary and takeaway",
        "## My thoughts",
    ):
        require(expected in paper_read_draft_template, f"paper-read-draft template must mention {expected}")
    require(
        "## Questions" not in paper_read_draft_template,
        "paper-read-draft template must fold open questions into My thoughts",
    )
    paper_read_draft_filename = PAPER_READ_DRAFT_FILENAME.read_text()
    for expected in (
        "def build_filename(",
        "publication year must contain exactly four digits",
        'return f"{author_slug}{year_text[-2:]}-{method_slug}.md"',
    ):
        require(
            expected in paper_read_draft_filename,
            f"paper-read-draft filename helper must mention {expected}",
        )
    for expected in (
        "## PaperRead Draft",
        "$paper-read-draft",
        "create a compact Obsidian PaperRead draft",
        "fills factual metadata only",
        "three personal sections",
        "One-sentence summary",
        "Open questions belong in My thoughts",
    ):
        require(expected in readme_text, f"README PaperRead draft section must mention {expected}")
    paper_read_review_text = PAPER_READ_REVIEW_SKILL.read_text()
    for expected in (
        "name: paper-read-review",
        "There is no chat-only review mode.",
        "**Mode:** `annotate` or `no-write`",
        "%% paper-read-review:one-sentence-summary:start %%",
        "%% paper-read-review:summary-and-takeaway:start %%",
        "Preserve frontmatter, hidden prompts, user prose, existing callouts, and heading order byte-for-byte outside generated markers.",
        "Zotero first",
        "Legal marker order",
        "interleaving untouched byte slices",
        "Separate adjacent callouts with one completely blank, unquoted line.",
        "160 generated words per reviewed section",
        "obsidian eval",
        "Completion Receipt",
        "**Reason:**",
    ):
        require(expected in paper_read_review_text, f"paper-read-review skill must mention {expected}")
    paper_read_review_openai = PAPER_READ_REVIEW_OPENAI.read_text()
    for expected in (
        'display_name: "PaperRead Annotation"',
        'default_prompt: "Use $paper-read-review',
        "allow_implicit_invocation: true",
    ):
        require(expected in paper_read_review_openai, f"paper-read-review metadata must mention {expected}")
    for expected in (
        "## PaperRead Annotation",
        "$paper-read-review",
        "review",
        "annotate",
        "no chat-only review mode",
    ):
        require(expected in readme_text, f"README PaperRead review section must mention {expected}")
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
