---
name: symphony-orchestration
description: Plan and operate Codex plus Symphony plus Linear orchestration. Use when the user asks about Symphony, durable multi-ticket Codex execution, Linear-backed task decomposition, large decomposable app/site/project builds, multi-page frontend/backend work, Symphony operations, planner-side Linear issue creation, Symphony MCP tools, worker status monitoring, or handoff/closeout workflows.
---

# Symphony Orchestration

## Overview

Use this skill to decide when Symphony is the right lane and to run the planner/operator workflow
consistently. Symphony is the scheduler and execution layer; Linear is the task graph and dashboard;
Codex remains the planner, reviewer, and integration owner.

## Routing Decision

Default to Codex-only work for a single bugfix, one feature, one review, fast debugging, broad
one-session exploration, or a vague request that has not yet been planned.

For vague or broad project prompts, plan or clarify first. If the resulting plan clearly needs durable
multi-ticket execution, recommend Symphony even when the user did not name Symphony or Linear:

- 3 or more independent, testable tasks.
- Clear acceptance criteria and verification for each task.
- Progress should be visible outside the Codex thread.
- Work can run unattended across time, restarts, or separate workers.
- Worker scopes can avoid file conflicts.

Use native Codex subagents before Symphony for one-session read-only exploration, audits, test
failure triage, and review passes.

For greenfield apps and sites, do a serial bootstrap first when no repo exists or shared scaffolding is
missing. After the scaffold is stable, split independent frontend, backend, content, testing, and polish
work into Symphony issues.

## Local Surfaces

Use these defaults unless the current repo or user says otherwise:

- Symphony repo: `SYMPHONY_ROOT`
- Workflow: `SYMPHONY_WORKFLOW`
- Linear secret file: `CODEX_SECRETS_DIR/symphony-linear.env`
- Installed CLI: `CODEX_LOCAL_BIN_DIR/symphony` or `symphony`
- Daemon state: `http://127.0.0.1:4000/api/v1/state`
- Workspace root: `SYMPHONY_WORKSPACE_ROOT/<issue-key>`

Do not print secrets. Source env files only for commands that need them.

## Workflow Selection

Use the workflow that matches the target repository. The committed
`SYMPHONY_WORKFLOW` is for Symphony Go itself and must not be used for an
unrelated app or website project.

For a new target repo, first dry-run a project workflow:

```bash
symphony workflow init \
  --target-root $TARGET_REPO_ROOT \
  --output $TARGET_REPO_ROOT/WORKFLOW.md \
  --project-slug <PROJECT_SLUG> \
  --team-key <LINEAR_TEAM_KEY> \
  --port 4001 \
  --concurrency 4 \
  --dry-run
```

Write the workflow only after reviewing it. Use a separate port/logs root from the always-on
`symphony-go` daemon when running an unrelated project.

## Planner Workflow

1. State why this is or is not a Symphony task.
2. Decompose into one Linear issue per independently reviewable worker task.
3. For each issue, define title, exact scope, acceptance criteria, verification command, and expected
   files or non-overlap guarantee.
4. Select or create a project-specific workflow before creating issues for any repo other than
   Symphony Go.
5. Confirm the repo has useful tests or review evidence before creating runnable issues.
6. Dry-run issue creation first.
7. Review payloads for project slug, team key, labels, state, acceptance criteria, and verification.
8. Create live Linear issues only after payload review.
9. After execution is approved, do not stop at dry-runs: write the reviewed workflow, create the
   approved issues, and start or refresh Symphony so workers actually run.
10. Monitor `/api/v1/state` for running count, issue identifiers, phase, retry rows, and workspace
   paths.
11. Review handoffs manually unless the workflow explicitly enables draft PR handoff.
12. Apply only reviewed files, run verification, commit/push if appropriate, comment evidence back to
   Linear, and move issues to `Done`.

## MCP Tool Preference

If Symphony MCP tools are visible in the current Codex thread, prefer them for planner/operator
actions:

- `symphony_create_issue`: dry-run or create one issue.
- `symphony_create_issue_batch`: dry-run or create a reviewed batch.
- `symphony_workflow_init`: dry-run or write a project-specific workflow.
- `symphony_state`: read the loopback daemon state API or one issue row.
- `symphony_refresh`: trigger one daemon refresh tick.
- `symphony_handoff_summary`: summarize selected workspace changes before manual handoff.
- `symphony_add_linear_comment`: add reviewed closeout evidence to one Linear issue.
- `symphony_move_linear_issue`: move one Linear issue to a reviewed target state.

Issue creation and closeout tools default to dry-run. Live Linear mutations must pass both
`dry_run: false` and `confirm: true`. Never let a worker use these tools to create follow-up Linear
issues or mutate Linear state from inside an issue workspace.

Workflow initialization also defaults to dry-run. Live file writes must pass both `dry_run: false`
and `confirm: true`.

If MCP tools are not visible, use the CLI fallback. Do not block a pilot on MCP availability.

## CLI Fallback

Dry-run one issue:

```bash
source CODEX_SECRETS_DIR/symphony-linear.env
symphony issue create \
  --workflow SYMPHONY_WORKFLOW \
  --title "<clear task title>" \
  --acceptance "<one concrete acceptance criterion>" \
  --verify "<repo verification command>" \
  --dry-run
```

Create only after reviewing the dry-run payload:

```bash
symphony issue create \
  --workflow SYMPHONY_WORKFLOW \
  --title "<clear task title>" \
  --acceptance "<one concrete acceptance criterion>" \
  --verify "<repo verification command>"
```

Run the daemon:

```bash
source CODEX_SECRETS_DIR/symphony-linear.env
GOCACHE=/private/tmp/symphony-go-build-cache \
  symphony --logs-root /private/tmp/symphony-run-log --port 4000 \
  SYMPHONY_WORKFLOW
```

Run it as a macOS LaunchAgent when always-on operation is intended:

```bash
symphony service install
symphony service start
symphony service status
```

Review handoff:

```bash
symphony handoff \
  --workspace SYMPHONY_WORKSPACE_ROOT/<issue-key> \
  --target SYMPHONY_ROOT \
  --include <relative-file> \
  --patch /private/tmp/<issue-key>.patch
```

## Natural Prompt Examples

The user does not need to say "use Symphony." These are sufficient prompts:

- "Build a polished business website for a small AI consulting agency."
- "Create a SaaS dashboard with auth, billing placeholders, analytics pages, and tests."
- "Modernize this app end to end, including UI polish, backend cleanup, and verification."

For these, first plan the product and technical shape. If the plan produces 3 or more independent,
testable implementation tasks, recommend the Symphony lane and prepare dry-run issue payloads.

## Guardrails

- Keep Symphony out of still-vague, high-judgment, fast interactive, or single-task work.
- Do not auto-run every Linear issue; only explicitly labeled ready issues should run.
- Keep `WORKFLOW.md` manual/default-safe unless the user asks for PR handoff or a pilot needs a
  temporary workflow.
- Use one daemon per Linear scope/logs root.
- For always-on operation, use `symphony service` and verify zero unexpected runnable Linear issues
  before starting launchd.
- Treat status sync as layered: Linear tracks task lifecycle, Symphony tracks worker runtime, Codex
  tracks reasoning and implementation, and GitHub tracks reviewable code output.
- Stop and report if credentials, labels, states, acceptance criteria, file scope, or verification
  evidence are unclear.

## Closeout Evidence

For every completed batch, report:

- Linear issue keys and final states.
- Worker workspace paths.
- Changed files accepted from each workspace.
- Verification commands and results.
- Commit hash or PR URL if code was published.
- Final scheduler state showing no stale `running` or unexpected `retrying` rows.
