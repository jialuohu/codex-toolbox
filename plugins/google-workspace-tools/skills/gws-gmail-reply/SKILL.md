---
name: gws-gmail-reply
description: Use when drafting or explicitly sending a reply to a Gmail message through an isolated gws account alias.
---

# Draft or send a Gmail reply

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Use
`"$gws_bin" gmail +reply --message-id <id> --body <body> --draft` in its exact
isolated environment. Remove `--draft` only after explicit user intent to send
now. Before sending, show an identity/recipient preview: verified sender,
resolved reply target, added To/CC/BCC recipients, thread context, attachment
basenames, and draft/send state. Attachments require user-identified absolute
paths.
