# Gmail composition and attachments

Read this reference before any compose operation. Resolve all `scripts/` paths
from the parent gws-shared skill directory. Apply [the shared account check](../SKILL.md)
and the selected compose skill's source, recipient, and thread rules first.
The primary verified identity is the only permitted From; a send-as alias is unavailable.

## Authoritative draft preview

Always create a server-side draft first using the selected skill's `--draft`
command through the account helper. Parse exactly one draft ID from the helper's
JSON result; zero, duplicate, or malformed IDs fail closed. Fetch that ID with
raw `users.drafts.get` using the `full` format.

The `gws v0.22.5 schema` defines `gmail.users.drafts.get` with required
`userId` and `id` parameters plus `format=full`, and
`gmail.users.drafts.send` with required `userId` parameters plus a `Draft`
request body. After shared preflight, use the account helper and
JSON-encode the parsed ID rather than interpolating it:

```bash
draft_get_params="$(
  DRAFT_ID="$draft_id" /usr/bin/python3 -I - <<'PY'
import json
import os
print(json.dumps({
    "userId": "me",
    "id": os.environ["DRAFT_ID"],
    "format": "full",
}, separators=(",", ":")))
PY
)" || exit 1
draft_json="$(/bin/bash "$gws_account" run --alias "$gws_alias" --expected-email "$expected_email" -- gmail users drafts get --params "$draft_get_params")" || exit 1
```

Treat the full draft readback as authoritative. Validate the actual From
case-insensitively against `$expected_email`; validate actual To/CC/BCC,
subject, the selected operation’s thread context, and attachment names and count against the
request and staged inputs. Recursively base64url-decode every inline
`text/plain` and `text/html` MIME leaf in `draft.message.payload`; preserve the
API part order and build a canonical MIME content digest from each part path,
lowercase MIME type, decoded byte length, and SHA-256 of its decoded bytes.
Validate decoded body content against the requested body and any expected
helper-generated MIME structure. Missing or undecodable body bytes fail closed.
Preview the decoded body content as non-executable text plus the canonical MIME
content digest in the identity/recipient preview; never render active HTML.
Preview the readback, including draft state. A draft-only request stops after
this preview.

## Optional send-now boundary

Only explicit user intent to send now is pre-authorization. Immediately before
sending, perform another full `users.drafts.get` and require an immediate
unchanged readback of the exact newly created draft, including From, To/CC/BCC,
subject, thread context, attachment names and count, decoded body bytes and
canonical MIME content digest. Then, and only then, encode that same ID as the
entire `Draft` request body and invoke the exact isolated raw send:

```bash
draft_json_again="$(/bin/bash "$gws_account" run --alias "$gws_alias" --expected-email "$expected_email" -- gmail users drafts get --params "$draft_get_params")" || exit 1
draft_send_body="$(
  DRAFT_ID="$draft_id" /usr/bin/python3 -I - <<'PY'
import json
import os
print(json.dumps({"id": os.environ["DRAFT_ID"]}, separators=(",", ":")))
PY
)" || exit 1
/bin/bash "$gws_account" run --alias "$gws_alias" --expected-email "$expected_email" -- gmail users drafts send --params '{"userId":"me"}' --json "$draft_send_body" || exit 1
```

Any mismatch, deadline, prior draft, or ambiguous request must fail closed;
never rebuild or send with `users.messages.send`.

## Attachment safety contract

Use absolute attachment paths only. Before draft or send, stage every
user-supplied attachment as immutable input to the compose operation:

1. Perform an initial `lstat` on the original absolute path. Require a regular
   final object, reject a final symlink, resolve its canonical target path, and
   record device/inode identity, basename, byte size, and SHA-256 digest.
2. Create a private temporary directory with mode `700`, register cleanup for
   every success and failure path, and create one mode-`700` child directory
   per attachment. Copy the exact bytes into a new mode-`600` staged file that
   preserves the original basename.
3. After the copy, perform a post-copy original restat and rehash. Require the
   same non-symlink regular object, canonical target, device/inode, byte size,
   and digest recorded initially. `lstat` and hash the staged copy; record its
   canonical target, device/inode, size, and digest, and require its staged
   digest and size to match the original record.
4. In the identity/recipient preview show the original absolute path, basename,
   size and digest. Do not substitute or expose the temporary path as the
   user's attachment identity.
5. Immediately before invoking gws, repeat `lstat`, size, and SHA-256 checks on
   the staged file. Require the final staged digest and identity to match the
   staged record. Invoke gws with only the staged copy; never pass the mutable
   original path.
6. Cleanup the private temporary directory after a draft, a send, or any
   failure. Fail closed on every mismatch or cleanup-registration failure.

Perform all validation, copying, and hashing with trusted
`/usr/bin/python3 -I`, never PATH-resolved `python3`. Open the original and
staged files without following symlinks where the platform supports it.
