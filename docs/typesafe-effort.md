# Adaptive reasoning effort: compatibility report v1

Checked 2026-09-23 for the local Codex CLI **0.155.1** and Codex Desktop
**26.715.72359** (bundled `codex-cli 0.145.0-alpha.30`). This is a protocol
inspection and offline prototype, not a live effort-control deployment.

## Result

| Requirement | CLI 0.155.1 | Desktop bundled runtime | Evidence and limit |
| --- | --- | --- | --- |
| Set effort before a new turn | Supported by the app-server protocol | Supported by the bundled protocol | `turn/start.effort` says it overrides effort for that turn and later turns. The client must own that turn-start request. |
| Change effort within an active turn | Experimental `turn/settings/update` is defined to publish effort for subsequent step captures; already captured steps are unchanged | No matching method in the bundled experimental schema | The CLI method appears only in the schema generated with `--experimental`; it was not exercised in a live turn. Its `applied` response means the setting was published, even if unchanged; a later inference is not guaranteed. This is a control for a client that owns the app-server request, not a sampling checkpoint exposed to an MCP tool or hook. |
| Confirm effort actually applied to a generation | No effective-generation acknowledgement | No effective-generation acknowledgement | The CLI's `turn/settings/update` response confirms publication, not the settings captured by a particular model generation. `thread/settings/updated` reports configured thread settings; thread metadata says `reasoningEffort` is not per-turn execution telemetry. |
| Observe each model-generation start | No event found | No event found | Both notification schemas have `turn/started` and tool/item events, but no model-generation start event. A turn may contain multiple generations. |
| Detect a manual effort override reliably | Unknown | Unknown | Settings updates contain effort but no documented source identifying a manual change. A plugin cannot safely distinguish user selection from another client update. |
| Observe cancel, resume, and compaction | Partial | Partial | The protocols expose turn interruption, thread resume, and compaction notifications. They do not provide an atomic generation boundary plus effort acknowledgement. |
| Preserve prompt-prefix caching while changing effort | Unverified | Unverified | The Responses API documents `configuration_update` for GPT-6 standard single-agent requests. The inspected Codex controls do not expose that item as an effort-control interface. |

**Conclusion:** CLI 0.155.1 has a partial, experimental live-turn control, but
neither inspected surface provides the generation-start checkpoint and
effective-generation acknowledgement needed for a 1/2/5/10-generation lease.
The bundled Desktop runtime also lacks the CLI's experimental live-turn method.
A toolbox MCP or hook cannot safely count generations or confirm a Jev-selected
effort for the active Codex task through these inspected interfaces. A separate
client that owns `turn/start` or experimental `turn/settings/update` can select
turn settings, but that alone does not meet the approved two-surface gate.

The [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation)
does document `configuration_update` for GPT-6 standard, single-agent
Responses requests. It preserves the request-level effort for prompt-prefix
caching, with compatibility limits around compaction. The
[Agents API session configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration#update-settings-for-an-existing-session)
applies effort changes to **new turns** after an update; an active turn keeps
its settings. These API controls do not establish Desktop or CLI plugin control.
The [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks)
lists prompt, tool, compaction, interruption, and stop events, but no
before-generation hook. Model-supported effort values must come from the
current model catalog; they are not universal constants.

The [Astra-Ares reference implementation](https://github.com/miuuyy/Astra-Ares/tree/a1dbc976103e300419cb0b4ab54150ad6a3e0b4b)
uses a separate, patched Codex CLI, rather than an MCP or ordinary hook. Its
[native patch](https://github.com/miuuyy/Astra-Ares/blob/a1dbc976103e300419cb0b4ab54150ad6a3e0b4ab/patches/native-checkpoint.patch)
inserts a checkpoint before sampling, applies the selected effort through live
turn settings, then checks the freshly captured `StepContext` before reporting
the decision as applied. Its [architecture notes](https://github.com/miuuyy/Astra-Ares/blob/a1dbc976103e300419cb0b4ab54150ad6a3e0b4ab/docs/architecture.md)
also describe a native `configuration_update` path for preserving the original
request effort and prompt prefix. This explains how it reaches a boundary our
unpatched Desktop and CLI integration does not expose. The project's
[validation notes](https://github.com/miuuyy/Astra-Ares/blob/a1dbc976103e300419cb0b4ab54150ad6a3e0b4b/docs/validation.md)
report fixture-level prefix checks, not measured workload cache hit rates or
savings.

## Reproduce the inspection

The following commands read installed versions and generate schemas outside
the repository. The generated schemas were inspected and are not committed:

```sh
codex --version
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /Applications/Codex.app/Contents/Info.plist
/Applications/Codex.app/Contents/Resources/codex --version
codex app-server generate-json-schema --out /tmp/codex-effort-schema
codex app-server generate-json-schema --experimental --out /tmp/codex-effort-experimental-schema
/Applications/Codex.app/Contents/Resources/codex app-server generate-json-schema --experimental --out /tmp/codex-desktop-effort-experimental-schema
```

Compare the two CLI `ClientRequest.json` files: only the experimental one
includes `turn/settings/update`. Its `v2/TurnSettingsUpdateParams.json` accepts
an effort for a named live turn; `v2/TurnSettingsUpdateResponse.json` defines
`applied` as publication for subsequent captures, with already captured steps
unchanged and no later inference guaranteed. The bundled Desktop experimental
`ClientRequest.json` lacks that method. Inspect both `ServerNotification.json`
files for generation events; `thread/settings/updated` and `turn/started` do
not report effective effort for each generation. Repeat this inspection when
either binary changes; version numbers and the report date are part of the
finding.

## Offline controller

The prototype is in [`plugins/typesafe-tools/effort`](../plugins/typesafe-tools/effort/README.md).
It accepts a mocked evaluator decision of model-supported effort for 1, 2, 5,
or 10 actual model starts. A mocked host applies changes only at a prepared
generation boundary and acknowledges the observed effort before the generation
starts. Tool results do not consume the duration. On expiry it restores the
baseline at the next boundary unless a fresh decision is ready. Manual changes
suspend automatic control until explicitly cleared. New input, failure,
cancellation, resume, and compaction invalidate pending decisions. An ambiguous
host outcome blocks further automatic starts until an independent observation
reconciles the effective effort.

Run the mock tests without credentials or network access:

```sh
python3 -m unittest discover -s plugins/typesafe-tools/effort -p 'test_*.py'
```

The next compatibility review must find, on **both** surfaces, an official
generation-start event, a pre-generation effort control, an acknowledgement of
effective effort, a reliable manual-override signal, and documented behavior
through cancel/resume/compaction. Only then can a live adapter and a separate
fixed-effort versus adaptive-effort benchmark be designed. Correctness,
elapsed time, cached input, and known charges must be measured; this prototype
supports no savings claim.
