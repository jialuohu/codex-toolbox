# OmniGraffle and LaTeXiT cleanup

Before `doctor --probe-app`, `getApp`, `open`, or any native command that can send AppleEvents, capture a non-launching inventory of running app instances and windows/documents. Record their identities and saved/modified state when available. A probe can launch OmniGraffle; an inventory taken afterward is not an initial baseline. If initial state is unavailable, treat ownership as unknown.

Record each task launch and the resulting exact app instance and window/document identity. An inventory difference, title, URL, or filename alone does not prove ownership. Keep this evidence across the task's commands, including probes delegated by the paper-figure workflow. Preserve pre-existing apps and windows, restored documents, and anything subsequently opened or changed by the user.

The backend already closes verified private working copies and idle task-owned LaTeXiT editors. Retain those guards. Do not repeat its close operations or close a retained working copy to bypass reconciliation.

On completion or failure, when control is available:

1. Verify the saved native source and exports before closing an ordinary output preview; return their file links. Close only an exact task-created window still known to be saved and idle. An explicit open/show/keep-open request or active interactive handoff keeps the requested deliverable open.
2. Preserve any unsaved, busy, ambiguous, or unexpected window/dialog. An unknown mutation outcome remains open for `reconcile`; do not retry the mutation or dismiss a save prompt. A failed begin/render may have queued native work even when no successful ownership receipt returned.
3. Use a supported normal quit only for a proven task-started app still matching the recorded instance, after confirming no pre-existing, user-created, new/untracked, unsaved, busy, or pending windows/documents/dialogs remain and no operation awaits reconciliation. Otherwise leave the app running. Never force-quit, use `killall`, or launch an absent app merely to clean it up.
4. Verify closure with a non-launching observation. Bound cleanup attempts; if identity, state, access, or completion cannot be verified, preserve the resource and report what remains and why. Keep the original operation result and reconciliation instructions.

Use only available documented native or Computer Use close/quit actions. This reference adds no CLI command and does not grant permission to change preferences or permissions.
