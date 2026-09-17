# Compatibility and recovery contract

## Supported boundary

V1 uses macOS, Python 3.9+, and the observed `remote-projects` records with
`id`, `label`, `hostId`, and `remotePath` fields.
Account layouts are read from
`electron-persisted-atom-state/sidebar-custom-sections-v3`. Project order,
appearance, and expansion values are copied only for newly registered projects.
Existing registrations retain their destination placement, including ungrouped.
The case-sensitive path is resolved on the explicitly selected project Mac;
two registrations resolving to the same directory are ambiguous, not merged.

Nonempty app-server project migration, legacy-ID mapping, or pending-deletion
state blocks legacy **writes**, even when the records look familiar. A no-change
audit remains supported. Source sections may contain `hostSectionIds`; these
are never copied. Section creation and placement use owning app tools after
restart. Unknown project fields block creation. This adapter is not a promise
of compatibility with future app versions. It cannot recover deleted task files,
cloud-only conversations, explicit thread-to-project overrides, local-only saved
projects, or inaccessible old account layouts.

The recovery record binds the sidebar Mac by a hash of its hardware identifier;
hostnames alone are insufficient. A shared nonblocking writer lock prevents two
recovery records from writing the same Codex home concurrently. The desktop app
does not honor that lock, so the app-exit and file-change checks are still required.

The account check reads only `tokens.account_id` from the existing auth cache
into memory. No authentication token is logged or saved. Cross-check that account
with the owning app before preparation; a missing/mismatched cache is a stop.
SSH uses existing BatchMode authentication. The host probe reads paths, a hashed
hardware identity, and non-archived task IDs/cwd from `state_5.sqlite` read-only.
No task bodies or SQL writes are used. A missing database prevents full verification.

## Commands

Resolve `helper` to this skill's `scripts/recover_sidebar.py`. Run these commands
on the sidebar Mac. Values below are placeholders selected from inspected evidence,
not literal account or host IDs. `--project-host local` means that same Mac;
otherwise supply its existing SSH alias. Cross-Mac execution uses SSH to run the
installed helper on the explicitly chosen sidebar Mac, without copying state home.

```sh
python3 "$helper" inspect
python3 "$helper" prepare --record "$recovery_dir" \
  --source-account "$source_account" --old-host "$old_host" \
  --new-host "$current_host" --project-host "$project_host"
python3 "$helper" apply --record "$recovery_dir"
python3 "$helper" verify --record "$recovery_dir" --observations "$observations"
python3 "$helper" rollback --record "$recovery_dir"
```

`--codex-home` overrides the default `CODEX_HOME` or `~/.codex`. Use a fresh
directory under `~/.codex/sidebar-recovery/` for each repair. Directories must be
owned by the user, mode 700, outside Git, and without symlink components. Files
are mode 600. Records contain private project names/paths and task identifiers:
never commit them or attach them to a public issue.

When the app hosting the conversation must exit, a bounded detached command can
finish the prepared repair. Set `umask 077` before creating logs. Use `nohup`
with redirected stdin, stdout, and stderr and `--wait-seconds 600`, then record
its PID. It exits after the deadline, never restarts the app, and never persists
a watcher. Poll `status.json` on resumption. If it says `writing`, inspect the
journal: retrying apply succeeds only when both after-hashes match, otherwise
rollback is required. Do not start a second worker for the same record.

Each apply requires unchanged planned fields and account layouts, stable account
and host, unchanged paths, and an absent app. Unrelated shutdown updates are retained
from a fresh read; exact bytes are checked again immediately before each write.
Two file renames are not jointly atomic.
The journal is written first; `.bak` is replaced before the main file. Rollback
uses scoped before-values and refuses conflicts; it preserves unrelated keys.
Post-write app relaunch is reported in the receipt. All application checks are
still required even if both file writes succeeded.

## Verification observations

Create this minimal JSON from fresh **owning app tool results**, after the last
apply/status receipt. Do not invent success flags or substitute the proposed plan
for actual observations. `projects` must include every restored/reused destination
project and its actual task IDs; historical reads list successful read IDs only.

```json
{
  "account_id": "destination-account-id",
  "sidebar_device": "name-returned-by-inspect",
  "collected_at": 1900000000,
  "projects": [{"id": "destination-project-id", "hostId": "current-host-id",
                "remotePath": "/example/project", "task_ids": ["existing-task-id"]}],
  "historical_task_reads": ["existing-task-id"],
  "sections": [{"id": "destination-section-id", "name": "Research",
                "itemKeys": ["codex:project:destination-project-id"]}]
}
```

The helper also checks persisted destination section membership and unchanged
source layout. `verified` means these observations passed; it is not an independent
MCP client and cannot attest fabricated input. Keep raw tool evidence in the task
and store only the reduced observations locally. Empty projects need no historical
read; a nonempty baseline requires one. Newly appearing tasks are allowed, but all
baseline tasks must remain associated with their respective projects.

Native app operations have their own receipts and rollback. Helper status refers
to the file transaction; `metadata-rolled-back` alone never proves native sections were
restored. Do not publish or install the toolbox as part of this skill.
