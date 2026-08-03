#!/usr/bin/env python3
"""Static checks for the Codex toolbox setup script."""

import hashlib
import json
import re
import shlex
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
DOCMOST_DIR = ROOT / "plugins" / "docmost-tools"
DOCMOST_PLUGIN = DOCMOST_DIR / ".codex-plugin" / "plugin.json"
DOCMOST_MCP = DOCMOST_DIR / ".mcp.json"
DOCMOST_APPROVED_LAUNCHER_SHA256 = (
    "1e3f754036aaa5d33b1aa21e31f6aeaba068bcbd2b8432335621766bb7f50c8c"
)
DOCMOST_SETUP = ROOT / "scripts" / "setup-docmost-tools.sh"
DOCMOST_SMOKE = DOCMOST_DIR / "server" / "src" / "docmost_tools" / "smoke_cli.py"
DOCMOST_AUTH_WRAPPER = DOCMOST_DIR / "server" / "scripts" / "docmost-auth"
DOCMOST_RUNTIME_LOCK = (
    DOCMOST_DIR / "server" / "src" / "docmost_tools" / "runtime_lock.py"
)
DESIGN_ENGINEERING_DIR = ROOT / "plugins" / "design-engineering-tools"
DESIGN_ENGINEERING_PLUGIN = DESIGN_ENGINEERING_DIR / ".codex-plugin" / "plugin.json"
DESIGN_ENGINEERING_PROVENANCE = DESIGN_ENGINEERING_DIR / "PROVENANCE.md"
DESIGN_ENGINEERING_BOUNDARIES = DESIGN_ENGINEERING_DIR / "SHARED-BOUNDARIES.md"
DESIGN_ENGINEERING_SKILLS_DIR = DESIGN_ENGINEERING_DIR / "skills"
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
    "f4a3c44f994335838d44eaa5a00c64969169d7a352629c93e534e91fce23a95b"
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
    "f156b8c52464b2ec3bcec6a677313dec596f8702e52d90010999586250e27a2c"
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


def scan_retired_reference_mentions(
    root: Path,
    checker_path: Path,
    retired_orchestrator: str,
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Return retired-orchestrator and retired-tracker mentions outside ignored paths."""
    retired_mentions = []
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
            if retired_orchestrator in line.lower():
                retired_mentions.append((str(relative_path), line_number, line.strip()))
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
    return retired_mentions, retired_tracker_mentions


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
            "Use `ui-ux-pro-max` as the broad default",
            "global AGENTS design-engineering routing must keep ui-ux-pro-max broad",
        ),
        (
            "$animation-vocabulary",
            "global AGENTS design-engineering routing must map vague motion naming to animation-vocabulary",
        ),
        (
            "Use `$apple-design` only for explicitly Apple-like physical interactions, gestures, springs, or direct manipulation",
            "global AGENTS design-engineering routing must map Apple-like interactions to apple-design",
        ),
        (
            "Generic typography, color, accessibility, and reduced-motion requests remain with `ui-ux-pro-max`",
            "global AGENTS design-engineering routing must keep generic typography, accessibility, and reduced motion with ui-ux-pro-max",
        ),
        (
            "$emil-design-eng` only for an explicit Emil Kowalski or animations.dev request",
            "global AGENTS design-engineering routing must reserve emil-design-eng for explicit Emil or animations.dev requests",
        ),
        (
            "$find-animation-opportunities",
            "global AGENTS design-engineering routing must map motion discovery to find-animation-opportunities",
        ),
        (
            "$improve-animations",
            "global AGENTS design-engineering routing must map motion audits to improve-animations",
        ),
        (
            "`$review-animations`, `$pick-ui-library`, and `$prototype` are explicit-only skills",
            "global AGENTS design-engineering routing must keep review, library, and prototype skills explicit-only",
        ),
        (
            "project design system, explicit user direction, accessibility requirements, and current official documentation override",
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
            "and len(scopes) == len(required_scopes)",
            "setup-gws must reject duplicate or extra scopes",
        ),
        (
            "and set(scopes) == required_scopes",
            "setup-gws must require the exact scope set",
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
            "and len(scopes) == len(required_scopes)\n",
            "gws shared runtime must reject duplicate or extra scopes",
        ),
        (
            "and set(scopes) == required_scopes\n",
            "gws shared runtime must require the exact scope set",
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
            "Keep the official Gmail connector available",
            "global AGENTS must retain the official Gmail connector",
        ),
        (
            "explicitly requests direct `gws` or multi-account Gmail",
            "global AGENTS must route direct or multi-account Gmail to google-workspace-tools",
        ),
        (
            "supplies an explicit account alias",
            "global AGENTS direct gws routing must require an explicit account alias",
        ),
        (
            "Use exactly one Gmail surface per request",
            "global AGENTS Gmail routing must select exactly one surface per request",
        ),
        (
            "do not mix the official Gmail connector and direct `gws` in the same request",
            "global AGENTS Gmail routing must forbid mixing connector and direct gws",
        ),
        (
            "Never infer or default an alias",
            "global AGENTS direct gws routing must reject default accounts",
        ),
        (
            "`$gws-shared`",
            "global AGENTS direct gws routing must require the shared preflight",
        ),
    )
    for expected, message in global_agents_requirements:
        require(expected in global_agents_text, message)
    gmail_routing_paragraphs = [
        paragraph
        for paragraph in re.split(r"\n[ \t]*\n", global_agents_text.strip())
        if re.search(r"\bconnectors?\b", paragraph, re.IGNORECASE)
        and (
            re.search(r"\bdirect\s+`?gws`?", paragraph, re.IGNORECASE)
            or re.search(r"`?\$gws-gmail`?", paragraph, re.IGNORECASE)
        )
    ]
    require(
        gmail_routing_paragraphs == [GLOBAL_GMAIL_ROUTING_PARAGRAPH],
        "global AGENTS Gmail routing policy must match the canonical reviewed paragraph",
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


def validate_docmost_tools_contract(
    marketplace: dict,
    script: str,
    readme_text: str,
    global_agents_text: str,
    default_plugins: list[str],
    managed_mcp_servers: list[str],
) -> None:
    """Keep the browser-authenticated Docmost integration deliberately bounded."""
    require(DOCMOST_PLUGIN.exists(), "docmost-tools plugin manifest must exist")
    require(DOCMOST_MCP.exists(), "docmost-tools must define an MCP config")
    require(DOCMOST_SETUP.exists(), "toolbox must include the Docmost setup helper")
    require(DOCMOST_AUTH_WRAPPER.exists(), "docmost-tools must include its stable auth wrapper")
    require(DOCMOST_SMOKE.exists(), "docmost-tools must include the bounded smoke CLI")
    plugin = json.loads(DOCMOST_PLUGIN.read_text())
    mcp = json.loads(DOCMOST_MCP.read_text())
    server = mcp.get("mcpServers", {}).get("docmost")
    require(server is not None, "docmost-tools must define the docmost MCP server")
    require(plugin.get("mcpServers") == "./.mcp.json", "docmost manifest must register its MCP config")
    require(
        plugin.get("author", {}).get("name") == "Codex Toolbox Contributors",
        "docmost manifest must use neutral publisher metadata",
    )
    capabilities = plugin.get("interface", {}).get("capabilities")
    require(
        capabilities == ["Read", "Write", "Interactive"],
        "docmost manifest must keep Read, Write, and Interactive capabilities",
    )
    require(server.get("command") == "/bin/zsh", "docmost MCP must use the strict shell launcher")
    arguments = server.get("args")
    require(
        isinstance(arguments, list)
        and len(arguments) == 2
        and arguments[0] == "-lc"
        and isinstance(arguments[1], str)
        and bool(arguments[1].strip()),
        "docmost MCP must use exactly one nonempty zsh -lc launcher",
    )
    require(server.get("cwd") == ".", "docmost MCP must use plugin-root relative cwd")
    require(
        server.get("env_vars")
        == ["CODEX_SECRETS_DIR", "CODEX_HOME", "CODEX_LOCAL_BIN_DIR"],
        "docmost MCP must forward only its secrets, Codex home, and uv fallback roots",
    )
    require(
        server.get("default_tools_approval_mode") == "auto",
        "docmost MCP reads must default to automatic approval",
    )
    tools = server.get("tools")
    required_writes = {"create_page", "update_page_title", "create_comment"}
    require(
        isinstance(tools, dict) and set(tools) == required_writes,
        "docmost MCP must prompt-gate exactly the approved write tools",
    )
    for tool in sorted(required_writes):
        require(
            tools[tool].get("approval_mode") == "prompt",
            f"docmost {tool} must require approval",
        )
    launcher = arguments[1]
    require("docmost-auth" not in launcher and "playwright" not in launcher, "docmost MCP launcher must not launch browser authentication")
    runtime_recovery_text = "rerun the full codex-toolbox setup from its checkout"
    auth_login_command = (
        'CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" '
        '"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
    )
    auth_required_sentence = (
        "Authentication required. Close the active task, run "
        f"`{auth_login_command}`, then start a fresh task or reconnect Docmost."
    )
    for expected in (
        "CODEX_SECRETS_DIR=",
        "UV_PROJECT_ENVIRONMENT=",
        'DOCMOST_RUNTIME_PARENT="$DOCMOST_CODEX_ROOT/runtime"',
        'DOCMOST_RUNTIME_DIR="$DOCMOST_RUNTIME_PARENT/docmost-tools"',
        'DOCMOST_RUNTIME_LOCK_HELPER="$DOCMOST_RUNTIME_DIR/libexec/runtime_lock.py"',
        "SECRET_FILE=\"$DOCMOST_SECRETS_ROOT/docmost.env\"",
        "[ ! -f \"$SECRET_FILE\" ] || [ -L \"$SECRET_FILE\" ]",
        "if [ \"$SECRET_MODE\" != 600 ]",
        '[ ! -d "$DOCMOST_RUNTIME_PARENT" ] || [ -L "$DOCMOST_RUNTIME_PARENT" ]',
        '[ ! -d "$DOCMOST_RUNTIME_DIR" ] || [ -L "$DOCMOST_RUNTIME_DIR" ]',
        '[ ! -f "$DOCMOST_RUNTIME_LOCK_HELPER" ] || [ -L "$DOCMOST_RUNTIME_LOCK_HELPER" ]',
        'exec "$DOCMOST_SYSTEM_PYTHON" "$DOCMOST_RUNTIME_LOCK_HELPER" --mode shared',
        '"$DOCMOST_RUNTIME_LOCK_HELPER" --validate-fd --mode shared',
        '--root "$DOCMOST_RUNTIME_PARENT"',
        "source \"$SECRET_FILE\"",
        "CODEX_SECRETS_DIR=\"$DOCMOST_SECRETS_ROOT\"",
        "$DOCMOST_RUNTIME_DIR/bin/docmost-mcp",
        "$DOCMOST_RUNTIME_DIR/bin/docmost-runtime-stamp",
        "docmost-runtime-stamp\" check",
        runtime_recovery_text,
        "readonly DOCMOST_CODEX_ROOT DOCMOST_SECRETS_ROOT DOCMOST_RUNTIME_PARENT",
        "exec \"$DOCMOST_UV\" run --frozen --no-sync --directory \"$DOCMOST_PLUGIN_SERVER_DIR\" docmost-mcp",
    ):
        require(expected in launcher, f"docmost MCP launcher must include {expected}")
    require(
        launcher.index('"$DOCMOST_RUNTIME_LOCK_HELPER" --validate-fd --mode shared')
        < launcher.index('docmost-runtime-stamp" check')
        < launcher.index('source "$SECRET_FILE"'),
        "docmost MCP launcher must validate its shared lock before runtime checks",
    )
    require(
        launcher.count('--root "$DOCMOST_RUNTIME_PARENT"') == 2
        and '--root "$DOCMOST_RUNTIME_DIR"' not in launcher,
        "docmost MCP launcher lock must live outside the mutable environment",
    )
    require(
        launcher.count(runtime_recovery_text) >= 3
        and "scripts/setup-docmost-tools.sh --install" not in launcher,
        "docmost MCP launcher must provide honest checkout-independent recovery",
    )
    require("CODEX_HOME:-$HOME/.codex" in launcher, "docmost MCP launcher must resolve the standard secrets fallback")
    require(
        "CODEX_HOME=\"$DOCMOST_CODEX_ROOT\"" not in launcher,
        "docmost MCP launcher must not repurpose CODEX_HOME",
    )
    marketplace_entry = next(
        (entry for entry in marketplace.get("plugins", []) if entry.get("name") == "docmost-tools"),
        None,
    )
    require(marketplace_entry is not None, "marketplace must include docmost-tools")
    require(
        marketplace_entry.get("source") == {"source": "local", "path": "./plugins/docmost-tools"},
        "docmost marketplace source must be the local plugin",
    )
    require(
        marketplace_entry.get("policy") == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "docmost marketplace policy must be AVAILABLE and ON_INSTALL",
    )
    require("docmost-tools" in default_plugins, "setup script must refresh docmost-tools by default")
    require("docmost" in managed_mcp_servers, "setup script must manage the docmost MCP migration")
    helper = DOCMOST_SETUP.read_text()
    require(
        f"LOGIN_COMMAND='{auth_login_command}'" in helper,
        "Docmost setup must preserve the canonical auth recovery command",
    )
    require(
        f"AUTH_REQUIRED_SENTENCE='{auth_required_sentence}'" in helper,
        "Docmost setup must preserve the canonical AUTH_REQUIRED sentence",
    )
    require(
        helper.count('[ ! -L "$RUNTIME_PARENT" ]') >= 2,
        "Docmost setup must reject a symlinked runtime parent",
    )
    require(
        helper.count('[ ! -L "$UV_PROJECT_ENVIRONMENT" ]') >= 3,
        "Docmost setup must reject a symlinked runtime directory",
    )
    require(
        "--reinstall-package docmost-tools" in helper,
        "Docmost setup must force reinstall the non-editable package",
    )
    lock_check_blocks = shell_function_blocks(helper, "require_fresh_dependency_lock")
    check_blocks = shell_function_blocks(helper, "check")
    install_locked_blocks = shell_function_blocks(helper, "install_locked")
    require(
        len(lock_check_blocks) == 1
        and 'run_uv lock --check --directory "$SERVER_DIR"' in lock_check_blocks[0]
        and len(check_blocks) == 1
        and check_blocks[0].index("require_fresh_dependency_lock")
        < check_blocks[0].index("run_uv sync --frozen --check")
        and len(install_locked_blocks) == 1
        and install_locked_blocks[0].index("require_fresh_dependency_lock")
        < install_locked_blocks[0].index("run_uv sync --frozen --no-dev"),
        "Docmost setup must check lock freshness before synchronization",
    )
    require(
        "run_locked shared --check-locked" in helper
        and "run_locked shared --status-locked" in helper
        and helper.count("validate_runtime_lock shared") >= 2,
        "Docmost setup must keep check and status under shared locks",
    )
    require(
        "run_locked exclusive --install-locked" in helper
        and "run_locked exclusive --login-locked" in helper
        and "run_locked exclusive --logout-locked" in helper
        and helper.count("validate_runtime_lock exclusive") >= 3,
        "Docmost setup must keep install, login, and logout under exclusive locks",
    )
    require(
        helper.count('--root "$RUNTIME_PARENT"') == 2
        and '--root "$UV_PROJECT_ENVIRONMENT"' not in helper,
        "Docmost setup lock must live outside the mutable environment",
    )
    require(
        'python3 "$RUNTIME_LOCK_SOURCE" --validate-fd --mode "$expected_mode"'
        in helper
        and "--check-locked) check" in helper
        and "--install-locked) install_locked" in helper,
        "Docmost setup locked actions must validate their inherited runtime lock",
    )
    runtime_lock = DOCMOST_RUNTIME_LOCK.read_text()
    require(
        "os.set_inheritable(descriptor, True)" in runtime_lock
        and "environment[LOCK_FD_ENV] = str(descriptor)" in runtime_lock
        and "environment[LOCK_MODE_ENV] = mode" in runtime_lock
        and "os.execvpe(" in runtime_lock,
        "Docmost runtime lock must pass the held descriptor to the locked action",
    )
    require(
        "descriptor <= 2" in runtime_lock
        and "not stat.S_ISREG(inherited.st_mode)" in runtime_lock
        and "inherited.st_uid != os.geteuid()" in runtime_lock
        and "inherited.st_nlink != 1" in runtime_lock
        and "(inherited.st_dev, inherited.st_ino) != (current.st_dev, current.st_ino)"
        in runtime_lock,
        "Docmost runtime lock must validate the inherited descriptor identity",
    )
    require(
        "shared_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_SH)"
        in runtime_lock
        and "exclusive_probe_succeeds = _probe_lock(lock_path, fcntl.LOCK_EX)"
        in runtime_lock
        and "return not shared_probe_succeeds and not exclusive_probe_succeeds"
        in runtime_lock
        and "return shared_probe_succeeds and not exclusive_probe_succeeds"
        in runtime_lock,
        "Docmost runtime lock must validate the inherited shared or exclusive mode",
    )
    for expected in (
        "--check", "--install", "--login", "--status", "--logout",
        "docmost.env must have mode 600", "Docmost profile directory must have mode 700",
        "Docmost browser profile directory must have mode 700", "sync --frozen",
        "playwright install chromium", "docmost-smoke", "docmost-auth-internal",
        "AUTH_WRAPPER", "LOGIN_COMMAND", '"$AUTH_WRAPPER" login',
        '"$AUTH_WRAPPER" logout', "AUTH_REQUIRED", "executable.is_file",
        "DocmostSettings.model_validate", "Docmost configuration is invalid",
        "UV_PROJECT_ENVIRONMENT", "runtime/docmost-tools",
        "sync --frozen --check --no-dev --no-editable",
        "sync --frozen --no-dev --no-editable",
        "run --frozen --no-sync", 'bin/docmost-runtime-stamp" write',
        "docmost-runtime-stamp", runtime_recovery_text,
    ):
        require(expected in helper, f"Docmost setup helper must include {expected}")
    auth_wrapper = DOCMOST_AUTH_WRAPPER.read_text()
    for expected in (
        "DOCMOST_SECRETS_ROOT", "docmost.env must not be a symlink",
        "docmost.env must have mode 600", "docmost-auth-internal",
        "login|status", "logout", 'exec "$DOCMOST_AUTH_INTERNAL" "$@"',
        'DOCMOST_RUNTIME_PARENT="$DOCMOST_CODEX_ROOT/runtime"',
        'DOCMOST_RUNTIME_ROOT="$DOCMOST_RUNTIME_PARENT/docmost-tools"',
        'DOCMOST_AUTH_WRAPPER="$DOCMOST_RUNTIME_ROOT/bin/docmost-auth"',
        'DOCMOST_RUNTIME_LOCK_HELPER="$DOCMOST_RUNTIME_ROOT/libexec/runtime_lock.py"',
        '[ -d "$DOCMOST_RUNTIME_PARENT" ] && [ ! -L "$DOCMOST_RUNTIME_PARENT" ]',
        '[ -d "$DOCMOST_RUNTIME_ROOT" ] && [ ! -L "$DOCMOST_RUNTIME_ROOT" ]',
        '[ -f "$DOCMOST_RUNTIME_LOCK_HELPER" ] && [ ! -L "$DOCMOST_RUNTIME_LOCK_HELPER" ]',
        'DOCMOST_REQUIRED_LOCK_MODE=shared',
        'DOCMOST_REQUIRED_LOCK_MODE=exclusive',
        '[ -n "${DOCMOST_RUNTIME_LOCK_MODE:-}" ] || [ -n "${DOCMOST_RUNTIME_LOCK_FD:-}" ]',
        '"${DOCMOST_RUNTIME_LOCK_MODE:-}" = "$DOCMOST_REQUIRED_LOCK_MODE"',
        '"$DOCMOST_RUNTIME_LOCK_HELPER" --validate-fd',
        '--mode "$DOCMOST_REQUIRED_LOCK_MODE" --root "$DOCMOST_RUNTIME_PARENT"',
        'exec "$DOCMOST_SYSTEM_PYTHON" "$DOCMOST_RUNTIME_LOCK_HELPER"',
        runtime_recovery_text,
    ):
        require(expected in auth_wrapper, f"Docmost auth wrapper must include {expected}")
    require(
        auth_wrapper.count(runtime_recovery_text) >= 3
        and "scripts/setup-docmost-tools.sh --install" not in auth_wrapper
        and "run --install" not in auth_wrapper,
        "Docmost auth wrapper must provide honest checkout-independent recovery",
    )
    require(
        'docmost_setup_command "$server_dir" --install' in script
        and 'docmost_setup_command "$server_dir" --status' in script
        and 'docmost_setup_command "$server_dir" --login' in script
        and 'ensure_docmost_ready ""' in script
        and 'ensure_docmost_ready "$DOCMOST_INSTALLED_SERVER_DIR"' in script,
        "toolbox setup must run the Docmost install/status/login recovery sequence",
    )
    require(
        script.index('ensure_docmost_ready ""') < script.index("\nensure_toolbox_marketplace\n"),
        "Docmost preflight must complete before marketplace or plugin refresh",
    )
    installed_distribution_blocks = shell_function_blocks(
        script, "installed_docmost_server_dir"
    )
    require(
        len(installed_distribution_blocks) == 1
        and all(
            expected in installed_distribution_blocks[0]
            for expected in (
                '"$CODEX_BIN" mcp get docmost --json',
                'transport.get("type") != "stdio"',
                'transport.get("command") != "/bin/zsh"',
                'raw_cwd = transport.get("cwd")',
                "not Path(raw_cwd).is_absolute()",
                'Path(os.environ["DOCMOST_CODEX_HOME"])',
                "plugin_root.relative_to(codex_home)",
                '("plugins", "cache", marketplace_name, "docmost-tools")',
                'plugin_root / ".mcp.json"',
                'server / "src" / "docmost_tools" / "server.py"',
                "transport_args != configured_args",
            )
        ),
        "toolbox setup must resolve Docmost from the installed MCP cwd",
    )
    launcher_sha256 = hashlib.sha256(launcher.encode()).hexdigest()
    require(
        len(installed_distribution_blocks) == 1
        and launcher_sha256 == DOCMOST_APPROVED_LAUNCHER_SHA256
        and (
            f'approved_launcher_sha256 = "{DOCMOST_APPROVED_LAUNCHER_SHA256}"'
            in installed_distribution_blocks[0]
        )
        and all(
            expected in installed_distribution_blocks[0]
            for expected in (
                "not isinstance(configured_args, list)",
                "len(configured_args) != 2",
                'configured_args[0] != "-lc"',
                "not isinstance(configured_args[1], str)",
                "hashlib.sha256(configured_args[1].encode()).hexdigest()",
                "not isinstance(transport_args, list)",
                "transport_args != configured_args",
            )
        ),
        "toolbox setup must pin the exact approved Docmost launcher",
    )
    require(
        script.index('DOCMOST_INSTALLED_SERVER_DIR="$(installed_docmost_server_dir)"')
        > script.index('for plugin in "${DEFAULT_PLUGINS[@]}"')
        and script.index('ensure_docmost_ready "$DOCMOST_INSTALLED_SERVER_DIR"')
        < script.index("\nensure_ui_ux_marketplace\n"),
        "toolbox setup must rebuild Docmost from the active plugin after refresh",
    )
    for expected in (
        "## Docmost Tools", "docmost.env", "current-user", "list-spaces",
        "create_page", "update_page_title", "create_comment", "runtime/docmost-tools",
        "every space visible", "DOCMOST_WRITE_PROFILE", "0.95.x",
        "marketplace upgrade", "setup-docmost-tools.sh --install",
    ):
        require(expected in readme_text, f"README must document Docmost {expected}")
    require(
        "plus `uv` and `python3` on `PATH`" in readme_text
        and "requires Python 3.12" in readme_text,
        "README must document Docmost uv and Python prerequisites",
    )
    require(
        "`codex mcp get docmost" in readme_text
        and "Marketplace `source.path` is not treated as the" in readme_text
        and "installed distribution" in readme_text,
        "README must distinguish installed Docmost cwd from marketplace source",
    )
    require(
        auth_login_command in readme_text,
        "README must preserve the canonical Docmost auth recovery command",
    )
    require(
        "Before login or logout, close the active Codex task" in readme_text,
        "README must tell users to close the active task before Docmost auth changes",
    )
    require(
        "After login or logout, start a fresh task or reconnect Docmost" in readme_text,
        "README must tell users to start a fresh task after Docmost auth changes",
    )
    for expected in (
        "Use the `docmost` MCP", "untrusted data", "create_page", "update_page_title", "create_comment",
    ):
        require(expected in global_agents_text, f"global AGENTS must document Docmost {expected}")
    gitignore = (ROOT / ".gitignore").read_text()
    for expected in (
        ".venv/",
        ".pytest_cache/",
        ".ruff_cache/",
        "__pycache__/",
    ):
        require(expected in gitignore, f".gitignore must exclude Docmost runtime state: {expected}")


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
        "Use built-in Codex web search by default",
        "ordinary public discovery",
        "Use Firecrawl only",
        "full-page clean Markdown",
        "without `scrapeOptions`",
        "limit of 5 or less",
        "scrape only the selected URLs",
        "explicit page limit",
        "Interact or Agent",
    ):
        require(
            expected in global_agents_text,
            f"global AGENTS cost-aware web routing must mention {expected}",
        )
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
        "Paper Search first",
        "normal Codex web search",
        "Firecrawl only",
        "Research/ReadLater",
        "explicit `add`, `save`, or `import`",
        "use_scihub=false",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS paper intake routing must mention {expected}",
        )
    for expected in (
        "$zotero-todoist-reading-tasks",
        "parent item key",
        "PDF attachment key",
        "one Todoist surface per request",
        "deadlineDate",
        "one-time reconciliation",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS Zotero-Todoist routing must mention {expected}",
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
        "$daily-command-center",
        "bounded cross-app reads",
        "Gmail is incoming context",
        "Todoist is the durable source of truth for actionable tasks",
        "Google Calendar is the source of truth for time commitments",
        "strict no-mutation behavior in scheduled runs",
        "connected Todoist app",
        "official hosted MCP as a Codex CLI fallback",
        "partial brief",
        "do not substitute web search",
    ):
        require(
            expected in global_agents_normalized,
            f"global AGENTS daily command center routing must mention {expected}",
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
    for expected in (
        "## Explanation routing",
        "$explain-clearly",
        "explain, teach, understand",
        "why/how",
        "code walkthrough",
        "execution-only",
        "explicit user instructions",
    ):
        require(
            expected in global_agents_text,
            f"global AGENTS explanation routing must mention {expected}",
        )
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
    retired_plugins = array_body(script, "RETIRED_PLUGINS")
    managed_mcp_servers = array_body(script, "MANAGED_MCP_SERVERS")
    managed_mcp_server_entries = shell_array_entries(script, "MANAGED_MCP_SERVERS")
    retired_mcp_servers = array_body(script, "RETIRED_MCP_SERVERS")
    pixellab_server = game_asset_mcp.get("mcpServers", {}).get("pixellab")
    robinhood_server = trading_mcp.get("mcpServers", {}).get("robinhood-trading")
    todoist_server = productivity_mcp.get("mcpServers", {}).get("todoist")
    coder_server = coder_mcp.get("mcpServers", {}).get("coder")
    obsidian_files_server = obsidian_mcp.get("mcpServers", {}).get("obsidian_files")

    validate_docmost_tools_contract(
        marketplace,
        script,
        readme_text,
        global_agents_text,
        default_plugin_entries,
        managed_mcp_server_entries,
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

    require(obsidian_files_server is not None, "obsidian-tools must define obsidian_files")
    require(
        "CODEX_OBSIDIAN_VAULT" in obsidian_files_server.get("env_vars", []),
        "obsidian_files must forward CODEX_OBSIDIAN_VAULT to its STDIO server",
    )

    retired_orchestrator = "sym" + "phony"
    retired_plugin_name = retired_orchestrator + "-tools"
    require(
        not (ROOT / "plugins" / retired_plugin_name).exists(),
        "retired orchestration plugin directory must be absent",
    )
    retired_mentions, retired_tracker_mentions = scan_retired_reference_mentions(
        ROOT,
        Path(__file__),
        retired_orchestrator,
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
    ):
        require(
            expected in readme_text,
            f"README explanation workflow must mention {expected}",
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
        workflow_plugin.get("version") == "0.2.0",
        "workflow-tools plugin version must reflect the explanation update",
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
    ):
        require(expected in explain_clearly_text, f"explain-clearly skill must mention {expected}")
    explain_clearly_openai = EXPLAIN_CLEARLY_OPENAI.read_text()
    for expected in (
        'display_name: "Explain Clearly"',
        'short_description: "Clear mental models and concrete examples."',
        'default_prompt: "Use $explain-clearly to explain this with a simple mental model and concrete example."',
        "allow_implicit_invocation: true",
    ):
        require(
            expected in explain_clearly_openai,
            f"explain-clearly OpenAI metadata must mention {expected}",
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
    require(
        research_plugin.get("version") == "0.6.2",
        "research-tools must use the current PaperRead workflow version",
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
