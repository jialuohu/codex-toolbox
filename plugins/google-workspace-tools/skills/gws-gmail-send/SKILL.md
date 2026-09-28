---
name: gws-gmail-send
description: Use when drafting or explicitly sending a Gmail message through gws for a selected isolated account alias.
---

# Draft or send Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) and read its
[compose and attachment contract](../gws-shared/references/compose.md) before
any operation. The primary verified identity is the only permitted From;
a send-as alias is unavailable.

Validate new-message thread context against the request.

Always create a server-side draft first:

```bash
/bin/bash "$gws_account" run --alias "$gws_alias" --expected-email "$expected_email" -- gmail +send --from "$expected_email" --to <recipients> --subject <subject> --body <body> --draft
```

Follow the mandatory reference for the full authoritative readback, identity/recipient
preview, attachment staging, and decoded MIME validation. A draft-only request
stops after preview. Only explicit user intent to send now permits the reference's
exact newly created draft send after immediate unchanged readback; never rebuild
or use `users.messages.send`. Fail closed on any mismatch or uncertain outcome.
