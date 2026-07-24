---
name: zotero-todoist-reading-tasks
description: Use when a user wants to create, schedule, reconcile, or repair Todoist reading tasks from saved Zotero items or collections, with default PaperRead note links.
---

# Zotero Todoist Reading Tasks

Turn a saved Zotero reading queue into one Todoist task per Zotero parent item.
Keep Zotero read-only and make each Todoist task a durable, directly linked
progress record.

## Authority and tool routing

- Inspect Zotero and Todoist before writing. Do not mutate Zotero.
- Treat an explicit request to create, schedule, reconcile, or repair reading
  tasks as authority only for the named Todoist project, collection, and tasks.
- A named Zotero item or collection request also authorizes at most one
  create-or-reuse action per uniquely resolved Zotero parent through
  `$paper-read-draft`. This bounded note authority is inherited from that named
  request; it does not authorize any other PaperRead note work.
- An explicit request for `without Obsidian notes` opts out of PaperRead work for
  that run. On opt-out, perform no PaperRead note operation and preserve any
  existing Obsidian line in a matched Todoist task.
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

## Create or reuse the PaperRead draft

For each uniquely resolved parent, after Zotero identity resolution and before
any Todoist write, invoke `$paper-read-draft` exactly once per uniquely resolved
Zotero parent unless the user explicitly requested `without Obsidian notes`.
Pass only the resolved parent identity and observed metadata that the PaperRead
skill needs; it remains the sole owner of note identity, safe creation, and URI
generation. Complete this PaperRead action once per parent before that parent's
first Todoist write, then reuse the recorded result for all later writes.

- Use only the URI returned by `$paper-read-draft` when its result is `created`
  or `reused`. Do not independently infer a note filename or URI.
- With a returned URI, the managed line is exactly:

  ```markdown
  Obsidian: [Open PaperRead note](obsidian://open?vault=<ENCODED_VAULT>&file=<ENCODED_NOTE_PATH>)
  ```

  Render the returned URI verbatim in that line; the placeholders illustrate
  only the encoded values already present in the returned URI. Do not construct
  a new URI.
- A canonical managed Obsidian line is exactly
  `Obsidian: [Open PaperRead note](obsidian://open?vault=<...>&file=<...>)`:
  it has the exact label and prefix, an `obsidian://open` target with both
  `vault` and `file` query values, and no extra text. This predicate is
  independent of a current PaperRead result. Do not require an existing
  canonical URI to equal a newly returned URI. Only this managed form is
  replaceable or removable. Preserve any other `Obsidian:` line or any other
  `obsidian://` content unchanged and report the task as ambiguous for manual
  review.
- Treat `link-unavailable`, `skipped`, an unavailable PaperRead call, or a
  missing returned URI as `note-missing`. Continue valid Todoist work without
  adding a stale Obsidian line, and record `note-missing` with the reason.
- On explicit opt-out, do not call `$paper-read-draft`, do not add, remove, or
  replace an Obsidian line, and do not report a note failure.

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

Maintain exactly one managed `Zotero:` line and, when PaperRead returned a URI,
exactly one managed `Obsidian:` line in the task description. On repair, replace
existing lines that begin with `Zotero:` and contain a `zotero://` URI. For an
authorized returned PaperRead URI, replace all canonical managed `Obsidian:`
lines with exactly one current managed line. For `note-missing`, remove all
canonical managed Obsidian lines so no stale link remains and preserve every
other description line unchanged and in order. If a `zotero://` or `obsidian://`
URI appears outside a managed line, do not duplicate or rewrite it; report the
task as ambiguous for manual review.

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
   matches, planned dates, final deadline, planned PaperRead action or opt-out,
   and any ambiguity that blocks a write.
2. Before each parent's first Todoist write, complete the authorized PaperRead
   action once and record its `created`, `reused`, `link-unavailable`,
   `skipped`, or `note-missing` result. Reuse that recorded result for all
   later writes for the parent. Apply only the authorized Todoist creations or
   updates. Use batch Todoist operations where the tool supports them.
3. Read back every created or changed task. Confirm its project and section,
   content, managed Zotero line, managed Obsidian line, planned due date, and
   `deadlineDate`.
4. Return a compact receipt grouped as `created`, `reused`, `repaired`, and
   `skipped`. For each item, include the PaperRead note status (`created`,
   `reused`, `opt-out`, or `note-missing` with the reason) and the read-back
   managed Obsidian line when one exists. For skipped items, state whether the
   cause was a missing PDF, ambiguous attachment, ambiguous task match, missing
   target, or unavailable service.

If Zotero cannot be read, do not infer the collection contents or keys. If
Todoist is unavailable, report that no task change was persisted. Never use
conversation history as the task database.
