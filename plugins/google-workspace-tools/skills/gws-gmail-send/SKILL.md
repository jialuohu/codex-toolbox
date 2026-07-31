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
prior draft, or ambiguous request is not send authorization.

Before draft or send, apply the shared attachment safety contract to every
user-supplied path: require an absolute path; use `lstat` to require a regular
final object and reject a final symlink; preview its canonical target path and
basename in the identity/recipient preview; then immediately revalidate the
same path and canonical target before invoking gws. Fail closed on change.
