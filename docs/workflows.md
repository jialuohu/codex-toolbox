# Planning and explanations

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Execution Routing](#execution-routing)
- [ChatGPT Planner](#chatgpt-planner)
- [Deep Planning](#deep-planning)
- [Claude Counselor](#claude-counselor)
- [Explain Clearly](#explain-clearly)

## Execution Routing

For large decomposable projects, start naturally in Plan mode. For example:

```text
Build a polished business website for a small AI consulting agency.
```

The global instructions let Codex plan first and then select the narrowest
execution lane. Tiny changes stay in the main task. Independent, testable work
can run through native Codex subagents. Other implementation work uses normal
Codex behavior. Use OpenSpec when durable requirements, acceptance criteria, or
spec governance should be settled before implementation.

## ChatGPT Planner

`$chatgpt-planner` consults GPT-6 Pro automatically in actual Codex Plan mode,
across workspaces. One global setup configures this installation;
each persistent Codex task gets one active ChatGPT conversation. Codex checks the
advice and owns the final plan, implementation, and verification.

| Mode and objective | Pro consultation |
| --- | --- |
| Plan mode, new task | Create a dedicated Pro chat and consult after gathering context |
| Plan mode, unchanged requirements | Reuse accepted advice in that task's conversation |
| Plan mode, material requirements change | Send a new request in the same conversation |
| Plan mode, saved conversation explicitly inaccessible | Verify the browser error and GPT-6 Pro, then create one replacement without another confirmation |
| Execution of an approved plan | None |
| Direct execution, including major work | None |

Ask `Use $chatgpt-planner setup globally` once. Follow the skill's
[global setup](../plugins/workflow-tools/skills/chatgpt-planner/references/connection.md):
sign into the selected automation browser, select GPT-6 Pro, and complete one
synthetic probe. New setups follow the machine's default HTTPS browser unless you
explicitly choose another. The helper resolves the current OS setting on macOS
and Linux; it does not infer a connection from an installed or running browser.
Setup is not operational until model selection and the complete probe are verified.
Saved setup is not proof of a current connection: every new consultation checks
the selected browser, sign-in, and exact model before reserving a request.
To switch an existing installation to the OS default, ask for that preference or
run `python3 scripts/planner_state.py prefer-browser --mode default --browser system-default`
from the skill directory. `python3 scripts/planner_state.py browser` reports the selected
browser without claiming availability. A different browser needs a fresh setup
probe; saved conversations and unresolved requests are preserved.

When browser-control tools are absent, connect that browser under Settings >
Computer Use and attach it to the task with its `@`-mention. Use the profile with
the extension installed. See the [official connection guide](https://learn.chatgpt.com/docs/chrome-extension).
No source or preference change can expose missing tools to a running task.

The first planning request creates the chat through supported browser controls.
Native Codex messaging is preferred only when the exact browser-created
conversation and request can be verified through native reads. Otherwise, use
the browser throughout. This uses the ChatGPT subscription, without an API key,
private endpoints, or another MCP server.

The skill uses text controls, compact completion polling, and one full response
retrieval to limit overhead. Native handoff is an optimization, not an assumption.
Record pilot tool calls and returned characters; report token counts only when
actual usage is available.

Private metadata lives under
`${CODEX_HOME:-$HOME/.codex}/state/chatgpt-planner`. Use `$chatgpt-planner status`
for saved configuration and optionally provide the persistent Codex task ID.
`configured` records completed setup; `available: null` means the current browser
has not been checked. A live check reports a specific recovery action when the
browser is missing, signed out, or cannot confirm GPT-6 Pro. It never silently
switches browser sessions or claims a stored setup guarantees current access.
There are no project bindings. The Python 3.9+ helper stores hashes, IDs, and
status, not prompt/reply text. Legacy state is backed up before migration;
unresolved legacy requests block activation.

The [owning skill](../plugins/workflow-tools/skills/chatgpt-planner/SKILL.md)
defines bounded context, duplicate prevention, exact reply validation, and a
15-minute deadline. A fresh, signed-in browser error saying “You don’t have access
to this conversation” for the exact saved conversation permits one replacement,
even when the old request is unresolved. The helper reserves it before dispatch
and saves its new UUID only after verifying the exact submitted prompt. Timeouts,
native errors, and uncertain sends are reconciled without another dispatch.
Execution mode stops consultation. Unavailable login, model, or transport produces
a clear disclosure and ordinary Codex planning continues.
The existing Claude Counselor policy remains separate.

## Deep Planning

Plan Mode uses `$deep-planning` when the user explicitly requests adversarial
planning or when work is architectural or high-risk. Ordinary multi-step work
uses normal Codex planning. The skill is a read-only critique gate: it gathers
observed facts, states assumptions and material unknowns, drafts the strongest
plan, challenges product value, architecture, implementation risk, edge cases,
tests, rollout, and scope, then chooses Codex-only, native Codex subagents, or
OpenSpec routing. It does not create artifacts, dispatch workers, or perform
verification after code changes.

## Claude Counselor

`$claude-counselor` gives Codex a bounded second opinion from the locally
authenticated Claude Code CLI. For major architectural, high-risk, or material
multi-file implementation work, it can run one independent planning pass and
one final code-review pass. Codex sends only selected task context through
stdin; Claude receives no tools or repository access, saves no session, and
returns schema-constrained JSON. Codex remains responsible for edits, tests,
evidence, and every final decision.

The wrapper uses the local Claude.ai login and refuses non-empty Anthropic API
authentication environment variables to avoid silently changing the billing
path. It never sends credentials, unrelated diffs, confidential submissions,
or private documents. Failures are not retried automatically.

Counselor calls default to a 10-minute deadline. Use `--timeout-seconds 900`
for large task-scoped reviews; do not shorten the default unless requested.
Version and login checks have separate 20-second deadlines. The final JSON
result stays on stdout, while metadata-only diagnostics on stderr report
stages, elapsed time, progress every 30 seconds, and available model and token
counts. Timeout errors retain these diagnostics without exposing prompts,
thinking, response text, raw stderr, or authentication data. Progress never
extends the deadline or retries a model call.

Example prompt:

```text
Use $claude-counselor to get an independent plan and final review for this architectural change.
```

## Explain Clearly

Use `$explain-clearly` when a concept, why/how question, comparison, or code
walkthrough needs more than a terse fact. It leads with the direct answer and
adapts depth, examples, and structure to the question. It has no fixed answer
sequence or example count. It also chooses the
smallest useful format: prose for simple results, a table for repeated
comparisons, `$archify` for graphical architecture/workflow maps or polished
interactive sequence/data-flow/lifecycle artifacts, `$pretty-mermaid` for
explicit Mermaid, terminal ASCII, or compact static diagrams, and bundled
Visualize for adjustable spatial explanations in the conversation. Native
inline Mermaid is an explicit choice or disclosed renderer fallback. Exact data
and legal state are validated before rendering; ambiguous
chess positions are reported rather than invented, and CLI or IDE tasks receive
text, table, Mermaid, ASCII, or coordinate fallbacks.

Example prompt:

```text
Use $explain-clearly to explain JavaScript closures with a simple mental model and one concrete example.
```
