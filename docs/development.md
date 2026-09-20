# Development and shipping

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Repository checks](#repository-checks)
- [Upgrade Toolbox](#upgrade-toolbox)
- [Instruction Development Checks](#instruction-development-checks)
- [Ship Toolbox](#ship-toolbox)

## Repository checks

Read [AGENTS.md](../AGENTS.md) before editing. Preserve unrelated work and run
focused tests for the changed surface, then the repository gates:

```bash
python3 scripts/check-codex-toolbox-setup.py
python3 -m unittest tests.test_privacy_audit
env -u CODEX_SESSION_ID python3 -m unittest discover -s tests
scripts/privacy-audit.sh current
git diff --check
```

The full Python suite needs the development dependency below. Unsetting
`CODEX_SESSION_ID` prevents credential-transport tests from inheriting the
active Codex session. Run affected plugin suites as required by their source
and CI workflows. Validation does not authorize setup or publication.

Keep the root README short. Put setup and usage details in the relevant guide,
link new guides from the [index](README.md), and keep execution rules in owning
skills. If documentation moves, update `DOCUMENTATION_GUIDES` in the setup
checker and tests that read or mutate that documentation.

## Upgrade Toolbox

Use [Upgrade Toolbox](../plugins/workflow-tools/skills/upgrade-toolbox/SKILL.md)
to audit upstream plugin, skill, MCP, and managed-marketplace sources. A check
request or bare invocation is read-only; an upgrade request prepares and tests
compatible source changes. Prefer stable releases, retain reviewed wrappers and
licenses, and report migrations or unknown upstreams separately. The audit
records declared, locked, and resolved versions: a release tag, plugin label,
and running package version need not be identical.

```text
Use $upgrade-toolbox to check upstream updates without changing anything.
Use $upgrade-toolbox to upgrade compatible upstream components, then $ship-toolbox.
```

Shipping still requires explicit `$ship-toolbox` invocation. `$sync-toolbox`
applies published changes; it does not discover or prepare upstream upgrades.
Maintenance does not add optional capabilities or update independently managed
installations. Reports remain outside Git and distinguish source validation,
publication/CI, installed versions, and runtime verification.

## Instruction Development Checks

Skill descriptions are discovery text: put the distinguishing trigger first,
aim for at most 200 characters, and document any exception above 240 in
`tests/fixtures/instruction-policy.json`. These are toolbox conventions, not
Codex limits. The offline audit parses real YAML, including literal and folded
descriptions; checks local reference chains and invocation policies; and reports
description lengths, entry sizes, ownership, and source hashes.

Install its development-only dependency in an isolated environment:

```bash
python3 -m venv /tmp/toolbox-instruction-audit
/tmp/toolbox-instruction-audit/bin/python -m pip install -r scripts/instruction-audit-requirements.txt
/tmp/toolbox-instruction-audit/bin/python scripts/audit_skill_instructions.py --check --json
/tmp/toolbox-instruction-audit/bin/python -m unittest tests.test_skill_instructions tests.test_instruction_readability tests.test_web_routing tests.test_privacy_audit
```

Use `--baseline tests/fixtures/instruction-baseline.json` to compare this cleanup
against the recorded pre-refactor inventory and enforce its 25% aggregate
description reduction. General CI omits that historical comparison so future
skills can be added deliberately. The Skill Instructions workflow runs offline
metadata, setup, instruction, and privacy checks; it never invokes a model.

Chronicle activates for screen or recent-activity context, Stevens Slides for
Stevens-branded requests, and Defuddle for standalone article extraction.
`ship-toolbox`, `pick-ui-library`, `prototype`, and `review-animations` remain
explicit-only. Customized imported skills use toolbox-owned entry routers with
verbatim `UPSTREAM.md` guidance and a `references/provenance.json` record. The
documented Codex registration entry is `SKILL.md`; preservation checks forbid
a second entrypoint inside each wrapped skill. See the official
[skill layout](https://learn.chatgpt.com/docs/build-skills). The
WeChat entry routes to separate interactive reading, setup/migration,
incremental digest, Sites transport, and scheduling references; its helper
interfaces, state formats, quotas, and delivery lifecycle are unchanged.
Chronicle's preserved original contains trailing whitespace; `.gitattributes`
exempts only that hash-verified `UPSTREAM.md` from whitespace checks.

`scripts/eval_skill_routing.py` prepares and scores the fixed 16 synthetic cases
in `tests/fixtures/skill-routing.json`. The intended three phases are `baseline`,
`candidate`, and `candidate-short` (descriptions truncated to 160 characters),
with one current model and settings, at most 48 model requests, and no automatic
retries. For example, prepare discovery data without document bodies with:

```bash
/tmp/toolbox-instruction-audit/bin/python scripts/eval_skill_routing.py \
  --phase candidate --model gpt-6-astra --effort high --prepare > /tmp/toolbox-routing.json
```

`--prepare` outputs the catalog and synthetic requests without document bodies.
After selection, `--lookup <skill-name>` outputs only that entry body; repeated
`--reference <repository-relative-path>` flags add specific reachable Markdown
references and reject references from other skills. The internal document store
is never printed by `--prepare`. Expected outcomes stay in the scorer. A future live
adapter must establish a capability-restricted Codex process with an empty
effective tool catalog before submitting fixtures. The checked CLI versions
do not provide verified isolation, so `--run` currently refuses with status
`unavailable`, exit code 2, and zero model requests. There is no live execution
adapter or bypass flag. `--score <response.json>` grades imported responses but
does not authenticate their runtime provenance or establish live safety. Passing
single-pass routing screens would remain screening evidence, not proof of
runtime safety.

Plugin versions live in `.codex-plugin/plugin.json`. The marketplace catalog
references local plugin paths without duplicating versions. Instruction changes
that affect public activation behavior patch-bump the owning plugins; preparing
or validating them does not install, publish, or synchronize the marketplace.

## Ship Toolbox

Use `$ship-toolbox` explicitly after completing a task-scoped plugin or skill
change. It requires synchronized `main`, runs repository and affected-plugin
gates, stages only explicit paths and hunks, commits and pushes without a second
confirmation, verifies the remote SHA and relevant CI, then refreshes and
checks the Git-backed local marketplace. It does not create branches, pull
requests, tags, releases, empty commits, or history rewrites, and it preserves
unrelated worktree changes.

Example prompt:

```text
Use $ship-toolbox to validate, commit, push, refresh, and verify the current toolbox changes.
```
