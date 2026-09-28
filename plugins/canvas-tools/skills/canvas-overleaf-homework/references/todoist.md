# Link the assignment in Todoist

Use exactly one Todoist surface and delegate mutations to
`$todoist-task-planning`. Resolve identity and deadlines through
[Assignment](assignment.md) before changing a task.

Only perform this section when the user explicitly asks to link, create, or
reconcile the assignment in Todoist.

1. Search active and completed tasks before changing anything. Match the Canvas
   managed identity first and block ambiguous or completed matches.
2. Canonicalize the Overleaf URL to its HTTPS project URL. Strip query strings
   and fragments, and never store a share token, Git token, or credential. The
   managed description line is exactly:

   ```text
   Overleaf: <CANONICAL_PROJECT_URL>
   ```

3. If one matching task exists, preserve its personal notes, labels, priority,
   project, section, hierarchy, duration, due value, and unrelated description
   lines. Add the line once, or replace one stale managed Overleaf line. Multiple
   managed links block the update until identity is resolved.
4. If no task exists, an explicit request to link this assignment authorizes one
   creation. Use `[<COURSE_CODE>] <ASSIGNMENT_TITLE>` as the title; include the
   Canvas identity, authoritative Canvas URL when returned, and Overleaf line;
   and use the resolved deadline. Create it undated only when the user explicitly
   selected this assignment for Todoist linking and no source has a deadline.
5. Preview `create`, `update`, `reuse`, or `skip`. Confirm before more than one
   creation or update. Never create projects, sections, labels, or duplicates.
6. Read back each changed task and verify its identity, links, due value, project,
   section, and incomplete state. This is one-time reconciliation, not ongoing
   synchronization.
