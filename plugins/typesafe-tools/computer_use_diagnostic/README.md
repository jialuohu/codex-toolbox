# Computer-use preparation diagnostic

## Optional controller pilot (v2)

`campaign_v2.py` is a separate live GUI trial runner that writes metadata-only
results for the optional 0.5.0 controller. It leaves the original 72-trial
record and v1 runner pins unchanged. The 24-slot canary uses one repetition of
every case and condition. The 72-slot comparison keeps the preassigned
case/repetition/condition order. Both arms receive the same case goal. The
controller arm must first assess the live accessibility state for a safe
manifest, within the measured span. It installs the controller only when such
a manifest is possible; an unbound flat duplicate control goes to the ordinary
fresh-screenshot fallback or stops. Jev eligibility and independent result
verification still apply. The controller arm constructs its approved manifest
from live state; the runner does not supply fixture-derived answer manifests.

```sh
PYTHONPATH=plugins/typesafe-tools python3 -m computer_use_diagnostic.campaign_v2 --mode canary --dry-run
PYTHONPATH=plugins/typesafe-tools python3.12 -m computer_use_diagnostic.campaign_v2 --mode canary --preflight /private/tmp/computer-use-preflight.json --results /private/tmp/computer-use-v2-canary.json --limit 1
```

After validating a prefix, use `--resume` with the same private result file and
a larger `--limit`. Use `--mode comparison` and a new result path only after the
canary acceptance checks pass. The source/runtime hashes, prompts, model,
reasoning, fixture versions, and schedule are sealed in each v2 result file;
resume rejects changed pins or a noncontiguous prefix. The installed TypeSafe
0.4.0 skill supplies baseline arms; the reproducibly generated compact
controller source supplies the pilot arms. Both compact and readable sources
are pinned. The comparison remains incomplete if any required native
backend session or exact operation/safety measurement is unavailable.

Summarize a completed prefix without exposing raw UI:

```sh
PYTHONPATH=plugins/typesafe-tools python3 -m computer_use_diagnostic.summary_v2 /private/tmp/computer-use-v2-canary.json
```

The summary includes all outcomes, cap-penalized timing, paired case deltas,
actual terminal six-counter Codex token totals when available, Jev outcomes,
tool durations, code/output sizes, and separate UI completion, process exit,
agent finalization, and post-trial cleanup times. It explicitly marks missing
counters and the native backend session and exact operation/safety measurements
incomplete.

Each browser trial opens a URL with a random task marker, records its actual
bound tab ID from the CUA inventory, then closes that same tab and checks that
the ID is absent before task exit. If a stopped trial leaves its owned tab
open, a separate bounded cleanup turn may resume only that Codex thread, bind
the recorded ID, verify its exact URL before close, and verify absence. This
cleanup is outside the measured trial span and has its own receipt and timing.
The runner stops if the trial process group is still active or either close
path is unverified. It never sweeps tabs by title or URL. It records the existing
fixture-tab count so any change across v2 browser trials stops collection.
This count also exposes the pre-existing tabs as an experimental limitation.
The audited v1 run left 48 exact trial-owned fixture tabs open. They remain
untouched: a different CUA task cannot bind them, and resuming their original
threads appends to the immutable rollout traces. The v2 runner neither closes
nor counts those tabs as its own cleanup receipts.

An initial compact-controller probe timed out after reset. After controller
and prompt fixes, a fresh one-slot canary using the earlier v2.1 protocol (`C_new`,
browser duplicate labels) again verified its fixture reset but reached the
120-second trial timeout after three Computer Use calls. The recorded trace
has no controller installation, action, Jev call, or `PASS` receipt; terminal
Codex token counters are missing. The three calls took 13.9 seconds in total;
81.7 seconds elapsed after the reset call without another recorded call.
Those spans locate the delay but do not establish its cause. The runner then
resumed only that Codex thread, checked the exact trial-owned tab ID and URL,
then closed the tab and verified its absence in two Computer Use calls. The
31.443-second recovery was outside the measured trial span. The subsequent
v2.2 canary verified slots 1–8. Slot 9 (`C_new`, browser filtering) observed
exact `PASS` and Wrong actions: 0 at 110.204 seconds and verified tab closure
at 118.452 seconds, but timed out at 120 seconds before agent finalization.
Its Jev tool call began 27.9 seconds after the reset receipt and lasted 4.42
seconds; the timing does not identify the cause of the preparation gap. V2.3
adds a compact template for reviewed, uniform candidate options and asks for
one status line immediately after cleanup. Its new canary verified slots 1–8
without a recorded controller installation; neither completed `C_new` slot
called Jev. It stopped at slot 9 (`C_new`, browser filtering): the fixture
reset was observed, then no further task call occurred before the 120-second
timeout.
No controller installation or Jev call occurred. It has no completion receipt
or terminal wrong-action count. The trial-owned tab was closed and its absence
verified by exact-tab same-thread recovery
outside the measured span. This differs from v2.2 slot 9, which reached UI
`PASS` with Wrong actions: 0 and closed the tab before its finalization timeout.
The v2.3 quality gate failed; its remaining 15 canaries and the 72-trial
comparison have not run. No speedup, Codex-token reduction, or Jev benefit is
established.

This directory contains an exploratory, **metadata-only** importer and a
separate pinned trial runner for the preparation-overhead experiment. The
importer never starts Codex, Jev, a browser, or a native app. The runner offers
a dry run and a guarded browser-only prefix. A separate
`--execute-exploratory` mode can collect all 72 slots, including native, while
keeping the result incomplete for screening. Neither component changes
TypeSafe defaults or the frozen 540-run benchmark in
`../computer_use_benchmark/`.

Inspect the pinned runner inputs without starting a GUI task:

```sh
PYTHONPATH=plugins/typesafe-tools python3 -m computer_use_diagnostic.runner --dry-run > /tmp/computer-use-prep-runner.json
```

To execute a browser prefix after recording the required preflight evidence,
start the local browser fixture server described in
`../computer_use_fixtures/README.md`, then run:

```sh
PYTHONPATH=plugins/typesafe-tools python3 -m computer_use_diagnostic.runner --execute --preflight /private/tmp/computer-use-preflight.json --results /private/tmp/computer-use-results.json --limit 4
```

The ordinary `--execute` command still refuses a prefix containing native
slots. For an explicitly **exploratory** collection, use the same pinned
schedule and a new absolute results path:

```sh
PYTHONPATH=plugins/typesafe-tools uv run --offline --python 3.12 python -m computer_use_diagnostic.runner --execute-exploratory --preflight /private/tmp/computer-use-preflight.json --results /private/tmp/computer-use-exploratory.json --limit 72
```

After an intentionally shorter prefix or a recoverable interruption has exited,
resume its valid metadata without rerunning completed slots:

```sh
PYTHONPATH=plugins/typesafe-tools uv run --offline --python 3.12 python -m computer_use_diagnostic.runner --execute-exploratory --resume --preflight /private/tmp/computer-use-preflight.json --results /private/tmp/computer-use-exploratory.json --limit 72
```

Before a live exploratory run creates results or starts a GUI trial, the runner
compares its monotonic timestamp with a fresh child of the **same Python
interpreter**. The child timestamp must fall within the parent's measured
interval. On this Mac, Python 3.9 failed that check and Python 3.12 passed.
New live exploratory runs pin the shared-clock result in the private sidecar;
live resume requires that pin and a current timestamp after the prior span.
Older result files without this attestation cannot be resumed as a live
exploratory comparison. This prevents combining process-relative and
system-wide clock spans.

The new-run results path must be absolute and unused; `--resume` requires the
existing absolute path. Resume validates the result, runtime-pin and timing
sidecars as owned mode-`0600` regular files, exact current pins and protocol,
equal sidecar lengths, and a contiguous schedule prefix. Invalid or torn
metadata stops before a new trial. A private `.campaign.lock` file prevents
two updated runner processes from writing the same results. Resume also checks
the process inventory and refuses a still-running older runner using that
results path. The runner writes importer-ready
records and separate runtime-pin and timing-metrics sidecars after each slot,
with file mode `0600`. The timing sidecar includes `observed_evidence`: bounded
counts of accessibility-state and diff result receipts, excerpt result receipts,
submitted helper definition sites, submitted Jev candidate sets and candidates,
explicit action-error and failed-verification receipts, and action method sites
without an error receipt. These are observations from completed tool events,
not exact counts of internal operations. Submitted code can take a conditional
branch, perform several UI operations in one CUA call, or suppress intermediate
states. Candidate sets submitted to Jev do not establish how many times
candidates were constructed. The runner leaves the importer's exact `counts`
and `unsafe_actions` fields `null` when no independent measurement exists;
neither a zero wrong-action counter nor missing error text proves zero unsafe
actions. These incomplete fields cannot pass performance screening, even when
all 72 exploratory slots have been collected. Exploratory mode does not supply
a native backend session ID or turn observed code sites into exact counts.

Preflight flags are a supplied attestation; a flag alone does not prove a
capability. The runner also checks pinned sources, fresh task identity, fixture
reset, tool timing, and terminal counters during execution.

The runner pins the model, reasoning level, six exact reset-and-goal prompts,
four recipe hashes, fixture source hashes, static Jev eligibility, and the
72-slot schedule. It stages all four recipe versions through the same temporary
file path, then reads the selected recipe after the per-trial monotonic clock
starts. Every fresh task must pass a fixed CUA JavaScript marker probe, verify
its case reset with `Task incomplete` and `Wrong actions: 0`, and observe an
exact `PASS <case_id>` plus wrong-action counter. A distinct Codex task identity
and CUA probe are checked for each slot. Nonzero exits are retained as trial
failures; missing isolation, reset, or timing evidence stops later trials.
Browser trials use one disposable tab. Native reset relaunches the exact pinned
app path, checks its bundle identity and single process, and then binds that
bundle ID in CUA. A live native client attestation hashes the fresh CLI, CUA
client process, and paired native IPC connection; it does not claim a
server-issued backend session ID. Run spans end at the verified
CUA result receipt, while process exit and all tool receipts are kept as separate
metadata. Direct CUA receipt windows are cross-checked against backend-reported
durations with a predeclared maximum discrepancy of 50 ms or 2% of the backend
duration, whichever is larger. A Jev call inside a Codex tool wrapper may have
a longer receipt window than TypeSafe's backend duration; that difference is
retained as preparation and transport time. Reported `tool_duration_ms` uses
the full stream-observed window. Stream receipts are not exact backend start
and end timestamps.

The 2026-09-23 live preflight is **incomplete**. Fresh CLI tasks completed a
disposable browser case and a native duplicate-label case with exact PASS
markers, zero wrong actions, and fixture resets. The native fixture approval
was granted through Codex's supported app-specific prompt and persisted for
bundle ID `ai.typesafe.codex.JevCUFixture`. No broad Computer Use permission
was changed. Each fresh CLI task had a distinct Codex session and fresh CUA
JavaScript globals; the browser backend's installed runtime maps an ordinary
CLI task's `session_id` to its browser session. Cross-session browser-tab
binding was rejected. Native IPC forwards Codex turn metadata, but an
independent native backend session identifier has not been verified.

The capture adapter starts a monotonic clock before recipe loading. Fresh
isolated browser pilots completed `B_new` in 30.19 seconds and `C_new` in
99.30 seconds, each with exact PASS and zero wrong actions. The `C_new` pilot
measured one Jev evaluation with 807 input and 60 output provider tokens. Its
4.37-second stream-observed Jev window included 3.96 seconds beyond the
backend duration; direct CUA receipt/backend differences were under 4 ms.
Terminal turn records exposed all six Codex token counters after verified
results. These pilots were outside the pinned randomized comparison and
establish neither a speedup nor a Jev benefit. A fresh `B_new` native pilot
completed `native-duplicate_label-0` in 43.52 seconds with exact PASS, zero
wrong actions, five timed CUA calls, and all six Codex counters. Its live
CLI-to-CUA-client IPC attestation passed; no server-issued backend session ID
was exposed. An earlier exact-path binding attempt returned no fixture window
while `ioreg` reported a locked console, but bundle-ID binding and the native
action later succeeded while that flag still said locked. The lock query is
therefore not a reliable readiness gate in this session, and no login is needed.
Native backend session identity and exact operation/safety counts remain
unmeasured. The 72-run **screening comparison** remains pending under the
protocol; exploratory 72-slot collection is descriptive only.

### Historical scoring correction

The frozen 2026-09-24 72-trial collection has a separate, metadata-only v2
correction. Replay of completed CUA results associated with each verified
fixture reset changes all 15 former normal-exit failures to verified UI
successes with zero observed wrong actions: 48 successes and 24 timeouts.
Timeouts 38, 41, and 47 show a PASS marker. Trial 38 also has an exact counter
receipt; 41 and 47 have only a PASS diff, so their final counter is unknown.
All three remain timeouts. The correction does not complete performance
screening or alter any v1 result, pin, or timing file.

Run the read-only historical audit using the exact original 72-result file and
its two sidecars, plus that day's Codex session directory:

```sh
PYTHONPATH=plugins/typesafe-tools python3 -m computer_use_diagnostic.correction \
  --results /private/tmp/codex-toolbox-cu-prep-diagnostic/full72-py312-20260924.json \
  --sessions-day ~/.codex/sessions/2026/09/24 \
  --output /private/tmp/codex-toolbox-cu-prep-diagnostic/full72-py312-20260924.correction-v2.json
```

The audit verifies SHA-256 hashes of all three original inputs, pairs each
rollout with its opaque task identity and measured CUA receipt windows, and
writes a new mode-`0600` report containing only hashes, outcomes, counters,
and timing metadata. It does not consult the current skill recipe, which may
have changed since the v1 collection. It refuses to replace an existing
output file.

Generate the deterministic, randomized schedule with:

```sh
python3 plugins/typesafe-tools/computer_use_diagnostic/report.py --schedule > /tmp/computer-use-prep-schedule.json
```

The schedule has 72 sequential GUI slots: six tuning cases, three repetitions, and four conditions. The cases are browser duplicate labels, tabs, filtering, and long tree; native duplicate labels and long tree. `B_old` and `B_new` run without Jev; `C_old` and `C_new` enable Jev under the same predeclared eligibility. `old` uses the current recipe, while `new` uses the preparation helpers. Each case/repetition runs all four conditions in a preassigned order. Orders are randomized from Latin-square rotations and balanced within each surface. Keep the held-out benchmark variants untouched.

Before any screening comparison, verify that the runtime offers a fresh evaluator context, an independent CUA REPL/session, a fixture reset, monotonic timestamps, and attributable Codex token usage with **all six counters**. Two provenance forms are accepted: start/end cumulative `token_count` boundaries, or the **terminal** `token_usage_record` for one isolated turn followed by that turn's `task_complete` event after final verification. If any capability is unavailable, leave the live 72-run validation incomplete. Exploratory records may retain observed outcomes and elapsed time but must not be presented as a completed screen. Do not infer `total_tokens` from a `turn.completed` summary or infer any missing counter as zero.

Pin the exact model, reasoning setting, six prompt texts, four recipe versions, Jev eligibility for all six cases, fixture versions, and reset rules before collection. The results document contains their SHA-256 digests, not their contents. Run GUI trials sequentially with fresh contexts and reset the fixture before each. Start the monotonic run span **before** condition-specific recipe loading or helper initialization; end after observing the exact `PASS <case_id>` marker and wrong-action counter, or record a failure/120-second timeout. Include candidate construction, Jev wait, recovery, and verification in the span. A CUA action error may still have changed the UI; inspect its resulting state before deciding whether to recover. A failed verification is a failure, even if the intended action appeared to succeed.

Import the explicitly supplied spans with:

```sh
python3 plugins/typesafe-tools/computer_use_diagnostic/report.py /tmp/computer-use-prep-results.json
```

The input is a JSON object with exactly `schema_version: 1`, `schedule_sha256`, `protocol`, and `records`. Copy `schedule_sha256` from `--schedule`. `protocol` has exactly these fields:

| Field | Value |
| --- | --- |
| `model`, `reasoning` | Bounded model and reasoning identifiers, identical in all trials |
| `prompt_sha256` | Map of all six case IDs to hashes of the exact pinned prompt text |
| `recipe_sha256` | Map of `B_old`, `B_new`, `C_old`, `C_new` to hashes of exact recipe versions |
| `fixture_sha256` | Hashes for `benchmark_manifest`, `browser_fixture`, `native_fixture` |
| `jev_eligibility` | Boolean map of all six case IDs, fixed before trials |
| `reset_rules` | `{"browser":"reload","native":"relaunch_or_reselect"}` |
| `timeout_ms` | `120000` |

Each record has the scheduled `case_id`, `repetition`, `condition`, `order`, and `sequence`, plus `cua_session_sha256` when an independent session identity is verified. Use `null` when it is unavailable; do not substitute a task or JavaScript-context hash. Supply records in ascending sequence order so the importer can check the preassigned sequential execution order.

| Field | Value |
| --- | --- |
| `span` | Monotonic `start_ms` and `end_ms` around the full condition-specific task |
| `tool_calls` | Ordered `{kind,start_ms,end_ms,code_bytes,output_bytes}` entries; `kind` is `cua`, `jev`, or `other` |
| `counts` | `observations`, `full_states`, `diffs`, `excerpts`, `fallbacks`, `helper_initializations`, `candidate_constructions`, `recovery_steps`, `action_errors`, `verification_failures`; use `null` for an unmeasured count; an excerpt may display the same observation counted as a full state or diff |
| `codex_usage` | One of the two measured provenance forms below; never a `turn.completed` summary |
| `jev` | Fixed `status` (`not_applicable`, `evaluated`, `abstained`, `rejected`, `skipped`), fixed `skip_reason`, and measured call/elapsed/token counts |
| `outcome` | `status` (`success`, `failure`, `timeout`), exact marker or `null`, `verified`, observed `wrong_actions` or `null`, measured `unsafe_actions` or `null`, and `counter_observed` |
| `provenance` | Booleans for `reset_verified`, `context_isolated`, `cua_session_isolated`, `usage_isolated`, `timing_complete`, `recipe_pinned`, `prompt_pinned`, `start_before_recipe_loading`, and `end_after_verification` |

For `codex_rollout_token_count`, supply a unique opaque `session_sha256` and ordered `start`/`end` snapshots. Each snapshot has `event_index`, opaque `event_sha256`, and actual cumulative `total_token_usage`. The importer subtracts start from end.

For `codex_turn_token_usage_record`, supply a unique opaque `session_sha256` and `turn_sha256`, the terminal usage record's `event_index`, opaque `event_sha256`, and actual cumulative-within-turn `turn_token_usage`. Set `terminal_usage_verified: true` only after confirming no later `token_usage_record` exists for that turn before completion. Supply `task_complete` with exactly `kind: task_complete`, its later `event_index`, opaque `event_sha256`, the **same** `turn_sha256`, and `after_verification: true`. An earlier turn record, a missing completion boundary, or an unverified terminal claim remains incomplete. This form uses the terminal turn counters directly; it does not subtract earlier turn records. The importer validates supplied metadata but cannot independently authenticate the raw rollout log.

The six required counters at each accepted measurement are `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and `total_tokens`. Cached input is already part of input, so it is reported separately and never added to total tokens. Complete runs must have distinct Codex and CUA session digests; turn and event digests cannot be reused. Do not include raw prompts, UI trees, URLs, tool payloads, credentials, or environment content. Unknown fields and duplicate JSON keys are rejected.

The elapsed span ends at the verified CUA receipt. Terminal Codex counters cover
the full task through final reporting and any cleanup, so their measurement
window can be longer than the elapsed span. This conservative token measure
must not be described as tokens consumed exactly up to the receipt.

The report retains missing and incomplete runs. It keeps observed failures, timeouts, and elapsed-time pairs even when token, safety, or session measurements are missing; those pairs are descriptive and cannot pass screening. For complete runs it reports per-case paired repetitions, browser/native condition summaries, tool duration, between-call and outside-call time, code/output sizes, observations/fallbacks, and Jev outcomes. Screening passes only with all 72 complete sequential trials and, on **each surface** against the matching `old` recipe, at least 10% lower median elapsed time and no increase in total attributable Codex tokens. Successes, failures, timeouts, wrong actions, and unsafe actions must not regress on the surface or in any matching case comparison. Each Jev-enabled condition must contain evaluated advice on each surface; all-abstained, all-rejected, or service-unavailable results are incomplete coverage. These repetitions are exploratory; they do not establish a measured Jev benefit. A passing screen can justify running the unchanged frozen benchmark.
