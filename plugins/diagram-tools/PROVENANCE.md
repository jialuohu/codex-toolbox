# Provenance

Diagram Tools is a toolbox-owned integration around two independently managed
upstream renderers.

## Archify

The Archify lane installs the single upstream
[`tt-a1i/archify`](https://github.com/tt-a1i/archify) `v2.16.0` release asset
[`archify.zip`](https://github.com/tt-a1i/archify/releases/download/v2.16.0/archify.zip),
which is distributed under the MIT license.

- Pinned SHA-256:
  `4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`
- Pinned size: 1,318,273 bytes
- Installed location: the isolated Diagram Tools runtime outside this
  repository

The release asset contains the upstream CLI, schemas, examples, authoring skill,
precompiled validators, templates, and MIT `LICENSE`. It is installed without
modifying upstream code. Toolbox-owned additions are the collision-safe
launcher, `runtime-info --json`, checksum/path/archive gates, atomic promotion,
rollback, routing, and integration tests.
Install and rollback atomically replace one `state.json` containing both the
active and previous receipts, so a crash cannot split rollback history.

The toolbox-owned `tests/archify-visual-evidence.mjs` is a CI-only evidence
harness. It imports the pinned release's internal `bin/visual-check.mjs` only
after checking the Archify version, archive digest, expected exports, and exact
viewport list; this internal import is not a product or runtime API. The
upstream `archify visual-check` CLI remains the acceptance gate. The CI harness
adds full light/dark screenshot coverage at all four desktop viewports, hashes
each delivered HTML artifact before and after capture, and records
`visualReview: "pending"` for the uploaded evidence.

Archify credits
[`Cocoon-AI/architecture-diagram-generator`](https://github.com/Cocoon-AI/architecture-diagram-generator)
v1.0 as its MIT-licensed original design basis. Both copyright notices are
preserved in the installed upstream license and summarized in
`THIRD_PARTY_NOTICES.md`.

## Pretty Mermaid

The Pretty Mermaid lane is an original, toolbox-hardened integration built
around
[`lukilabs/beautiful-mermaid`](https://github.com/lukilabs/beautiful-mermaid),
which is distributed under the MIT license.

The command surface and skill use cases were informed by the MIT-licensed
[`imxv/pretty-mermaid-skills`](https://github.com/imxv/pretty-mermaid-skills)
project. Its source code is not vendored. Local changes add real PNG rendering,
offline runtime separation, capability-based API selection, parsed CSS
materialization, conformance gating, atomic promotion, rollback, and toolbox
integration.

`@resvg/resvg-js` is used under MPL-2.0. Other runtime support packages retain
their upstream licenses as recorded in `runtime/bootstrap/package-lock.json`
and `THIRD_PARTY_NOTICES.md`.
