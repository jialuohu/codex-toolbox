# Tasks, courses, and daily briefs

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Canvas Student Planning](#canvas-student-planning)
- [Todoist Task Planning](#todoist-task-planning)
- [Daily Command Center](#daily-command-center)

## Canvas Student Planning

The opt-in `canvas-tools` plugin packages `canvas-mcp==1.12.0` with a positive
student-only tool allowlist. `$canvas-student-planning` reads courses,
assignments, due dates, grades, submission state, and peer reviews; it can also
perform guarded assignment submissions and explicitly reconcile incomplete
assignments into Todoist without claiming continuous synchronization.

`$canvas-overleaf-homework` prepares one Canvas-linked assignment in a configured
Overleaf project from selected questions on a user-supplied public source. It
preserves the exact problem wording and original figures, compiles a temporary
LaTeX snapshot before guarded sequential writes, resolves the displayed deadline
from Canvas with a Todoist fallback, and adds a duplicate-safe Overleaf link to
the assignment task. It does not solve or submit the homework.

Canvas credentials remain outside Git in
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/canvas-tools/canvas.env`.
The file must be owned by the current user with mode `600` and contain an HTTPS
`CANVAS_API_URL` ending in `/api/v1` plus `CANVAS_API_TOKEN`. Canvas personal
tokens inherit the permissions of their account, so never paste one into chat or
place it in command arguments, logs, or repository files. See
[`plugins/canvas-tools/README.md`](../plugins/canvas-tools/README.md) for setup.

```bash
codex plugin add canvas-tools@jialuo-codex-toolbox
```

Start a fresh task after installation. Canvas writes remain prompt-gated;
assignment submission additionally requires the upstream full preview and
single-use confirmation token. Todoist writes use the existing
`$todoist-task-planning` workflow and one Todoist surface. Overleaf homework
setup also requires the configured `overleaf-tools` plugin and `$latex-compile`.

## Todoist Task Planning

The default `productivity-tools` plugin bundles `$todoist-task-planning` and
Todoist's official hosted MCP at `https://ai.todoist.net/mcp`. Prefer the
connected Todoist app in ChatGPT or Codex Desktop. The hosted MCP is the Codex
CLI fallback when app tools are unavailable; use one Todoist tool surface per
request so a task is never written twice.

Todoist remains the durable source of truth for tasks; Google Calendar is used
only for explicit meetings and focused work blocks. Deadline-only tasks stay in
Todoist, including deadlines with a clock time.

If the connected app is unavailable in a CLI session, authorize the hosted MCP
on that device:

```bash
codex mcp login todoist
```

Start a fresh Codex task after login. Example requests include:

```text
Add "submit expense report" to my Todoist for Friday.
Block two hours tomorrow afternoon to work on the proposal.
Schedule a 30-minute remote check-in with Alice next Tuesday at 2 PM.
Show my overdue tasks and what is due this week.
```

Task creation is allowed when explicitly requested. Calendar writes, attendee
invitations, deletions, and ambiguous updates remain confirmation-gated. A
one-time task/event cross-link is not ongoing bidirectional synchronization.

## Daily Command Center

Use `$daily-command-center` for a read-only daily brief that brings together
Gmail context, Google Calendar commitments, and Todoist priorities. It reads
the connected sources on each run, keeps Todoist authoritative for actionable
tasks and Calendar authoritative for time commitments, and proposes follow-up
actions without changing email, calendar, or task records.

Invoke it manually when you want a morning or daily planning pass:

```text
Use $daily-command-center to prepare my read-only daily brief.
```

It can also be used from a scheduled task at your preferred local time. The
scheduled run remains read-only and reports partial coverage if a connected
source is unavailable; use the relevant interactive workflow for any later
email, calendar, or Todoist change.
