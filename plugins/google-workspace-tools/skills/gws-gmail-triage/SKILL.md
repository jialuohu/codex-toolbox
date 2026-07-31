---
name: gws-gmail-triage
description: Use when listing unread Gmail summaries for a user-selected isolated gws account alias.
---

# Triage Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. After a passing preflight, run `gws gmail +triage --max <bounded-count>` in the same environment. Use a user-supplied Gmail query when one is needed. This is read-only. Return a minimal sender, subject, and date summary; do not turn a triage request into an archive, label, trash, or reply action.
