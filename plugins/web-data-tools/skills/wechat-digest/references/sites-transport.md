# Sites Transport

Read this only for the operation selected by SKILL.md. Resolve every `scripts/`
path from the parent skill directory, not from this references directory.

## Pinned Sites Source Transport

`scripts/sites_source_transport.py` is only for the owner-only digest Sites source bound by the per-device `${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/sites-source-transport.json` file. Keep that file outside every Git checkout, owned by the current user, and at mode `600`. It must contain exactly `project_root`, `project_id`, and `remote_url`; never add a credential or token:

```json
{
  "project_root": "/absolute/path/to/info-site",
  "project_id": "<sites-project-id>",
  "remote_url": "https://git.chatgpt-team.site/<repository-id>/<sites-project-id>.git"
}
```

The transport fails closed when the private boundary file is missing, unsafe, malformed, or inconsistent. It has exactly two operations: start `sites_source_transport.py push` to non-force push the current clean `HEAD` to the pinned `main` branch and verify exact readback, or start `sites_source_transport.py readback` to compare that branch with local `HEAD` without a remote mutation.

Start the selected operation as a tool-controlled terminal process and send nothing before the transport emits and flushes the exact readiness line `{"event":"credential_input_ready"}`. That line means every local preflight passed and terminal echo is already disabled. Only after observing that exact line, send one fresh credential JSON line through tool-controlled non-echoed stdin. Use only a fresh structured credential returned for this exact Sites project. On success, the transport emits exactly one redacted SHA receipt after the readiness line; earlier failures emit no readiness line, and failures emit only a bounded error.

Do not use shell `echo`, a pipe, command interpolation, CLI credential arguments, credential environment variables, credential files, temporary files, or logs to pass or retain the credential. Never print the credential, token, authorization header, stdin payload, Git child arguments, Git environment, or raw Git output.
