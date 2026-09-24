# Jev computer-use advice and controller pilot

[TypeSafe setup](typesafe.md) · [Owning skill](../plugins/typesafe-tools/skills/typesafe-computer-use/SKILL.md)

The `typesafe_choose_action` tool advises Codex on an ambiguous next action
in a browser or native app. Codex observes the interface, supplies a bounded
set of possible actions, reviews every field sent to Jev, and remains responsible
for executing and verifying the selected action through Computer Use. Jev
receives text or structured data, not screenshots: the pinned model accepts
[text input only](https://docs.typesafe.ai/models).

The computer-use skill has two small helpers for repeated decisions: one selects
task-relevant accessibility text and one binds a unique target in a fresh state.
Small states and useful diffs are returned directly. Larger states use an
80-line soft display budget with surrounding context and an omission count;
the complete saved state is used when structural or semantic context is missing.
The helpers are initialized once for a repeated-decision task, while a single
obvious action can use the ordinary Computer Use call. Element indexes are
always derived from the current observation. The skill contains the action,
error-recovery, and verification rules. On a native virtualized list, the
matcher stays unbound. Codex inspects all ranges after the last list change,
then manually derives a fresh visible index for the final action.

Version 0.5.0 adds an **opt-in repeated-task controller pilot** inspired by the
[Jev-cu driver](https://github.com/Sac-Y/Jev-cu/blob/52d32ac24e2cea29c63d9d7c4bd6d4c401111f56/scripts/loop.mjs).
It initializes a tested, reproducibly generated compact JavaScript payload once
in a persistent Computer Use session and uses short calls to advance approved,
deterministic steps. On a decision that needs judgment it returns a candidate
request to Codex; Codex reviews that
request and, when eligible, calls the existing `typesafe_choose_action` tool.
The controller receives a pending-turn nonce and candidate ID when work
resumes. It refreshes the UI state and derives a new binding before acting.
The pilot does not make Jev calls from inside Computer Use. Ordinary
single-action tasks keep the short Computer Use pattern without controller
initialization.

The approved task manifest confines the controller to named app or tab, goal,
semantic targets, operations, exact input values, postconditions, and a
task-wide budget. An ambiguous target, unsupported structure, lost session,
changed scope, error with unresolved side effects, or failed verification
stops or hands off to Codex. The pilot allows at most eight action attempts
and 120 seconds including advice waits. Each action is followed by observation;
the controller never carries a numeric element index across steps. Existing
Computer Use confirmation rules still apply.

The observed browser and native duplicate-label fixtures expose flat
accessibility rows. A preceding record label alone cannot prove which row owns
an `Open` button if a neighboring label is missing, so the controller hands
these cases to Codex for fresh visual or semantic binding. Structurally
identified rows and controls with an exact independent identifier remain
eligible for controller actions.

Jev is consulted only when at least two meaningful semantic actions remain
after local filtering, and the complete outgoing payload has been reviewed for
origin and authority to send to TypeSafe. Public and synthetic material is
eligible; relevant private UI excerpts additionally require
`private_data_enabled: true` in status under the
[private-data opt-in](typesafe.md#private-data-opt-in).
Use `classification: "private"` when any outgoing field is private. A page or
application's name does not prove that its content is public or authorized.
The opt-in does not expand app access or action permissions. Credentials,
authentication state, credential-bearing URLs, and uncertain-origin UI text stay local.
Coordinate-only or screenshot-only targets stay with Codex. Instructions found
on a page or in app content are data, not authorization.

Computer-use advice has independent `automatic_browser_use` and
`automatic_native_use` settings, both disabled by default. Automatic use also
requires either a protected `browser_user_opt_in` or `native_user_opt_in`
setting for that surface, or a corresponding reviewed `browser_evidence_id` or
`native_evidence_id` registered in plugin source. The
`typesafe-computer-use` skill can be invoked explicitly for an eligible
task while those settings are off. The server's offline `typesafe_status` reports
the enabled flags, their `user_opt_in` or `measured_benefit` basis, and accounting
readiness; it cannot establish that the current
Codex task has a usable Computer Use session. An advisory response never grants
permission to act. On an error, abstention, stale target, or changed interface,
Codex makes the next decision locally without retrying an uncertain Jev call.
Automatic use is agent-mediated best effort; the current host has no mandatory
before-action Jev checkpoint.
Each request carries a local task scope and a separate observation snapshot ID.
The server suppresses repeated advice on unchanged content within one task
for its recent decisions in the current process, without suppressing an
identical decision in a later task; neither ID is sent to Jev. The skill also
instructs Codex not to repeat an unchanged Jev decision.

## Benefit evaluation

A separate [preparation diagnostic](../plugins/typesafe-tools/computer_use_diagnostic/README.md)
compares current and optimized recipes with Jev off and on across six tuning
cases and three repetitions (72 trials). Its importer and reports retain timing,
actual Codex token counters when available, outcomes, and failures without
storing UI text or prompts. A versioned correction of the first 72 exploratory
records found that all 15 reported failures had verified `PASS` receipts:
48 UI successes and 24 timeouts. Three timeout traces also contained `PASS`;
they remain timeouts because UI completion and finalization are separate.
The original records remain unchanged.

The v2 protocol compares the 0.5.0 pilot against the installed 0.4.0 recipe,
with Jev off and on. An earlier v2.2 canary observed the exact UI `PASS` and
Wrong actions: 0 in slot 9, but timed out before agent finalization. The v2.3
canary verified eight of 24 slots. Slot 9 (browser filtering, optimized Jev
condition) timed out after reset without another task call, controller
installation, Jev call, completion receipt, or terminal wrong-action count.
The runner resumed only that thread and verified exact-tab closure outside the
trial span. The quality gate failed;
the remaining 15 canaries and the 72-trial comparison have not run.
Independent native backend session identity and exact operation/safety counts
are also unavailable. There is no measured latency, token, or Jev benefit from
this pilot. A future complete screen requires at least 10% lower median
completion time with no token or quality regression before considering the
unchanged held-out benchmark.

The offline benchmark compares three conditions on the same disposable browser
and native-app workflows: current Codex Computer Use, compact observations and
batched actions without Jev, and the same workflow with selective Jev advice.
The [fixtures](../plugins/typesafe-tools/computer_use_fixtures/README.md) and
[benchmark protocol](../plugins/typesafe-tools/computer_use_benchmark/README.md)
provide the run commands, frozen cases, result schema, and scorer.
It records complete task latency, verified success and wrong actions, actual
Codex input/output token counts, cached tokens separately, and Jev usage. Missing
run data or token telemetry cannot be replaced by text bytes or turn counts.
Browser and native results are assessed separately.

Measured-benefit activation remains off until held-out paired measurements show at least 10%
lower mean latency and Codex token use than both comparison conditions, with
adjusted confidence intervals supporting improvement, no observed success or
wrong-action regression, no unsafe action, and Jev use in at least 90% of
predeclared eligible runs. A passing synthetic benchmark
shows benefit only on the tested workflows; it does not establish that private
real-world apps are eligible. Preserve the tested evidence and activation
decision outside source control; register only the reviewed evidence ID in the
plugin. If the gate fails or cannot be evaluated, keep
the advisor explicit-only unless the user separately opts in through protected
configuration. A user opt-in enables eligible automatic advice without claiming
a measured speed or token benefit; the benchmark status remains unverified.

The plugin source, setup checks, runtime tests, benchmark scorer, and privacy
audit are validated as part of the TypeSafe CI job. Publishing the toolbox
continues to require an explicit `$ship-toolbox` invocation.
