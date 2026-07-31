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
basenames, and draft/send state.

Before draft or send, apply the shared attachment safety contract to every
user-supplied path: require an absolute path; use `lstat` to require a regular
final object and reject a final symlink; preview its canonical target path and
basename in the identity/recipient preview; then immediately revalidate the
same path and canonical target before invoking gws. Fail closed on change.
