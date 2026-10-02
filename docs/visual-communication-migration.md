# Visual Communication migration

Visual Communication retains the `diagram-tools` plugin ID. Version `0.6.0`
owns `explain-clearly` and `paper-figure-workflow`, together with the existing
diagram skills. Workflow Tools `0.19.0` no longer owns `explain-clearly`.
The migration retires the separate `paper-figure-tools` installation only after
both replacement packages pass installed-byte and skill-ownership checks.
Draw.io, OmniGraffle, Photo Tools, and external Visualize/Remotion installations
remain separate.

## Inspect before migrating

```sh
scripts/setup-codex-toolbox.sh --migration-plan visual-communication
```

This command reads installed plugin discovery, configured enabled intent,
cached package manifests and contents, moved-skill ownership, candidate packages,
and any previous transaction receipt. It does not install packages, change
configuration, create recovery snapshots, or run rendering tools. A disabled,
mixed, incomplete, unknown, or conflicting family is blocked with a JSON reason.

The supported predecessor set is Diagram Tools `0.5.3`, Workflow Tools `0.18.2`,
and Paper Figure Tools `0.3.1`, all enabled, with the original skill owners.
Each predecessor must have exactly one recoverable cached package. Arbitrary
older or newer combinations require a separately reviewed migration.
The predecessor migration is pinned to the approved targets `0.6.0` and
`0.19.0`; a later source checkout does not silently broaden that transition.

An already consolidated family is `current` when Diagram Tools and Workflow
Tools are enabled, their versions are at least `0.6.0` and `0.19.0`, Paper Figure
Tools is absent, and both moved skills have their single new owner. This state
permits normal maintenance with newer consolidated source versions or changed
source bytes. Preflight does not require installed packages to equal the source
checkout before an ordinary update; the update's per-package readback does.

Codex CLI `0.159.0` can omit an installed plugin after its marketplace entry is
removed. The preflight therefore reconciles discovery with configured intent
and cached packages; a missing discovery row is not proof of a fresh install.
It checks other enabled installed plugin skill roots, local Codex/agent skills,
and configured skill paths for competing moved-skill names. Known collisions
still block. A same-named family plugin from another marketplace also blocks
because its plugin-qualified namespace could be ambiguous.

The ownership claim is explicitly limited to **verified family and local skill
sources**. An enabled remote plugin can expose skills without a local cached
manifest. Such a plugin is recorded as `skill_ownership: unverified`, not assumed
to have no skills. It may remain unchanged only when the complete predecessor
and successor family skill-name counts are identical, including non-moved skills.
An extra duplicate owner therefore blocks even when the name set is unchanged.
The helper preserves its
plugin ID, remote source ID, marketplace, version, installed/enabled state, and
all non-family configuration. Source metadata is hashed rather than copied into
receipts. A fresh family or later update that changes the skill-name set blocks
while any enabled remote skill ownership remains unverified. Missing local
manifests, incomplete remote identity, and unknown family state still block.

This replaces the original requirement for a globally proven single owner with
a narrower migration guarantee: exactly one family owner, no competing owner
in inspected local sources, and no newly introduced unqualified skill name.
It does **not** prove an opaque remote plugin has no pre-existing collision.
Receipts expose `ownership_scope`, `opaque_remote_plugins`, and
`family_skill_names_preserved` so that limitation stays visible. The helper
never disables, removes, or installs an unrelated plugin to make checks pass.
Already-running agents' in-memory skill lists are outside this check; start a
new Codex chat after migration to load the new owners.

On macOS with Python 3.9, the helper discovers an already installed Python 3.11+
from `PATH` or the managed Toolbox Health runtime. It uses the standard-library
TOML parser and never installs Python or a parser during preflight. If no parser
is available, the command blocks with `python_3_11_parser_unavailable_no_runtime_installed`.

## Explicit migration

```sh
scripts/setup-codex-toolbox.sh --migrate visual-communication
```

This bounded command migrates the family and exits. It does not run the full
toolbox setup. An entirely fresh family is a read-only no-op directing the user
to normal setup; an already consolidated current family is also a no-op.
Ordinary setup blocks the predecessor family before prerequisites, marketplace
refresh, configuration changes, or plugin updates. Once the family is current,
normal setup may proceed separately.

For a supported predecessor installation, the helper:

1. Captures and verifies predecessor and candidate packages under
   `$CODEX_HOME/state/visual-communication-migration/`.
2. Rehearses the complete upgrade **and recovery** in a temporary Codex home,
   with temporary `HOME` and an allowlisted environment containing no inherited
   credentials, provider profiles, or session identifiers.
3. Rechecks the original installation and candidates for concurrent changes.
4. Installs Diagram Tools with supported `codex plugin add` and verifies its
   exact cached bytes, version, enabled state, and skills.
5. Installs and verifies Workflow Tools the same way, then removes the retired
   Paper Figure Tools through supported `codex plugin remove`.
6. Verifies the final family versions and single family owner per moved skill,
   plus unchanged unrelated discovery, remote source identities, and non-family
   configuration. Any opaque remote ownership remains disclosed as unverified.

Per-command marketplace source overrides select the verified local snapshots.
They do not rewrite the registered marketplace. The helper never writes active
Codex configuration itself, changes native diagram runtimes, touches user figure
projects, or installs a new MCP server. Package snapshots contain plugin files
only, not authentication files or a copy of the user's configuration.
Generated `node_modules`, Python bytecode, Git metadata, and `.DS_Store` files
are excluded from package identity and snapshots. The source checkout's generated
dependencies are left in place; installed native diagram runtimes outside the
plugin caches are unaffected.

## Failure and recovery

A journal records the next operation before each live mutation. A failed
operation triggers recovery from captured predecessor packages using supported
`plugin add` commands. The complete recovery path must already have passed in
the isolated rehearsal. A recovered failure is reported as blocked, not as a
successful migration.

After an interruption, ordinary setup remains blocked. Running the explicit
migration command again performs recovery only and exits with status 2 and a
`recovered` receipt; inspect a new plan before another migration attempt. Recovery
can restore a missing family cache left by an interrupted install. Every cache
that still exists must exactly match a captured predecessor or target package;
same-version user edits, unknown versions, changed enabled intent, changed
unrelated installations, damaged snapshots, and unsafe paths block recovery
before any restore. A partially written, unverifiable package is deliberately
blocked rather than overwritten. The saved receipt and packages remain available
for diagnosis; no automatic cleanup deletes them.

The migration uses an exclusive transaction lock. It does not claim that an
unrelated concurrent package manager is locked: discovery/configuration changes
are detected before the first live update and after the transaction. Repeated
completed runs do not reinstall packages.

## Developer interface and validation

The setup wrapper invokes:

```sh
python3 scripts/migrate_visual_communication.py --plan --root CHECKOUT --codex-bin CODEX
python3 scripts/migrate_visual_communication.py --apply --root CHECKOUT --codex-bin CODEX
python3 scripts/migrate_visual_communication.py --check-setup --root CHECKOUT --codex-bin CODEX
python3 scripts/migrate_visual_communication.py --verify-package diagram-tools --root CHECKOUT --codex-bin CODEX
```

`--codex-home PATH` selects an explicit home for isolated tests. Exit 0 means
the requested inspection/no-op/migration succeeded. Exit 2 means blocked or
recovered without migration. `--check-setup` permits only fresh or current
families; it does not authorize an upgrade. JSON distinguishes `predecessor`,
`fresh`, `current`, `migrated`, `recovered`, `verified`, and `blocked`.
`--verify-package diagram-tools|workflow-tools` is read-only and verifies one
installed package against the source candidate's exact version, bytes, skills,
and enabled state. For this normal-setup readback only, permissions use Git's
regular-file semantics: the owner's executable bit is preserved, while other
permission bits are normalized. A source file with mode `0600` and identical
installed bytes with mode `0644` therefore matches; changed bytes or executable
status still block. The receipt states `mode_semantics: git_executable_bit`.
Migration snapshots, candidate checks, recovery, and existing transaction
receipts retain their original full-permission hashes and reject permission-only
edits. It reports `scope: package`; it does not claim the complete
family is ready while fresh installation is still in progress. Setup invokes
it immediately after each supported in-place `plugin add`. A stale or changed
readback blocks instead of falling back to destructive removal. A verified
live migration, recovery, or package readback reports `live_execution_verified: true`.

Run `python3 -m unittest tests.test_visual_communication_migration`. The suite
uses synthetic packages and temporary homes for disabled/mixed states, retired
catalog entries, collisions, corrupt readback, missing caches, interruption,
recovery, unrelated preservation, opaque remote disclosure, unchanged complete
skill-name sets, and repeated execution. If `codex` is
available, additional real-CLI tests exercise upgrade, recovery, journaled
transactions, same-version changed-byte refresh, and later-version updates
against synthetic packages in temporary homes. These tests
do not migrate the user's installed plugins.
