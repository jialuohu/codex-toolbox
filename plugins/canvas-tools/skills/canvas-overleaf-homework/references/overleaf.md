# Build and update the Overleaf project

Use `$overleaf` for every project operation. Apply these write and verification
requirements to full preparation and narrow edits alike. Start with configuration
status and project listing, and resolve the project URL or name to one configured
alias. If it is not configured, stop with configuration guidance; do not use
browser automation or raw Git as a workaround. Read the current target file and
preamble before changing an existing project.

- For a new or effectively empty project, instantiate the files under
  [homework template](../assets/homework-template/README.md). Name the assignment body
  `homework/homework-<NN>.tex`, using two digits for a numeric homework number,
  and update `\assignmentfile` in `main.tex`.
- For an existing project, follow its organization when that can preserve the
  same safety properties. Never overwrite the entire project merely to impose
  the bundled template.
- Add a blank `solution` environment, with matching items for multipart questions,
  for each newly inserted problem. Change an existing solution scaffold only when
  explicitly requested; preserve its answer text.
- Reconstruct the intended project in a temporary local directory and compile
  `main.tex` with `$latex-compile` before any Overleaf mutation. A compile error
  blocks the write; report whether it appears pre-existing or introduced by the
  proposed change.
- Before every mutation, freshly list or read the target and pass its exact revision
  and blob value. Use `expected_blob_sha: "absent"` only after a fresh listing
  proves the destination does not exist.
- Preview the exact project alias, path, action, and commit message. Perform one
  prompt-gated file write or import at a time; never run Overleaf mutations in
  parallel. Prefer a unique literal text edit over a full-file replacement.
- After each write, read the new revision and affected file before continuing.
  On stale state, reassess from fresh data. On `OUTCOME_UNKNOWN`, preserve the
  candidate commit and call `overleaf_reconcile_commit`; never retry blindly.
- After the last write, read back all changed text and compile a fresh local
  snapshot. Verify requested problem numbers, exact statements, figure paths,
  blank new solutions with the correct item count and labels, and the displayed
  deadline.
