# Planning and explanations

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Execution Routing](#execution-routing)
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
