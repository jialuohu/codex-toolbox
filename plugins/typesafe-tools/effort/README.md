# Offline effort controller

`controller.py` is a pure state machine. `mock_runtime.py` supplies a deterministic
evaluator and host; neither imports Codex, TypeSafe, or a network client. No
plugin manifest, MCP tool, or installed configuration invokes this code.

An adapter would request a decision using a session/turn/epoch ticket, call
`prepare_generation` before an actual model start, apply any returned
`EffortChange`, and call `acknowledge_change` only after observing the host's
effective effort. It then calls `generation_started` once and
`generation_finished` when that model response ends. `tool_result` leaves the
generation count unchanged. A missing or contradictory acknowledgement makes
the effective effort unknown and requires `reconcile` with a fresh host
observation. Expiration schedules baseline restoration at the next boundary;
restoration also requires acknowledgement.

The model catalog, not this prototype, supplies supported effort values. The
controller allows only durations of 1, 2, 5, or 10 model starts. Decisions and
generation events are bound to one session, turn, and epoch. A manual change
uses the host-observed effort and blocks automatic decisions until
`clear_manual_override` receives another observation.
If a manual change races with an automatic command, even the manual observation
does not settle the earlier command; a later reconciliation is required.

```sh
python3 -m unittest discover -s plugins/typesafe-tools/effort -p 'test_*.py'
```

See the [versioned compatibility report](../../../docs/typesafe-effort.md) for
the current Desktop and CLI integration limits.
