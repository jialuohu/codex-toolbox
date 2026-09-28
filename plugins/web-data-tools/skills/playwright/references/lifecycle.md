# Session ownership and cleanup

Read this before any browser command. This toolbox-owned contract also applies
to the unscoped examples in the imported CLI and workflow references. It grants
no additional navigation, form-submission, download, or other mutation authority.

## Select and record the session

For new automation, generate one unpredictable task-specific session name using
the entrypoint's `node:crypto` UUID command. Pass `--session "$PW_SESSION"`
explicitly on every browser command, including cleanup and copied examples.
Retain that exact value across calls. Do not use the default session or assume
an inherited `PLAYWRIGHT_CLI_SESSION` belongs to this task.

Record the persistent Codex task ID, exact session name, whether this task created
the CLI session through `open` or `attach`, and the creation result in task context.
A name prefix alone is not ownership evidence. A session selected by the user or
inherited from another task is borrowed: use only the authorized scope and do not
close or detach that existing session. For new work, create a separate generated
session instead of restarting a borrowed one.

`open` creates a browser owned by that CLI session. `attach` creates a control
session for an external browser; the browser and its existing tabs remain borrowed.
Attaching under a fresh generated name owns only the new control session. Record
any task-created tabs separately if they need cleanup through an available
documented tab API; never infer ownership from a title, URL, or tab index alone.

## Finalize or hand off

Run this check after success, failure, cancellation, or a task/mode transition,
including when no final screenshot was produced. Reconcile an uncertain command
before deciding cleanup is safe; do not blindly retry a mutation or add an
unconditional shell exit trap that can discard unfinished work.

| Observed state | Action |
| --- | --- |
| Owned `open` session; outputs saved and verified; no pending work | `"$PWCLI" --session "$PW_SESSION" close` |
| Owned `attach` control session; no pending work | `"$PWCLI" --session "$PW_SESSION" detach`; leave the external browser running |
| Borrowed session or missing creation evidence | Preserve it; report cleanup as unverified if relevant |
| Explicit request to open, show, keep open, or hand off a live browser | Retain the requested session/tab and record its identity and reason |
| Unsaved user work, pending downloads, unresolved operations, or unknown outcome | Preserve the affected session/tab for reconciliation; report the blocker |

Creating a screenshot, PDF, or other saved output alone is not a request to leave
the browser open. Default to cleanup after verifying that output; an explicit
live handoff overrides that default. Stop an owned trace/recording and verify its
saved artifact before teardown. If ownership changes through user interaction,
reassess before closing; do not discard unsaved state.

After scoped `close` or `detach`, inspect `"$PWCLI" --session "$PW_SESSION" list`
and confirm that exact session is no longer running. Record a short receipt:
session name, owner task, action (`closed`, `detached`, `retained`, or `unverified`),
observed result, and retention/blocker reason when applicable. A command exit
alone does not establish cleanup. A failed observation is `unverified`, not success;
do not escalate to broad process cleanup.

Never use `close-all`, `kill-all`, `delete-data`, profile deletion, browser-wide
quit, or process-name killing as task cleanup. Preserve cookies, profiles,
downloads, saved artifacts, and unrelated sessions. Lost tool access does not
authorize a different browser-control route or a global shutdown.

## Verified command semantics

The local `@playwright/cli` 0.1.21 runtime documentation and dispatcher were
inspected for this contract. The pinned upstream
[session management reference](https://github.com/microsoft/playwright-cli/blob/74354ecc7a43da16d91a9bc54fa8db8283a3fcf5/skills/playwright-cli/references/session-management.md)
documents named `close`, `detach` for attached sessions, and the separate
destructive `delete-data` command. Headed sessions stay open; headless sessions
normally expire after one idle hour. Idle timeout is not task cleanup. Check the
resolved version's help if it differs; do not guess unsupported commands.

Instruction tests validate these requirements without launching a browser. They
do not prove runtime cleanup, process exit, or reduced RAM use.
