---
name: gws-gmail-triage
description: Use when listing unread Gmail summaries for a user-selected isolated gws account alias.
---

# Triage Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. After a passing
preflight, run `"$gws_bin" gmail +triage --max <bounded-count>` in the same
environment. Use a user-supplied Gmail query when needed. This is read-only.
Return a minimal sender, subject, and date summary; do not turn triage into an
archive, label, trash, or reply action.
