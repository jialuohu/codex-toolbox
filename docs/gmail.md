# Multi-account Gmail

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Isolated Multi-Account Gmail with gws](#isolated-multi-account-gmail-with-gws)

## Isolated Multi-Account Gmail with gws

The default `google-workspace-tools` plugin provides Gmail-only skills for
direct use of the pinned [`googleworkspace/cli`](https://github.com/googleworkspace/cli)
release `v0.22.5`. This is a Google Workspace GitHub project, but its own
README says it is **not an officially supported Google product** and describes
the CLI as pre-v1 software where breaking changes remain possible. Its
changelog also records that there is no current `gws mcp` command and no native
multi-account selector. The toolbox therefore uses one isolated configuration
directory per explicit account alias and exposes skills only—no gws MCP.

Keep the official Gmail connector for ordinary connected Gmail requests. Use
direct `gws` only when a request explicitly needs it or names a multi-account
workflow, require an alias such as `account-one`, and use one Gmail surface per
request. There is no default gws account. The normal toolbox setup installs the
plugin only; it does not install the `gws` binary, create profiles, or start
OAuth.

First run the read-only status check. A new device is expected to report missing
components until the opt-in setup is complete:

```bash
scripts/setup-gws.sh --check
```

On macOS arm64, install the pinned binary explicitly:

```bash
scripts/setup-gws.sh --install
```

Create the OAuth client manually in Google Cloud Console:

1. Create or select a personal-use Cloud project and enable the Gmail API.
2. Configure the OAuth audience as **External**. Before the final account
   logins, publish the app **In Production**; External apps left in Testing
   mode issue refresh tokens that expire after seven days for this scope.
3. Create an OAuth client of type **Desktop app** and download its JSON. An
   unverified personal-use app can show an unverified warning after publication;
   review it, confirm the project is yours, and accept the warning to continue.
4. The only Gmail permission requested is
   `https://www.googleapis.com/auth/gmail.modify`. `gws` v0.22.5 automatically
   adds the three identity scopes `openid`, `userinfo.email`, and
   `userinfo.profile` so it can verify the signed-in account. Never request
   `https://mail.google.com/`.

Register the downloaded Desktop client once, using a neutral absolute path:

```bash
scripts/setup-gws.sh --register-client /absolute/path/to/client_secret.json
```

Add each account separately with a non-secret alias. During each browser login,
select the matching account and approve the displayed `gmail.modify` permission
plus the three identity scopes; abort if any other scope is shown:

```bash
scripts/setup-gws.sh --add-account account-one@example.com --alias account-one
scripts/setup-gws.sh --add-account account-two@example.net --alias account-two
```

Profiles live outside Git under
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/gws/accounts/<alias>`.
Profile directories use mode `700`, files use mode `600`, and the runtime forces
the file keyring backend plus a missing profile-local ADC sentinel. OAuth client
JSON, tokens, profile metadata, and full real email addresses must remain
machine-local.

Check an account before use, or list aliases and health without displaying full
email addresses:

```bash
scripts/setup-gws.sh --check-account account-one
scripts/setup-gws.sh --list-accounts
scripts/setup-gws.sh --check
```

Reauthenticate an existing profile, including one with an expired or revoked
token, without changing its expected identity, then check it again:

```bash
scripts/setup-gws.sh --reauth-account account-one
scripts/setup-gws.sh --check-account account-one
```

Start a fresh Codex task after installation or profile changes so the
`google-workspace-tools` skills are available from the start.
