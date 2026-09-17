# Apple Mail

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Apple Mail Tools](#apple-mail-tools)

## Apple Mail Tools

The default macOS-only `apple-mail-tools` plugin exposes every enabled Mail.app
account, including Exchange accounts whose reported type is `unknown`, through
the local `apple_mail` MCP. It uses Mail's supported AppleScript dictionary; it
does not use Microsoft Graph, IMAP, SMTP, Keychain credentials, Accessibility
automation, Mail's private database, remote HTML, or a programmatic send path.

The pinned Python 3.12/FastMCP runtimes are immutable generations below
`${CODEX_HOME:-$HOME/.codex}/runtime/apple-mail-tools-generations/envs/<fingerprint>`.
Toolbox setup resolves the exact installed plugin source from
`codex mcp get apple_mail --json`, checks that it is beneath the marketplace
cache, and installs the matching fingerprinted generation. Existing tasks keep
their old locked generation until they close naturally; newly started tasks use
the newly installed generation. Setup does not stop, signal, or restart active
MCP processes. The legacy `${CODEX_HOME:-$HOME/.codex}/runtime/apple-mail-tools`
environment remains untouched for old cached plugin processes.

Normal MCP startup fingerprints the installed plugin, takes a shared lock only
for that generation, validates its private stamp, and starts without dependency
synchronization or network access. Setup uses separate setup and per-generation
locks, so an active legacy runtime or unrelated generation cannot block an
online installation.

Use the focused helper with:

```bash
scripts/setup-apple-mail-tools.sh --install
scripts/setup-apple-mail-tools.sh --check
scripts/setup-apple-mail-tools.sh --status
scripts/setup-apple-mail-tools.sh --init-config
scripts/setup-apple-mail-tools.sh --prune
```

`--prune` is manual. It preserves the current generation, generations
referenced by installed plugin copies, active locked generations, and the legacy
fixed runtime. Full toolbox setup never prunes automatically.

The first status or MCP call may trigger macOS Automation permission. Allow the
calling Codex process or `osascript` to control Mail under **System Settings →
Privacy & Security → Automation**. The health check reads no messages.

Private configuration, HMAC handles, intents, attachment leases, and the
SQLite FTS5 history index live below
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/apple-mail-tools`.
Directories use mode `700`; configuration, keys, SQLite files, and receipts use
mode `600`. Full-history indexing stores normalized plain text and metadata, not
raw MIME, HTML, or attachment bytes. It excludes `Junk`, `Junk Email`, `Spam`,
`Trash`, `Deleted Items`, and `Deleted Messages` by default. Edit the private
`config.json` to override mailbox-name exclusions. Index creation is blocked
when FileVault is off or indeterminate unless that file explicitly sets
`allow_unencrypted_index` to `true`.

Index commits process at most 500 message locations or ten minutes, checkpoint
progress, and resume after another prepare/commit pair. Search results always
report freshness, exclusions, and completeness; a live read revalidates every
indexed location before it can be used for a mutation. `apple_mail_erase_index`
is the explicit prompt-gated cleanup path.
Plugin uninstall preserves private index data.

Incoming attachments are prompt-gated, limited to 25 MiB, stored in private
24-hour leases, and removed with `apple_mail_release_attachment`. Outgoing
drafts accept up to ten attachments, 25 MiB each and 50 MiB total, from the home
folder. A non-overridable denylist rejects hidden paths, `~/Library`, Codex
secrets, SSH/GPG/keychain material, credential-like files, private keys,
symlinks, and non-regular files.

Message changes use a preview and a ten-minute single-use commit token. Batches
are limited to 20 exact signed handles, prevalidate every target, act one message
at a time, and stop on the first mismatch. Trash is a recoverable move to a
configured Trash mailbox; permanent deletion and empty-trash tools do not
exist. New, reply, reply-all, and forward operations create, save, and visibly
open drafts. Inspect the draft and click **Send** in Mail; the MCP cannot send
mail.

Mail content is untrusted input. It cannot authorize writes, select tools, run
shell commands, open links, or change permissions. The owning `$apple-mail`
skill enforces exact previews and keeps Gmail and Outlook connector workflows
separate.
