# Local Codex task creation

[Documentation index](README.md) · [Repository](../README.md)

`codex-task-tools` creates a durable, user-owned task in an **existing backend
project on this Mac** when you explicitly ask for a new task. It uses the
supported Codex App Server through a private toolbox broker. The broker remains
running after the creation call returns so the task can finish and approvals can
be reported. The owning [skill](../plugins/codex-task-tools/skills/codex-task-creation/SKILL.md)
defines the request and retry contract.

## Setup and status

After this plugin is published, normal toolbox setup installs it and its managed
background service. These focused commands use the published marketplace:

```bash
scripts/setup-codex-task-tools.sh --install
scripts/setup-codex-task-tools.sh --check
scripts/setup-codex-task-tools.sh --status
```

For a local development install before publication, use a separately named
marketplace in the **existing Codex home**. The broker must reach the
already-running local daemon, so a separate Codex home would point to the wrong
socket. Run from the repository root:

```bash
task_marketplace_name="codex-task-tools-local-$(date +%s)"
task_marketplace="${CODEX_HOME:-$HOME/.codex}/local-marketplaces/$task_marketplace_name"
umask 077
mkdir -p "$task_marketplace/.agents/plugins" "$task_marketplace/plugins"
rsync -a --exclude '.venv/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
  plugins/codex-task-tools "$task_marketplace/plugins/"
TASK_MARKETPLACE_NAME="$task_marketplace_name" python3 - "$task_marketplace" <<'PY'
import json
import os
import pathlib
import sys

source = json.loads(pathlib.Path('.agents/plugins/marketplace.json').read_text())
plugin = next(item for item in source['plugins'] if item['name'] == 'codex-task-tools')
catalog = {
    'name': os.environ['TASK_MARKETPLACE_NAME'],
    'interface': {'displayName': 'Codex Task Tools local development'},
    'plugins': [plugin],
}
target = pathlib.Path(sys.argv[1]) / '.agents/plugins/marketplace.json'
target.write_text(json.dumps(catalog, indent=2) + '\n')
PY
codex plugin marketplace add "$task_marketplace"
codex plugin add "codex-task-tools@$task_marketplace_name"
CODEX_TASK_MARKETPLACE_NAME="$task_marketplace_name" \
CODEX_TASK_DEV_MARKETPLACE_ROOT="$task_marketplace" \
  scripts/setup-codex-task-tools.sh --install
CODEX_TASK_MARKETPLACE_NAME="$task_marketplace_name" \
CODEX_TASK_DEV_MARKETPLACE_ROOT="$task_marketplace" \
  scripts/setup-codex-task-tools.sh --check
```

The installer verifies the staged root and name against Codex's registered
local marketplace before accepting its plugin path. Keep this private staged
directory while that development plugin is installed. Pass the same two environment
variables to later `--check` or `--status` calls; those commands inspect the
installed service without changing it. A direct Git marketplace setup
before publication will not yet contain this plugin.

The service connects to the already-running Codex daemon. It does not restart
that daemon. The plugin uses the current host's Codex authentication and does
not override instructions, model, sandbox, or approval settings. It records the
effective settings returned at task creation. Whether project-specific defaults
apply when the backend assignment is persisted afterward remains unverified;
inspect the returned settings before relying on them.
Setup refuses to replace a running broker while a tracked task or approval is
active, or when broker health cannot be established.
Private task receipts live under `${CODEX_HOME:-$HOME/.codex}/state/codex-task-tools`
with restricted permissions; they are not part of the repository.

Version `0.1.1` accepts exactly Codex CLI/App Server `0.156.1` and `0.159.0` on
macOS. Unknown versions are refused before the broker binds its task journal.
The [protocol qualification fixture](../plugins/codex-task-tools/server/tests/fixtures/app-server-compatibility.json)
records 32 generated schema comparisons. The changes are an optional initialize
capability and two additional error values; the broker's request shapes are
unchanged. Generated request-schema checks and broker fault tests cover both
accepted versions. Live `0.159.0` initialization, project discovery, and task
readback were checked; this upgrade does not claim a live task-creation or
approval-response test. A missing background service remains a setup failure,
not a reason to create a task through an unmanaged subprocess.
Normal broker readback uses App Server's full-history read; on `0.159.0`, a loaded
thread with paginated history may be persisted by App Server during that read.

For a `0.1.0` broker disconnected by the Desktop update, setup runs the verified
candidate's upgrade helper in an isolated environment before replacing the stable
runtime. The helper checks the predecessor's source hashes, distribution,
LaunchAgent, process, socket, and private journal. A separate private `upgrade.lock`
serializes helper attempts before any quiesce operation. It fences new broker work using
the existing quiesce operation, then requires every journal row to be settled,
every tracked thread to be unloaded with complete terminal turn history, and the
pending-request table to be empty. Unknown, active, foreign, or incomplete state
blocks the upgrade. Unrelated chats are not stopped or resumed.
Readback checks unloaded status before and after full history. A concurrent external
thread load can still make App Server persist history; these checks are not an atomic
snapshot of the thread store.

After stopping only the proven-idle broker, the helper takes its existing ownership
lock and repeats the journal and live-readback checks. While retaining that lock,
it verifies that the installation project matches the executing isolated candidate,
replaces the stable environment through `uv sync`, and checks the installed package
version and source bytes. Setup does not repeat this replacement after the helper
returns. Setup validates the helper's JSON completion receipt before startup and
emits the verified receipt to stderr. Service commands retain their own JSON output.
An already stopped predecessor must pass the same proof. The ordinary
service stop still refuses unknown counts. The upgrade never deletes a lock or
edits task-journal rows.
Both isolated startup and locked installation refresh only the `codex-task-tools`
package, preventing reuse of an older wheel with the same version; dependencies
remain frozen to the verified lockfile.

Failure before shutdown releases only the barrier established by that invocation.
A failed final proof restores the unchanged predecessor only after its shutdown
and ownership checks permit restoration. Interruption that prevents cleanup can
leave the broker quiesced; a later attempt refuses a pre-existing barrier. Review
the interrupted attempt before clearing it through the existing supported
`service_quiesce` operation and rerunning setup. Failure after stable-runtime
replacement begins leaves the broker unloaded until setup can finish safely.
The helper does not restart an old or partially replaced environment after an
installation failure. The replacement child receives only the selected stable
path as `UV_PROJECT_ENVIRONMENT`; an inherited `VIRTUAL_ENV` is removed.
A private `upgrade-install.json` marker is written before replacement and removed
only by the same invocation after verifying installed source, version, and stopped
state. Every `--install` attempt refuses a pre-existing marker, including when a
failed replacement already reports `0.1.1` or has missing package metadata. Inspect
the failed receipt, installed package, and marker before arranging a repair under
the broker ownership lock; keep the broker unloaded until that repair is verified.
Setup never clears or skips an interrupted-install marker automatically. `--status`
remains available for inspection; `--check` reports an explicit upgrade requirement
for an existing `0.1.0` runtime.

## Create and follow a task

For example, ask Codex:

```text
Create a new task under my existing example-project project. Title it
"Check one configuration file" and prompt it to inspect the file and report
findings. Return the task ID and verified status.
```

The MCP exposes these tools:

| Tool | Purpose |
| --- | --- |
| `codex_projects_find` | Resolve existing backend projects to canonical references and roots. |
| `codex_task_create` | Create, name, and submit one task using a stable idempotency key. |
| `codex_task_status` | Read the receipt, current task state, and pending requests. |
| `codex_task_respond` | Answer one current approval or input request after the user supplies its response. |

`codex_task_create` accepts `projectRef`, `title`, `prompt`, `idempotencyKey`,
and `cwd` when a project has multiple roots. Use the exact `projectRef` returned
by `codex_projects_find`; project names and matching directories do not establish
identity. For retries, reuse the original key and identical arguments. If a
response is uncertain, read the existing receipt and resolve it before any
new creation or prompt submission. A changed request requires a new key.

The broker creates the thread, applies its project assignment through the
supported metadata API, and reads the thread back to verify `projectId` before
it names the task or submits the prompt. Supplying `projectId` to
`thread/start` alone did not persist assignment in the certified runtime.
If assignment cannot be verified, the receipt retains the task ID and holds
prompt submission for recovery.

The result reports creation, title, prompt submission, execution, persistence,
and backend project membership independently. It also reports Desktop
verification separately. Supported backend assignment does not establish that
the task is visible under the same project in Desktop; that requires a supported
Desktop read of the exact task. Missing Desktop evidence is **unverified**.

For an ambiguous outcome that cannot be resolved through supported task and
history reads, use the broker's explicit recovery command to adopt a verified,
user-confirmed task ID. Do not replay an uncertain creation or an accepted
prompt. The local receipt and backend history are retained for readback after
service restarts.

```bash
"${CODEX_HOME:-$HOME/.codex}/runtime/codex-task-tools/.venv/bin/codex-task-tools-recover" \
  adopt --idempotency-key "<original-key>" --task-id "<confirmed-task-id>"
```

Publication of this plugin is a separate shipping operation.
