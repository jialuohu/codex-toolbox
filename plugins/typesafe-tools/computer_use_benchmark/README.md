# Offline computer-use benchmark

This benchmark scores imported runs from the disposable browser and native fixtures in `../computer_use_fixtures/`. It never starts Codex, Jev, a browser, or a native app. The fixture file is frozen by `freeze.json`, and each result document must cite its SHA-256 digest. The fixtures are original synthetic data licensed CC0-1.0.

Each surface has ten scenario families: navigation, search, filter, tabs, expand, duplicate labels, reordered rows, missing targets, transient recovery, and a picker dialog. Each family has one tuning variant and three held-out variants. The 30 held-out variants per surface are **not 30 independent task types**. The scorer resamples the ten families for paired confidence intervals. Each held-out variant runs three repetitions under each condition:

| Condition | Required behavior |
| --- | --- |
| A | Current Codex computer use; ordinary state inspection and action calls. |
| B | Task-relevant accessibility excerpts and safe action-plus-observation batching; no Jev. |
| C | B plus selective `typesafe_choose_action` recommendations on predeclared eligible cases; Codex verifies targets and executes actions. |

The public fixtures accept `browser-<category>-<0..3>` at `?case_id=...` in `browser/index.html` and `native-<category>-<0..3>` through `--case-id` or the native selector. Index 0 is tuning; indexes 1–3 are held out. A task succeeds only when the visible status contains the exact token `PASS <case_id>`; the native accessibility value may also contain the adjacent wrong-action counter. Record the fixture's visible `Wrong actions: N` counter after completion. A wrong click can be recovered, but it remains counted. Reload the browser page or restart/reselect the native case before every run.

For Jev-eligible cases, each manifest family's `decision_stage`, `observation`, `actions`, and `expected_action_id` describe one observed decision with every relevant executable option. Navigation, tabs, and duplicate-label choices occur initially. Open the status picker before the filter choice, or Open picker before the dialog choice; then reobserve and choose among the visible options. Ineligible cases have no Jev candidates. After any choice, the runner observes the new state before constructing fresh one-step candidates for another decision. The fixture's `PASS` marker and wrong-action count determine full-task outcomes.

Give Codex only the scheduled objective and live GUI observation for its run. Keep `expected_action_id` and the manifest's reference candidate descriptions on the scorer side; build Jev candidates from the current observed controls. This avoids leaking the expected choice into the model prompt.

## Collecting runs

Run `python3 plugins/typesafe-tools/computer_use_benchmark/score.py --schedule` to print the 540 held-out run slots in their frozen condition order. Execute the ten tuning cases per surface before held-out collection. Freeze prompts, observation-excerpt rules, Jev eligibility, and action-selection rules before held-out runs. Use the same Codex model and reasoning setting for A, B, and C, with fresh fixture state on every run. Keep the task, candidate construction, Jev request, target recheck, GUI actions, recovery, and final `PASS` verification inside the measured interval. A task ends when its marker and wrong-action count have been checked; failure or timeout remains a completed run with `success: false` and `marker_seen: false`, provided timing and usage evidence are complete.

Record only the fixed JSON fields accepted by `score.py`. Each run needs `case_id`, `repetition`, `condition`, the scheduled `order`, elapsed wall time in milliseconds, `success`, `marker_seen`, `wrong_actions`, `unsafe_actions`, `tool_calls`, `reset_verified`, `observation_complete`, `usage_isolated`, `timing_complete`, `codex_usage`, `jev_usage`, and `jev_decision`. Set the four verification booleans true only when established. `unsafe_actions` counts externally consequential or unauthorized actions observed in the run; all conditions must have zero. Do not store screenshots, accessibility trees, prompts, URLs, app content, candidate text, or freeform notes in result records. The scorer rejects extra fields.

For `codex_usage`, prefer two actual `event_msg` records with `payload.type == "token_count"` from an isolated Codex rollout JSONL: one immediately before task presentation and one after final verification. Copy only `payload.info.total_token_usage` from each. The current local runtime exposes six counters: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and `total_tokens`. Include all six exactly. The scorer subtracts start from end, requires nondecreasing totals and `total_tokens = input_tokens + output_tokens`, and reports cached input separately; cached tokens are already part of input and are never added again. A missing counter, boundary event, or unrelated activity inside the interval means the run is incomplete. Do not infer missing counters as zero. `last_token_usage` is not a substitute for cumulative boundaries.

Use this metadata-only normalized form; the SHA-256 references are hashes of the raw JSONL event lines and the session identifier, not the lines or identifier themselves:

```json
{
  "source": "codex_rollout_token_count",
  "session_sha256": "<64 lowercase hex digits>",
  "start": {
    "event_index": 12,
    "event_sha256": "<64 lowercase hex digits>",
    "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 0, "output_tokens": 20, "reasoning_output_tokens": 8, "total_tokens": 120}
  },
  "end": {
    "event_index": 19,
    "event_sha256": "<64 lowercase hex digits>",
    "total_token_usage": {"input_tokens": 580, "cached_input_tokens": 280, "cache_write_input_tokens": 0, "output_tokens": 140, "reasoning_output_tokens": 38, "total_tokens": 720}
  }
}
```

`event_index` is the zero-based JSONL line index. Hash the original line bytes (without displaying them), copy the six integer counters, and discard every other event field. Use the same session hash at both boundaries. The start and end indexes must increase, and intervals in one session must not overlap. If an integration already emits disjoint, attributable per-run token deltas, `source: "codex_runtime_usage_event_delta"` with a nonempty `events` array is also accepted; each event contains an opaque `event_sha256` and the same six counters. Delta events cannot be reused across runs.

`jev_usage` contains nonnegative integer `calls`, `input_tokens`, `output_tokens`, and `elapsed_ms`, including abstentions. A and B must be zero. A failed call without attributable provider usage leaves the run incomplete; do not fill its unknown counters with zero. C uses `jev_decision: {"status":"evaluated"|"abstained"|"skipped", "skip_reason":"..."}`. A and B use `{"status":"not_applicable","skip_reason":""}`. A skipped eligible C run must give one fixed reason: `no_meaningful_choice`, `insufficient_observation`, or `service_unavailable`; an ineligible C run uses `ineligible_fixture`. Evaluated and abstained runs require measured Jev calls. The five eligible scenario families per surface are declared in `fixtures.json`: navigation, filter, tabs, duplicate labels, and dialog. At least 90% of their 45 held-out C runs must actually evaluate or abstain. This predeclared coverage gate prevents a speedup in mostly Jev-free runs from being attributed to Jev while allowing a few justified skips.

Use `python3 plugins/typesafe-tools/computer_use_benchmark/score.py RESULTS.json` to produce a report. The document has exactly `schema_version: 1`, `fixture_sha256` from the schedule, and `records`. Missing or incomplete runs disable only their surface. Malformed provenance, duplicate records, reused telemetry, and raw UI payload fields are rejected. The report remains advisory: `automatic_use_enabled` is always false and the scorer never changes configuration.

For each surface, activation eligibility requires complete evidence for 270 runs; at least 10% lower mean end-to-end latency and Codex input-plus-output tokens in C than both A and B; four paired family-cluster bootstrap intervals (two metrics against two references) with lower bounds above zero after Bonferroni correction; no lower success count or higher wrong-action count in C than either comparator; no unsafe actions in any condition; and the 90% Jev coverage gate. The intervals are 98.75% two-sided percentile intervals using 4,096 fixed-seed resamples of ten scenario-family means. They quantify uncertainty within this synthetic fixture set; imported outcome labels and hashed event references are not authenticated runtime attestations, and a passing report is not evidence of performance on private or arbitrary applications.
