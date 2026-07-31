---
name: gws-gmail-forward
description: Use when drafting or explicitly sending a Gmail forward through an isolated gws account alias.
---

# Draft or send a Gmail forward

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Default to `gws gmail +forward --message-id <id> --to <recipients> --draft`. Preview the verified sender, every To/CC/BCC recipient, original-message attachment impact, added attachment basenames, and send/draft state before sending. Remove `--draft` only for explicit user intent to send now. New attachments must use user-identified absolute paths.
