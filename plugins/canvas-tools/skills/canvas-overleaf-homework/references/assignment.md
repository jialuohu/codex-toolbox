# Resolve the assignment and deadline

Use `$canvas-student-planning` for Canvas reads and `$overleaf` for project
configuration. Todoist lookup here is read-only; task changes require the
explicit [Todoist operation](todoist.md).

1. Check the Overleaf configuration and resolve the project URL or name to one
   configured alias. If it is not configured, stop with configuration guidance;
   do not use browser automation or raw Git as a workaround.
2. Resolve the current Canvas student, course, and assignment. Use the numeric
   `(course_id, assignment_id)` pair as stable identity. Derive the homework
   number from the user's request or a unique assignment-title match; ask when
   it is ambiguous rather than guessing.
3. Search Todoist for the exact managed identity line first:

   ```text
   Canvas: course_id=<COURSE_ID>; assignment_id=<ASSIGNMENT_ID>
   ```

   For a legacy task without that line, accept course code, exact assignment
   title, and due instant only when they identify one unique candidate.
4. Use Canvas's deadline when it has one. Use the unique matching Todoist task's
   deadline only when Canvas has none. If both have deadlines and the instants
   differ, show both in the user's timezone and stop before any deadline-bearing
   Overleaf or Todoist write. If neither has one, use `Not specified`.
5. Preserve the source instant and render a real deadline as
   `Month D, YYYY at h:mm AM/PM TZ`. Use the Canvas profile name, course code or
   title, and term when available; omit unknown optional metadata rather than
   inventing it.
