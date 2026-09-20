# TypeSafe and Jev

[Documentation](README.md) · [Owning skill](../plugins/typesafe-tools/skills/typesafe-judgment/SKILL.md)

TypeSafe Tools is an optional research-evidence integration. `typesafe_status`
checks local readiness; `typesafe_evaluate` accepts bounded typed evaluations.
Default capped mode blocks paid calls until a hard spending cap is verified.
An explicit `monthly_budget_usd: null` configuration removes the wrapper's
spending limit and billing-bound requirement. Credentials and the separate
automatic-use pilot gate still apply. Installation or removing the cap does not
establish pilot success or make a paid request.

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
version `0.1.4`; exported versions receive a content-derived Codex cachebuster.
Exports are immutable under `exports/<source-sha256>`; updates atomically move
the marketplace catalog pointer and retain previous exports. A colliding or
modified export is rejected without overwriting it. Repeated setup verifies the
catalog pointer, installed version/source, export contents, and installed cache
before reporting a no-op. Symlink installation paths are rejected.
Changed source for an already-disabled installation
reports `update_skipped_disabled`; it never silently enables the plugin.
Credentials, model configuration, and the accounting ledger are outside this
export and are preserved. Start a new Codex task to pick up the new skill/tools.

`--status` is offline and does not install packages or verify live MCP discovery.
Use the explicit CLI checks above to verify installation, then `typesafe_status`
for runtime readiness and the configured spending mode. Setup does not infer
paid readiness from package installation.
General toolbox setup does not add this optional plugin automatically.

## Configuration and coordination

The runtime defaults to model `jev-1.13.0` and a $5 UTC-calendar-month local
budget, with Python `3.12.13` and dependencies pinned in `uv.lock`. Its credential path is
`${CODEX_SECRETS_DIR:-$CODEX_HOME/secrets}/typesafe/api-key`; optional configuration
is the protected sibling `config.json`. Keep those files outside source control.
No credential is needed for startup, status, or offline tests.

Omitting `monthly_budget_usd` retains the $5 cap. A positive amount up to $5
selects capped mode with that limit. On an explicit request to remove the cap,
set the protected configuration field to JSON `null`, preserving other fields:

```json
{"monthly_budget_usd": null}
```

Uncapped mode has no wrapper spending ceiling and does not require audited
billing evidence. It keeps payload limits, credential protection, eligibility
review, response validation, deadlines, and the automatic-use pilot gate.
Changing the configuration does not send a provider request.

The upstream `typesafe-ai` skill describes application development. The
toolbox-owned `typesafe-judgment` skill governs the optional runtime. Existing
research tools retrieve evidence; Jev may rank supplied passages or flag
claim–source mismatches. Codex retains all candidates and their original order,
checks sources and numerical details, and makes the final decision. Pro and
Claude keep their separate advisory roles. External actions remain with their
owning plugins and authorization rules.

Upstream application design, code generation, and local mocked tests remain
available while billing is blocked. Installing its development skill does not
authorize a paid SDK, CLI, direct HTTP, or generated-application smoke test.
Do not use those paths to bypass an active wrapper block. A separately
requested application deployment needs its own applicable authorization and
billing controls; it is outside this wrapper's accounting.

Every outgoing field must contain only reviewed public or synthetic material,
including questions and labels. A provenance label is not proof of eligibility.
Do not send confidential reviews, private messages or notes, credentials, or
uncertain-origin text. Failures and unavailable readiness fall back to ordinary
Codex work without automatic retries or background evaluations.

## Spending modes and pilot

Capped mode has no vetted billing bound and therefore dispatches no paid
requests. A future supported bound must establish either an applicable provider
spending limit or a reliable maximum billable request cost before enabling the
transport. The ledger reserves spending atomically before dispatch, retains
uncertain reservations, and stops on accounting inconsistencies. The budget is
local to wrapper calls, not unrelated account usage. These cap and reservation
rules apply to capped mode; explicit uncapped mode does not enforce them.

The inspected [API contract](https://docs.typesafe.ai/api) and
[model page](https://docs.typesafe.ai/models) document usage and pricing, but no
applicable hard charge guarantee has been verified. The audited billing registry
is empty. In capped mode, unknown reservations remain in their original UTC month indefinitely;
they are never refunded by a timeout, process restart, or month rollover. A
reservation that crosses a month boundary before dispatch is retained without
sending a request. Provider failures receive no automatic retry.

In capped mode, validated usage is reconciled even when an individual answer is invalid. An
unknown or invalid usage report retains the complete reservation. The ledger
stores only submission time, billing evidence, usage, cost, and eligibility
metadata (classification, invocation, question count, and byte size), never the
payload. Classification records the review; it does not prove public origin.

Before registering billing evidence for capped mode, verify that the bound covers all charges,
including the documented zero output-token price and absence of additional
fees. This implementation rejects bounds with paid output tokens. Payload byte
limits are never converted into a billing token estimate. Live tuning observed
independently rounded probabilities and Scores. Validation checks whether their
rounding intervals admit probabilities summing to one and a consistent weighted
Score. It allows two decimal places, retains finer reported precision, and
returns the original values unchanged. This precision assumption is based on
observed responses; incompatible provider output still fails validation.

An accounting failure in capped mode requires a separate reviewed recovery. Preserve the
private ledger and marker; do not delete state or automatically refund unknown
reservations. A crash during first initialization can leave a partial ledger.
Only after verifying that it contains no reservations, that no call was
dispatched, and that no earlier accounting state was lost may an operator
replace that partial initialization. Otherwise reconcile against provider
records and retain uncertain charges. No recovery/reset tool is exposed.

The pilot uses frozen public/synthetic inputs and rubrics: 30 passage-ranking
cases and 30 claim–source cases, with separate tuning and held-out evaluation.
It measures final correctness, unsupported conclusions, completion time with
verification, latency, and usage. Live scoring requires runtime readiness in
the selected spending mode and explicit authorization for those evaluations;
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
