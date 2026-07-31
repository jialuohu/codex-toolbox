---
name: gws-gmail-reply-all
description: Use when drafting or explicitly sending a Gmail reply-all through an isolated gws account alias.
---

# Draft or send Gmail reply-all

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. Start with
`"$gws_bin" gmail +reply-all --message-id <id> --body <body> --draft` in its
exact isolated environment. Remove `--draft` only after explicit user intent
to send now. Before sending, show an identity/recipient preview: verified
sender, every resolved To/CC/BCC recipient, thread context, attachment
basenames, and draft/send state.

Before draft or send, apply the shared attachment safety contract to every
user-supplied path: require an absolute path; use `lstat` to require a regular
final object and reject a final symlink; preview its canonical target path and
basename in the identity/recipient preview; then immediately revalidate the
same path and canonical target before invoking gws. Fail closed on change.
