# OmniGraffle feasibility gate

For current production CLI status, see [plugin acceptance](../../plugins/omnigraffle-tools/ACCEPTANCE.md).
The dated findings below preserve the prototype investigation and its earlier blockers.

These are development probes for the proposed `omnigraffle-tools` plugin, not
an installed plugin or completed drawing workflow. No marketplace, setup,
version, or skill-routing changes should be made until the required native
acceptance tests pass.

The stock LaTeXiT GUI prototype passed the two behavioral demonstrations on
2026-09-16, including an additional update after restarting both apps. The
isolated-server design remains blocked. Production CLI implementation,
failure-handling tests, packaging, and release checks are still outstanding.

## Run the probes

From the repository root, inspect prerequisites without contacting OmniGraffle:

```sh
python3 scripts/omnigraffle/preflight.py
```

Explicitly enable bounded, non-mutating AppleEvents:

```sh
python3 scripts/omnigraffle/preflight.py --probe-app --timeout-seconds 5
```

For the subsequently selected stock-app GUI route:

```sh
python3 scripts/omnigraffle/preflight.py --equation-backend stock-gui --probe-app
```

This checks the stock service exception and the official LaTeXiT bundle at
`--latexit-app` (default `/Applications/LaTeXiT.app`). Xcode is not required for
that backend. The default `isolated` backend retains its original feasibility
checks. Neither mode grants permissions or certifies GUI access, rendering,
or live LinkBack behavior from static prerequisites.

`--app` selects an existing OmniGraffle 7 application by exact path. `--tex-bin`
adds an existing TeX directory to discovery. The helper installs nothing and
does not change documents, app preferences, permissions, or the clipboard.
AppleEvents can launch the selected app. A fixed AppKit process inventory
checks canonical application paths and process IDs before each probe. Multiple
running copies, a mismatched path, unavailable discovery, or a changed process
block further queries. With no running instance, only the version query may
launch it; identity is checked before the next query. This is a diagnostic
guard, not a transaction lock or a guarantee against a concurrent app launch.
The probe stops on the first failure without retrying. JSON is printed to stdout; exit 2 means prerequisites are
blocked. Exit 0 means only that prerequisites are present, **not** that native
authoring, rendering, or LinkBack acceptance has passed.

Passive checks also read the application's signed sandbox entitlements with
`codesign`. If sandboxing is enabled and the isolated LinkBack service is absent
from the Mach lookup exceptions, the preflight reports
`isolated_linkback_service_exception_missing` and skips AppleEvents. Unreadable
entitlements remain unverified. A listed exception is not callback proof;
this static check does not evaluate every possible sandbox mechanism.

One probe evaluates the fixed JavaScript expression `1+1`; no user-supplied
script is accepted. The fixed AppleScript uses a dynamic target and the event codes from the
installed OmniGraffle 7 dictionary. A version response alone is insufficient:
document access and JavaScript evaluation must respond as well. JavaScript's
numeric result may be returned as either `2` or `2.0`. Permission
denials and AppleEvent timeouts are reported separately; a timeout does not
identify its cause.

The separate `compile_latexit_probe.py` accepts the pinned source ZIP and a new
output directory. It checks the source hash before extraction and compiles two
unmodified upstream translation units. See `--help` for its arguments. It does
not link or run LaTeXiT, install dependencies, contact OmniGraffle, or certify
equation/LinkBack behavior.

`python3 scripts/omnigraffle/document.py /path/to/file.graffle` inventories the
observed version-16 ZIP/plist format without app access or writes. It reports
canonical paths, file/member/object hashes, canvas/object IDs, connector
references, and explicit limitations. It bounds file size, decompression,
metadata, and nesting; rejects unsafe ZIP paths, duplicate identifiers, and
malformed plists; and treats embedded object archives as opaque bytes. It has
no output-file option. Image/LinkBack associations and nested groups still need
qualification against native fixtures; this is not the completed inspect/audit
interface from the integration plan.

## Initial preflight on 2026-09-16

| Check | Observation | Meaning |
| --- | --- | --- |
| OmniGraffle 7.26 | Version request returned; document, Pro-edition, and JavaScript requests timed out with `-1712` | Native scripting readiness remains blocked; edition/export availability unknown. |
| Native compiler | Unmodified `LatexitEquation.m` and `LaTeXProcessor.m` compiled to ARM64 object files | Compiler compatibility only; neither a linked application nor rendering proof. |
| App build tools | Command Line Tools available; full Xcode, `momc`, and `ibtool` unavailable | Standard LaTeXiT project/model build cannot run. |
| Rendering tools | TeX Live/MacTeX and Ghostscript absent in checked locations | The upstream LaTeXiT rendering path cannot be validated. |
| Bundled Tectonic | Existing LaTeX plugin detected Tectonic 0.17.0 | This does not establish compatibility with LaTeXiT's external-tool contract. |
| Native acceptance | No authored diagram, rendered equation, or live callback test | Release remains blocked. |

These observations are a dated local run, not universal compatibility claims.
Re-run the probes after dependencies or application state change. Do not
terminate the user's application, dismiss dialogs, grant permissions, or
install dependencies as an automatic timeout recovery.

## Authorized dependency setup on 2026-09-16

The user explicitly authorized dependency setup. The owning LaTeX runtime
installer completed a managed full TeX Live 2026 installation at
`~/.cache/codex-runtimes/codex-texlive/full`. Ghostscript 10.07.1 was installed
through Homebrew. A fixed `x^2+1` example compiled to PDF and rendered to PNG;
invalid TeX exited with status 1 without waiting for input. These are dependency
checks, not LaTeXiT or LinkBack acceptance.

Xcode 27.0 (27A266a) was installed from Apple's App Store. Its SDK, `momc`, and
`ibtool` checks passed after the user completed first-launch acceptance.
The system developer-directory selection remains Command Line Tools. Use
`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`
for task-local builds rather than changing that system selection.

The user closed both OmniGraffle copies. A fresh instance at
`/Applications/OmniGraffle.app` passed the path/process guard and all four
scripting probes; it reported version 7.26 and Pro capability. Dependency and
application readiness are no longer the blockers. No existing LaTeXiT
application was replaced and no plugin was registered or published.

## Native prototype findings on 2026-09-16

After the user unlocked the Mac, native document and Pro-edition queries
responded, and JavaScript returned `2.0`. A temporary native document containing
two English/Chinese text shapes and a connector was created and exported to
PDF, PNG, and SVG. Save/reopen preserved graphic IDs 2, 3, and 4, the labels,
connector endpoint IDs, and the saved-file SHA-256.

Those initial observations did not certify the selected application installation:
subsequent process inspection found two running copies with the same bundle
identifier, one in Applications and one on a mounted installer volume. The
preflight now blocks this ambiguity.

After resolving that ambiguity, a fresh native document in the sole selected
application passed drawing and PDF/PNG/SVG export. Explicit straight connector
points rendered correctly with both English and Chinese labels. With
`resolution:1`, scale 1, a 480-by-240-point region, and no border, the PNG was
exactly 480 by 240 pixels and was visually inspected. The installed terminology
defines resolution as pixels per point (1.0 is 72 DPI). This is drawing/export
proof only; equation insertion and persistence have not passed.

Two implementation issues were observed in this limited prototype:

- The default connection had correct endpoint IDs but an incorrect rendered
  path. Explicitly setting its straight line type and point list corrected it.
- An export using `resolution:72` and a 480-by-240-point region produced a
  34,560-by-17,280-pixel PNG. The command timed out while PNG encoding continued;
  the destination appeared later, without a retry, and the native file hash
  remained unchanged. Do not assume this raw setting means dots per inch.
  Translate and bound export dimensions before invoking the application.

An attempted PDF image insertion returned an AppleEvent handler error for a
POSIX-path string and a type-coercion error for a file descriptor. Inspection
found the one newly created shape; it was not recreated. The test document was
closed without saving that partial insertion. These failed setter probes do
not establish that all native image-import routes are unavailable.

## LinkBack initiation investigation

No supported command was found that makes OmniGraffle initiate its LinkBack
client connection for an identified graphic without GUI interaction:

- The installed AppleScript suite and terminology expose no LinkBack or
  external-edit command.
- The [Omni Automation API](https://omni-automation.com/omnigraffle/OG-API.html)
  exposes no LinkBack member. `GraphicView.edit` edits text; `MenuItem` supplies
  presentation properties, and `PlugIn.Action.perform` invokes plug-in actions.
- The [OmniGraffle manual](https://support.omnigroup.com/documentation/omnigraffle/mac/7.8/en/menus-and-keyboard-shortcuts/)
  documents the **Edit LinkBack Item** menu action. This does not satisfy the
  required non-GUI command path.
- The public [LinkBack client implementation](https://github.com/omnigroup/LinkBack/blob/main/Source/LinkBack.m)
  creates a connection owned by the calling process and its delegate. Calling
  it from a helper would not establish OmniGraffle's association with a graphic.
  Server-side `sendEdit` needs an already connected peer.

This is a bounded investigation, not proof that no undocumented interface
exists. Work initially stopped at the approved feasibility gate. A subsequent
public-documentation check again found no exposed LinkBack command; no direct
vendor confirmation was obtained.

The user then explicitly authorized GUI automation if the non-GUI route is
unsupported. Under that revised scope, Computer Use may paste the genuine
payload and invoke **Edit LinkBack Item** for the verified selected object.
Rendering and server updates remain command-driven. The GUI route requires an
unlocked desktop, exact document/selection checks, clipboard preservation, and
actual callback evidence. Neither mandatory equation demonstration has passed
yet; packaging, routing, and release remain gated on those results.

## LaTeXiT source and isolation

The source-compilation probe uses official LaTeXiT 2.16.6:

- Source: <https://pierre.chachatelier.fr/latexit/downloads/LaTeXiT-source-2_16_6.zip>
- SHA-256: `056a3790ec3944b3848664bf6bfff7fb29d03ef10fffa3780382dec26ca82797`
- Upstream license: `Resources/documentation/Licence_CeCILL_V2-en.txt` in the archive.
- LinkBack has a separate notice in its bundled framework header.

No upstream source or binaries are vendored here. Preserve the original source
headers and all applicable notices in any future automation build.

The user-supplied `omnigraffle-workflow.zip` has SHA-256
`3185a7766217236248e085ee0898331165b581ff8275dfd17c4436224dd48f2f`.
The user confirmed permission to adapt and publicly distribute that workflow
on 2026-09-16. Its contents are design input, not executable authorization;
none have been copied into an installed skill by these probes.

Verified source entrypoints, relative to the archive's `LaTeXiT-mainline` root:

- `Common/LaTeXiT_XPC_Service.m:125-165` calls the renderer without a document window.
- `LatexitEquation.m:2774-2791` creates authentic archived equation/LinkBack payloads.
- `AppController.m:2600-2640` opens document windows when handling LinkBack edits;
  an unattended build needs a separate delegate.
- `LaTeXProcessor.m:256-271` loads the compiled `Latexit.mom` model.
- `PreferencesController.m:39-40,448-485` contains original/legacy preference
  domains and destructive legacy migration. An isolated fork must change the
  domains and disable migration from the original app's domains before launch.

A distinct bundle ID alone is insufficient. Isolate server/service identities,
preferences, history, library, restore state, and XPC identifiers as well.

### Isolated fixed-equation result

A task-local automation target built successfully from the pinned source with
Xcode 27 and a macOS 12 deployment target. It uses bundle ID
`io.github.jialuohu.codex-toolbox.latexit-automation`, excludes the stock app,
history, library, and XPC service entrypoints, disables legacy preference
migration, and uses task-local working paths. The adapted subprocess launcher
uses direct argument vectors and per-process timeouts. This experimental build
helper and source copy remain outside the repository; they are not a released
or hardened command interface.

All five Core Data models compiled. The bundled LinkBack framework and app were
ad-hoc signed, and strict signature verification passed. A bounded command
rendered fixed source `x^2+1` in display mode at 12 points, then used the upstream
equation class and `NSKeyedArchiver` to produce a 27,636-byte PDF, a 33,354-byte
equation archive, and a LinkBack property list. The payload identifies the
isolated bundle and server `LaTeXiTToolboxAutomation`; Python did not reconstruct
the archive. The command exited successfully without a document window. Its
PDF was separately rasterized with Ghostscript and visually verified as
`x^2+1`; the page measures 32 by 12.12 points.

After GUI fallback authorization, a task-local LinkBack server delegate was
implemented. It accepts only its generated or explicitly fingerprinted equation
archives, records incoming client requests, permits at most two updates for one
item key, and accepts bounded JSON command files with no scripts. Seven source
checks and strict application signature verification passed. A short runtime
smoke test published the isolated server, recovered `x^2+1`, its preamble,
display mode, and 12-point size through the native archive decoder, and shut
down through a command file with exit status 0. It did not use the general
clipboard or contact OmniGraffle.

This proves render/archive/readback and server startup/shutdown. It does not
prove invalid-TeX handling through the adaptation, two equation updates,
restart persistence, a live callback, or production-grade isolation. A returned
`sendEdit` call alone will not establish that OmniGraffle applied an update;
native document and rendered-output checks remain required.

After the user unlocked the desktop, native scripting passed again and a fresh
test document was created/exported. Computer Use still could not attach: name
and path lookup selected `com.omnigroup.OmniGraffle7.MacAppStore`, while the
verified installed/running identifier was `com.omnigroup.OmniGraffle7`; direct
lookup of that identifier returned `Invalid app`, including after a tool reset.
A bounded AppleScript/System Events fallback for the two menu actions compiled.
The user then explicitly authorized that fallback and further implementation
within the agreed scope.

## Isolated-design blocker: isolated LinkBack service

The authorized System Events test pasted the genuine equation PDF and LinkBack
payload into the verified test document and saved it as graphic ID 5. The saved
ZIP contains the PDF in `image1.pdf` and the native LinkBack envelope in the
root `ImageLinkBack` array. The embedded PDF and opaque equation archive match
the automation build's output byte for byte. The clipboard was restored with
a change-count guard. This establishes insertion and a saved payload, not the
required two updates or reopen/restart acceptance.

With only that graphic selected, the enabled **Edit in LaTeXiTToolboxAutomation**
menu action was invoked once. No client edit callback arrived. The macOS
sandbox log recorded:

```text
Sandbox: OmniGraffle(23304) deny(1) mach-lookup io.github.jialuohu.codex-toolbox.latexit-automation:LaTeXiTToolboxAutomation
```

The installed OmniGraffle 7.26 signature enables App Sandbox. Its
`com.apple.security.temporary-exception.mach-lookup.global-name` entitlement
lists `fr.chachatelier.pierre.LaTeXiT:LaTeXiT` but not the isolated service.
The [LinkBack server source](https://github.com/omnigroup/LinkBack/blob/main/Source/LinkBackServer.m)
constructs the service name from the bundle identifier and server name. The
test payload and running server used matching isolated identities. Apple's
[sandbox entitlement reference](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/AppSandboxTemporaryExceptionEntitlements.html)
describes the Mach lookup exception. The live denial, rather than absence from
the entitlement list alone, establishes this test's connection blocker.

The experimental bundle also lacked the `LinkBackServer` discovery metadata
key; correcting that omission cannot remove the observed sandbox denial.
GUI initiation therefore does not resolve the current isolated-server design.
A supported service-access path from OmniGraffle remains necessary. Reusing the
stock LaTeXiT service identity would violate the approved isolation requirement;
changing OmniGraffle's signature or sandbox is outside this integration.

The bridge shut down through its bounded command interface with exit 0 and
`updates_sent: 0`. No callback retry or equation update was sent. Native
queries became unresponsive after the menu action; only the test's own stalled
read-query process was terminated. OmniGraffle was not force-quit. The saved
test artifact and restored clipboard remain available for reconciliation.

The unrelated input/output shapes retain their structural hashes. The
connector hash changed; comparison with the earlier native fixture isolates
the difference to stroke-color serialization, but complete unrelated-object
preservation was not certified for that isolated-server attempt. Its
full-canvas visual, two-update, save/reopen, and restart checks were incomplete.

## Stock LaTeXiT GUI demonstration on 2026-09-16

After the user selected the official-app test route, LaTeXiT 2.16.6 rendered
`x^2+1` at 12 points in display mode. Its GUI **Copy the image as > PDF** action
produced a genuine `LinkBackData` payload owned by
`fr.chachatelier.pierre.LaTeXiT`, server `LaTeXiT`. A task-local Cocoa helper
preserved the clipboard privately, captured opaque PDF/archive bytes, and
restored the clipboard with a change-count guard. No payload ownership was
rewritten. This route uses the stock app's state rather than the original
isolated automation target.

The earlier hung OmniGraffle instance was terminated only after the user
confirmed there was no work to preserve and explicitly allowed discarding
unsaved work. Subsequent acceptance restarts used normal application quitting.

| Step | Verified result |
| --- | --- |
| Native creation | One 480-by-240-point canvas, English/Chinese text shapes 2 and 3, connector 4. |
| Genuine insertion | Equation graphic 5, native name `prototype-equation`, stock LinkBack owner, embedded PDF/archive saved. |
| Callback initiation | OmniGraffle's **Edit in LaTeXiT** opened **Equation linked with another application** with an active LinkBack indicator and source `x^2+1`. |
| First update | GUI rendering of `x^2+2` changed OmniGraffle's document, retained graphic 5, and saved a changed embedded PDF/archive. The extracted PDF was rendered and visually checked. |
| Second update | `x^3+3` propagated through the existing connection and passed the same identity/save/render checks. |
| Save/reopen | Native file fingerprint remained unchanged; the GUI callback recovered exact source, preamble, display mode, and 12-point size. |
| Both apps restarted | Both process IDs changed. Reopening the native file and invoking the callback recovered the same source/settings with an active LinkBack connection. |
| Post-restart update | `x^3+4` propagated to the same graphic and was saved and visually checked, establishing a working update after restart. |
| Full-canvas export | Native PDF and 480-by-240-pixel PNG correctly rendered bilingual labels, connector, and `x^3+4`. |
| Invalid TeX | An undefined command produced an inline error table, returned to the idle render button, and left the native document unmodified and saved-file fingerprint unchanged. No modal error dialog appeared. |

Before restarting, unrelated graphic and background hashes matched the saved
baseline exactly after insertion and both updates. After the restart update,
the sole unrelated-object difference was omission of the connector's explicit
black stroke-color field. Its native AppleScript color remained RGB `(0,0,0)`,
matching the baseline; all remaining unrelated graphic fields matched exactly.
This is semantic preservation with a documented native serialization change,
not byte-for-byte preservation of every object through application restarts.

After a stock LaTeXiT update, the native LinkBack envelope contains
`serverActionKey: _Refresh`. OmniGraffle then labels its action **Refresh in
LaTeXiT**. That action successfully reopened the linked editing window after
save/reopen and restart. An adapter must recognize both observed labels and
verify the exact selected graphic before invocation.

An additional baseline-copy open attempt raised OmniGraffle's document-open
alert and caused the querying AppleEvent to time out; dismissing the alert
restored responsiveness. This did not alter the native acceptance artifact.
Its cause was not established. A production adapter must distinguish modal
errors from hung processes and must not retry an uncertain mutation.

The local final native file SHA-256 was
`ceef3e101248bb5822f988e1c3d536735b63bd24b83ab94be302ad22036607ad`.
Stage files, receipts, screenshots/rendered checks, and private clipboard
backups remain task-local; generated artifacts and clipboard data are not
vendored. The prototype demonstrates feasibility on this unlocked Mac, not a
production CLI, unattended operation while locked, or an isolated LaTeXiT app.

## Remaining acceptance work

The GUI route has passed the two behavioral demonstrations below. Carry its
official-app ownership and unlocked-desktop requirements into the revised
implementation contract. The isolated-service design would still require a
supported sandbox-access solution; stock-app success does not validate it.

The demonstrated acceptance scenarios are:

1. Insert an authentic equation, update it twice, save/reopen, and verify exact
   source/preamble/mode/size plus rendered output. Preserve the graphic identity
   and unrelated objects/assets.
2. Demonstrate an actual unattended OmniGraffle–LaTeXiT LinkBack edit/update
   callback cycle, including restart persistence. Editing a ZIP, replacing a
   PDF, or verifying source metadata does not prove this callback path.

Production commands still need structured, bounded errors for missing
dependencies, invalid TeX, stale documents, modal alerts, and timeouts. The GUI
invalid-TeX check is not yet a tested CLI error contract. Preserve the
transaction, serialization, journal/reconciliation, fingerprint, backup,
object-identity, and opaque-archive requirements from the implementation plan.

Next implement the CLI with fixed native scripting and GUI adapters, archive
helper fixes, app-aware routing, provenance, packaging, and native/portable
tests. Ordinary native shapes and export remain scripting operations; equation
creation, editor controls, and callback initiation use the official GUI.
Publication and installed-profile rollout remain separate shipping actions.

## Development validation

Run the portable probe tests without native applications or dependencies:

```sh
python3 -m unittest tests.test_omnigraffle_preflight tests.test_latexit_compile_probe
```

On 2026-09-16, all 29 probe tests passed. The setup checker, privacy checks,
and whitespace checks also passed. Repository test discovery completed with
two module-import errors because the system Python lacked PyYAML; both affected
modules subsequently passed all 22 tests in a temporary environment using
`scripts/instruction-audit-requirements.txt`. The entire suite was not rerun in
that environment. These checks do not establish native application acceptance.

After the numeric-response and process-identity guards were added, all 36
portable probe tests passed. The setup checker and privacy checks passed again.
The native prototype and dependency smoke tests remain separate from those
portable tests and from the two required equation acceptance demonstrations.

After dependency setup, the 36 probe tests and five privacy tests passed again;
five task-local prepared-source checks and the setup/privacy/whitespace gates
also passed. Full discovery with the pinned PyYAML environment ran 719 tests
and reported 49 failures (including subtests), all in the existing Sites source
transport module. That module rejected inherited credential-related environment
variables. Rerunning that module with only ordinary path, home, temporary-directory,
and locale variables passed. No credential values were printed or changed.
The whole suite was not rerun in that minimal environment; this is not an
unqualified full-suite pass.

After GUI fallback authorization, the read-only document inspector added 24
portable tests. All 65 inspector, preflight, compiler, and privacy tests passed
together; the real native drawing fixture also passed structural inspection.
Seven task-local server source checks passed. The server startup/readback/shutdown
smoke test is separate from these checks and from the failed GUI callback
acceptance test.

After the live sandbox denial, three additional preflight tests cover isolated
versus stock service exceptions, malformed/unavailable entitlements, and
blocking AppleEvents when the isolated exception is absent. All 68 inspector,
preflight, compiler, and privacy tests passed together. The passive preflight
reported the installed app's missing isolated-service exception; the setup,
current-tree privacy, and whitespace checks passed. The full repository suite
was not rerun for this diagnostic-only change.

After adding the explicit stock-GUI preflight mode, all 72 inspector,
preflight, compiler, and privacy tests passed. The live stock-mode preflight
reported prerequisites present with all four OmniGraffle scripting checks
responding. Setup, current-tree privacy, and whitespace checks passed. These
checks are distinct from the observed GUI demonstration above; the full
repository suite was not rerun for this diagnostic/documentation change.
