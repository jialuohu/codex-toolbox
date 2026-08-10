# Third-Party Notices

The rolling runtime installs third-party packages from npm into the user's
Codex runtime directory. They are not vendored in this plugin.

| Package or project | Role | License |
|---|---|---|
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

Exact installed versions and integrity hashes are recorded in each runtime's
`package-lock.json`. The installed npm packages include their full upstream
license texts.
