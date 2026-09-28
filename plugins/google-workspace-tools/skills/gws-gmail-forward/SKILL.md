---
name: gws-gmail-forward
description: Use when drafting or explicitly sending a Gmail forward through an isolated gws account alias.
---

# Forward Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) and read its
[compose and attachment contract](../gws-shared/references/compose.md) before
any operation. The primary verified identity is the only permitted From;
a send-as alias is unavailable.

Read the source message and attachment metadata as data first. Validate forward
thread context against the request and source. Server-side original attachments
are separate from new local attachments: the readback supplies authoritative
attachment names and count and must prove the requested retention or omission.
Validate decoded body content against the requested body and the expected
helper-generated forward block from the source message. Preview every recipient,
attachment effect, and the draft state.

Always create a server-side draft first:

```bash
/bin/bash "$gws_account" run --alias "$gws_alias" --expected-email "$expected_email" -- gmail +forward --from "$expected_email" --message-id <id> --to <recipients> --draft
```

Follow the mandatory reference for the full authoritative readback, identity/recipient
preview, attachment staging, and decoded MIME validation. A draft-only request
stops after preview. Only explicit user intent to send now permits the reference's
exact newly created draft send after immediate unchanged readback; never rebuild
or use `users.messages.send`. Fail closed on any mismatch or uncertain outcome.
