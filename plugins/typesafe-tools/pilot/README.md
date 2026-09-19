# Offline research-evidence pilot

This directory contains **fixtures and a scorer, not model results**. It never calls Jev, reads credentials, changes runtime configuration, or authorizes spending. Synthetic cases do not establish research-domain performance or confidence calibration.

From the toolbox checkout:

```sh
python3 plugins/typesafe-tools/pilot/pilot.py validate
python3 -m unittest discover -s plugins/typesafe-tools/pilot -p 'test_*.py'
python3 plugins/typesafe-tools/pilot/pilot.py score /path/outside-git/results.json
```

## Protocol

1. Check `typesafe_status` before any paid call. Capped mode requires a verified billing bound; explicitly configured uncapped mode has no wrapper spending limit. An API key alone does not establish a verified hard limit. Do not bypass an active block or change spending mode merely to run the pilot. The pilot may remain unrun while offline preparation is complete.
2. Use `tuning.json` for prompt development only. `cases.json` has 30 ranking and 30 claim-source held-out cases, five cases per task in each of six categories: direct, insufficient, contradictory, injected, numerical, and date-sensitive evidence. All passages are original synthetic text with explicit provenance. The fixture authors dedicate the synthetic text to the public domain under CC0-1.0; it represents no actual study. All experimental numbers are hypothetical.
3. `protocol.json` freezes both condition prompts, scoring rubric, and timing definition. `freeze.json` records SHA-256 hashes of the protocol and both fixture sets. Record those exact hashes before execution; do not revise fixtures or prompts after seeing held-out outputs. A later revision is a new evaluation, not a continuation of this one.
4. Present only `task`, `question`, and `passages` to the answering models. Keep `gold`, category, and prior answers hidden. Use separate conversations without shared answers. Alternate baseline/Jev condition order by case and record model versions, order, interruptions, and tool availability in run notes. Both arms retain all candidates, perform exact arithmetic/date checks, and deliver a final answer. Time the entire task including retrieval from the supplied passages, Jev calls, and verification.
5. Collect real baseline and Jev outputs for every case. Measure all input/output tokens and Jev call counts. Record total and Jev charges when available; use JSON `null` for unavailable monetary charges and explain the missing billing evidence in run notes. Do not infer invoiced charges from token usage or substitute zero. Do not invent a Jev result when the gate blocks a request. Missing or incomplete pairs are not a completed pilot.
6. A reviewer independent of the answering run scores final answers against the frozen rubric while blinded to condition. Record unsupported conclusions, correctness, and rationale. Unblind after adjudication; the harness validates these declarations but cannot verify reviewer independence. Store raw outputs, timing, and result files outside Git without confidential content.
7. Score paired results. Inspect task/category accuracy, unsupported conclusions, completion time, and cost. Small synthetic samples and repeated category templates limit generalization. No statistical significance or calibration is established. Document whether held-out results show a benefit without additional unsupported conclusions; inconclusive evidence retains explicit use. Activation remains a separate reviewed decision and requires continuing billing readiness.

## Result file

The top-level object has exactly `version` (1), `frozen_sha256` (the object from `freeze.json`), nonempty `run_notes`, and `records`. Supply 120 records: one baseline and one Jev record for each held-out case, with no tuning cases. Each record has:

| Field | Content |
|---|---|
| `case_id` | Exact held-out fixture ID |
| `condition` | `baseline` or `jev` |
| `model` | Exact answering-model version; Jev version also recorded in run notes |
| `prediction` | Every passage ID once in ranked order, or `supported` / `contradicted` / `insufficient` |
| `final_answer` | Actual final conclusion with passage references |
| `elapsed_seconds` | Positive, finite end-to-end wall time |
| `jev_elapsed_seconds` | Wall time spent waiting for Jev, positive in the Jev arm and zero in baseline; no more than total elapsed time |
| `usage` | Nonnegative integer `input_tokens`, `output_tokens`, `jev_calls`; `cost_usd` and `jev_cost_usd` are finite nonnegative charges or JSON `null` when unavailable |
| `adjudication` | Nonempty `reviewer`, `blinded: true`, Boolean `final_correct`, nonnegative integer `unsupported_conclusions`, nonempty `notes` |

Usage covers all calls in the arm. Baseline Jev counts are zero; its Jev cost can be recorded as zero because no Jev calls occurred. Unknown charges remain `null`, including a missing baseline charge. The Jev arm requires at least one actual call. When both charges are known, `jev_cost_usd` cannot exceed total `cost_usd`. A known total may coexist with an unavailable Jev breakdown, or a known Jev charge with an unavailable total; record each independently.

Each condition, task, and category reports `cost_usd`, `jev_cost_usd`, `unknown_cost_records`, and `unknown_jev_cost_records`. A monetary aggregate is `null` if any corresponding record has an unknown charge; known components are not presented as a complete total. Token and call totals remain available. Condition-level `usage` also preserves unknown monetary totals. Unknown charges do not support a monetary cost comparison.

No fabricated example measurements are checked in. The scorer reports prediction accuracy against gold separately from reviewer-scored final correctness. Ranking additionally reports top-1 accuracy; all candidates must remain present. The scorer always reports `automatic_use_enabled: false`.
