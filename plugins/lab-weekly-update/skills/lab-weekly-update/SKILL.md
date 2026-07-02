---
name: lab-weekly-update
description: Draft concise lab weekly updates from technical work artifacts. Use when the user asks to summarize recent engineering or research progress from repo diffs, benchmark outputs, profiling artifacts, experiment notes, meeting notes, or TODOs into a weekly update, sync update, or lab-status note.
---

# Lab Weekly Update

## Overview

Create a weekly lab update that is evidence-backed, concise, and useful for a technical audience. Prefer concrete artifacts, measured results, and next actions over broad narrative.

## Workflow

1. Identify the target period, project, and audience from the prompt. If missing, infer the current week and the active repo or workspace.
2. Gather evidence before drafting:
   - Inspect relevant git status, recent commits, diffs, benchmark outputs, profiling reports, experiment logs, meeting notes, and TODO files.
   - Preserve exact artifact names, paths, dates, metrics, and commands when they matter.
   - Separate current verified results from older context or unverified memory.
3. Organize the update into:
   - Done: completed work and merged or validated changes.
   - Results: benchmark, profiling, correctness, or experiment outcomes with numbers.
   - Blockers: environment issues, failing checks, missing data, or decisions needed.
   - Next: concrete follow-ups for the next week.
4. Call out uncertainty explicitly. Use phrases like "not verified in this pass" or "needs rerun" when evidence is incomplete.
5. Keep the final text compact unless the user asks for a detailed report.

## Output Shape

Default to this structure:

```markdown
## Weekly Update

### Done
- ...

### Results
- ...

### Blockers / Risks
- ...

### Next
- ...
```

If the user asks for a Docmost, slide, email, or meeting-note format, adapt the headings while preserving the same evidence discipline.

## Quality Rules

- Do not invent metrics, paths, commits, or conclusions.
- Do not treat stale benchmark numbers as current if a correctness or environment change invalidated them.
- Prefer "no blocker found" over an empty blocker section only when evidence supports it.
- Keep project-specific caveats tied to artifacts or commands so another person can reproduce the reasoning.
