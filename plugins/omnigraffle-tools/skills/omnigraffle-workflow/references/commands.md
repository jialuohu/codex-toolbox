# Local command contract

Resolve this installed skill directory; the entry point is `python3 scripts/omnigraffle.py`. Read `--help` and command-specific help for exact flags and the accepted JSON schema before use.

| Command | Responsibility |
| --- | --- |
| `doctor` | Application versions, scripting access, exports, official LaTeXiT and TeX readiness |
| `inspect`, `audit` | Canonical file, canvas/object identities and structural findings; read-only |
| `create` | Native editable shapes, text, groups, connectors and equations from JSON |
| `update` | Explicit changes to inspected identities, preserving unrelated content |
| `equation-source` | Retrieve source and equation settings |
| `equation-render` | Render with official LaTeXiT |
| `equation-insert`, `equation-update` | Genuine native equation insertion and LinkBack updates |
| `export` | Explicit canvas/document PDF/PNG and supported SVG |
| `reconcile` | Inspect interrupted operation outcome without repeating its mutation |

Mutation and equation parameters arrive through `--request JSON_FILE`. `doctor` accepts optional `--probe-app`; `inspect FILE` and `audit FILE` accept optional `--output REPORT`; `reconcile OPERATION_ID` reads an existing journal. `--state-dir` selects the local operation state directory. Paths, labels and TeX remain data. Geometry and sizes use points. Results must identify paths, native identities, versions, hashes, warnings and verification status; an unsupported operation is an error, not a successful empty result.

Do not write audit output over the input or an alias (symlink or hard link). Reject malformed archives, excessive decompression, missing assets, ambiguous or duplicate identifiers and malformed outer LinkBack records. Unsupported native formats are read-only through file adapters; use native inspection where supported. Native `.graffle` is authoritative after creation; an old JSON specification must not erase manual changes.

Each write uses a canonical target, expected saved fingerprint and inspected canvas/object IDs, and checks unsaved application changes. Serialize application access. Preserve originals, stage changes, verify and replace only an authorized destination. Journal pending mutation before dispatch; after a timeout call `reconcile` and do not automatically retry. Never count a sent AppleEvent or callback as proof the resulting document was saved correctly.

## Request examples

Generate a fresh canonical lowercase UUID for each new operation. Reuse an operation ID only to retrieve its existing receipt, never to request a changed operation. Paths below are examples; replace them with actual canonical destinations. Existing-document requests require `input` and the inspected `expected_sha256`. Replacing an existing output additionally requires `overwrite: true` and its current `expected_output_sha256`.

Create one canvas with native bilingual text:

When `$mono-color` supplied the colors, optionally include `palette: {"catalog_path": "/absolute/path/to/active/mono-color/references/design-system/colors.json"}` on `create` or `update`. The receipt records that exact catalog and hash; shape `fill`/`stroke` fields carry the selected HEX values. This records provenance without replacing approved colors or loading a fallback catalog.

```json
{
  "operation_id": "c1d63ea4-036a-4fa9-9f1c-7f47074b251e",
  "output": "/absolute/output.graffle",
  "spec": {
    "canvases": [{
      "key": "main", "name": "Workflow", "width": 480, "height": 240,
      "objects": [{"key": "input", "kind": "shape", "x": 40, "y": 80,
                   "width": 140, "height": 60, "text": "Input / 输入", "font_size": 16}]
    }]
  }
}
```

Update uses `changes: [{"canvas_id": 1, "object_id": 3, "set": {"text": "Revised label"}}]` plus the common operation, source fingerprint and output fields. IDs must come from inspection, not these illustrative values.

Text operations replace the target's whole label. Label-only changes retain its first-character font and size; mixed rich-text runs are not retained. Native text font sizes use whole points. Equations may use fractional sizes from 1 to 256 points. `--timeout` bounds each adapter call, not the whole multi-step command. A timeout leaves the operation pending until reconciliation.

`--state-dir` changes receipt storage only. The application lock, pending-operation guard and operation-ID registry remain shared across receipt directories. Overwriting a destination preserves its file mode, access-control list and extended attributes on macOS, with an original backup retained in the private receipt directory. The lock coordinates toolbox commands; another application must not write the closed destination during publication.

Equation settings use `equation: {"source": "x^2+1", "preamble": "\\documentclass[10pt]{article}\n\\usepackage{amsmath}\n\\pagestyle{empty}", "mode": "display", "font_size": 16}`. Insertion additionally takes inspected `canvas_id`, a new `key`, and `x`/`y` in points; update takes `canvas_id` and `object_id`. Supply trusted TeX only: restrictions on commands are additional validation, not a TeX sandbox.

Provide a compilable preamble for new equations. Linked updates must retain the exact existing preamble returned by `equation-source`; source, mode and size remain editable. A preamble change returns `protected_preamble` before rendering and requires a new equation insertion instead.

Export takes `scope: "canvas"`, inspected `canvas_id`, uppercase `format: "PDF"` (or `PNG`/supported `SVG`), and optional `dpi`, plus common fields. `scope: "document"` omits `canvas_id`. Unsupported constructs return errors; do not silently discard requested object properties.

## Current bounds and acceptance

Native objects use `shape`, `text`, `connector`, `group`, or separately inserted `equation` kinds. Connector endpoints must be nonoverlapping native shape/text objects on one canvas. Groups are flat collections of distinct shape/text/connector children; nested, shared and equation group members are unsupported. Native text font sizes must be integers. Prefer at most 1,000 native objects total and canvas names of at most 256 characters. Native adapters reject requests beyond their own narrower limits even if general JSON validation accepts them.

File adapters read bounded modern ZIP/plist files; they do not mutate opaque LinkBack archives. Production GUI editing requires an already configured safe TeX profile, running official applications and existing permissions. The CLI does not configure these automatically. Structural and export-signature checks do not replace visual inspection.

Portable CI runs without installed applications. A separately gated local suite retains temporary evidence and never installs dependencies or changes preferences:

```bash
OMNIGRAFFLE_MAC_INTEGRATION=1 python3 -m unittest tests.test_omnigraffle_mac
OMNIGRAFFLE_MAC_INTEGRATION=1 OMNIGRAFFLE_MAC_EQUATIONS=1 python3 -m unittest tests.test_omnigraffle_mac
```

Set `OMNIGRAFFLE_MAC_RESTART_APPS=1` as an additional explicit action only for the restart demonstration. Before quitting, restart refuses any open OmniGraffle document or visible window in either application. After verifying new process identities, it may close only an empty default startup document/editor. OmniGraffle must report unmodified state, no saved path and no graphics. LaTeXiT must have an empty body, no rendered preview or dialog, and no modification indicator. LaTeXiT 2.16.6 omits `AXEdited`; in that case the test uses those blank-editor checks and a normal close, leaving any save prompt untouched. Restored content or unknown windows stop the test. It never force-quits or changes startup preferences. Without that flag, two callback updates can be tested, but restart acceptance is explicitly not claimed. The suite retains artifacts and receipts after failure; inspect and reconcile any unknown mutation before rerunning. Inspect exported PDF/PNG manually for Chinese glyph coverage, clipping, baselines and final reading size before claiming visual acceptance.
