# Third-Party Notices

Diagram Tools uses one pinned Archify development archive, a separate rolling
Pretty Mermaid runtime, and an optional pinned Wrangler publisher runtime.
Runtime dependencies are installed outside this repository.

| Package or project | Role | License |
|---|---|---|
| [tt-a1i/archify 2.17.0-dev.1](https://github.com/tt-a1i/archify/tree/72c750bb070d95171dbb2244e5b62b1b7da69c12) | Typed JSON to interactive HTML/SVG renderer and validator; pinned development snapshot | MIT |
| [Cocoon-AI/architecture-diagram-generator v1.0](https://github.com/Cocoon-AI/architecture-diagram-generator) | Original design basis credited by Archify | MIT |
| [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) | Embedded variable font subsets in Archify HTML and SVG | SIL Open Font License 1.1 |
| [Simple Icons 16.28.0](https://github.com/simple-icons/simple-icons/tree/16.28.0) | Source collection for optional Archify brand marks | Collection: CC0-1.0; individual marks retain their own terms |
| [lukilabs/beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) | Mermaid renderer | MIT |
| [@resvg/resvg-js](https://github.com/thx/resvg-js) | SVG-to-PNG renderer | MPL-2.0 |
| [@xmldom/xmldom](https://github.com/xmldom/xmldom) | XML parser and serializer | MIT |
| [culori](https://github.com/Evercoder/culori) | CSS color parsing | MIT |
| [pngjs](https://github.com/pngjs/pngjs) | PNG decoding and inspection | MIT |
| [Cloudflare Wrangler 4.135.0](https://github.com/cloudflare/workers-sdk) | Optional Cloudflare Pages Direct Upload CLI | MIT / Apache-2.0 |
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

The full MIT terms ship in the installed archive. The pinned asset is
`archify.zip` from commit `72c750bb070d95171dbb2244e5b62b1b7da69c12`,
1,885,058 bytes, SHA-256
`d2296515b0091fb8f00580ea9e0b665d91ca5839fde651abe3ecd57a3ca178ec`.
Generated Archify HTML and SVG embed the JetBrains Mono variable font subsets
and their SIL Open Font License 1.1 notice. The full font license also ships as
`assets/JetBrainsMono-OFL.txt`. Viewing these artifacts does not request Google
Fonts; uncovered characters, including CJK, still use the system fallback stack.

The packaged `THIRD_PARTY_NOTICES.md` retains source and license details for
optional brand marks, including individually licensed Simple Icons entries and
the separately sourced OpenAI mark. The collection's CC0 license does not grant
rights to every underlying logo or replace applicable trademark policies.

The packaged notification-only checker
may request
`https://tt-a1i.github.io/archify/skill-updates/archify/stable.json`; it does not
install updates.

Exact installed Pretty Mermaid package versions and integrity hashes are
recorded in each runtime's `package-lock.json`. Installed npm packages include
their full upstream license texts.
