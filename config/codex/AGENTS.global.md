## Orchestration routing

For large or vague project requests, plan normally first, then choose the execution lane.

- Use Codex-only work for tiny edits, one bugfix, one review, fast debugging, or single-session exploration.
- Use native Codex subagents when a plan contains independent, testable subtasks and parallel work will improve reliability or latency. Keep simple deterministic reads and tightly coupled edits in the main task.
- For non-trivial coding work with multiple implementation steps, use the Superpowers planning and subagent-driven-development workflow.
- Use OpenSpec when the project needs durable requirements, acceptance criteria, or spec governance across tasks or sessions before implementation.
- In Plan mode, prepare the architecture, task boundaries, acceptance criteria, verification, and execution routing only. Do not implement changes or mutate external systems in Plan mode.
- For greenfield apps or sites, bootstrap serially until the shared foundation is stable, then split independent frontend, backend, content, testing, and polish work across native Codex subagents.

## Deep planning in Plan Mode

In Plan Mode for non-trivial, ambiguous, architectural, high-risk, or multi-step work, use `$deep-planning` by default before presenting the final plan. If `$deep-planning` is unavailable, follow the same adversarial critique protocol inline: gather observed facts, state assumptions and material unknowns, draft the strongest plan, critique product value, architecture, implementation risk, edge cases, tests, rollout, and scope, revise the plan, then choose Codex-only, native Codex subagents, Superpowers, or OpenSpec routing. For non-trivial plans, keep the final response ordered as Observed Facts, Assumptions / Unknowns, Strongest Plan, Adversarial Review, and Revised Plan / Routing unless the active Plan Mode format is stricter.

Do not use deep planning for tiny edits, simple command-output checks, pure execution, post-code verification, or full Superpowers design-doc workflows. `deep-planning` must not write files, create issues, dispatch workers, refresh schedulers, or write `docs/superpowers/` artifacts.

## Superpowers workflow

For non-trivial coding tasks, prefer the Superpowers workflow.

- If requirements are unclear, use `superpowers:brainstorming`.
- If the task needs multiple implementation steps, use `superpowers:writing-plans`.
- After plan approval, use `superpowers:subagent-driven-development` for bounded multi-step implementation and native Codex subagents for independent parallel work. Use OpenSpec first when durable requirements or acceptance criteria are still needed.
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

The personal toolbox repo is identified by `CODEX_TOOLBOX_ROOT` on each machine, and its GitHub remote is `jialuohu/codex-toolbox`. It is a repo-scoped Codex plugin marketplace named `jialuo-codex-toolbox`.

- Keep plugins focused by domain. Current default plugins are `obsidian-tools`, `research-tools`, `web-data-tools`, `game-asset-tools`, `workflow-tools`, `paper-figure-tools`, `productivity-tools`, `trading-tools`, `vibe-trading-tools`, and `chronicle-tools`.
- The setup script also manages third-party Git marketplaces: `ui-ux-pro-max-skill`, pinned to `v2.10.0` with sparse checkout limited to the core `ui-ux-pro-max` skill, and the official Context7 marketplace `context7-marketplace`. Do not vendor these third-party plugins into `codex-toolbox` unless explicitly asked.
- Do not reintroduce the retired starter plugins `lab-weekly-update` or `context7-docs` unless explicitly asked.
- Do not commit secrets, OAuth state, API keys, or env-file contents. MCP configs may reference `CODEX_SECRETS_DIR`, but the secret files remain per-device.
- Keep toolbox-managed MCP servers in the plugin `.mcp.json` files, not as duplicate direct `[mcp_servers.*]` tables in `~/.codex/config.toml`. The setup script migrates direct entries for managed servers out of the user config.
- After changing the toolbox, run JSON validation for marketplace/plugin/MCP files, scan for sensitive keywords, run `scripts/setup-codex-toolbox.sh`, and verify `codex plugin list --marketplace jialuo-codex-toolbox --json` plus `codex mcp list`. If third-party marketplace management changed, also verify the relevant plugin list, such as `codex plugin list --marketplace ui-ux-pro-max-skill --json` or `codex plugin list --marketplace context7-marketplace --json`.
- Keep `docs/superpowers/` out of the repo; those are local planning artifacts.

## MCP Tool Routing

Prefer MCP servers, connected apps, and installed skills for external services, private knowledge sources, and specialized tool integrations when the task matches an available integration. If a relevant MCP/app/connector is installed but its tools are not visible in the active tool list, call `tool_search` for that exact integration before falling back. Use normal local tools such as `rg`, package scripts, tests, and `git` for checked-out repos, memory files, private filesystem content, and ordinary local codebase work. Use the narrowest tool that naturally owns the data.

Use the `ui-ux-pro-max` skill for UI/UX design intelligence: page and component design, visual polish, design-system recommendations, accessibility review, typography/color decisions, layout critique, dashboard/landing-page structure, and frontend experience quality checks. Treat its recommendations as advisory; local Codex frontend instructions, the target repo's design system, and explicit user direction override any conflicting upstream skill guidance.

Use Context7 for current, version-aware library and framework documentation, API references, migration examples, and code examples from package docs. Prefer Context7 over general web search when the task is about how to use a specific library or framework. Use Firecrawl instead for broad public web search, arbitrary pages, crawls, site maps, and documentation extraction that is not covered by Context7. For OpenAI/Codex product behavior, prefer official OpenAI/Codex docs before Context7 or generic web search.

Use Firecrawl as the default for public web search, current web pages, documentation scraping, site maps, crawls, structured extraction from websites, pages that need JavaScript rendering, and public web extraction. If Firecrawl tools are not visible, call `tool_search` for Firecrawl before using built-in web search; if `firecrawl_search` is still not exposed, retry with exact terms such as `firecrawl_search scrape web search` and a larger result limit before falling back. After using `firecrawl_search`, call the Firecrawl feedback tool only when that tool is exposed. Do not use Firecrawl for the user's private local files, saved Zotero library, Obsidian vault content, or other private workspace data unless the user explicitly asks to send that content to Firecrawl.

Use `$wechat-digest` for configuring selected WeChat Official Account subscriptions and for reading their new articles, daily updates, or digest summaries through the BestBlogs-backed state workflow. This route takes precedence over the general Firecrawl default when the request concerns configured subscriptions or incremental updates. Use Firecrawl only through the skill's validated per-article fallback after the required claim and renewal gates; do not substitute generic search or scraping for subscription scanning, baseline state, deduplication, or acknowledgment. For a user-supplied standalone article URL or a historical or topical search that does not depend on subscription state, use Defuddle or Firecrawl as appropriate.

Use `$mineru-document-extraction` for complex, scanned, OCR-heavy, or layout-sensitive local documents when a simple reader may lose columns, tables, formulas, figures, or page structure. Prefer the installed `pdf` or `documents` skill for straightforward born-digital files and simple reads, Zotero for an item already saved in the user's library, Defuddle or Firecrawl for web content, and `obsidian_files` only for vault I/O after extracted content has been reviewed. MinerU is a local skill plus `scripts/setup-mineru.sh`, not an MCP server: start with `scripts/setup-mineru.sh --check`; run `--install` and then the opt-in `--download-models` only when local setup is requested. Keep model caches, extraction outputs, and benchmarks outside the Git checkout and any Obsidian vault. Follow the skill's high-to-medium and hybrid-to-pipeline fallbacks explicitly; if MinerU remains unavailable for a complex document, report the limitation instead of silently degrading to a simple extractor.

Use PixelLab MCP (`pixellab`) only for pixel-art game asset workflows: sprites, character rotations, animations, top-down or sidescroller tilesets, isometric tiles, and map objects. Do not use PixelLab for web search, private/local files, normal coding, or generic image generation unless the user explicitly asks for PixelLab assets. Creation and destructive tools can spend credits or change saved assets, so keep them prompt-gated unless the user explicitly confirms the action.

Use `$paper-figure-workflow` for AI/systems paper figure workflows: editable draw.io or diagrams.net pipeline diagrams, Matplotlib and SciencePlots plots, Inkscape cleanup or SVG/PDF conversion, `figures_src/`, `figures/`, and reproducible commands such as `make figures`.

Use `$paper-library-intake` when one paper named by title, DOI, arXiv ID/URL, or publisher URL must be found, checked against Zotero, classified, added, or repaired. Search Zotero first for the private-library state, use Firecrawl first for public discovery and canonical-page inspection, then use Paper Search for scholarly cross-checks and lawful open-access retrieval. `find`, `check`, and `explain` are read-only. An explicit `add`, `save`, or `import` request authorizes only that paper's parent item, lawful attachment, suitable topical memberships, `Research/ReadLater`, and the skill's bounded missing-topic creation; it does not authorize merge, delete, semantic indexing, or unrelated cleanup. Follow the skill's WebDAV/Zotero-Storage preflight and readable-PDF completion rule.

Use `paper_search_mcp` for structured academic cross-source validation and lawful open-access retrieval across arXiv, Semantic Scholar, CORE, IEEE, Unpaywall, CrossRef, PubMed, BASE, and related sources. In the paper-library intake workflow, Firecrawl remains the first public discovery path and Paper Search is the cross-check/retrieval layer. The toolbox disables direct Sci-Hub and the upstream generic fallback whose default enables Sci-Hub; prefer source-native OA downloads. If another generic fallback is present, always set `use_scihub=false`.

Use Zotero MCP for the user's saved research library: collections, item metadata, saved full text, PDFs, notes, annotations, and library search. Use Zotero first when the question may concern an already-saved paper. Treat Zotero mutation/control tools as library mutations: an explicit scoped add/save/import request confirms that paper's intake mutations; otherwise confirm before adding items, creating annotations, updating semantic indexes/databases, switching libraries, deleting, or changing saved library content.

Use the Todoist app or Todoist MCP with `$todoist-task-planning` for personal task capture, deadlines, task review, and task status changes. Prefer the connected Todoist app; use the hosted MCP as a Codex CLI fallback, and never perform the same operation through both. Todoist is the authoritative personal task store; do not use conversation history as a task database. Deadline-only tasks stay in Todoist. Use Google Calendar only for explicit meetings or time blocks, confirm before calendar writes or invitations, and do not create meeting follow-up tasks unless the user asks or supplies a concrete action item.

Use `obsidian_files` for unattended local Obsidian vault reads, searches, note creation, and note edits under `CODEX_OBSIDIAN_VAULT`. Prefer line-based `edit_file` changes for existing notes; use whole-file overwrite only for new files or when explicitly requested. Never move, delete, or broadly rewrite vault files unless the user explicitly asks and the relevant tool is enabled. Prefer the installed Obsidian skills for Obsidian Markdown syntax, Bases, JSON Canvas, and official CLI guidance. Do not use a Local REST API Obsidian MCP unless it is explicitly re-enabled.

Use Vibe-Trading MCP for finance research, backtests, factor analysis, market screening, research swarms, trade-journal analysis, and Shadow Account reports. Its optional Codex override file lives under `CODEX_SECRETS_DIR`; native Vibe-Trading config, run history, connector profiles, and state live under `VIBE_TRADING_HOME`. Treat Vibe-Trading connector setup, OAuth, broker-profile selection, and any live-trading adjacent action as explicit-confirmation work.

Use Robinhood Trading MCP (`robinhood-trading`) for official Robinhood Agentic account workflows: connecting the Robinhood Trading MCP, reading Robinhood Agentic account data, and user-requested Agentic trading actions. Prefer Robinhood's official Streamable HTTP MCP endpoint over unofficial Robinhood packages or local wrappers unless the user explicitly asks for an unofficial package. Treat Robinhood order placement, cancellation, rebalance, strategy deployment, or account disconnection as live-financial actions; only perform them when the user explicitly asks for that action and accepts the execution risk.

Use Alpaca MCP only for direct Alpaca account, market data, trading, assets, crypto, options, and news workflows. Keep reads scoped to account, market-data, and trading questions. Treat Alpaca account/order mutation tools as live-financial actions; do not place, replace, cancel, exercise, close, liquidate, or update account settings unless the user explicitly asks for that action and approves it.

Use GitHub connector tools or `gh` for GitHub issues, pull requests, remote repository metadata, review comments, Actions status, and PR creation/update workflows. Use local `git`, `rg`, tests, and filesystem tools for checked-out code and local history unless remote GitHub state is needed.

Use Google Drive, Google Docs, Google Sheets, Google Slides, Gmail, and Google Calendar connected apps for the user's workspace data when the task is about those services. Confirm before sends, deletes, sharing/permission changes, calendar scheduling or RSVP changes, moving files, or other user-visible mutations. Use local document/spreadsheet tools only for local files or generated artifacts that are not already in a connected workspace app.

Use Clay only for GTM, account, prospecting, CRM, enrichment, and company/contact research workflows. Do not spend enrichment or data-point credits unless the user explicitly asks for that specific enrichment. For the user's own accounts or deals, prefer Clay account tools over public company enrichment when account access is available.

Use `node_repl` for JavaScript execution, quick Node-based inspection, and browser-control workflows that explicitly call for the in-app browser or Chrome automation. Prefer `node_repl` with the browser/Chrome plugins for browser automation when available. Use Computer Use only when the task requires operating a local Mac GUI app directly.

For OpenAI/Codex product behavior, prefer official OpenAI/Codex docs over Context7 or generic web search.

For MCP servers, keep API keys, tokens, passwords, and similar secrets in files under `CODEX_SECRETS_DIR` and source those files from the MCP command wrapper. Do not put secrets directly in Codex config files.
