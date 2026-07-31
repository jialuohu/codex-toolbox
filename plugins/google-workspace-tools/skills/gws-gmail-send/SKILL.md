---
name: gws-gmail-send
description: Use when drafting or explicitly sending a Gmail message through gws for a selected isolated account alias.
---

# Draft or send Gmail

**REQUIRED:** Apply [gws-shared](../gws-shared/SKILL.md) first. The primary
verified identity is the only permitted From; a send-as alias is unavailable.

## Authoritative draft preview

Always create a server-side draft first with
`"$gws_bin" gmail +send --from "$expected_email" --to <recipients> --subject <subject> --body <body> --draft`
in the exact isolated environment. Parse exactly one draft ID from the helper's
JSON result; zero, duplicate, or malformed IDs fail closed. Fetch that ID with
raw `users.drafts.get` using the `full` format.

Treat the full draft readback as authoritative. Validate the actual From
case-insensitively against `$expected_email`; validate actual To/CC/BCC,
subject, new-message thread context, and attachment names and count against the
request and staged inputs. Preview the readback in the identity/recipient
preview, including draft state. A draft-only request stops after this preview.

## Optional send-now boundary

Only explicit user intent to send now is pre-authorization. Immediately before
sending, perform another full `users.drafts.get` and require an immediate
unchanged readback of the exact newly created draft, including From, To/CC/BCC,
subject, thread context, and attachment names and count. Then, and only then,
invoke raw `users.drafts.send` with that exact draft ID. Any mismatch, deadline,
prior draft, or ambiguous request must fail closed; never rebuild or send with
`users.messages.send`.

## Attachment staging

Apply the shared attachment safety contract independently to each attachment:
perform the initial lstat, canonical device/inode, SHA-256, and byte size
record; create a private temporary directory; copy the exact bytes to a
mode-`600` file with the same basename; perform the post-copy original restat
and rehash; and require the staged digest to match. Preview the original
absolute path, basename, size and digest. Perform the final staged digest check,
pass only the staged copy to gws, and cleanup on every exit. Never pass the
mutable user-supplied path.
