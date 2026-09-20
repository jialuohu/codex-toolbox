# Provenance

Diagram Tools is a toolbox-owned integration around two independently managed
upstream renderers.

## Optional Cloudflare Pages publisher

The toolbox-owned Diagram Publish helper stages accepted HTML and invokes
Wrangler `4.135.0`, installed from `runtime/publisher/package-lock.json` into a
versioned runtime outside the checkout. Wrangler is distributed by Cloudflare
under MIT / Apache-2.0 licenses; its dependencies retain their installed license
files. The helper uses the documented Pages REST API to verify target identity,
reconcile deployment attempts, and remove specifically requested deployments.
No Cloudflare credentials, account configuration, deployment history, or
installed dependencies are distributed with the plugin.

## Archify

The Archify lane installs the committed canonical archive from
[`tt-a1i/archify`](https://github.com/tt-a1i/archify) development snapshot
`2.17.0-dev.1`, commit `72c750bb070d95171dbb2244e5b62b1b7da69c12`:
[`archify.zip`](https://raw.githubusercontent.com/tt-a1i/archify/72c750bb070d95171dbb2244e5b62b1b7da69c12/archify.zip).
Archify's code is distributed under MIT; embedded fonts and brand marks retain
the terms recorded in the packaged third-party notices.

- Pinned SHA-256:
  `d2296515b0091fb8f00580ea9e0b665d91ca5839fde651abe3ecd57a3ca178ec`
- Pinned size: 1,885,058 bytes
- Channel: development; an immutable commit, never a moving `main` reference
- Installed location: the isolated Diagram Tools runtime outside this
  repository

The archive contains the upstream CLI, schemas, examples, authoring skill,
precompiled validators, templates, MIT `LICENSE`, `THIRD_PARTY_NOTICES.md`, and
JetBrains Mono's complete SIL Open Font License 1.1 text. It is installed without
modifying upstream code. Toolbox-owned additions are the collision-safe
launcher, `runtime-info --json`, checksum/path/archive gates, atomic promotion,
rollback, routing, and integration tests.
Install and rollback atomically replace one `state.json` containing both the
active and previous receipts, so a crash cannot split rollback history.
Stable `2.16.0` remains distinct from this development snapshot. An upgrade from
the stable runtime preserves its receipt as the previous generation for
`scripts/setup-archify-tools.sh --rollback`; fresh installations have no rollback
generation. The notification-only checker still uses the stable manifest and
does not change the selected runtime or follow development commits.

The toolbox-owned `tests/archify-visual-evidence.mjs` is a CI-only evidence
harness. It imports the pinned archive's internal `bin/visual-check.mjs` only
after checking the Archify version, archive digest, expected exports, and exact
viewport list; this internal import is not a product or runtime API. The
upstream `archify visual-check` CLI remains the acceptance gate. The CI harness
adds full light/dark screenshot coverage at all four desktop viewports, hashes
each delivered HTML artifact before and after capture, and records
`visualReview: "pending"` for the uploaded evidence. Automated
`browser_evidence` and perceptual `visual_review` remain independent claims;
neither deterministic delivery nor screenshots establish visual approval.

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
