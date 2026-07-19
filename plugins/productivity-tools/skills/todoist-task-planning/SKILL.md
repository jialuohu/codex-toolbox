---
name: todoist-task-planning
description: Manage a personal task system across Todoist and Google Calendar. Use when the user asks to add, edit, complete, find, review, or organize tasks; capture deadlines or task details; block focused work time; or schedule a remote meeting while keeping tasks and calendar events distinct.
---

# Todoist Task Planning

Todoist is the source of truth for actionable work. Google Calendar is the source
of truth for time commitments. Use the connected tools to persist records; ChatGPT
or Codex conversation history is not a task database.

Prefer the connected Todoist app when it is available. Use the official `todoist`
MCP as a Codex CLI fallback when the app tools are unavailable and that MCP is
authenticated. Choose one Todoist tool surface per request. Never write the same
operation through both, because that can create duplicate tasks.

## Safety and intent

- Read and search before changing external data.
- Treat an explicit request such as "add this task" as authorization for that one
  Todoist creation. Do not ask for redundant confirmation.
- Confirm before any Google Calendar write, guest invitation, deletion, bulk
  change, or ambiguous update. Show the exact proposed record first.
- Never infer permission for unrelated cleanup, task completion, rescheduling, or
  invitations.
- Ask when the date, timezone, duration, task identity, calendar, or attendee email
  could materially change the result.
- Search for an existing matching record before creating one. Match on stable ID or
  URL first; use title plus relevant date only as a candidate, not proof.

## Classify the request

### Deadline-only tasks

Create or update one Todoist task with the title, deadline, and useful private
details. A deadline time still describes when the task is due; it does not imply a
work session. Do not create a Google Calendar event unless the user explicitly asks
to reserve time, names a work interval, or schedules a meeting.

Examples:

- "Submit the report by Friday" -> one Todoist task due Friday.
- "Submit it by Friday at 5 PM" -> one Todoist task due Friday at 5 PM.
- "Remind me to renew the certificate next month" -> one Todoist task after
  resolving the intended date; no all-day calendar marker.

### Focused work

For a request to reserve focused effort, use a Todoist task plus a Google Calendar
time block. Search Todoist for the task and Calendar for conflicts first. If the user
gave a broad window, find free time inside it and preview a specific start, end,
timezone, calendar, and title for confirmation. After approval, create the calendar
time block and add reciprocal IDs or URLs when the tools expose stable links.

Do not turn the task's deadline into the calendar time block. Preserve the deadline
in Todoist and schedule the work block early enough to make completion realistic.
Use a busy event by default and omit attendees. Keep private task notes in Todoist.

### Meetings

A meeting is a Calendar record by default, not a Todoist task. Preview its title,
start, end, timezone, attendees, shareable description, location, and conferencing
before creation. For a remote meeting, add Google Meet only when requested or clearly
implied, and verify each attendee's email before inviting them.

Do not create a Todoist follow-up task unless the user asks to track follow-up work
or provides a concrete action item. Do not invent future action items. If a follow-up
is requested, link it to the event after the event exists.

Calendar descriptions may be attendee-visible. Put only shareable agenda and joining
details there; keep private preparation notes, sensitive context, and internal links
out of attendee-visible fields.

## Execute and verify

1. Resolve relative dates against the current date and report the absolute date in
   the preview or result. Use the connected calendar's timezone when available.
2. Search the authoritative service for an existing record and inspect likely
   duplicates.
3. Preserve user wording for the title; place supplemental context in the
   description instead of silently expanding the commitment.
4. Apply only the scoped change. When both services are involved, write the primary
   record first, then add cross-links only if doing so will not duplicate records.
5. Read back the created or updated record when the tool supports it. Report the
   service, title, due date or time range, and stable link. Never claim ongoing
   bidirectional sync from a one-time cross-link.

## Reviews and failures

For a review, query Todoist for overdue and upcoming tasks and use Calendar only to
evaluate available capacity or existing commitments. Do not silently schedule tasks
from a review.

If Todoist is unavailable, say that the task was not persisted; do not substitute
conversation memory. If Calendar is unavailable after a Todoist task is saved, keep
the task and report that the requested time block or meeting is still unscheduled.
Never report partial work as fully synchronized.
