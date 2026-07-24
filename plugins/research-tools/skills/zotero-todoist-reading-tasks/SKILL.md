---
name: zotero-todoist-reading-tasks
description: Create, schedule, reconcile, and repair Todoist paper-reading tasks from saved Zotero collections or items, including desktop deep links to parent records and PDF attachments. Use when a user wants a Zotero reading queue turned into Todoist tasks, readings distributed across dates, or Zotero links added to existing paper-reading tasks.
---

# Zotero Todoist Reading Tasks

Turn a saved Zotero reading queue into one Todoist task per Zotero parent item.
Keep Zotero read-only and make each Todoist task a durable, directly linked
progress record.

## Authority and tool routing

- Inspect Zotero and Todoist before writing. Do not mutate Zotero.
- Treat an explicit request to create, schedule, reconcile, or repair reading
  tasks as authority only for the named Todoist project, collection, and tasks.
- Require the exact task identity and an explicit deletion request before
  deleting anything. Do not infer cleanup authority from a reconciliation.
- Prefer the connected Todoist app when it is available. Use the official hosted
  Todoist MCP only as a fallback. Choose exactly one Todoist tool surface for the
  request, never both.
- Do not create a project, section, or label unless the user explicitly asks for
  that structure. Resolve existing targets before task changes.
- Route missing-paper imports, metadata repair, and attachment repair to
  `$paper-library-intake`; this workflow only reads Zotero.

## Resolve the reading set

1. Identify the active Zotero library and resolve the requested collection by
   its full path and key. For a group library, obtain the numeric group ID from
   the live library listing; never guess it.
2. Call `zotero_get_collection_items` for the resolved collection and retain
   top-level bibliographic items. Exclude child attachments, notes, and
   annotations as task candidates.
3. Preserve the collection or user-provided order. When the user explicitly asks
   for a prerequisite-aware order, inspect saved titles and abstracts and rank
   foundational work before dependent systems or applications. State that this
   order is a recommendation.
4. For two or more parents, call `zotero_get_items_children` once with all parent
   keys. Use the single-item child tool only for one parent.

## Build Zotero desktop links

Use the parent item key for selection and the PDF attachment key for opening a
PDF. Never pass a parent key to `open-pdf`.

For the personal library:

```text
zotero://select/library/items/<PARENT_KEY>
zotero://open-pdf/library/items/<ATTACHMENT_KEY>
```

For a group library:

```text
zotero://select/groups/<GROUP_ID>/items/<PARENT_KEY>
zotero://open-pdf/groups/<GROUP_ID>/items/<ATTACHMENT_KEY>
```

When exactly one PDF child exists, use its PDF attachment key. When there is no
PDF child, create or repair only the `Show item` link and report that the PDF
link is unavailable. When there are multiple PDF children, use an authoritative
primary attachment only if Zotero exposes one; otherwise ask instead of guessing.

Render a personal-library task line as:

```markdown
Zotero: [Open PDF](zotero://open-pdf/library/items/<ATTACHMENT_KEY>) · [Show item](zotero://select/library/items/<PARENT_KEY>)
```

For an item without a PDF, render:

```markdown
Zotero: [Show item](zotero://select/library/items/<PARENT_KEY>)
```

Substitute the group-library forms when applicable.

## Reconcile task identity

Search only the requested Todoist project or section before creating tasks.

1. Match an existing task by its parent-key select URI first. This is the stable
   identity for one Todoist task per Zotero parent item.
2. For an older task without a Zotero URI, strip an optional `Read:` prefix and
   compare the normalized title with the Zotero title. Reuse it only for a
   unique one-to-one match.
3. Treat multiple task candidates or multiple Zotero title candidates as unsafe;
   stop on ambiguity and show the candidates.
4. If no match exists, create `Read: <paper title>` in the requested target.

Maintain exactly one managed `Zotero:` line in the task description. On repair,
replace existing lines that begin with `Zotero:` and contain a `zotero://` URI,
then preserve every other description line unchanged and in order. If a
`zotero://` URI appears outside a managed line, do not duplicate or rewrite it;
report the task as ambiguous for manual review.

Repeated runs are idempotent reconciliation, not continuous synchronization.
Never claim that later Zotero or Todoist changes will propagate automatically.

## Schedule the reading

- Treat the planned reading day as the Todoist due date and the final cutoff as
  `deadlineDate`. Never substitute one for the other.
- If the user supplies an inclusive date range but no daily allocation, preserve
  reading order and distribute tasks evenly across the available calendar days.
  Put any quotient remainder on earlier days to retain buffer before the final
  deadline. If fewer papers than days exist, use the earliest days.
- If only a final deadline is supplied, start the available range today in the
  Todoist account timezone. Honor any excluded weekdays or unavailable dates the
  user specifies.
- Use `dueString` when creating a task. Use `reschedule-tasks` when moving an
  existing task so recurring rules and time-of-day are preserved.
- A link-only repair must not change scheduling. Otherwise preserve existing
  titles, labels, priority, hierarchy, duration, due time, and deadline unless
  the user explicitly requests a change.

## Apply and verify

1. Preview the resolved Zotero parents, attachment choice, Todoist target,
   matches, planned dates, final deadline, and any ambiguity that blocks a write.
2. Apply only the authorized creations or updates. Use batch Todoist operations
   where the tool supports them.
3. Read back every created or changed task. Confirm its project and section,
   content, managed link line, planned due date, and `deadlineDate`.
4. Return a compact receipt grouped as `created`, `reused`, `repaired`, and
   `skipped`. For skipped items, state whether the cause was a missing PDF,
   ambiguous attachment, ambiguous task match, missing target, or unavailable
   service.

If Zotero cannot be read, do not infer the collection contents or keys. If
Todoist is unavailable, report that no task change was persisted. Never use
conversation history as the task database.
