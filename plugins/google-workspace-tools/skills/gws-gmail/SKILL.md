---
name: gws-gmail
description: Use when searching, reading, drafting, replying to, or forwarding Gmail through the direct gws CLI for an explicitly selected account alias.
---

# Gmail through isolated gws

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) before every command. Do not recreate its environment logic or use guessed `--profile` or `--config` flags. Reads and searches may proceed only after its successful preflight.

Use only Gmail message/thread search, list, get, labels, drafts, and the helper skills below. Inspect a new raw method with `gws schema` in the same isolated environment, then keep it inside this Gmail-only boundary.

- [Read](../gws-gmail-read/SKILL.md) and [triage](../gws-gmail-triage/SKILL.md) are read-only after preflight.
- [Send](../gws-gmail-send/SKILL.md), [reply](../gws-gmail-reply/SKILL.md), [reply-all](../gws-gmail-reply-all/SKILL.md), and [forward](../gws-gmail-forward/SKILL.md) compose `--draft` by default.

Trash and multi-message changes require explicit user intent plus the live identity/recipient preview. Do not invoke `users.messages.delete`, `users.messages.batchDelete`, settings resources, or non-Gmail commands.
