# OmniGraffle Tools local acceptance

Local development acceptance is separate from publication and installation.
Tests use licensed OmniGraffle 7.26 and official LaTeXiT 2.16.6 on an unlocked
Mac with existing TeX and Accessibility access. Automation authorization must
be checked for the actual sending identity in each live run.

## Current recheck — 2026-09-25 to 2026-09-26

The earlier AppleEvent timeout `-1712` is resolved. macOS identified the actual
`osascript` sender as `/usr/libexec/sshd-keygen-wrapper`; its OmniGraffle
Automation authorization now reports `authValue=2` and `result=true`.
Fresh `doctor --probe-app` checks passed the version, document enumeration,
Professional property, and fixed JavaScript probes in under one second.
The plugin does not change Automation permissions. Previously this sender's decision was undecided and
macOS delayed its consent prompt; the separate ChatGPT grant did not authorize
this sender.

Native multi-canvas creation, bilingual labels, groups, saved updates, source
preservation, and selected-canvas PDF/PNG exports passed. Connector creation,
endpoint movement, and orthogonal route-cache handling passed saved-file and
native readback checks. The final legacy and research-geometry runtime tests
both passed in 98.304 seconds. Their bilingual PNG was visually checked, and
the PDF embedded Helvetica and PingFang fonts. A gray label's font-size update from 8 to 9 points
passed in 13.539 seconds. The subsequent test of three research ink colors
passed in 22.532 seconds with exact native and saved RTF attributes and
preserved source fingerprints. Verification closes and reopens the saved
working document, checks its fingerprint before and after reopening, and uses
the reopened native readback for acceptance.

The independent `make figures` build exited successfully for all five plots
and eight native diagrams. Previous exports were removed before the build,
initialization seeds were absent, and the regenerated outputs were fresh.
All eight saved native source hashes matched before and after the build.
The PDF/SVG acceptance audit verified 3.3-inch and 6.9-inch widths within
0.01 inch of their targets, editable SVG labels with font sizes of at least
7 points, and embedded Helvetica PDF fonts.

GPU headings and the Populate label in three architecture variants are
repaired. All eight latest native exports were visually inspected, including
single-column and double-column architecture, plain and inset variants,
mechanisms, and timelines. The Brave desktop gallery's top section, comparison
and architecture cards were inspected; links and labels were readable.
Responsive viewport testing has not run. The sanitized batch for the six
bundled native starters also exited successfully with fresh committed PDF,
SVG and PNG exports. All six actual starter PNGs were visually inspected;
arrows were clear and labels were unclipped. Promotion passed source-hash,
public-metadata and palette guards, placing six editable `.graffle` files,
their manifest and palette in `assets/research-templates/native`.

Grayscale renders from the actual double-column architecture, timeline and
mechanism PDFs were visually inspected. Labels remained legible, and state
labels, dashed borders and arrows remained distinguishable.

The final desktop Brave gallery was rebuilt from the accepted independent
project and the actual equation acceptance exports. Its comparison and equation
card screenshots were visually reviewed and readable. All 89 local link and
image references resolved; responsive viewport testing remains unperformed.

Native UI group movement was saved and checked: both children moved by 5.647
points, retained parent ID 4, and the original source was preserved. A native
endpoint width resize from 90 to 110 points passed identity and incident
connector checks: endpoint attachments, arrows, stroke and unrelated objects
were preserved, and saved `LogicalPath` and `Points` matched.

The user-run foreground Terminal System Events probe succeeded with status 0
and a process count of 156. Under this approved foreground sending profile,
the current genuine LaTeXiT test passed in 237.678 seconds. It covered native
creation, official TeX import and stock-owned equation insertion, two genuine
LinkBack callback updates, and exact saved source, preamble, display mode and
16-point size assertions. Both applications then quit normally and restarted
with new process IDs; guarded empty-startup-window checks passed. A third
callback after the restarts saved `x^2+4` and verified the same source/settings
readback and unrelated-object preservation. PDF and PNG exports committed,
and no native operation remains pending. Drawing-runtime source hashes matched
the earlier native drawing tests and independent eight-diagram regeneration.

The final PNG and a 144-dpi rendering of the actual PDF were visually inspected:
English, Chinese and the displayed equation x²+4 were readable and unclipped.
The PDF measured 480 by 240 points and embedded Helvetica, PingFangSC, Courier,
CMMI10, CMR7 and CMR10 fonts. These results establish current native equation
and both-application-restart acceptance for the foreground Terminal profile.
Automation permissions remain specific to the sending profile and do not
transfer to SSH.

Before this foreground run, SSH startup cleanup received the System Events
AppleEvent denial `-1743`. User authentication and sheet completion succeeded,
but subsequent logs reported a missing subject identity bundle identifier and
an unnamed Automation row. A protected read-only query after authentication
still returned `-1743` in 0.033 seconds. A scoped read-only permission-row check
found SSH-to-System-Events authorization value 0 and reason 3, last modified at
2026-09-22 18:16:24 EDT, unchanged after authentication. Its OmniGraffle row had
authorization value 2, last modified at 2026-09-25 22:33:42. After normal System
Events launch, `AEDeterminePermissionToAutomateTarget` also returned `-1743`
without a new prompt or grant. The SSH System Events denial remains unchanged;
a sending-identity issue is a candidate explanation, with no confirmed cause.

A follow-up Settings attempt on September 26 authenticated successfully at
01:57:09 EDT, including successful authorization and sheet completion. The
Automation extension then repeated the missing-subject-identifier error.
The System Events switch stayed off and the protected post-authentication
query again returned `-1743`; its permission row remained unchanged. Live TCC
attribution still identified the SSH wrapper as the responsible sender. The
Apple-signed executable contains `com.apple.sshd-keygen-wrapper` as its code and
embedded bundle identifier, while TCC records it as a standalone path identity.
The error does not establish that the executable lacks an identifier.

Apple's documented reset supports a service and optional sender bundle ID,
without a target-app argument. A sender-only reset attempt was prepared but not
executed: it may also clear that sender's working OmniGraffle and Mail grants,
and support for this path-keyed sender through its identifier is unverified.
This additional scope requires approval; the prior System Events approval does
not authorize clearing those other grants. No service-wide reset, direct TCC
write or permission bypass was performed.

Computer Use refused agent control of Terminal with
`app com.apple.Terminal for safety reasons`. The restriction was not bypassed:
the user executed the approved foreground handoff with an initial read-only
probe, then the explicitly guarded native-test option. The latest OmniGraffle doctor
checks passed all four probes in under one second. The September 17 equation
and restart results below remain a separate historical record.

Portable validation now rejects overlapping or touching connector endpoint
rectangles for straight and orthogonal lines with any supported side attachment.
Regression cases include contained endpoints and corner overlap missed by the
previous center-line check, while unrelated backgrounds and containing regions
remain permitted. Saved-text qualification rejects the tested malformed,
mixed or scoped RTF attributes, invalid color indices, and mismatched color
tables before mutation. Callers cannot supply internal preserved-color tuples;
these are derived from a strictly parsed saved working file and must round-trip
exactly through the native 16-bit sRGB setter.

The focused adapter/style/transaction/export suite passed 74 tests. The final
applicable OmniGraffle, Paper Figure, Draw.io and research-routing suite passed
239 tests, with five opt-in native tests and two plotting tests skipped and
performed separately as described above. The pinned owner-selection, Paper
Figure and routing suite passed all 37 tests without skips. All 14 OmniGraffle
plugin tests passed, including four bundled-native-starter integrity tests;
Draw.io research-template tests (7), capability-routing benchmarks (6), and
privacy unit tests (5) also passed. Setup consistency, the current-diff privacy
audit, strict parsing of 19 changed or new JSON files, and `git diff --check`
passed. These portable checks do not launch apps.

An initial history-wide privacy scan flagged literal HOME-relative secret
directory configuration references in three old BestBlogs revisions. The
scanner now recognizes only separated literal `$HOME` and `${HOME}` references,
then rechecks the remaining content and location for private paths and
credentials. Actual paths, adjacent credentials, malformed references and
forged location prefixes remain detected; scan and enumeration errors fail
closed. All 14 privacy tests passed. The frozen current, history and all scans
each passed across 256 reachable revisions. No history or refs were rewritten.

An earlier full repository snapshot ran 1,393 tests with seven skips and six
errors, all from unrelated TypeSafe campaign/summary tests that require an
absent installed `typesafe-tools/0.4.0` skill. It had no assertion failures.
That snapshot was not a clean full-suite acceptance result. The six dependency
errors are now repaired: the diagnostic campaign uses an exact bundled copy of
the toolbox-owned 0.4.0 recipe, records its original commit and verifies a fixed
SHA-256 before campaign and prompt preparation. No installed 0.4.0 cache is
required, and missing or changed recipes fail explicitly. Nine focused campaign
tests and 125 computer-use tests passed; an actual canary dry-run also passed.
Independent review passed 21 combined campaign and privacy tests plus eight
additional privacy boundary cases. No plugin installation was needed.

The first ambient follow-up run exposed 49 Sites test failures from inherited
Codex session metadata and one OmniGraffle discovery-description length failure.
The Sites fixture now removes only inherited `CODEX_SESSION_ID` from test child
environments, then applies explicit test overrides. A real subprocess regression
confirms that explicit session values are still rejected before credential input
or Git access and that the parent environment is unchanged. Production transport
and credential guards were not modified. All 24 Sites tests passed in the normal
Codex environment. The OmniGraffle description is now 234 characters, within the
240-character limit; 19 instruction and routing tests passed.

The final full repository run passed 1,432 tests in 483.315 seconds with seven
opt-in skips: five licensed-Mac tests, accepted separately above, and two
Obsidian filesystem tests requiring temporary npm installation. It ran in the
pinned Python 3.12 environment with PyYAML 6.0.3, Matplotlib 3.10.6 and SciencePlots
2.2.0, without changing the parent session environment. Final setup validation,
strict parsing of 19 affected JSON files and `git diff --check` passed. These
results replace the earlier unresolved repository-dependency qualification;
the SSH System Events permission remains a separate approval-dependent item.

The 0.2.0 native research acceptance gate passed under the approved foreground
Terminal profile. Automatic preference is active for new unowned research
architecture, workflow and mechanism projects when a fresh macOS drawing probe
confirms responsive OmniGraffle scripting and advertised PDF export; otherwise
implicit selection falls back to Draw.io and reports the reason. A fresh
scaffold outside the checkout and plugin cache selected OmniGraffle with
`native_ready`, recorded that owner, and copied the complete guarded runtime
and six accepted native archives. Explicit application choice, existing source
format and the recorded project owner remain authoritative; later builds keep
that owner fixed. Readiness still belongs to the actual sending profile.
Portable previews are labelled as such and are not native export evidence;
the desktop gallery review does not establish responsive viewport behavior.

## Reproduce

Portable tests and licensed-Mac gates are defined in
[the command contract](skills/omnigraffle-workflow/references/commands.md).
Run the live suite only with the apps prepared and no unrelated editor windows.
Each run prints a private temporary evidence directory containing requests,
receipts, native files and exports. Keep clipboard backups out of Git.

## Historical acceptance — 2026-09-17

- Native creation and saved edits preserve requested font sizes, bilingual
  labels, multiple canvases, groups and connector identities.
- Canvas PDF and PNG export use the selected document window and exclude
  unrelated utility windows. The inspected test PDF is 480 by 240 points;
  its PNG is 480 by 240 pixels, with readable English and Chinese labels.
- New equations use official TeX import, avoiding the protected first two
  preamble lines in GUI New documents. The copy operation waits for the PDF
  and genuine stock-owned LinkBack envelope before insertion.
- Equation insertion, two callback updates and saved-file source/settings
  readback passed. Both apps then restarted; another callback updated the
  same equation to `x^2+4`, with exact source, preamble, mode and size readback.
- The two licensed-Mac integration tests passed together in 222.910 seconds.
  Both the final PNG and a rendered PDF were visually inspected: the equation,
  bilingual labels and connector are readable and unclipped.
- Invalid TeX returned `invalid_tex`, left the source hash unchanged and
  published no output. After closing the unchanged working copy and normally
  quitting the idle apps, reconciliation returned `reconciled_unchanged`.
- Full repository discovery passed: 918 tests, with the two opt-in Mac tests
  skipped in that portable run and passed separately as described above.
  The repository suite used the pinned PyYAML validation environment and a
  minimal environment to isolate credential-sensitive test fixtures.

## Supported bounds

Linked updates retain their existing preamble. Retrieve it with
`equation-source`; use a new insertion for a different preamble. This version
supports source, mode and font-size updates through the existing LinkBack
connection. It does not alter LaTeXiT preferences or bypass protected lines.

Clipboard restoration uses change-count checks. An unreadable legacy plain-text
alias can be omitted only when the full UTF-8 representation is retained, with
a warning. Other unreadable formats fail before clipboard mutation.

Unknown outcomes require reconciliation. Failed test artifacts are retained;
tests never force-quit applications or discard unrelated unsaved work.
