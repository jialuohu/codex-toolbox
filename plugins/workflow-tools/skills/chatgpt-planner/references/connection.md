# Global setup

Perform setup in execution mode on a setup request. Setup is shared by all
workspaces using this Codex installation. No project path or pre-existing
conversation is needed. Saved setup records a successful check, not a permanent
guarantee of login, quota, or model availability. `status` reports `configured`
separately from `available`; availability is unknown until a live check.

## Verify the browser

Use the machine's current default HTTPS browser unless the user explicitly selects
another browser. `system-default` is a selection policy, not a concrete browser or
proof of a working connection. Resolve it before each new request:

```text
python3 scripts/planner_state.py browser
```

The read-only resolver uses macOS NSWorkspace or Linux's HTTPS MIME association;
it neither launches the browser nor reads profiles, cookies, or account data.
Unsupported or unknown defaults stop selection without falling back to `iab`.
New installations default to `system-default`. Existing installations retain their
saved choice until the user requests a preference change. For an authorized switch:

```text
python3 scripts/planner_state.py prefer-browser --mode default --browser system-default
python3 scripts/planner_state.py browser
```

This saves the preference without asserting readiness or altering any conversation.
`setup.browser` remains the concrete browser that passed the last probe. If the
selected browser differs, complete a fresh probe there before new consultations.
When the OS default changes later, resolve it again and verify it; do not silently
continue in the old browser. Pending requests retain their original browser and
conversation for reconciliation, never a second send in the new default.

Explicit alternatives are `brave`, `chrome`, `edge`, `opera`, `vivaldi`, and `iab`.
Select the matching current browser inventory entry, never a stale numeric ID.
Read its current tool documentation. If signed out, show that exact automation
tab and let the user sign in there. A different browser or panel may not share
its session. Do not read credentials, cookies, or private application state.
If browser tools are missing, check available tool discovery first. An installed or
running browser is insufficient. Follow the [official browser connection steps](https://learn.chatgpt.com/docs/chrome-extension):
connect the selected browser under Settings > Computer Use, enable its toggle,
then attach it to the task with its `@`-mention, using the extension's profile.
These are user UI actions when no browser tools are exposed. Do not claim a code
change connected the browser, change site permissions, or automate the Codex UI.
Inspect inventory again after attachment; if tools remain absent, a fresh task may
be needed. Do not switch browsers to work around missing tools.

For SSH or CLI use, distinguish the shell host from the machine providing GUI
control. Resolve the default on the GUI host; never infer the client laptop's
browser from a remote shell. A desktop connection, enabled feature flag, or a
successful MCP startup does not prove the current CLI task has browser tools.
If extension checks pass but tools are absent, start a fresh CLI task under the
same host account and check its loaded MCP tools. Browser calls require genuine
Codex session and turn metadata; do not fabricate identifiers in a standalone
diagnostic. Do not restart a shared app-server while other work is active without
the user's authorization. See [remote connections](https://learn.chatgpt.com/docs/remote-connections).

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

Supply the five planning fields plus a fresh `connection` observation on stdin,
as described in the [live check](transport.md#live-connection-check). The helper
replaces planning content with synthetic setup data before constructing the prompt
and never sends the connection observation. The returned prompt requests
READY with exact request markers. Reserve first, send once through the browser,
and observe its exact visible request and response as described in
[transport](transport.md). Never use the setup exception for real planning.

Only after the helper accepts the completed probe, enable global readiness:

```text
python3 scripts/planner_state.py setup --mode default --request-id <completed-probe-id>
python3 scripts/planner_state.py status
```

Setup uses the saved preference (initially `system-default`). To select an explicit
alternative, use `--browser <name>` during setup. The resolved selection must match
the concrete browser actually observed for this probe; the OS default is rechecked
at setup completion so a mid-probe change cannot verify the wrong browser.
Old probes without that evidence cannot establish or change the preference;
perform a fresh probe instead. Existing configured installations remain readable.

There is no per-project binding and no mandatory app restart for model verification.
The browser's selected-model control and accepted probe are the verification basis.
A flag records an actual observation; it does not manufacture evidence. Keep the
probe conversation in ChatGPT; do not delete user history as cleanup.
Before calling the connection persistent, repeat the live login/model check in a
fresh task and after an app restart. A successful check in this task alone does
not establish either result; report those checks separately if they cannot run.

The first real Plan-mode task creates its own conversation, never reuses the setup
probe. Check native access during the probe if available, but failure does not
prevent browser-only setup. Native tools do not independently establish model
identity. Recheck visible model selection before each later consultation.

## Legacy migration

`status` reads version-1 state without changing it. A deliberately requested setup
probe migrates resolved state under a lock, writing a private, durable
`state.v1.backup.json` before creating version-3 global state. Version-2 state is
also migrated on the first write, with a private `state.v2.backup.json` that
preserves setup, task mappings, and request history. Status and connection checks
remain read-only. Older helpers must reject version-3 state. Existing project
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
