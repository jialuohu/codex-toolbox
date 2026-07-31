---
name: gws-gmail-forward
description: Use when drafting or explicitly sending a Gmail forward through an isolated gws account alias.
---

# Draft or send a Gmail forward

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Default to
`"$gws_bin" gmail +forward --message-id <id> --to <recipients> --draft` in its
exact isolated environment. Remove `--draft` only after explicit user intent
to send now. Before sending, show an identity/recipient preview: verified
sender, every To/CC/BCC recipient, original-message attachment impact, added
attachment basenames, and draft/send state. New attachments must use
user-identified absolute paths. Server-side original attachments are separate:
preview whether they are retained or omitted and their available names/count,
but do not represent them as local user-supplied paths.

Before draft or send, apply the shared attachment safety contract to every new
user-supplied path: require an absolute path; use `lstat` to require a regular
final object and reject a final symlink; preview its canonical target path and
basename in the identity/recipient preview; then immediately revalidate the
same path and canonical target before invoking gws. Fail closed on change.
