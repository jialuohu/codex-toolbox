# Global setup

Perform setup in execution mode on a setup request. Setup is shared by all
workspaces using this Codex installation. No project path or pre-existing
conversation is needed. Global readiness records a successful check, not a
permanent guarantee of login, quota, or model availability.

## Verify the browser

Use the user-selected supported browser and signed-in ChatGPT account. Prefer an
already connected, signed-in browser; this installation was verified with Brave.
Supported preference names are `brave`, `chrome`, `edge`, and `iab`; select the
matching current browser inventory entry, never a stale numeric browser ID.
Read its current tool documentation. If signed out, show that exact automation
tab and let the user sign in there. A different browser or panel may not share
its session. Do not read credentials, cookies, or private application state.

Create a blank ChatGPT tab and use visible controls to select **GPT-6 Pro**.
The current UI displays this as **6 Pro**: select Latest, then adjust the Power
menu item until its visible label is 6 Pro (Pro, 5 of 5). Use the observed menu
item's arrow-key controls; do not hardcode clicks or assume High means Pro.
Do not guess model URL parameters, infer Pro from subscription status, or
substitute another model. If the visible controls cannot establish the exact
model, leave setup unavailable and explain what remains.

Use a fresh UUID as the setup task ID. The helper namespaces setup tasks separately
from ordinary Codex tasks. Send a fixed harmless probe using the transport
procedure with `--mode default --setup-probe`:

```text
python3 scripts/planner_state.py plan --task-id <setup-uuid> --mode default --setup-probe --model-confirmed
```

Supply the normal five-field packet on stdin; the helper replaces all fields with
synthetic setup data before constructing the prompt. The returned prompt requests
READY with exact request markers. Reserve first, send once through the browser,
and observe its exact visible request and response as described in
[transport](transport.md). Never use the setup exception for real planning.

Only after the helper accepts the completed probe, enable global readiness:

```text
python3 scripts/planner_state.py setup --mode default --request-id <completed-probe-id> --browser brave
python3 scripts/planner_state.py status
```

There is no per-project binding and no mandatory app restart for model verification.
The browser's selected-model control and accepted probe are the verification basis.
A flag records an actual observation; it does not manufacture evidence. Keep the
probe conversation in ChatGPT; do not delete user history as cleanup.

The first real Plan-mode task creates its own conversation, never reuses the setup
probe. Check native access during the probe if available, but failure does not
prevent browser-only setup. Native tools do not independently establish model
identity. Recheck visible model selection before each later consultation.

## Legacy migration

`status` reads version-1 state without changing it. A deliberately requested setup
probe migrates resolved state under a lock, writing a private, durable
`state.v1.backup.json` before creating version-2 global state. Existing project
bindings are not promoted to task conversations or global readiness.

Pending legacy requests block migration. Inspect and reconcile through the old
installed helper when available. If the user explicitly requests abandonment
after confirming the remote request has stopped, the new helper supports:

```text
python3 scripts/planner_state.py abandon --mode default --legacy --request-id <legacy-id> --confirm-abandon
```

Never infer abandonment from silence or timeout. Keep the old state and backup
outside Git. A conflicting backup or invalid permissions requires investigation,
not overwrite. Retired `bind`, `verify`, and `--project` calls are not accepted by
the new CLI, so stale callers fail visibly rather than creating project state.

## Private state and installation

Default state: `${CODEX_HOME:-$HOME/.codex}/state/chatgpt-planner`; unset/empty
CODEX_HOME uses the home directory default. Directory permissions must be 0700
and files 0600. Reject relative paths, symlink roots, and paths inside Git.
Use `--state-dir <absolute-private-directory>` consistently if needed. Do not
copy active coordination state between hosts.

Keep automatic routing concise in the managed global AGENTS source and detailed
behavior in this skill. Install through the supported toolbox setup path and
verify the installed version and effective global instructions in a fresh task.
Do not overwrite bundled skills or treat a source edit as a completed rollout.
If browser sign-in or a live probe is unavailable, report implementation and
live readiness separately.
