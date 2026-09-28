# Draw.io page and app cleanup

Before `getApp`, `open_drawio_*`, the Desktop helper, or another open/launch action, capture a non-launching inventory of existing pages, app instances and windows. Record exact task-created handles or IDs when the creating tool returns them. Preserve pre-existing resources and later user activity; an inventory difference, matching URL, title, or file path alone is not ownership proof.

Reuse the task's editor instead of opening another browser tab or Desktop window for the same artifact. When a supported browser workflow is available, prefer an owned Computer Use page with its exact returned handle/ID. Do not invent MCP output arguments to obtain a URL or suppress opening, and do not open a second page to compensate for a missing receipt. The MCP OS-open path and Desktop `--open` do not provide a stable page/window ownership receipt; if ownership cannot be verified, keep that resource and report the limitation.

On completion or failure, when control is available:

1. Save and verify the `.drawio` source and requested exports, then deliver file links. Close only an exact task-created preview page/window that is still saved and idle. Keep the requested deliverable open for an explicit open/show/keep-open request or active interactive handoff.
2. Use the supported close action for the recorded handle/ID after rechecking its identity and state. Preserve unsaved edits, busy exports, changed or unknown pages/windows, and dialogs. Never dismiss a save prompt; an unknown mutation outcome must be resolved before cleanup that could discard work.
3. Normally quit Desktop only if this task demonstrably started that same app instance and no pre-existing, user-created, new/untracked, unsaved, busy, or pending windows/dialogs remain. A returned export command does not prove app ownership or isolation from an existing instance. Never quit a shared browser, force-quit an app, or use `killall`.
4. Verify closure without launching anything. Bound attempts and report resources left open when identity, saved state, access, or completion is unverified. Preserve the original failure and saved artifacts.

The Desktop helper has no close/quit API. Use only available documented browser or native controls; do not invent helper flags or process-management commands.
