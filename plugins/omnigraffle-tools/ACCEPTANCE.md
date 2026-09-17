# OmniGraffle Tools acceptance — 2026-09-17

This is local development acceptance, separate from publication and installation.
Tests use licensed OmniGraffle 7.26 and official LaTeXiT 2.16.6 on an unlocked
Mac with existing TeX, Automation and Accessibility access.

## Reproduce

Portable tests and licensed-Mac gates are defined in
[the command contract](skills/omnigraffle-workflow/references/commands.md).
Run the live suite only with the apps prepared and no unrelated editor windows.
Each run prints a private temporary evidence directory containing requests,
receipts, native files and exports. Keep clipboard backups out of Git.

## Verified behavior

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
