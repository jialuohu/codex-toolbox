# Preview cleanup

Read before starting any interactive preview. Record existing browser tabs and
any server you reuse without launching them. Save the exact browser/tab handle
from task creation and the owning terminal session or child-process handle for
each server. A matching title, URL, port, or inventory difference alone does not
prove ownership. An OS opener returns no exact tab identity; do not use it for
disposable reviews when an owned Computer Use tab is available.

Prefer the delivered HTML and visual-check screenshots for static inspection.
When a live preview is required, reuse one owned tab. `archify preview` supports
`--no-open`: keep its task-owned terminal session, read its returned loopback URL,
then create the preview tab through the current browser tool's documented
entrypoint. Keep preview regeneration separate from final publication: verify
the final saved bytes and hash again before publishing. If using a static
loopback server instead, retain its exact task-created process/session identity.

After success or failure, while control remains available:

1. Verify the saved HTML/JSON and any completed download outside the tab. Keep
   files and receipts; closing the view never authorizes deleting artifacts.
2. Close only the exact task-created review tab, using the documented bound
   close action, and verify its ID is absent. Preserve pre-existing/borrowed
   tabs, unknown ownership, unsaved edits, pending work, and explicit
   open/show/keep-open requests. A genuine live handoff retains the needed tab
   through the browser's documented deliverable/handoff mechanism.
3. Stop the owned preview server through its original terminal session or exact
   child handle using normal SIGINT or SIGTERM; wait for completion. The toolbox
   launcher requests one cancellation from its child, allowing upstream to drain
   its watcher, server, and rendering work. It also requests shutdown if its
   private parent connection is lost. It does not kill unrelated apps or
   a shared browser. Do not use process-name/port sweeps or global termination.
4. Keep a server only when a retained live preview still needs it. Report that
   retained dependency and how it can be stopped; otherwise stop it even if
   publication failed or the browser could not open. Verify terminal completion
   rather than claiming cleanup just because a signal was sent.

On a close error, inspect before retrying. Unknown state, lost ownership,
interrupted control, or a server that does not finish leaves cleanup unverified;
report the specific resource and reason. Cancellation reports the exact runtime
PID for scoped inspection if shutdown stalls; the launcher does not force-kill
it. A hard host exit or SIGKILL of the runtime cannot run orderly cleanup. Do
not close unrelated windows to compensate.
