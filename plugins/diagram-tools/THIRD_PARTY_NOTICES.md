# Third-Party Notices

Diagram Tools uses one pinned Archify release asset and a separate rolling
Pretty Mermaid runtime. Neither runtime is committed to this repository.

| Package or project | Role | License |
|---|---|---|
| [tt-a1i/archify v2.16.0](https://github.com/tt-a1i/archify/releases/tag/v2.16.0) | Typed JSON to interactive HTML/SVG renderer and validator | MIT |
| [Cocoon-AI/architecture-diagram-generator v1.0](https://github.com/Cocoon-AI/architecture-diagram-generator) | Original design basis credited by Archify | MIT |
| [lukilabs/beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) | Mermaid renderer | MIT |
| [@resvg/resvg-js](https://github.com/thx/resvg-js) | SVG-to-PNG renderer | MPL-2.0 |
| [@xmldom/xmldom](https://github.com/xmldom/xmldom) | XML parser and serializer | MIT |
| [culori](https://github.com/Evercoder/culori) | CSS color parsing | MIT |
| [pngjs](https://github.com/pngjs/pngjs) | PNG decoding and inspection | MIT |
| [postcss](https://github.com/postcss/postcss) | CSS parser | MIT |
| [postcss-value-parser](https://github.com/TrySound/postcss-value-parser) | CSS value parser | MIT |

The command design and skill use cases were informed by
[imxv/pretty-mermaid-skills](https://github.com/imxv/pretty-mermaid-skills),
which is MIT-licensed. Its source code is not included.

Archify's installed `LICENSE` preserves:

```text
Copyright (c) 2026 tt-a1i (Archify)
Copyright (c) 2025 Cocoon AI (original "architecture-diagram-generator")
```

The full MIT terms ship in the installed release. The pinned asset is
`archify.zip`, SHA-256
`4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`.
Generated Archify HTML retains upstream links that may request JetBrains Mono
from `fonts.googleapis.com` and `fonts.gstatic.com`; system monospace fallbacks
remain when those hosts are unavailable. The packaged notification-only checker
may request
`https://tt-a1i.github.io/archify/skill-updates/archify/stable.json`; it does not
install updates.

Exact installed Pretty Mermaid package versions and integrity hashes are
recorded in each runtime's `package-lock.json`. Installed npm packages include
their full upstream license texts.
