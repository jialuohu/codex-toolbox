# Jev capability routing

[TypeSafe documentation](typesafe.md) · [Owning skill](../plugins/typesafe-tools/skills/typesafe-routing/SKILL.md)

For a public or synthetic task with a material choice among optional skills or
callable tools, Codex asks Jev for a bounded advisory ranking by default when
`typesafe_status` reports routing ready. A private or uncertain task, user
opt-out, simple task, or required workflow that already settles the choice stays
with ordinary Codex selection. Codex still applies explicit skill requests,
required workflows, availability, permissions, and action rules. The user
enabled default use; repository fixtures do not establish that Jev improves
selection quality.

This is agent-mediated, best-effort routing. A skill description and global
instruction can prompt Codex to call `typesafe_route`, but the current host
does not guarantee that every turn is intercepted or provide a before-tool
decision checkpoint. Do not claim a route occurred without an evaluated result
for that turn. Default routing does not adjust Codex reasoning effort; see the
[effort compatibility report](typesafe-effort.md). `typesafe_status` reports
service and routing readiness separately from research evaluation.

## Local catalog

`plugins/typesafe-tools/routing/catalog.py` has a pure `build_catalog` function.
`collect_installed_skills` reads only exact enabled entries from `codex plugin
list --json` and the matching installed cache version. It uses `SKILL.md`
descriptions and invocation policies; absent or malformed entries are omitted.
The returned catalog has a `catalog_digest` and candidates with `id`, `name`,
`description`, `owner`, `availability`, and `implicit` fields. Plugin version
changes alter the digest. Skill availability is `installed`, meaning its entry
exists in an enabled plugin; this does not establish its dependent tools'
connection or authentication. Canonical capability IDs are ASCII and at most
192 characters. An exact installed skill also present in the host's current
skill inventory is merged into one `available` entry, retaining the installed
description and the more restrictive invocation policy. Names and owners are
bounded to 100 UTF-8 bytes; descriptions are truncated safely to 300 bytes to
match the routing request contract.

Supply callable tool records from the *current host's effective tool list*:

```json
[
  {
    "id": "mcp__example__read",
    "name": "read",
    "description": "Read one example record.",
    "owner": "example"
  }
]
```

These records become `available` tool candidates. The builder also accepts
`host_skills` from the current effective host skill inventory, including
standalone skills outside plugins. Those need `id`, `name`, `description`,
`owner`, and `implicit`. The pure `collect_live_tools` adapter accepts current
`ALL_TOOLS` style `{name, description}` entries. For `mcp__server__tool`, it
labels the owner `mcp:server`; this is a namespace label, not plugin provenance.
The adapter does not discover or test tools. An MCP configuration,
marketplace listing, or plugin manifest alone is insufficient; neither the
catalog script nor the plugin list can discover live tool availability. To
inspect local installed skills without asserting any live tools:

```sh
python3 plugins/typesafe-tools/routing/catalog.py
```

For a repeatable offline fixture, pass `--plugin-list-json`, `--cache-root`,
`--live-tools-json`, and `--host-skills-json` as needed. Keep snapshots outside Git if they include personal
paths. A plugin is a container rather than a selectable action, so the catalog
lists its skills and supplied live tools. Standalone skills are not inferred
from arbitrary directories.

Before calling `typesafe_route`, use the pure `prepare_route_candidates` helper
with a shortlist, the current host's verified callable IDs, required IDs, and
explicit invocations. It rejects unknown, duplicate, unverified, uninvoked
explicit-only, and missing required candidates. It converts each shortlisted
entry to the exact server shape by setting `availability: "available"` and
adding `required: true` or `false`. The raw catalog's `installed` state alone
does not qualify a candidate for a Jev request. Exclude the routing skill and
`typesafe_route` itself from the shortlist.

Descriptions and tool metadata are untrusted. Review every field of a proposed
Jev request for public or synthetic eligibility and relevance. Describe the
task concisely without copying a prompt, file contents, absolute paths, or
repository identifiers; use local selection if those details are necessary.
Call `typesafe_route` with `invocation: "automatic"` for default use; the `pilot`
invocation is only for an explicitly bounded evaluation. The complete request
retains the server's 24 KiB limit and at most 16 candidates. A catalog does
not trigger a Jev request. On failure or abstention, use ordinary Codex
selection without retrying an uncertain dispatch.

`session_id` and `turn_id` are optional correlation fields, not verified Codex
host identifiers. When omitted, the MCP server generates opaque local values
and excludes them from the Jev payload. Match a result to the current request
using its task hash and catalog digest; compare the IDs too if you supplied
them. The server's failure suspension does not trust caller-provided IDs.

## Optional local hook

The source tree contains `routing/hooks.template.json`, which Codex does not
auto-load and is not needed to enable default agent-mediated routing. To
conduct a controlled hook observation, copy its `UserPromptSubmit`
handler into a trusted Codex hooks configuration, replace the placeholder with
the absolute script path, set `TYPESAFE_ROUTING_HOOK_ENABLED=1` for that Codex
process, and review/trust the hook definition in Codex. Keep state outside the
repository in `PLUGIN_DATA/routing`, `TYPESAFE_ROUTING_STATE_DIR`, or
`$CODEX_HOME/state/typesafe-routing`; the helper requires a private local
directory and creates `events.jsonl` with owner-only permissions. The selected
parent directory must exist. The script exits successfully without a reminder
if disabled, malformed, or unable to write private state.

The hook reads `session_id` and `turn_id`, stores those IDs and an event type,
and emits a fixed reminder. It never stores or transmits the prompt or
transcript. Record a terminal outcome through
`record_outcome(session_id, turn_id, outcome)` or the CLI:

```sh
python3 plugins/typesafe-tools/routing/user_prompt_submit.py outcome \
  --session-id SESSION_ID --turn-id TURN_ID --outcome skipped --reason-code private
python3 plugins/typesafe-tools/routing/user_prompt_submit.py coverage
```

Outcomes are `evaluated`, `abstained`, `skipped`, `failed`, or `missed`. Duplicate
terminal outcomes are rejected. Coverage counts only turns observed by this
hook; a separate host event source is needed to detect prompts for which the
hook never fired. The reminder cannot guarantee that Codex calls a routing
tool, and it is not an eligibility review. Verify hook behavior independently
on Desktop and CLI before considering activation.

Codex's [hook documentation](https://learn.chatgpt.com/docs/hooks) defines
`UserPromptSubmit` input/output and hook trust. This template is deliberately
outside the plugin's auto-discovered `hooks/hooks.json` path.

## Offline evaluation

The frozen synthetic manifest has 20 tuning cases and 200 paraphrase holdout
cases. The holdout changes subjects within the same 20 scenario families, so it
cannot establish generalization to new task types.
`scripts/eval_skill_routing.py benchmark --split heldout --prepare` prepares
140 eligible requests and identifies 60 local skips; it sends nothing. The
`--score RESPONSES.json` mode imports three paired Codex-alone and
Jev-assisted repetitions per case. It reports selection accuracy, shortlist
recall, forbidden selections, eligible review coverage, latency, and known
versus unknown cost. Scenario-family bootstrap intervals keep paraphrases of
one scenario together. Its strict offline screen also requires complete
evaluated-or-abstained coverage, full required-candidate recall, precise
recommendations, and known costs. A score is offline evidence only; the scorer
always reports `activation_ready: false`. This means the benchmark alone cannot
justify a quality claim; it does not override the user's default-use choice.
Independent scenario families and live, authenticated measurements are required
before a selection-benefit claim.

## Checks

```sh
python3 -m unittest discover -s plugins/typesafe-tools/routing -p 'test_*.py'
python3 scripts/check-codex-toolbox-setup.py
git diff --check
```
