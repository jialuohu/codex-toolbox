# Observation and binding

For repeated decisions in one `cua_repl` task, initialize these **two** pure
helpers once. They have no UI effects. The matching helper supports the
`index role label` lines verified on the synthetic fixtures: browser rows have
`10 text Quartz` near `12 button Open`, while native rows may have
`98 text Quartz Research · Ready` next to `99 button Open`. Use the complete
native row text as exact context. Other tree formats remain unbound until
verified. `L` prefixes in excerpts are text
line numbers, not accessibility element indexes.

Read the fixed [helper source](../scripts/helpers.js) through the local file tools
and paste its two function declarations into the persistent `cua_repl` session
once, after the required first entry-point call. Do not import the file, read
the filesystem, or use network calls inside `cua_repl`. Load these helpers only
when several decisions need them; the optional [controller pilot](controller.md) uses its
own helpers.

Use discriminative task-specific terms and required verification text. Avoid
generic repeated labels such as `Open` as excerpt terms on a long tree; the
target row's context window already includes its control. Small trees and useful
diffs go straight to the output; long trees carry counts of shown and omitted
lines. An empty match, incomplete marker, or context that exceeds 80 lines
returns the complete saved state. If a diff lacks required context, fetch a full
state **within the same call**. If Codex later sees missing semantic context,
print the saved full state before binding. Never infer a target from omitted
lines. Native `showing start-end of total items` means a viewport slice when
`start > 0` or `end < total`, even if the returned tree is short. Fetch a full
state once in the same call; if it still shows a slice, scroll and inspect the
remaining coverage before acting. `cuMatchUnique` stays unbound on such a slice
because one visible row is not proof of global uniqueness. If the app keeps
virtualizing the tree, use a manual fallback: after the last semantic change,
inspect ranges that cover the list without gaps, check for duplicate target
rows, then return to the target and derive its index from a fresh observation.
Restart coverage after any filter, sort, or other change that can reorder rows.
This does not count as a `cuMatchUnique` binding; never concatenate old element
indexes. A screenshot can resolve visual context locally; it is not Jev input.

```javascript
var cuAx = await target.getAXState({ emit: false });
var cuView = cuSelectExcerpt(cuAx, { terms: ["Quartz", "Wrong actions"], required: ["Quartz", "Wrong actions"] });
if (cuView.needsFull) {
  cuAx = await target.getAXState({ emit: false, disableDiffing: true });
  cuView = cuSelectExcerpt(cuAx, { terms: ["Quartz", "Wrong actions"], required: ["Quartz", "Wrong actions"], full: true });
}
var cuSnapshotId = `cu-${Date.now()}-${Math.random().toString(36).slice(2)}`;
nodeRepl.write(cuView.direct && !cuView.incomplete ? cuView.text : JSON.stringify(cuView));
```

Only pass a **fresh complete** state to `cuMatchUnique`. It accepts exact role
and label, local context labels, operation, and explicit preconditions. It
returns `unbound` for duplicate labels without unique context, changed indexes,
missing or disabled targets, incomplete diffs, or unsupported structures. A
missing `selected` annotation cannot satisfy a selection precondition. Do not
reuse a binding after any action. Batch multiple actions only when each next
action is deterministic without an intervening observation or a potentially
stale element index.

## Act and verify

Before executing a recommended action, reacquire the relevant UI state and
match the target by role, label, surrounding context, exposed operation, and
preconditions. Independently check that this action advances the user's stated
objective; reject a valid but irrelevant candidate, including a visible decoy.
Derive a **fresh** element index from that state. If the target changed,
matches more than once, fails the objective check, or cannot be bound safely,
choose again using the new state. Codex applies all existing action and
confirmation rules, calls `cua_repl`, and verifies the resulting state. A Jev
result never triggers a UI action on its own. After checking objective relevance
and authorization, use one call for fresh observation, unique binding, one
action, and result observation.

If an action throws, its side effect may still have happened. Inspect the
returned UI before any recovery or retry. A failed or missing verification is
unverified, even when an action returned without error. Confirm the exact goal
and task-specific evidence in the fresh observed result; candidate text,
Jev responses, and controller statuses are not verification. A partial tree
blocks unique target binding, but an independent, complete result subtree may
verify the goal while an unrelated list remains virtualized. Missing or partial
result evidence remains unverified.

Read [verification examples](verification-examples.md) only when using or adapting
the synthetic fixture recipes and their exact case markers and counters.
