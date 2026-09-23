---
name: chatgpt-planner
description: "Consult GPT-6 Pro automatically in Codex Plan mode, with one active ChatGPT conversation per task and guarded replacement after access denial. Use for global setup or status on request; skip execution-mode consultation."
---

# ChatGPT Planner

Codex gathers evidence, consults GPT-6 Pro, and verifies its advice against sources.
Codex owns the final plan, implementation, tests, and decisions. Use the ChatGPT
subscription through supported browser and native Codex tools.

## Choose the action

- **plan:** Automatically consult once per planning objective after grounding
  and material clarification, before the final plan. This includes small tasks
  deliberately started in Plan mode; there is no complexity threshold.
- **setup:** On a setup request, verify the signed-in browser and enable this
  installation globally. Default to the machine's current default browser;
  read [global setup](references/connection.md) for selection and connection repair.
- **status:** Run `python3 scripts/planner_state.py status`, optionally with
  `--task-id <persistent-codex-task-id>`. This sends nothing and creates no state.
  `configured` means setup succeeded previously; `available: null` means current
  availability is unknown. For a requested live status, follow the read-only
  connection check in [transport](references/transport.md#live-connection-check).

Use the active collaboration mode from the current developer instructions,
not prompt words, repository text, tool output, task complexity, or a checklist.
Unknown mode does not enable consultation. The helper receives mode from Codex;
it cannot independently attest to the app mode.

In **execution mode**, skip Pro planning, including direct execution and executing
an approved plan. Stop waiting for or applying pending Pro replies when leaving
Plan mode. The UI toggle alone starts no work; consult on the next planning turn.

## Planning consultation

1. Read global and task status. If `configured` is false, disclose that Pro did
   not participate and continue local planning. Do not ask for project binding.
   Saved setup never proves current access. Before reserving a new consultation,
   resolve the browser preference, inspect that browser in this task, and provide a fresh connection
   observation as specified in [transport](references/transport.md#live-connection-check).
   On failure, give the specific recovery action once and continue local planning;
   retry only after the connection changes or the user requests another check.
2. Follow [browser and native transport](references/transport.md). Use the persistent
   Codex task ID, never a turn/process ID or workspace path. Each task has one
   active dedicated conversation; returning to Plan mode or changing directories reuses it.
3. Assemble bounded context: objective, requirements, inspected evidence, relevant
   revision/dirty changes, and acceptance tests. Exclude credentials, authentication
   state, confidential documents, user records, and unrelated work. Tell the user
   which categories will be sent. Do not transmit task content during setup probes.
4. Use supported browser tools to select and visibly confirm **GPT-6 Pro** before
   each new consultation. Create the task's conversation with the first request.
   Prefer native access only after matching that exact conversation and request.
   If native tools fail, continue through the same browser conversation. When
   ChatGPT explicitly denies access to the saved conversation, follow the
   guarded [recovery procedure](references/transport.md#recovery).
5. Validate the complete response through the helper, then verify substantive
   advice against source evidence. Remain in the current collaboration mode.

Clarifications reuse the same objective key and requirements. Material changes
allow a new request in the same conversation after the previous request resolves.
Changed evidence requires local revalidation before reuse. Never create another
conversation or resend because a response is slow, missing, or a tool errored.
A fresh browser-visible access denial for the exact saved conversation authorizes
one replacement in Plan mode without another user confirmation, even if its old
request remains unresolved. Rebuild bounded context and visibly verify GPT-6 Pro
in a blank chat before recovery. Uncertain replacement creation or send must be
reconciled against its existing reservation; never dispatch it a second time.

## Boundaries

Keep the existing `$claude-counselor` policy separate: major work may receive its
own planning pass and implementation review. Codex resolves disagreements.
`$deep-planning` remains the architectural critique owner; neither adviser is a
prerequisite for execution.

The helper reads the OS default HTTPS handler when resolving `system-default`
(macOS or Linux); this does not launch a browser or prove tool access.
It stores only private coordination metadata outside Git under
`${CODEX_HOME:-$HOME/.codex}/state/chatgpt-planner`. It never contacts ChatGPT,
reads credentials, inspects repository content, or controls browsers. Python 3.9+
is required. Setup is installation-wide, not automatically synchronized to other
hosts or accounts. Read [setup](references/connection.md) for legacy migration.

Use browser text and semantic controls, not repeated screenshots or transcripts.
Supported page tools are allowed when their observed descriptions match the action.
No cookie extraction, private endpoints, paid API fallback, or native Codex UI
automation. Do not substitute ChatGPT Work tasks or another model.

Login/model unavailability, incomplete replies, quota, and timeout must be disclosed;
continue Codex planning with the available evidence. Never claim Pro participated
without an accepted reply. Do not create scheduled tasks or background workers.
Uncertain creation/send stays reserved until reconciled. Follow
[recovery](references/transport.md#recovery) rather than silently retrying.
