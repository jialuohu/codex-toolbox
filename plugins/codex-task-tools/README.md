# Codex Task Tools

This plugin exposes a local MCP for existing-project lookup, explicit task
creation, task status, and pending-request responses. Its managed broker keeps
the App Server connection and private retry ledger alive after an MCP call
returns. The task creator needs an explicit user request and a canonical backend
project reference.

See the [usage and setup guide](../../docs/codex-tasks.md) and the
[owning skill](skills/codex-task-creation/SKILL.md). The Python package and
locked dependencies are in `server/`. Task receipts and the service wrapper
belong under the user's private Codex state directory, outside Git.
