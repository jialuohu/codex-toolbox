---
name: ship-toolbox
description: Validate, commit, and push task-scoped changes in the jialuohu/codex-toolbox repository on main, then refresh and verify the local Git-backed marketplace. Use only when explicitly invoked as $ship-toolbox after adding or updating toolbox plugins or skills. Do not use for ordinary commits, feature branches, pull requests, tags, releases, rebases, force pushes, or unrelated repositories.
---

# Ship Toolbox

Ship one completed toolbox change from the synchronized `main` branch through
validation, an explicit scoped commit, remote verification, relevant CI, local
setup, and installed-state verification. Treat invocation as authorization for
this task-scoped sequence only.

## Boundaries

- Operate only in the `jialuohu/codex-toolbox` repository identified by
  `CODEX_TOOLBOX_ROOT`, its Git root, and its `origin` remote.
- Use `main` with upstream `origin/main`. Do not create or switch branches,
  pull requests, tags, or releases.
- Do not rebase, amend, force-push, reset, revert automatically, or rewrite
  published history.
- Never stage unrelated work. Never use `git add .` or `git add -A`.
- Never commit secrets, OAuth state, API keys, credentials, environment-file
  contents, generated runtime state, or private paths.
- Stop when scope, repository identity, ownership of a change, or recovery
  state is ambiguous.

## 1. Establish Repository and Recovery State

1. Resolve the Git root and confirm the normalized `origin` is exactly
   `jialuohu/codex-toolbox`.
2. Confirm the current branch is exactly `main` and its upstream is
   `origin/main`.
3. Fetch `origin/main`, then inspect ahead/behind counts with
   `git rev-list --left-right --count origin/main...HEAD`.
4. Stop if `main` is behind or diverged. Do not pull, merge, or rebase.
5. Require synchronized `main` for a new release. Permit an ahead-only state
   solely as push-failure recovery when every unpushed commit is clearly part
   of the active task; otherwise stop.
6. Inspect status plus staged and unstaged diffs. Derive an explicit
   task-scoped path and hunk list from the active request. Preserve clearly
   unrelated changes unstaged; stop for ambiguous mixed changes or overlapping
   hunks.

## 2. Validate the Exact Release Scope

Run all repository gates before a new commit:

1. Parse marketplace, plugin, MCP, and other changed JSON files.
2. Run `git diff --check` and shell syntax checks for changed shell scripts.
3. Run `python3 scripts/check-codex-toolbox-setup.py`.
4. Run `scripts/privacy-audit.sh current`.
5. Run the affected plugin's validators, unit tests, contract tests, and
   integration tests when present.
6. Run the full repository suite with
   `python3 -m unittest discover -s tests`.

When unrelated worktree changes exist, stage only the task-scoped paths and
hunks first, export the index to a temporary Git-backed snapshot, and run gates
that would otherwise observe the dirty worktree against that exact snapshot.
Do not weaken a gate because an unrelated change makes the working tree fail.
Do not push when any required gate fails.

## 3. Stage, Review, Commit, and Push

1. Stage only explicit paths with `git add -- <path>...`. Use interactive hunk
   staging for a shared file when needed.
2. Review `git diff --cached --name-status`, the staged diff, and
   `git diff --cached --check`. Confirm every staged hunk belongs to the task.
3. Derive a concise Conventional Commit message from the staged intent.
4. If the staged diff is non-empty, commit and run `git push origin main`
   without requesting another confirmation; explicit invocation already
   authorizes these task-scoped actions.
5. Verify `git rev-parse HEAD` exactly matches `git ls-remote origin
   refs/heads/main`.

If there is no staged change, do not create an empty commit. When local and
remote `main` already match, continue directly to refresh verification. In an
approved push-failure recovery state, push the existing verified commit rather
than creating another commit.

## 4. Require Remote Evidence

- Locate relevant GitHub Actions runs for the pushed SHA when `gh` is
  authenticated and applicable workflows exist.
- Wait for the relevant runs to complete. Continue only after they succeed.
- If CI fails, report the commit SHA, run URL, failing job, and available log
  evidence. Stop before local refresh; do not revert or rewrite the push.
- If no relevant workflow exists, state that explicitly and continue without
  claiming CI passed.

## 5. Refresh and Verify Locally

1. Run `scripts/setup-codex-toolbox.sh` from the committed tree. If unrelated
   worktree changes remain, use a clean export of `HEAD` so they cannot enter
   local configuration.
2. Verify `codex plugin marketplace list --json` reports
   `jialuo-codex-toolbox` with `sourceType` equal to `git`, source
   `https://github.com/jialuohu/codex-toolbox.git`, and ref `main` when shown.
3. Verify `codex plugin list --marketplace jialuo-codex-toolbox --json` reports
   every affected plugin installed, enabled, and at its expected version.
4. Verify newly added skill files exist under the installed plugin source.
5. Require `codex mcp list` to succeed. If third-party marketplace management
   changed, verify those marketplace plugin lists too.

Do not remove a live runtime lock or terminate an active service to force setup.
Ask the user to close the owning task, then rerun setup from the same committed
SHA.

## Failure and Reinvocation Scenarios

- **Wrong branch:** Stop without staging, committing, pushing, or refreshing.
- **Behind or diverged:** Stop and report the counts; never repair history
  automatically.
- **Ambiguous mixed changes:** Stop and request an exact scope. Keep unrelated
  paths and hunks unstaged.
- **No-change refresh:** When `HEAD` equals `origin/main`, skip commit and push,
  then rerun setup and installed-state verification.
- **Push failed:** Keep the local commit. On reinvocation, validate and push
  that same ahead-only commit without an empty follow-up commit.
- **CI failed:** Report the published SHA and failure, withhold setup, and
  resume from CI verification after a task-scoped fix is published.
- **Post-push setup failed:** Report remote and CI success separately from the
  incomplete local refresh. On reinvocation, rerun setup and verification for
  the same SHA without committing again.
- **Privacy or test gate failed:** Stop before commit and identify the failing
  gate without bypassing it.

## Completion Receipt

Report the commit subject and SHA, push target, remote-SHA match, relevant CI
result and URL, setup result, affected installed plugin versions, Git-backed
marketplace evidence, MCP-list result, and any preserved unrelated changes or
remaining uncertainty.
