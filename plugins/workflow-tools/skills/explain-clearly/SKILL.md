---
name: explain-clearly
description: Use when the user asks to explain, teach, clarify, compare, walk through, or help them understand a concept, system behavior, error, or code; especially for why/how questions or when a definition alone is not enough. Do not use for execution-only requests or simple facts that need only a terse answer.
---

# Explain Clearly

## Overview

Make the idea usable, not merely correct. Lead with the answer, build one
truthful mental model, and ground it in one concrete example before adding
detail.

## Answer Contract

Present these layers in order, using natural prose rather than mandatory
headings:

1. **Direct answer:** State the conclusion in one or two plain sentences.
2. **Mental model:** Give the smallest accurate way to think about the idea.
   Label an analogy as an analogy and do not let it replace the real mechanism.
3. **Concrete example:** Make the default response contain exactly one worked
   example and connect every step back to the idea. Extend that same example to
   expose a misconception instead of starting another. For code, trace the
   input, important state or control flow, and output.
4. **Mechanism and limits:** Explain what literally happens, then add only the
   caveat or common misconception needed to prevent a wrong understanding.

Infer the user's level from their wording. Define unavoidable jargon inline.
For a terse factual query that was explicitly routed here, or when the user
explicitly requests brevity, the Direct answer may be the complete response.

## Choose the Smallest Useful Format

Add a visual only when it makes an important relationship materially easier to
understand. Use concise prose or a short list for one conclusion or a simple
procedure; a Markdown table for three or more comparable entities or repeated
fields; `$pretty-mermaid` by default for a static relationship, hierarchy, or
sequence; and bundled Visualize for spatial, changing, adjustable, or
inspectable information on a supported desktop, web, or mobile surface. Pretty
Mermaid saves editable `.mmd` source and renders SVG on graphical surfaces or
ASCII in a terminal. Use native inline Mermaid only when explicitly requested
or as a disclosed fallback for an unavailable renderer or rejected syntax.
Build project files or use Sites for a standalone or hosted application rather
than putting it in inline Visualize.

Lead with the result, show the smallest useful representation, and add only the
essential caveat. Do not narrate every element already visible in a diagram or
table. A visual is presentation, not evidence: validate the source data,
coordinates, calculations, and legal state first. For chess, reconstruct and
validate the exact position, orientation, side to move, and move legality before
drawing a board or arrow; report ambiguity instead of inventing pieces. Never
use a generative image model for an exact factual diagram. Make Visualize output
responsive and accessible; in a CLI or IDE, fall back to Mermaid, a table,
ASCII, or explicit coordinates.

## Adapt the Explanation

- For a comparison, lead with the practical distinction, compare only the
  dimensions that affect the user's decision, and give one contrasting example.
- For a code walkthrough, show the result first, then trace only the lines and
  state changes that cause it. Make snippets runnable when practical.
- For an error, distinguish the visible symptom from the underlying cause and
  show one minimal failing-to-working example when a fix is requested.
- For sourced or current claims, establish the facts with the appropriate tool
  or domain skill first. Preserve uncertainty instead of simplifying it away.

## Control Depth

Default to layered concision and complete the answer after the mechanism-and-
limits layer. Use multiple worked examples only when the user asks for them or
two cases must be contrasted to answer the question. Add deeper internals,
history, or edge cases only when they prevent a likely misunderstanding. Avoid
quizzes, repeated summaries, decorative analogies, and closing offers that add
no information. Other explicit user instructions for length, format, audience,
or depth override these defaults.

## Example Shape

For `setTimeout(fn, 0)`, first say that `fn` runs after the current synchronous
work, not immediately. Model it as joining a queue, trace `1 -> queued callback
-> 3 -> 2`, then clarify that the queue is the intuition while the event loop
and task queue are the mechanism.
