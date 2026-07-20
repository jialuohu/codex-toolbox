---
name: daily-command-center
description: Prepare a concise, strictly read-only daily command-center brief across Gmail, Google Calendar, and Todoist. Use for daily or morning briefs, daily planning, and scheduled command-center runs that need email context, time commitments, and priority tasks without changing any source.
---

# Daily Command Center

Prepare a bounded cross-app read of the user's current Gmail, Google Calendar,
and Todoist state. Keep the brief strictly read-only, including manual
invocations: never send, draft, label, archive, trash, or delete email; create,
update, delete, or respond to Calendar events; or create, update, complete,
delete, or reschedule Todoist records.

## Source ownership and tool choice

- Gmail is incoming context, Todoist is the durable source of truth for
  actionable tasks, and Google Calendar is the source of truth for time
  commitments. Conversation history is not a task database.
- Prefer connected apps. For Todoist only, use the official hosted MCP as a
  fallback when the app is unavailable; choose exactly one Todoist surface per
  run.
- Resolve the current date and timezone from connected profiles. If the profiles
  disagree materially, report the mismatch and use the Calendar timezone for
  schedule rendering.
- For a later explicit mutation request, stop this daily brief and route to the
  relevant service workflow. `$todoist-task-planning` continues to own task and
  time-block mutations.

## Read the bounded sources

1. Search Gmail with exactly
   `newer_than:2d in:inbox -category:promotions -category:social -in:spam -in:trash`.
   Cap the initial search at 30 messages, group results by thread, and expand at
   most five likely-action threads. Do not treat Gmail labels alone as proof of
   importance. Prioritize direct requests, deadlines, financial or security
   notices, service interruptions, and application or administrative
   consequences.
2. Query Calendar with explicit timezone-aware bounds from the start of today
   through the next seven days. Show today in detail and flag notable upcoming
   commitments or conflicts. Page only inside that same bounded window when
   necessary.
3. Query Todoist for the authenticated current user's overdue, today, and
   seven-day upcoming tasks. Report an empty state without inventing work.

## Write the brief

Use these sections in this stable order:

1. `Today at a glance`
2. `Attention now`
3. `Calendar`
4. `Tasks`
5. `FYI`
6. `Suggested actions`
7. `Coverage and caveats`

Keep scheduled output concise. Limit `Attention now` to five items and `FYI`
to three. For every attention item, state its source, time or date, why it
matters, any known deadline, and the recommended next step. Number suggestions
and phrase them as proposals for an interactive follow-up.

Redact verification codes, credentials, full account identifiers, and
unnecessary sensitive details. For financial or security alerts, recommend
direct verification rather than taking action.

## Coverage failures and recurrence

If one connector fails or is unavailable, still finish a partial brief, name the
missing source, and do not substitute web search. State the bounded coverage and
avoid unsupported claims such as "the only urgent email." Re-read live sources
on every run; repeated unresolved items are acceptable. Never suppress an item
solely because conversation history says it was previously seen.
