---
name: sync-toolbox
description: "Sync and apply the latest published codex-toolbox to this machine, or check whether its checkout and installed setup are current."
---

# Sync Toolbox

Apply published `jialuohu/codex-toolbox` through its existing full setup. A clear
request to update this machine authorizes this local sequence. Sync never
stages, commits, pushes, or invokes `ship-toolbox`; publishing is a separate task.

## Inspect first

- Resolve the checkout from `CODEX_TOOLBOX_ROOT` or the user's repository
  context. Verify its Git root and normalized `origin` identify exactly
  `jialuohu/codex-toolbox`; do not guess another checkout or clone a replacement.
- Inspect branch, upstream, and `git status --porcelain`, including untracked
  files. Applying requires clean `main` tracking `origin/main`. Stop on another
  branch, local changes, unpublished commits, or divergence. Never switch
  branches, stash, reset, rebase, or repair history automatically.
- Record the current SHA, toolbox plugin names, versions and enabled flags from
  `codex plugin list --marketplace jialuo-codex-toolbox --json`, and marketplace
  source/root from `codex plugin marketplace list --json`. Keep temporary
  receipts outside the checkout; do not copy credentials or full configuration.
- For a status-only request, use read-only inspection and `git ls-remote origin
  refs/heads/main`. Do not fetch, fast-forward, refresh, install, or authenticate.
  If the remote commit is unavailable locally, report the comparison limits.

## Select and apply a published revision

1. For an update, run `git fetch origin main`, then
   `git rev-list --left-right --count origin/main...HEAD`. The first count is
   remote-only commits; the second is local-only commits. Continue only when
   the second is zero. Record the full `origin/main` SHA as the selected revision.
2. Inspect relevant GitHub Actions for that exact SHA and the applicable
   workflow definitions. Wait for required runs to succeed. Failed, cancelled,
   missing, or inaccessible required evidence blocks setup; do not substitute
   an older green run. If no relevant workflow applies, say so and continue
   without claiming CI passed.
3. Recheck clean state and fast-forward with `git merge --ff-only <selected-sha>`
   when behind. When already current, skip the merge and still apply setup.
   Require `HEAD` to equal the selected revision before continuing.
4. Run `scripts/setup-codex-toolbox.sh` from that committed checkout. Use the
   production Git-backed marketplace on `main`; do not silently accept a local
   development mode or a different source/ref override. The setup script owns
   managed instructions, pets, default plugins, runtime dependencies, stale
   configuration migrations, and third-party marketplace pins. Do not duplicate
   those mechanisms or broaden them to unrelated plugins or accounts.
5. Compare the installed toolbox plugins with the selected revision's plugin
   manifests. Include previously installed optional plugins, not just setup
   defaults. Marketplace upgrade may already refresh them; only repair remaining
   mismatches, using the setup script's scoped `codex plugin remove` / `codex
   plugin add` sequence. Preserve optional-plugin selection and enabled flags;
   verify a supported way to restore a disabled flag before replacing that plugin.
   If an optional plugin disappeared upstream, report it rather than deleting it.

## Verify and report

- Require the toolbox marketplace to use Git source
  `https://github.com/jialuohu/codex-toolbox.git` and ref `main` (inspect only the
  relevant config fields if the CLI omits the ref). Resolve its reported root
  and compare its Git SHA with the selected revision, checkout `HEAD`, and a
  fresh remote `main` SHA. A concurrent advance or unavailable SHA comparison
  means incomplete synchronization; do not silently claim a different revision.
- Verify every setup default and previously installed toolbox plugin against
  its expected version and enabled state. Check the installed files for newly
  added or changed skills, not just the marketplace listing.
- Run `scripts/sync-agents.sh --check`,
  `python3 scripts/sync-codex-pets.py --check`, third-party plugin listings for
  marketplaces refreshed by setup, and `codex mcp list`. A successful MCP listing
  proves configuration discovery, not authentication or server health; report
  runtime/authentication results separately using available setup evidence.
- Report the before/after SHA, CI evidence, setup result, installed version
  changes, instruction/pet checks, and remaining limitations. Never claim
  completion from a successful Git update alone.

## Interrupted setup

Stop at a failed setup step and report completed stages separately. Keep the
selected SHA and plugin receipt for recovery; rerun from that same committed
revision after resolving the cause. If remote `main` has moved, reselect and
verify its CI before a new attempt instead of mixing revisions. Never bypass
failed checks, remove live runtime locks, or terminate active services. If a
lock requires user action, identify its owner and ask the user to close it.
