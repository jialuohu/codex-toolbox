# Provenance

This plugin is an original, toolbox-hardened integration built around
[lukilabs/beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid),
which is distributed under the MIT license.

The command surface and skill use cases were informed by the MIT-licensed
[imxv/pretty-mermaid-skills](https://github.com/imxv/pretty-mermaid-skills)
project. Its source code is not vendored. Local changes add real PNG rendering,
offline runtime separation, capability-based API selection, parsed CSS
materialization, conformance gating, atomic promotion, rollback, and toolbox
integration.

`@resvg/resvg-js` is used under MPL-2.0. Other runtime support packages retain
their upstream licenses as recorded in `runtime/bootstrap/package-lock.json`
and `THIRD_PARTY_NOTICES.md`.
