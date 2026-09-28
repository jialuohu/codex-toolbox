---
name: omnigraffle-workflow
description: "Create, edit and export OmniGraffle .graffle diagrams with LaTeXiT equations. Use for explicit OmniGraffle, existing .graffle sources, or new unowned research architecture, workflow and mechanism diagrams when native drawing is ready."
---

# OmniGraffle Workflow

Before any app access or readiness probe, read [UI cleanup](references/ui-cleanup.md) and capture initial process/window state without launching apps. Apply it on completion or failure when control is available.

Produce editable native `.graffle` files and visually checked PDF/PNG previews. Explicit application choice takes precedence, followed by the existing artifact format and project or venue convention. Prefer this accepted native workflow for new research architecture, workflow and mechanism diagrams without another selected owner. For a new unowned request, a fresh `doctor --probe-app` must show responsive scripting and advertised PDF export; if unavailable, disclose Draw.io fallback before native dispatch. Explicit OmniGraffle, existing `.graffle` sources and recorded project owners retain their owner during an app blocker. `$drawio` owns draw.io/`.drawio`; `$archify` remains the general graphical default; `$pretty-mermaid` owns explicit Mermaid and compact static diagrams. `$paper-figure-workflow` owns publication directories, regeneration commands and cross-figure checks, delegating native drawing here.

## Runtime and operations

Read [the command contract](references/commands.md). Resolve this active skill directory and use `python3 scripts/omnigraffle.py --help`, then `doctor`, before native work. Requests are JSON data, never executable scripts. Use the CLI's documented schema and fixed adapters; do not generate AppleScript from labels or paths. Geometry and font sizes use points.

Default installation installs plugin files only. Do not install applications or TeX, change permissions, or build dependencies during ordinary drawing. Report missing dependencies from `doctor`; use the existing LaTeX skills for explicit TeX setup. Stock official LaTeXiT owns new equations: GUI automation requires an unlocked desktop and uses the user's shared LaTeXiT application state. No isolated LaTeXiT build, MCP server or persistent daemon is shipped. Read [equation behavior](references/equations.md) before equation operations.

Current [native acceptance](../../ACCEPTANCE.md) verified genuine LaTeXiT editing after both apps restarted in the user's foreground Terminal. This accepted caller profile does not grant another process permission: SSH-to-System Events remained denied in the tested profile. The drawing readiness probe never establishes equation GUI readiness. Verify the current caller's unlocked desktop, System Events access and LaTeXiT controls before equation operations.

## Preserve meaning and native state

1. Inspect the canonical input path, current saved fingerprint, canvas/object identifiers and application unsaved state. Reject stale or ambiguous targets. Read the native artifact and rendered figure before revising; retained JSON is never authoritative after native creation.
2. Match comments against their original page dimensions. Preserve accepted changes, unrelated objects, notation, approved colors, and label language. A Chinese edit request does not translate English labels. For new figures, use explicit label language, then project conventions, then the user's language.
3. Use native shapes, text, groups and connectors. Keep each equation separately editable. Never flatten the whole diagram to make export easy. Serialize operations across both applications, preserve recoverable originals, stage outputs, and verify before replacing an authorized destination.
4. Record mutations before execution. After a timeout or interruption use `reconcile`; do not replay a mutation whose outcome is unknown. Check both file fingerprint and unsaved native state before subsequent changes.

## Style and palettes

Read [research defaults](references/style.md) as overridable guidance, not global design rules. Preserve established figure style. For new research figures, apply each setting in this order: explicit request, project or venue convention, research default, general default. For new palette selection or requested recoloring, invoke `$mono-color`, resolve its active `SKILL.md`, and read `<mono-color-skill-dir>/references/design-system/colors.json` from that exact installation. Pass the exact absolute catalog path and returned HEX values to the drawing operation. There is no duplicated fallback catalog. If unavailable, preserve supplied colors and report palette selection unavailable. Palette alternatives are optional; palette selection does not import poster textures or generate artwork. Record selected values and provenance with project-local source for independent regeneration; never require the original plugin-cache path at regeneration time.

## Verification and delivery

Export the explicit canvas/document to PDF or PNG; use SVG only when supported by the installed application/license. Inspect the entire rendered figure and dense crops at final reading size with the PDF skill as appropriate. Check dimensions, clipping, fonts including CJK glyphs, connectors and equation baselines. Structural `audit` is read-only and does not establish visual quality or LinkBack editability.

Verify equation source, preamble, mode, size and identity through the actual LaTeXiT LinkBack callback and saved native artifact; a vector PDF or replaced metadata alone is insufficient. Deliver native and inspected export paths, object identities, versions, hashes, warnings and actual verification status. Report unperformed checks explicitly. Publication and installed-profile rollout follow the separately invoked shipping workflow.

After verification, close owned saved preview windows and return file links. Keep them open for an explicit open/show/keep-open request or active interactive handoff; follow the cleanup reference for uncertain state and app quitting.

## Research diagram templates

Read [the template contract](../../assets/research-templates/README.md) before
creating a new architecture, execution comparison, or cache/memory mechanism.
It links six saved editable `.graffle` starters and their source/export
acceptance manifest. Copy a starter to a new project-owned filename before
editing; the copied palette provenance travels with its native source.
`scripts/verify_research_starters.py` checks bundled source integrity and
recorded acceptance without an app; it does not verify current app or LaTeXiT
readiness.
`scripts/research_workflow.py --template architecture|timeline|mechanism
--width single|double source --out ABSOLUTE_JSON` writes an exact-size native
initialization specification and palette-provenance sidecar. The optional
positive `--width-in` replaces `--width`; `--with-inset` adds editable vector
primitives to the mechanism template. The earlier `workflow.json` starter and
`--spec` interface remain usable.

Use `validate` and the visibly labelled `preview` only for portable checks.
Use `doctor --probe-app` before preparing a fresh guarded `create` request.
Saved native `.graffle` content is authoritative after creation; do not replay
the JSON seed over native edits or linked equations. Inspect a saved and
reopened native document and its final-size exports before claiming acceptance.
