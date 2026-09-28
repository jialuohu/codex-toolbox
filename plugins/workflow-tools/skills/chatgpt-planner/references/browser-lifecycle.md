# Browser ownership and cleanup

Read this before browser work, including setup probes and live status checks.
The persistent ChatGPT conversation and the temporary browser tab have separate
lifetimes. The Python helper owns coordination metadata; it does not control tabs.

## Establish ownership

Use the browser selected by the transport contract. Read the current tool
documentation and follow its required first-call entrypoint: create a tab with
the documented `cua.createBrowserTab` API when a new tab is needed, or select the
explicitly referenced existing tab with the documented `cua.getTab` API. If the
tool requires a single entrypoint call, do not combine it with inventory, waits,
or other calls. Read its returned documentation before subsequent operations.
For another supported browser tool, follow that tool's observed equivalent;
never guess close, handoff, or inventory methods.

Immediately after creation, record in task context the persistent Codex task ID,
concrete browser ID, exact returned tab ID, creation result, and whether the tab
is temporary or an explicit user handoff. A fresh inventory must identify that
same tab before acting. The URL checks conversation identity; a matching URL,
title, or ChatGPT account does not prove tab ownership. Tabs selected from the
user's inventory are borrowed and must not be closed as automatic cleanup.

Reuse the same owned tab during one consultation. A temporary tab created by
this task to inspect a saved conversation is still owned; the saved conversation
does not require a permanently open tab. Never share a mutable composer across
tasks. Do not create duplicate tabs merely because retrieval is slow.

## Finalize every browser path

| Outcome | Required disposition |
| --- | --- |
| Completed response accepted by the helper, including native retrieval | Close the owned temporary tab after required verification |
| `reuse`, `retrieve`, or `revalidate` finishes without pending work | Close any owned temporary inspection tab |
| Setup probe accepted or read-only live status completed | Close the owned temporary probe/status tab; preserve probe conversation history |
| Failure before dispatch with no reservation, send, or pending work | Close the owned temporary blank/inspection tab |
| Unresolved reservation, uncertain send, ongoing generation, or timeout | Retain and hand off the exact tab for reconciliation; never repeat a send |
| Explicit request to open, show, keep open, or sign in on that tab | Retain the requested tab and record the handoff reason |
| Borrowed tab, missing ownership evidence, unsaved user work, pending downloads, or unknown outcome | Preserve it; report the blocker without inventing closure |

Run this disposition check on success, failure, cancellation, or leaving Plan
mode. Execution mode stops consultation, polling, and reply application; it may
close a proven idle owned temporary tab. A mode change or timeout never releases
a request reservation. Native transport becoming available does not resolve a
pending request or authorize closing its browser handoff.

Before closing, use the current documented inventory/observation API to verify
the recorded browser/tab ID is still the owned resource and has no pending work
or user edits. Close only that tab through the documented tab API. Then read a
fresh inventory and verify that exact ID is absent. A close-call result alone is
not evidence of absence. Record a compact receipt in task context: owner task,
browser ID, tab ID, disposition (`closed`, `retained`, or `unverified`), observed
absence for a closed tab, and a reason for retention or failure. Do not store
prompt text, cookies, or credentials in this receipt or add it to planner state.

If closure or verification fails, report cleanup as unverified. If the task lost
the creation receipt or tool access after interruption, preserve the tab until
ownership can be re-established in its owning task. Do not sweep by URL/title,
bind a foreign task's tab, close a whole window, quit the browser, or kill processes.
Use a handoff API only if current tools document it; otherwise retain the tab and
report that the handoff could not be verified. Do not repeatedly reopen tabs.

Keep ChatGPT history, saved conversation UUIDs, task mappings, request hashes,
reservations, and profiles. Cleanup never clears state, abandons a request, sends
a message, or changes the guarded replacement procedure. Ordinary saved results
default to closing temporary tabs after verification; only an explicit live
handoff or unresolved state requires retention.

Static instruction tests establish this contract's presence and reachability.
They do not demonstrate browser closure, process exit, or RAM recovery.
