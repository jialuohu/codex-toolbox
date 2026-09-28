# Task-owned UI cleanup

Read this before launching, binding, opening, or probing a UI resource. Cleanup
is part of the authorized task, not permission to close unrelated user work.

## Establish ownership

Follow the current CUA tool's required first-call and target-selection rules.
Do not unconditionally make `listApps()` the first call. Use supported inventories
to record initial tabs, windows, and running-app state before creation or launch
when those rules permit. Binding can launch a native app; if initial state cannot
be established, record it as unknown rather than infer that the task started it.

Keep a task-local ownership record: exact browser and tab IDs, exact window/app
identity exposed by the owning tool, the observed creation or launch event, and
whether the resource must remain open. A title, URL, or inventory difference alone
does not establish ownership. For an app, record its initially nonrunning state
and evidence that the current instance is the one the task launched. Missing
instance evidence makes application quit ineligible.

Preserve this record through a task handoff without putting private UI content
in shared artifacts. Lost ownership evidence becomes unknown; never reconstruct
ownership by matching titles or sweeping open resources.

## Decide what remains open

After verifying the result, close saved task-created tabs and windows by default.
Preserve a resource if any of these apply:

- The user explicitly asked to open, show, or keep it open, or the live view is
  a required deliverable. A saved artifact alone does not require its editor to
  remain open.
- It existed before the task, belongs to the user or another task, or ownership
  is unknown.
- It has unsaved work, an unresolved mutation, a pending download, authentication
  or approval in progress, or a genuine continuation handoff.

For retained browser tabs, use supported `tab.markDeliverable()` for live outputs
and `tab.markHandoff()` for pending continuation or protected incomplete work.
Marks are turn-scoped: renew them when the next turn still needs the tab.
Do not mark routine research, intermediate, duplicate, or blank tabs merely to
avoid cleanup. Browser automatic turn-end cleanup is a fallback, not evidence
that closure has already happened.

## Close and verify

At success, failure, cancellation, or timeout, while control remains available,
reobserve each owned resource and apply the preservation rules before closing.
Close only its exact bound tab with supported `tab.close()`, or use the owner's
documented close operation. For a native window, reobserve its normal Close
control and verify the target and focus before acting. A stale accessibility
index or a keyboard shortcut aimed at an uncertain window is unsafe.

Quit an app normally only if it is proven task-started, is still the same
instance, is idle, and has no protected windows or work. The native CUA `App`
interface has no `close()` or `quit()` method: use a supported owner operation
or an observed normal Quit control; do not invent API methods. Never force quit,
use `killall`, terminate native app processes, close windows indiscriminately, or dismiss a
save dialog to finish cleanup. An unexpected save prompt or changed state stops
that close. An owning CLI may stop its own headless preview server normally.

Reinventory afterward to verify exact-resource absence or that the intended
preserved resource remains. If close reports an error, inspect before any retry;
it may already have succeeded. Missing access, uncertain state, or an unverified
close leaves the resource protected. Report concrete leftovers and the reason;
do not claim cleanup from the action call alone. An abrupt loss of control may
prevent cleanup; report that limit when execution resumes.

The controller's `verified`, `stopped`, and `handoff` statuses establish no UI
ownership and close nothing. A handoff can continue the same task; do not close
its working view merely because the controller returned. Keep this lifecycle
decision with Codex. It does not widen controller budgets or change frozen
diagnostic trial reset, reuse, or evidence rules.
