---
name: gws-gmail-send
description: Use when drafting or explicitly sending a Gmail message through gws for a selected isolated account alias.
---

# Draft or send Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Compose with `gws gmail +send --to <recipients> --subject <subject> --body <body> --draft` by default. A request to “write” means draft only.

Remove `--draft` only when the user explicitly says to send now. Immediately before that command, show an identity/recipient preview: verified sender, To/CC/BCC recipients, subject, attachment basenames, and whether it is a draft or send. Do not convert a deadline, a prior draft, or an ambiguous request into send authorization. Each `--attach` value must be an absolute path specifically identified by the user.
