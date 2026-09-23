# Compatibility and recovery contract

## Route selection

Use `app-owned-placement-v1` to recover **registered** project placement through
owning Codex app tools. This route does not call the desktop-build fingerprint
adapter, require app closure, or write legacy registration and section files.
An unknown desktop version is not by itself a refusal for app-owned placement.
The owning tools have no target-host selector and must run in a task opened in
the destination sidebar Mac's Codex desktop app. A task on an SSH project host
viewed from a different Mac can address that other Mac's sidebar; verify the
actual sidebar device before preparation and every operation. The operator must
verify that each observation came from that desktop's owning tools and retain
tool provenance in the task. The helper checks the supplied account, machine,
host, and path evidence, but cannot independently attest the app-tool endpoint
or fabricated results.

Match the current account ID against the destination's read-only identity cache,
the sidebar hardware identity against the local machine, and every project by
current app ID, observed host ID, physical host, and filesystem-resolved,
case-preserving path. The app-owned route checks that the observed host ID
matches the selected project-host alias and probes that host and its paths; it
does not read the client's saved connection binding or desktop build.
Refuse missing or ambiguous account/device evidence, duplicate IDs or physical
host/path identities, incomplete `list_projects` or `list_threads` results,
unavailable hosts/sources,
or non-unique destination section names. A source section ID is never a
destination ID. A snapshot records layout evidence, not permission to act.

App-owned recovery restores a verified prior custom or Pinned section only when
the registered destination project is currently ungrouped and recovery was
explicitly requested. Preserve a project already in any custom or Pinned section,
even if the source layout differs. Create only uniquely missing custom sections,
in source order, through the owning section tool; preserve unrelated sections,
projects, and task `itemKeys`. Project registration is a separate capability.
Use a documented owning registration tool only if one is exposed with a verified
contract. No project-create tool is currently exposed. Show the user the precise
destination host and folder in Codex's Add Project flow, then collect fresh
observations and prepare a new receipt after registration. Independent safe
section moves may verify, but a missing registration remains **partial recovery**
until that project is added and placed. Do not invent an API, synthesize an ID,
or fall through to unknown-build file writes. This route does not provide
automatic cross-Mac mirroring or custom-section project-order guarantees.

### App-owned commands and evidence

Resolve `helper` to this skill's `scripts/recover_sidebar.py`. The source layout
may be a previously verified portable `export-layout` snapshot or an
`export-app-layout` snapshot captured while the source layout is still visible.
Run app export from a task in the source sidebar Mac's app, and preparation,
application, verification, and rollback from a task in the destination Mac's app.
If neither layout source survives, stop rather than reconstructing placement
from names. Store snapshots and observations in a private mode-700 directory
outside Git, with mode-600 files and no symlink components.

```sh
python3 "$helper" export-app-layout --project-host "$project_host" \
  --new-host "$source_host_id" --observations "$source_observations" \
  --output "$snapshot"
python3 "$helper" prepare --route app-owned --source-layout "$snapshot" \
  --project-host "$project_host" --new-host "$destination_host_id" \
  --observations "$before_observations" --record "$recovery_dir"
python3 "$helper" apply --record "$recovery_dir" \
  --observations "$fresh_before_observations"
python3 "$helper" apply --record "$recovery_dir" --native-event "$event_file"
python3 "$helper" verify --record "$recovery_dir" \
  --observations "$after_observations"
python3 "$helper" rollback --record "$recovery_dir" --native-event "$event_file"
python3 "$helper" rollback --record "$recovery_dir" \
  --observations "$fresh_after_rollback_observations"
```

Keep each `--observations` file as a reduced wrapper built from **fresh**
owning-tool results. Set `collected_at` to the actual collection time, use the
hashed `sidebar_machine` from the destination Mac's read-only machine identity,
and obtain `account_id`
from the existing account identity; never place tokens in the file. The wrapper
has `schema: 1`, `kind: "owning-app-sidebar-observation"`, `collected_at`,
`sidebar_machine`, and `account_id`. Its `projects_result` retains the observed
`schemaVersion` and **all** `projects`, with each entry's `projectId`,
`projectKind`, `label`, `path`, and `hostId`. Its `threads_result` retains the
observed `schemaVersion`, **all** `sections` with `sectionId`, `name`, and
`itemKeys`, plus explicit empty `unavailableHosts` and `unavailableSources`.
Drop thread titles, summaries, and unrelated task listings; do not remove any
section or project from the inventory. Do not fabricate completeness by
enlarging a capped task list; section membership and task-association evidence
have different coverage.

The app-owned receipt is schema 3 with adapter `app-owned-placement-v1`,
separate from v1/v2 file receipts. Read its planned section and placement
operations before acting. For each owning-tool action, write a private event
with exactly `operation_id`, `stage`, `observed_at`, and `observation` (a fresh
wrapper in the shape above). Submit `intent` before the tool call, then
`confirmed` after fresh readback or `unresolved` if the outcome is uncertain.
Do not repeat an unresolved call; reconcile it against a fresh owning-app
listing first. If fresh readback proves that an attempted action made no change,
record the terminal `not-applied` stage; this permits rollback of earlier
confirmed actions, but retrying the failed action requires a new receipt.
Preparation bounds the action journal against its private file size limit before
any app action. The route progresses through `prepared`, `applying`, and
`placement-verified` only when each expected placement is observed.

For rollback, record `rollback-intent` before each inverse owning-tool action,
then `reversed` after fresh readback or `rollback-unresolved` for an uncertain
result. An inverse project move is allowed only while the project remains in
the recovery-owned section and returns to its recorded prior owner (`threads`
for an originally ungrouped project). Delete a recovery-created section only
when the user explicitly requests removal, it remains empty, and the
`rollback-intent` event is submitted with `--remove-empty-sections`. Never
delete a pre-existing section or move unrelated members. Final rollback status
is `rolled-back` only after fresh reconciliation.

App-owned `verify` checks app-visible project and section placement and unchanged
unrelated section members. It reports `task_associations_verified: false` because
the owning sidebar tools do not expose a complete historical membership audit.
Do not describe placement verification as full task-association recovery. The
private receipt stores complete section `itemKeys`, including task and project
IDs needed to check preservation; it excludes task titles, summaries, bodies,
and credentials.

## Legacy registration adapter boundary

The v2 legacy helper supports macOS and Python 3.9+. Its remote adapter uses
validated `remote-projects` records (`id`, `label`, `hostId`, `remotePath`) and account
layouts under `electron-persisted-atom-state/sidebar-custom-sections-v3`.
The selected compatibility profile must match the desktop version/build and
audited implementation fingerprint. It establishes whether remote registrations
remain client-owned despite local projects moving to app-server storage.

Unknown builds or migration ownership, target-remote migration/deletion state,
and unsupported project fields block writes with a diagnostic. This is a
compatibility refusal for that adapter, not evidence that the app has no project
API. Backend project inventory is read-only; never create or reassign server
projects as a substitute for client registrations. Profiles do not promise
compatibility with future builds.

The current destination adapter requires a saved discovered SSH connection in
the sidebar client's `codex-managed-remote-connections`. Its host ID and alias
must match `--new-host` and `--project-host`; an imported host ID cannot create
that binding. Custom connection commands, per-connection Codex-home overrides,
and other connection formats require another validated profile. Use the existing
supported connection setup before preparation; never rewrite saved connections
to make a profile match. Local project registrations remain outside this adapter.

Legacy section bindings are established with owning app tools after reopening.
Snapshots never carry reusable `hostSectionIds`. Under this legacy route,
existing destination names, appearance, order, and placement—including
ungrouped—win. For a missing registration, surviving destination placement
under an old connection precedes the donor layout. Conflicting identity or
placement evidence needs resolution.
Append missing registrations and sections; never delete historical registrations.
Built-in Pinned placement is preserved too: destination placement wins over the
donor, and source-pinned projects remain pinned when no destination choice exists.
Pin and unpin only through owning app tools; the helper never writes
`pinned-project-ids` or creates a custom replacement for the built-in section.

## Legacy registration identity and trust; shared privacy

Bind the sidebar Mac and project Mac by hashed physical hardware identity.
Resolve project paths on that host without case-folding. SSH and remote-control
IDs are aliases, not separate physical identities. Duplicate registrations
resolving to one directory are ambiguous, not automatically merged.

Resolve the actual project-host Codex home from its app-server initialization;
do not assume a default task database location. Read effective trust through
`config/read` for both each selected path and its filesystem-resolved path.
Every newly registered folder must be trusted at both paths; a missing approval
blocks the batch before app writes. Existing reused registrations do not acquire
a new trust requirement merely from inspection. Present the application's folder
approval step, then reprepare after consent. Never import trust, edit trust
configuration, or treat exported provenance as authorization.

The account check reads only the existing cache's account ID into memory.
Never log tokens or copy authentication material. Cross-check the destination
account with the owning app. SSH uses existing BatchMode authentication.
Read task metadata only; no task bodies, SQL writes, or history changes.
Working-directory matches supply candidate associations. Explicit assignments
and projectless choices must remain intact.

The task baseline covers unarchived tasks across all source kinds supported by
the audited protocol and all model providers. The read-only `thread/list` probe
explicitly supplies `sourceKinds`, `modelProviders: []`, and
`useStateDbOnly: true`; it does not scan or repair rollout files. Persist only
relevant task IDs and backend `projectId` assignment metadata alongside client
assignment/projectless choices, never task bodies. A non-null backend assignment
excludes a task from cwd-based candidates. Recheck those server assignments
through the read-only API during verification; never rewrite them for recovery.

Recovery directories are user-owned, mode 700, outside Git, without symlink
components; files are mode 600. Records can contain private names, paths, and
task IDs: never commit them or attach them publicly. `inspect --summary` omits
private identifiers and paths; use detailed inspection only within the task.

Create `--observations` and `--native-event` inputs inside the existing mode-700
receipt directory, using new filenames and `umask 077`. For example, after
constructing reduced JSON from actual observations:

```sh
umask 077
printf '%s\n' "$observed_json" > "$recovery_dir/observations-1.json"
printf '%s\n' "$event_json" > "$recovery_dir/native-event-1.json"
chmod 600 "$recovery_dir/observations-1.json" "$recovery_dir/native-event-1.json"
```

Use a canonical absolute receipt path with no symlink components. On macOS,
`/tmp` is a symlink and is not an accepted private-input path; do not bypass
the check by weakening file permissions or the symlink guard.

## Commands and donor snapshots

Resolve `helper` to this skill's `scripts/recover_sidebar.py`. Commands run on
the destination sidebar Mac except `export-layout`, which runs on the source.
Values below are placeholders from inspected evidence. For inspection and export,
`--project-host local` selects the same Mac. For v2 destination preparation,
supply the explicitly selected existing SSH alias matching the client's saved
discovered connection; `local` is not a supported remote registration target.
Use `--app-path` for the verified desktop application. `--codex-home` selects
the sidebar's actual Codex home, defaulting to `CODEX_HOME` or `~/.codex`.

```sh
python3 "$helper" inspect --summary
python3 "$helper" inspect --summary --project-host "$project_host" \
  --old-host "$old_host" --app-path "$app"
python3 "$helper" export-layout --source-account "$source_account" \
  --old-host "$old_host" --project-host "$project_host" --output "$snapshot"
python3 "$helper" prepare --record "$recovery_dir" \
  --source-account "$source_account" --old-host "$old_host" \
  --new-host "$current_host" --project-host "$project_host" --app-path "$app"
python3 "$helper" prepare --record "$other_recovery_dir" \
  --source-layout "$snapshot" --new-host "$current_host" \
  --project-host "$project_host" --app-path "$app"
python3 "$helper" apply --record "$recovery_dir"
python3 "$helper" apply --record "$recovery_dir" --native-event "$event_file"
python3 "$helper" verify --record "$recovery_dir" --observations "$observations"
python3 "$helper" verify --record "$recovery_dir" --inventory-only
python3 "$helper" rollback --record "$recovery_dir"
```

Use a fresh private directory such as `~/.codex/sidebar-recovery/<recovery-id>`.
Start with `inspect --summary` without a project host for the client inventory.
When probing a project host and multiple registration hosts exist, select the
registration group with `--old-host`; never probe another host's directories on
the selected Mac. Detailed inspection reports saved connection IDs, sources,
and aliases plus the selected host's actual home, machine identity, and paths.
Summary output continues to omit those private identifiers and paths.

Choose either local source-account evidence or a donor snapshot; do not combine
them. The accounts may match. A donor snapshot is bounded and versioned, carrying
selected paths, labels, supported appearance, section structure, ordering, and
provenance. It excludes task content, credentials, trust, and reusable server
bindings. Transfer it privately and revalidate every project-host identity and
path at the destination. Importing a snapshot never imports host authorization.
Portable projects use the reserved `section: "@pinned"` value for built-in
Pinned placement. It is not a portable custom-section key and does not generate
a section-creation action. `section_position` records the selected source order.

For additional historical connection aliases on the destination, repeat
`--alias-host "$verified_alias"` during preparation. Supply only aliases already
bound to the same physical project host by independent connection evidence;
the option is an explicit binding, not an identity-discovery mechanism.

V2 receipts preserve frozen source evidence, including selected source section
IDs. Relevant source drift before writing invalidates preparation. Same-account
verification allows recorded additions, including new empty sections, rather
than requiring an unchanged entire layout.
V1 receipts remain readable under their original apply and rollback semantics;
never silently upgrade an old plan. Prepare a new record for v2 behavior.

## File transaction and native operations

Before a transaction, reprobe project-host identity, actual Codex home, resolved
paths, and trust. Before each file replacement, recheck the local application
build/profile, account, sidebar identity/home, app absence, and exact file bytes.
Remote evidence is not re-requested between every pair of renames. A shared
nonblocking writer lock prevents concurrent helper writers to one Codex home.
The app does not honor that lock, so process and fresh-byte checks remain
necessary. Preserve unrelated updates from fresh reads.

A conflicting historical backup is a specific preparation blocker, not a reason
to repeatedly prepare against the same state. Inspect the affected desktop's
backup through its supported workflow; never delete or reset the backup to make
the repair pass.

Write the durable journal before staged main and backup replacements; two renames
are not jointly atomic. Inspect the journal after interruption. Resume only when
recorded states reconcile; never overwrite an unknown state. The persistent
status distinguishes file progress, native-operation progress, and verification.

If closing the app interrupts the conversation, set `umask 077` and launch a
single bounded `nohup` apply worker with redirected stdin/stdout/stderr and
`--wait-seconds 600`. Record its PID and private receipt path. The wait is capped
at 600 seconds; it never restarts or kills the app and installs no watcher.
The worker holds the receipt lock to prevent duplicate workers. Its waiting and
expiry progress lives in `worker.json`; it does not overwrite the transaction
phase in `status.json`. After reopening, inspect `status.json`, `worker.json`
when present, and `native.json` before continuing. Never start a second worker
for the same record.

For each native section action, record intent before invoking the owning tool,
then confirmed or unresolved status with fresh reduced observations. Use stable
operation identity from the planned action when resuming. An uncertain create
must be reconciled with current sections; absence of a returned ID does not
prove failure. Do not retry until current observations establish what happened.
Helper success and section-tool success are separate from verified recovery.

### Legacy native-event input

Native receipts serialize updates under the record lock and recheck the active
account and sidebar target. Each private event file contains exactly
`operation_id`, `stage`, `observed_at`,
and `sections`; do not add a `schema` field. Take `operation_id` verbatim from
`plan.json`'s `native_actions`. Forward stages are `intent`, `confirmed`, and
`unresolved`, submitted through `apply`. Reverse stages are `rollback-intent`,
`rollback-unresolved`, and `reversed`, submitted through `rollback`. Each section
contains exactly `id`, `name`, and
`itemKeys`. Read these values through supported owning app tools; the helper
cannot execute the native operation or validate fabricated evidence.
Include built-in Pinned membership in native and verification section observations,
using `{"id":"pinned","name":"Pinned","itemKeys":["codex:project:<observed-id>"]}`
derived from the app's actual pinned projects. This normalized observation is
not permission to invent members or create that section.

For example, an intent for the planned `section:s0` creation can look like this
when a fresh app listing actually reports no destination sections:

```json
{
  "operation_id": "section:s0",
  "stage": "intent",
  "observed_at": 1900000000,
  "sections": []
}
```

After the creation succeeds and a fresh listing observes the new section,
record its confirmed result in a separate private event file:

```json
{
  "operation_id": "section:s0",
  "stage": "confirmed",
  "observed_at": 1900000001,
  "sections": [
    {"id": "observed-section-id", "name": "Research", "itemKeys": []}
  ]
}
```

All IDs, names, and timestamps above are placeholders, not usable evidence.
Use actual epoch seconds and complete fresh section observations. Record the
intent after file application and before calling the section tool. A placement
uses its own planned `place:<project-id>` operation ID; confirmation must show
`codex:project:<project-id>` in the intended section's `itemKeys`. Preserve other
observed section entries and members in the reduced evidence.

An unknown tool outcome needs an `unresolved` event and a fresh reconciliation.
Do not submit another intent for the same operation. Submit `confirmed` only
when fresh evidence establishes the planned result. The CLI rejects a stage
submitted through the wrong forward or reverse operation. Read both `status.json`
and `native.json` when resuming.

Rollback reverses native placements first. Before invoking a reverse tool action,
persist `rollback-intent` with fresh sections through
`rollback --record "$recovery_dir" --native-event "$event_file"`. It requires
the recorded section ID/name and project placement to remain unchanged.
For a section creation, reverse its project placements first; the section must
still be empty and explicitly included in the user's rollback request. Only for
that scoped removal, add `--remove-empty-sections` to the rollback-intent command.
The flag records authorization; it does not delete the section itself.

For example, after an explicitly requested section removal passes the unchanged
and empty checks, its rollback-intent file has this shape:

```json
{
  "operation_id": "section:s0",
  "stage": "rollback-intent",
  "observed_at": 1900000003,
  "sections": [
    {"id": "observed-section-id", "name": "Research", "itemKeys": []}
  ]
}
```

Record that intent with
`rollback --record "$recovery_dir" --native-event "$event_file" --remove-empty-sections`,
then use the owning app tool. Record `reversed` only after a fresh listing proves
the placement or created section is gone. For an uncertain reverse outcome,
record `rollback-unresolved` and reconcile fresh observations before recording
`reversed`; never submit another rollback-intent or blindly repeat the tool call.
All reverse event files use the same four fields and actual observed timestamps.

Unpin recovery-owned projects through owning tools before file rollback as well;
the built-in Pinned section itself is never deleted. Then roll back file metadata
with the app closed.
Compare only recovery-owned fields; preserve unrelated later registrations and
metadata, and refuse conflicts on affected fields. Report retained sections or
unresolved native actions separately from metadata rollback.
A rolled-back v2 record cannot be applied again; prepare a new recovery record.

## Legacy registration verification evidence

Build observations from fresh owning app results after the latest apply/native
receipt. Include the destination account and sidebar device, collection time,
all restored/reused client project identities and resolved paths, intended
section membership, complete relevant task associations, and successful
historical-task read IDs. Record completeness only after paginating the relevant
source; a partial task listing cannot become complete by setting a flag.

The v2 observation object uses the following fields. `sidebar_machine` is the
hashed identity returned by detailed inspection and recorded in the plan, not
a device display name. V1 observations retain their original schema.

```json
{
  "account_id": "observed-destination-account-id",
  "sidebar_machine": "64-character-hardware-identity-hash-from-inspect",
  "collected_at": 1900000002,
  "complete": {
    "projects": true,
    "sections": true,
    "task_associations": true
  },
  "projects": [
    {
      "id": "observed-project-id",
      "hostId": "observed-current-connection-id",
      "remotePath": "/example/project",
      "task_ids": ["observed-existing-task-id"]
    }
  ],
  "sections": [
    {
      "id": "observed-section-id",
      "name": "Research",
      "itemKeys": ["codex:project:observed-project-id"]
    }
  ],
  "historical_task_reads": ["observed-existing-task-id"]
}
```

Replace every placeholder with observed values. Collect after the latest file
and native operation; `collected_at` is the actual collection time. Set the three
`complete` flags to true only when supported app results establish the complete
relevant inventory and associations, including pagination where available. If
the tools cannot establish completeness, leave the repair unverified. Never
infer completeness from a large list limit, a backend task inventory, or the
number of expected projects. The prepared backend task baseline must also be
complete; improve unavailable evidence and prepare again if it was incomplete.

Normalize the app tool's `sectionId` to the observation schema's `id`. Its
built-in `threads` / Projects section represents ungrouped projects, so omit that
container from `sections`; retain custom sections and built-in `pinned` when
present. A project listed under Projects still has intentional ungrouped placement.

Include every expected reused or restored project. `task_ids` describe observed
membership, not a copied candidate list. The v2 verifier conservatively requires
every eligible baseline candidate to appear in the observed associations. If
that cannot be established, investigate the discrepancy and retain unverified
status; do not rewrite tasks or manufacture observations. Each planned native
action needs a confirmed receipt before verification.

Retain only reduced evidence locally, never task bodies. Backend inventory,
working-directory candidates, and helper output cannot substitute for observed
client associations. Newly created tasks are allowed, while pre-existing
client/server explicit assignments and projectless choices must remain unchanged. Read one
pre-existing task when available; an empty baseline needs no historical read.

### Complete inventory with limited app observations

The desktop app tool and the project-host API have different coverage. In the
audited app, `list_threads` accepts at most 50 unpinned results without a cursor;
it also returns all pinned tasks. `read_thread` and `wait_threads` do not expose
project membership. The supported [app-server API](https://learn.chatgpt.com/docs/app-server)
provides cursor-based `thread/list` pagination, which the helper already uses
across all sources and providers. Its backend `projectId` is not this client's
remote-sidebar membership. Do not archive, pin, reorder, or open tasks to work
around the listing cap, or call private desktop IPC.

For an applied v2 recovery, `verify --inventory-only` requires no observations
file and can run while the app is open. It checks the selected host, actual
Codex home, resolved project identities, complete task inventory, recorded
server assignments, and preserved client choices. It writes a fresh private
`inventory-audit-<id>.json` receipt with counts and any affected task IDs; stdout
contains counts and the receipt location without task IDs. No task content,
credentials, or unrelated inventory is retained. Repeated audits create separate
receipts and never change recovery status, app state, or task history.

Read `inventory_status` separately from `phase`: `verified` means the recorded
task metadata passed this audit, while `phase` remains the recovery's existing
status. `application_membership_checked` is always false in this mode. An
incomplete inventory or changed baseline returns exit 2 with an `incomplete` or
`conflicts` result. Missing IDs in a partial result are unobserved, not proven
absent; even a complete unarchived inventory cannot distinguish later archival
or a changed working directory from deletion. Investigate rather than rewriting
tasks. V1 receipt behavior and normal `verify` requirements remain unchanged.

When app membership cannot be fully observed, report the completed inventory
audit and the specific remaining placement coverage. Never claim that the app
stores only 50 tasks or that the API cannot enumerate older tasks. An exhaustive
client membership check still requires a supported app capability exposing it;
the inventory audit is not a substitute.

The helper validates observations, but cannot attest fabricated inputs.
Keep tool provenance in the task. Missing project, section, association, or
historical-read evidence leaves **applied but unverified**. After verification,
repeat preparation against the same source to confirm no new changes.
