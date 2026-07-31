---
name: gws-gmail-reply-all
description: Use when drafting or explicitly sending a Gmail reply-all through an isolated gws account alias.
---

# Draft or send Gmail reply-all

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Start with `gws gmail +reply-all --message-id <id> --body <body> --draft`. Reply-all is especially recipient-sensitive: preview every resolved To/CC/BCC recipient, the verified sender, thread context, attachment basenames, and send/draft state. Only remove `--draft` after explicit user intent to send now. Attachments must be user-identified absolute paths.
