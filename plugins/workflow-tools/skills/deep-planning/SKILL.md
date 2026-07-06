---
name: deep-planning
description: Use when Codex is in Plan Mode for non-trivial, ambiguous, architectural, multi-step, high-risk, or orchestration-bound work; when reviewing a plan before coding; or when the user asks to think deeply, challenge assumptions, do adversarial planning, or choose between Codex-only, Superpowers, OpenSpec, and Symphony/Linear. Do not use for tiny edits, simple command-output checks, pure execution, post-code verification, or full Superpowers design-doc workflows.
---

# Deep Planning

Use this skill to raise Plan Mode quality before a plan is accepted. It is an
adversarial critique gate, not an execution workflow.

## Boundaries

- Do not edit or write files, create issues, dispatch workers, refresh
  schedulers, mutate external systems, or run implementation steps from this
  skill.
- Do not write `docs/superpowers/` artifacts. Superpowers owns design docs,
  implementation plans, execution, TDD, and completion verification.
- Do not replace `superpowers:brainstorming` when the user wants a full
  collaborative design/spec workflow. Use this skill only to critique and route
  Plan Mode work.
- For tiny edits, simple command-output checks, pure execution, or post-code
  verification, skip the full protocol and answer directly.

## Protocol

1. **Ground the plan.** Gather observed facts before asking questions. Read the
   minimal files, docs, memory, or tool output needed to avoid guessing.
2. **Name assumptions and unknowns.** Separate observed facts from assumptions.
   Ask only material questions whose answers would change architecture, scope,
   risk, or routing.
3. **Draft the strongest plan.** Prefer a simple, surgical plan with explicit
   goals, non-goals, constraints, affected surfaces, and verification.
4. **Run adversarial review.** Challenge the draft across the review axes
   below. Assume the plan is wrong somewhere and find where.
5. **Revise or block.** Fix the plan inline when the answer is inferable. Ask
   the user only when a material unknown remains.
6. **Route execution.** End by choosing the next lane: Codex-only, Superpowers,
   OpenSpec, or Symphony/Linear.

## Adversarial Review Axes

- **Product value:** Does the plan solve the real user goal, or only the stated
  implementation idea? What would be wasteful?
- **Architecture:** Are boundaries, dependencies, data flow, and ownership
  coherent with the existing system?
- **Implementation risk:** What is likely to fail first? Which assumptions are
  brittle, expensive, or hard to reverse?
- **Edge cases:** What missing states, permissions, concurrency, migration, or
  platform cases could break the plan?
- **Tests:** What failing test or deterministic check proves the plan is right?
  What evidence would be weak or misleading?
- **Rollout:** How will the change be introduced, verified, reverted, or
  handed off without surprising the user?
- **Scope:** What should be cut, deferred, or split so the plan stays small and
  reviewable?

## Routing

- **Codex-only:** Use for tiny edits, one bugfix, one review, fast debugging,
  or single-session exploration.
- **Superpowers:** Use when the task needs collaborative brainstorming, a
  written implementation plan, TDD execution, subagent-driven development, or
  verification-before-completion.
- **OpenSpec:** Use when the work benefits from durable requirements,
  acceptance criteria, or multi-agent/spec governance before implementation.
- **Symphony/Linear:** Use when the revised plan has 3 or more independent,
  testable implementation tasks, needs durable multi-ticket execution, or
  should be visible outside the Codex thread.

## Output Contract

For non-trivial Plan Mode work, use this exact section sequence unless the
current conversation format requires something stricter. Do not skip
**Strongest Plan** even when the revised plan is similar; the critique needs a
clear target.

- **Observed Facts:** Brief source-backed facts gathered before planning.
- **Assumptions / Unknowns:** Assumptions you are making and any material
  question that remains.
- **Strongest Plan:** The best current plan before critique.
- **Adversarial Review:** The most important objections and failure modes.
- **Revised Plan / Routing:** The final plan and the chosen execution lane.

For tiny Plan Mode prompts, keep the answer short and skip formal sections.
