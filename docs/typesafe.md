# TypeSafe and Jev

[Documentation](README.md) · [Owning skill](../plugins/typesafe-tools/skills/typesafe-judgment/SKILL.md)

TypeSafe Tools is an optional research-evidence integration. `typesafe_status`
checks local readiness; `typesafe_evaluate` accepts bounded typed evaluations.
Version 0.3.0 also exposes `typesafe_route` for capability ranking. Automatic
routing is enabled by default when the credential is ready and the supplied task
is eligible; set `automatic_routing` to `false` in protected configuration to
opt out. Research evaluation retains its separate automatic-use pilot gate.
See [capability routing](typesafe-routing.md) and the
[reasoning-effort compatibility report](typesafe-effort.md). The wrapper no longer
has a spending cap or billing configuration. A route call may incur provider
charges; plugin installation alone does not send one.

## Install the published plugin

After refreshing the Git-backed toolbox marketplace, explicitly install this
optional plugin and the separately pinned development skill:

```sh
python3 scripts/setup-typesafe-tools.py --install-upstream
codex plugin add typesafe-tools@jialuo-codex-toolbox --json
codex plugin list --marketplace jialuo-codex-toolbox --json
codex mcp list
```

Keep only one TypeSafe Tools installation. When moving an enabled local pilot
installation to the published plugin, first verify the published version is
available, then remove `typesafe-tools@typesafe-tools-local` with
`codex plugin remove` before adding the published plugin. Credentials,
configuration, and the ledger remain outside the plugin cache. Do not enable a
previously disabled installation as part of an update. The local installer
rejects an existing published copy rather than creating a duplicate.

## Install a local pilot

Run from the toolbox checkout, after repository validation:

```sh
python3 scripts/setup-typesafe-tools.py --status
python3 scripts/setup-typesafe-tools.py --install-upstream
python3 scripts/setup-typesafe-tools.py --install
codex plugin list --marketplace typesafe-tools-local --json
codex mcp list
```

The upstream command uses exactly one official route: `npx --yes skills@1.7.0
add`, targeting Codex globally, with telemetry disabled. It pins revision
`65a39f393687675ce170e6094757de20370365b9` of
[the upstream skill](https://github.com/typesafe-ai/skills/tree/65a39f393687675ce170e6094757de20370365b9/skills/typesafe-ai),
then verifies both `SKILL.md` and `LICENSE` against recorded SHA-256 checksums.
The upstream content remains unchanged outside toolbox Git. A matching global
installation is a no-op; distinct copies, extra files, or mismatched content stop
installation without overwriting them. Symlinks to the same installation count
as one copy. Updates to the upstream pin require an explicit repository change.

The local plugin installer exports only TypeSafe Tools under
`$CODEX_HOME/local-marketplaces/typesafe-tools-local`, registers that separate
marketplace, and installs with `codex plugin add`. It leaves the published
`jialuo-codex-toolbox` registration and other plugins unchanged. Source remains
version `0.3.0`; exported versions receive a content-derived Codex cachebuster.
Exports are immutable under `exports/<source-sha256>`; updates atomically move
the marketplace catalog pointer and retain previous exports. A colliding or
modified export is rejected without overwriting it. Repeated setup verifies the
catalog pointer, installed version/source, export contents, and installed cache
before reporting a no-op. Symlink installation paths are rejected.
Changed source for an already-disabled installation
reports `update_skipped_disabled`; it never silently enables the plugin.
Credentials, model configuration, and the usage ledger are outside this
export and are preserved. Start a new Codex task to pick up the new skill/tools.

`--status` is offline and does not install packages or verify live MCP discovery.
Use the explicit CLI checks above to verify installation, then `typesafe_status`
for runtime readiness. Setup does not infer credential readiness from package
installation.
General toolbox setup does not add this optional plugin automatically.

## Configuration and coordination

The runtime uses model `jev-1.13.0`, with Python `3.12.13` and dependencies pinned
in `uv.lock`. Its credential path is
`${CODEX_SECRETS_DIR:-$CODEX_HOME/secrets}/typesafe/api-key`; optional configuration
is the protected sibling `config.json`. Keep those files outside source control.
No credential is needed for startup, status, or offline tests.

Automatic routing is on by default. To disable it, set the protected
configuration field to `false`:

```json
{"automatic_routing": false}
```

The former `monthly_budget_usd`, `billing_evidence_id`, and
`routing_pilot_evidence_id` keys are obsolete and rejected. Remove them from
existing protected configuration when updating. Payload limits, credential
protection, eligibility review, response validation, and deadlines remain.
Changing the configuration does not send a provider request.

The upstream `typesafe-ai` skill describes application development. The
toolbox-owned `typesafe-judgment` skill governs the optional runtime. Existing
research tools retrieve evidence; Jev may rank supplied passages or flag
claim–source mismatches. Codex retains all candidates and their original order,
checks sources and numerical details, and makes the final decision. Pro and
Claude keep their separate advisory roles. External actions remain with their
owning plugins and authorization rules.

Upstream application design, code generation, and local mocked tests remain
available without a credential. The upstream SDK, CLI, direct HTTP, and
generated applications operate outside this wrapper's privacy and usage
controls. Do not use them to bypass an active wrapper block.

Every outgoing field must contain only reviewed public or synthetic material,
including questions and labels. A provenance label is not proof of eligibility.
Do not send confidential reviews, private messages or notes, credentials, or
uncertain-origin text. Failures and unavailable readiness fall back to ordinary
Codex work without automatic retries or background evaluations.

## Usage records and research pilot

The private ledger records request metadata and reported input/output tokens,
not payloads or monetary charges. If a request fails after dispatch, its usage
remains unresolved; the wrapper does not automatically retry it. Existing
capped-ledger records remain intact for historical inspection but no longer
limit new calls. Inconsistent or inaccessible ledger state blocks dispatch to
avoid losing request records.

Live tuning observed independently rounded probabilities and Scores. Validation
checks whether their rounding intervals admit probabilities summing to one and a
consistent weighted Score. It allows two decimal places, retains finer reported
precision, and returns the original values unchanged. Incompatible provider
output still fails validation.

The pilot uses frozen public/synthetic inputs and rubrics: 30 passage-ranking
cases and 30 claim–source cases, with separate tuning and held-out evaluation.
It measures final correctness, unsupported conclusions, completion time with
verification, latency, and usage. Live scoring requires runtime readiness and
explicit authorization for those evaluations;
fixtures and offline tests cannot establish a Jev benefit. Automatic research
use stays disabled until held-out results support a benefit without additional
unsupported conclusions. Inconclusive results retain explicit use.

```sh
python3 -m unittest tests.test_typesafe_tools
uv run --frozen --project plugins/typesafe-tools/server pytest plugins/typesafe-tools/server/tests -q
python3 -m unittest discover -s plugins/typesafe-tools/pilot -p 'test_*.py'
python3 plugins/typesafe-tools/pilot/pilot.py validate
python3 scripts/check-codex-toolbox-setup.py
git diff --check
```
