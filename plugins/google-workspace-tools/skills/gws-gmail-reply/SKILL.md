---
name: gws-gmail-reply
description: Use when drafting or explicitly sending a reply to a Gmail message through an isolated gws account alias.
---

# Draft or send a Gmail reply

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Use `gws gmail +reply --message-id <id> --body <body> --draft` as the default. Before any explicit send, preview the verified sender, resolved reply target, added To/CC/BCC recipients, subject/thread context, attachment basenames, and send versus draft state. Only remove `--draft` for explicit user intent to send now. Attachments require user-identified absolute paths.
