## Orchestration routing

For large or vague project requests, plan normally first, then choose the execution lane.

- Use Codex-only work for tiny edits, one bugfix, one review, fast debugging, or single-session exploration.
- If planning produces 3 or more independent, testable implementation tasks, route to the Codex + Symphony + Linear lane by default even when the user did not mention Symphony or Linear. Do not present Codex-only as an equal execution option unless the user explicitly asks for a quick single-session build or opts out of Symphony/Linear.
- In Plan mode, prepare the architecture, issue breakdown, project workflow choice, and reviewed preflight Linear payloads only. Do not create live Linear issues, refresh/dispatch Symphony, or mutate Linear state in Plan mode.
- In normal execution mode, create live Linear issues only after dry-run payload review and explicit approval. Scheduler refreshes and Linear closeout mutations also require confirmation.
- After the user approves Symphony execution, do not stop at dry-runs. Write the reviewed project workflow, create the approved Linear issues, and start or refresh Symphony so workers actually run.
- For greenfield apps or sites, do the serial bootstrap first when no repo exists or the shared foundation is not ready. Stop bootstrap at the stable shared foundation; split remaining frontend, backend, content, testing, and polish work into Symphony issues instead of continuing the whole build inline.
- Use a project-specific Symphony workflow for unrelated projects. Do not run a new project through `SYMPHONY_WORKFLOW`; create or dry-run a workflow for that target repo first.

## Superpowers workflow

For non-trivial coding tasks, prefer the Superpowers workflow.

- If requirements are unclear, use `superpowers:brainstorming`.
- If the task needs multiple implementation steps, use `superpowers:writing-plans`.
- After plan approval, use the orchestration routing rules above. Choose Symphony for durable multi-ticket work and any plan with 3 or more independent, testable implementation tasks; otherwise offer `superpowers:subagent-driven-development` as the default execution path.
- During implementation of features or bugfixes, use `superpowers:test-driven-development`.
- Before claiming completion, use `superpowers:verification-before-completion`.

Do not force the full workflow for tiny edits, quick explanations, or simple command-output checks.

## Reliability and evidence

Be factual. Distinguish clearly between facts observed from files/tool output, facts sourced from docs/web/MCPs, assumptions or inferences, and unverified guesses. Do not present assumptions or pattern-matching guesses as facts.

Use evidence before claims. Before saying work is complete, fixed, installed, configured, or passing, run the relevant verification command or state exactly why it could not be run. For current external facts, use the appropriate tool or source instead of relying on memory.

Keep evidence lightweight but explicit. For long-running, high-stakes, multi-source, or multi-agent tasks, maintain a short running evidence log in working notes or a temporary file as facts are discovered. Do not create committed fact-log files unless explicitly requested. In final answers, summarize the evidence used and any remaining uncertainty when it materially affects the result.

Manage context deliberately. Use targeted searches and read only the files needed for the decision. Parallelize independent read-only inspection when useful. Avoid broad context gathering when a narrower command answers the question.

Delegate when it improves reliability. Use subagents for broad research, independent audits, many-file scans, or parallel investigations when available. Do direct local exact reads and searches yourself when they are simple, deterministic, or require exact file contents. Do not rely on subagent conclusions without checking the key evidence before making final claims.

## Codex toolbox repo

The personal toolbox repo is `CODEX_TOOLBOX_ROOT` and its GitHub remote is `jialuohu/codex-toolbox`. It is a repo-scoped Codex plugin marketplace named `jialuo-codex-toolbox`.

- Keep plugins focused by domain. Current default plugins are `obsidian-tools`, `research-tools`, `web-data-tools`, `game-asset-tools`, `symphony-tools`, `trading-tools`, `vibe-trading-tools`, and `chronicle-tools`.
- The setup script also manages third-party Git marketplaces: `ui-ux-pro-max-skill`, pinned to `v2.10.0` with sparse checkout limited to the core `ui-ux-pro-max` skill, and the official Context7 marketplace `context7-marketplace`. Do not vendor these third-party plugins into `codex-toolbox` unless explicitly asked.
- Do not reintroduce the retired starter plugins `lab-weekly-update` or `context7-docs` unless explicitly asked.
- Do not commit secrets, OAuth state, API keys, or env-file contents. MCP configs may reference local secret files under `CODEX_SECRETS_DIR/`, but the secret files remain per-device.
- Keep toolbox-managed MCP servers in the plugin `.mcp.json` files, not as duplicate direct `[mcp_servers.*]` tables in `~/.codex/config.toml`. The setup script migrates direct entries for managed servers out of the user config.
- After changing the toolbox, run JSON validation for marketplace/plugin/MCP files, scan for sensitive keywords, run `scripts/setup-codex-toolbox.sh`, and verify `codex plugin list --marketplace jialuo-codex-toolbox --json` plus `codex mcp list`. If third-party marketplace management changed, also verify the relevant plugin list, such as `codex plugin list --marketplace ui-ux-pro-max-skill --json` or `codex plugin list --marketplace context7-marketplace --json`.
- Keep `docs/superpowers/` out of the repo; those are local planning artifacts.

## MCP Tool Routing

Prefer MCP servers, connected apps, and installed skills for external services, private knowledge sources, and specialized tool integrations when the task matches an available integration. If a relevant MCP/app/connector is installed but its tools are not visible in the active tool list, call `tool_search` for that exact integration before falling back. Use normal local tools such as `rg`, package scripts, tests, and `git` for checked-out repos, memory files, private filesystem content, and ordinary local codebase work. Use the narrowest tool that naturally owns the data.

Use the `ui-ux-pro-max` skill for UI/UX design intelligence: page and component design, visual polish, design-system recommendations, accessibility review, typography/color decisions, layout critique, dashboard/landing-page structure, and frontend experience quality checks. Treat its recommendations as advisory; local Codex frontend instructions, the target repo's design system, and explicit user direction override any conflicting upstream skill guidance.

Use Context7 for current, version-aware library and framework documentation, API references, migration examples, and code examples from package docs. Prefer Context7 over general web search when the task is about how to use a specific library or framework. Use Firecrawl instead for broad public web search, arbitrary pages, crawls, site maps, and documentation extraction that is not covered by Context7. For OpenAI/Codex product behavior, prefer official OpenAI/Codex docs before Context7 or generic web search.

Use Firecrawl as the default for public web search, current web pages, documentation scraping, site maps, crawls, structured extraction from websites, pages that need JavaScript rendering, and public web extraction. If Firecrawl tools are not visible, call `tool_search` for Firecrawl before using built-in web search; if `firecrawl_search` is still not exposed, retry with exact terms such as `firecrawl_search scrape web search` and a larger result limit before falling back. After using `firecrawl_search`, call the Firecrawl feedback tool only when that tool is exposed. Do not use Firecrawl for the user's private local files, saved Zotero library, Obsidian vault content, or other private workspace data unless the user explicitly asks to send that content to Firecrawl.

Use PixelLab MCP (`pixellab`) only for pixel-art game asset workflows: sprites, character rotations, animations, top-down or sidescroller tilesets, isometric tiles, and map objects. Do not use PixelLab for web search, private/local files, normal coding, or generic image generation unless the user explicitly asks for PixelLab assets. Creation and destructive tools can spend credits or change saved assets, so keep them prompt-gated unless the user explicitly confirms the action.

Use Symphony MCP (`symphony`) and the `symphony-orchestration` skill for durable Codex plus Linear orchestration: planning runnable Linear issues, dry-running reviewed issue payloads, monitoring Symphony daemon state, refreshing a scheduler tick, summarizing worker handoffs, and closing out Linear comments/state moves after review. Keep issue creation and closeout dry-run first; live issue creation, Linear closeout mutations, and dispatch refreshes require explicit confirmation. Symphony workers should not create more Linear issues or mutate Linear state from inside their issue workspace.

Use `paper_search_mcp` for academic paper discovery across arXiv, Semantic Scholar, CORE, IEEE, Unpaywall, CrossRef, PubMed, BASE, and related sources. Prefer it when the user wants to find new papers, compare search results, inspect paper metadata, or download papers from public scholarly sources. Prefer Zotero MCP instead when the question is about papers the user has already saved.

Use Zotero MCP for the user's saved research library: collections, item metadata, saved full text, PDFs, notes, annotations, and library search. Use Zotero instead of `paper_search_mcp` when the question is about papers the user has already saved. Treat Zotero mutation/control tools as library mutations: confirm intent before adding items, creating annotations, updating semantic indexes/databases, switching libraries, deleting, or changing saved library content.

Use `obsidian_files` for unattended local Obsidian vault reads, searches, note creation, and note edits under `CODEX_OBSIDIAN_VAULT`. Prefer line-based `edit_file` changes for existing notes; use whole-file overwrite only for new files or when explicitly requested. Never move, delete, or broadly rewrite vault files unless the user explicitly asks and the relevant tool is enabled. Prefer the installed Obsidian skills for Obsidian Markdown syntax, Bases, JSON Canvas, and official CLI guidance. Do not use a Local REST API Obsidian MCP unless it is explicitly re-enabled.

Use Vibe-Trading MCP for finance research, backtests, factor analysis, market screening, research swarms, trade-journal analysis, and Shadow Account reports. Its optional Codex override file is `CODEX_SECRETS_DIR/vibe-trading.env`; native Vibe-Trading config, run history, connector profiles, and state live under `VIBE_TRADING_HOME/`. Treat Vibe-Trading connector setup, OAuth, broker-profile selection, and any live-trading adjacent action as explicit-confirmation work.

Use Robinhood Trading MCP (`robinhood-trading`) for official Robinhood Agentic account workflows: connecting the Robinhood Trading MCP, reading Robinhood Agentic account data, and user-requested Agentic trading actions. Prefer Robinhood's official Streamable HTTP MCP endpoint over unofficial Robinhood packages or local wrappers unless the user explicitly asks for an unofficial package. Treat Robinhood order placement, cancellation, rebalance, strategy deployment, or account disconnection as live-financial actions; only perform them when the user explicitly asks for that action and accepts the execution risk.

Use Alpaca MCP only for direct Alpaca account, market data, trading, assets, crypto, options, and news workflows. Keep reads scoped to account, market-data, and trading questions. Treat Alpaca account/order mutation tools as live-financial actions; do not place, replace, cancel, exercise, close, liquidate, or update account settings unless the user explicitly asks for that action and approves it.

Use GitHub connector tools or `gh` for GitHub issues, pull requests, remote repository metadata, review comments, Actions status, and PR creation/update workflows. Use local `git`, `rg`, tests, and filesystem tools for checked-out code and local history unless remote GitHub state is needed.

Use Google Drive, Google Docs, Google Sheets, Google Slides, Gmail, and Google Calendar connected apps for the user's workspace data when the task is about those services. Confirm before sends, deletes, sharing/permission changes, calendar scheduling or RSVP changes, moving files, or other user-visible mutations. Use local document/spreadsheet tools only for local files or generated artifacts that are not already in a connected workspace app.

Use Clay only for GTM, account, prospecting, CRM, enrichment, and company/contact research workflows. Do not spend enrichment or data-point credits unless the user explicitly asks for that specific enrichment. For the user's own accounts or deals, prefer Clay account tools over public company enrichment when account access is available.

Use `node_repl` for JavaScript execution, quick Node-based inspection, and browser-control workflows that explicitly call for the in-app browser or Chrome automation. Prefer `node_repl` with the browser/Chrome plugins for browser automation when available. Use Computer Use only when the task requires operating a local Mac GUI app directly.

For OpenAI/Codex product behavior, prefer official OpenAI/Codex docs over Context7 or generic web search.

For MCP servers, keep API keys, tokens, passwords, and similar secrets in `CODEX_SECRETS_DIR/*.env` files and source those files from the MCP command wrapper. Do not put secrets directly in `Codex config files`.
