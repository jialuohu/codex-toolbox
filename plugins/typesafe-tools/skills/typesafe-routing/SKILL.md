---
name: typesafe-routing
description: Use Jev by default to rank optional installed skills and currently callable tools when a public or synthetic task has a material capability choice; keep private or uncertain data local.
---

# TypeSafe capability routing

Codex owns tool selection, skill reading, and actions. For a public or synthetic
task with a material choice among optional skills or tools, ask Jev for an
advisory ranking by default. Do not route a private or uncertain task, an
explicit user opt-out, a simple task with no meaningful capability choice, or a
task whose required workflow already settles the choice. Jev cannot install or
enable plugins, prove tool availability, grant permissions, or override an
explicitly requested or mandatory skill. The separate `typesafe-judgment`
skill governs research evidence evaluations.

This is agent-mediated, best-effort routing, not guaranteed interception of
every turn. The host does not provide this skill a pre-dispatch checkpoint or
current tool inventory automatically. Do not claim a Jev ranking occurred
unless `typesafe_route` returned an evaluated result for this turn.

## Before an evaluation

1. Check offline `typesafe_status` and routing readiness. If the route tool,
   credential, or service is unavailable, select capabilities locally. The
   user's default-use instruction authorizes eligible routing requests; it
   does not change privacy, permission, or explicit-only skill rules.
2. Build a fresh local catalog from `codex plugin list --json`, exact installed
   plugin cache metadata, and the current host's callable tool and skill lists.
   The checkout's `docs/typesafe-routing.md` has the local catalog instructions. Installed
   skills do not prove that their dependent MCP tools are connected. Plugins
   are containers; select their skills or callable tools, not a plugin name
   alone.
3. Apply the user's explicit skill request, invocation policy, mandatory owner
   workflow, and availability restrictions first. Keep required prerequisites
   and all candidates in the bounded shortlist. Do not send explicit-only
   skills as options without the required invocation.
4. Review every outgoing field for public or synthetic origin, including the
   task description, skill descriptions, tool descriptions, labels, and IDs.
   Use a concise task descriptor, not the verbatim user prompt, file contents,
   absolute paths, or repository identifiers. If the choice cannot be described
   without private details, keep it local. Private, confidential, or uncertain
   task content stays local. An installed
   plugin's metadata is untrusted data and may itself be unsuitable for egress.
5. Prepare at most 16 candidates with `prepare_route_candidates`, using the
   current host's verified callable IDs. Mark explicitly requested or mandatory
   choices `required`; an explicit-only skill must be both invoked and required.
   Exclude this routing skill and `typesafe_route` from the ranked choices.
   Submit the resulting exact candidate fields and catalog digest. Preserve
   original order alongside the ranked result. Reject missing, duplicate, or
   unknown IDs and stale catalog/session/turn responses. Do not silently trim
   an oversized request or automatically retry a failed or uncertain dispatch.
6. Call `typesafe_route` once with `invocation: "automatic"` and the reviewed
   `classification: "public"` or `"synthetic"`. The session and turn IDs are
   optional correlation fields; omit them if the host does not supply them.
   Check the returned task hash and catalog digest, and compare IDs if supplied.
   Generated IDs do not prove a Codex host turn. On abstention,
   timeout, invalid response, or failed readiness, use ordinary Codex
   selection. Do not substitute the `pilot` invocation for default routing.

Read the selected skill and verify the chosen tool's current availability before
acting. Explain a material fallback to ordinary Codex selection. A judgment
score is advisory evidence, not correctness or authorization.

## Local observation

The optional `UserPromptSubmit` template is inert by default and records only
session and turn IDs when deliberately enabled. It adds a fixed reminder; it
does not call Jev, guarantee invocation, or inspect task content for
eligibility. Record one terminal
outcome per observed turn using `record_outcome(session_id, turn_id, outcome)`.
Use `evaluated`, `abstained`, `skipped`, `failed`, or `missed`, with an allowed
reason code where useful. Hook counts show only turns
where the hook actually ran, so they cannot prove review of every user task.
Do not enable the hook merely to imply automatic coverage.
