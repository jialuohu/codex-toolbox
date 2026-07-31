---
name: gws-gmail
description: Use when searching, reading, drafting, replying to, or forwarding Gmail through the direct gws CLI for an explicitly selected account alias.
---

# Gmail through isolated gws

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) before every command.
Use its validated `profile`, isolated environment, and absolute `$gws_bin`; do
not use guessed `--profile` or `--config` flags. Reads and searches may proceed
only after successful preflight.

Raw Gmail resource access is read-only: restrict messages, threads, drafts, and
labels to list/get/search. Inspect those methods with `"$gws_bin" schema` in the
same isolated environment.

- [Read](../gws-gmail-read/SKILL.md) and [triage](../gws-gmail-triage/SKILL.md) are read-only after preflight.
- Route every compose, send, reply, reply-all, and forward through the linked
  [send](../gws-gmail-send/SKILL.md), [reply](../gws-gmail-reply/SKILL.md),
  [reply-all](../gws-gmail-reply-all/SKILL.md), and
  [forward](../gws-gmail-forward/SKILL.md) helper skills. Raw
  `users.messages.send` is unavailable. Raw `users.drafts.send` is permitted
  only inside one of those helper skills, after explicit user intent to send,
  for the exact newly created server-side draft whose full fields passed the
  helper's first validation and immediate unchanged readback. It is unavailable
  for an existing, user-selected, guessed, or modified draft.

The only permitted mutations outside those helper skills are requested label
application/removal, Trash/untrash, and a bounded batch mutation. Each requires
explicit user intent and a target preview containing the exact action, explicit
alias and verified identity, query snapshot if used, count, exact
message/thread IDs, labels being added or removed, and all targets before
execution. A query alone never authorizes a mutation.

Raw label create/update/patch/delete and raw draft create/update/delete methods
are unavailable. Raw draft list/get remains read-only; raw draft send has only
the narrow helper boundary above. Do not invoke `users.messages.delete`,
`users.messages.batchDelete`, `users.settings`, watch methods, or non-Gmail
commands. Any raw method outside the read-only and narrow mutation allowlists
above is unavailable; fail closed.
