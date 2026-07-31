---
name: gws-gmail-send
description: Use when drafting or explicitly sending a Gmail message through gws for a selected isolated account alias.
---

# Draft or send Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Compose with
`"$gws_bin" gmail +send --to <recipients> --subject <subject> --body <body> --draft`
in its exact isolated environment. A request to “write” means draft only.

Remove `--draft` only after explicit user intent to send now. Immediately before
that command, show an identity/recipient preview: verified sender, To/CC/BCC
recipients, subject, attachment basenames, and draft/send state. A deadline,
prior draft, or ambiguous request is not send authorization. Each `--attach`
must be a user-identified absolute path.
