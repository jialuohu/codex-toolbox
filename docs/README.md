# Documentation

[Repository](../README.md) · [Repository rules](../AGENTS.md)

Choose the guide for your task; there is no need to load every guide.
Commands run from the repository root. Guides cover setup and usage; the owning
`plugins/<plugin>/skills/<skill>/SKILL.md` defines the full execution contract.

| Task | Guide covers |
|---|---|
| [Install or update](setup.md) | Device prerequisites, authentication, sync, instructions, pets |
| [Create diagrams](diagrams.md) | Archify, Mermaid, draw.io, OmniGraffle, paper figures |
| [Use Mail.app](apple-mail.md) | Local accounts, indexing, attachments, drafts |
| [Use explicit multi-account Gmail](gmail.md) | gws installation, OAuth, account profiles |
| [Edit Overleaf projects](overleaf.md) | Git-backed setup and guarded edits |
| [Use Docmost or mirror Lab Wiki](docmost.md) | SSO, runtime recovery, guarded writes, Obsidian mirror |
| [Design visuals or slides](design.md) | Motion, photo workflows, Stevens presentations |
| [Plan tasks or coursework](productivity.md) | Canvas, Todoist, read-only daily briefs |
| [Find, save, or read papers](research.md) | Zotero intake, private reviews, PaperRead, MinerU |
| [Extract public pages](web.md) | Firecrawl routing and credit limits |
| [Inspect Coder workspaces](coder.md) | CLI authentication and read-only access |
| [Plan or explain work](workflows.md) | Plan-mode Pro consultation, Claude second opinions, explanations |
| [Recover Codex sidebar mappings](../plugins/workflow-tools/skills/recover-codex-sidebar/SKILL.md) | On-request macOS account-switch recovery, preview, verification, rollback |
| [Develop, validate, or publish](development.md) | Instruction audits, repository checks, explicit shipping |

## Source map

| Source | Owns |
|---|---|
| [Marketplace catalog](../.agents/plugins/marketplace.json) | Available plugins and source paths |
| `plugins/<plugin>/.codex-plugin/plugin.json` | Plugin metadata and version |
| `plugins/<plugin>/.mcp.json` | Managed MCP configuration, when present |
| `plugins/<plugin>/skills/<skill>/SKILL.md` | Triggers, permissions, workflow, validation |
| [Setup script](../scripts/setup-codex-toolbox.sh) | Default installation and migrations |
| [Global instructions](../config/codex/AGENTS.global.md) | Cross-repository response and routing rules |
| [Repository rules](../AGENTS.md) | Development, verification, and shipping rules |
