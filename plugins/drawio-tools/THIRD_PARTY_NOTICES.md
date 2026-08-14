# Third-Party Notices

The isolated runtime installs third-party packages during setup. They are not
vendored in this plugin.

| Package or project | Role | License |
|---|---|---|
| [JGraph `@drawio/mcp`](https://github.com/jgraph/drawio-mcp) | Official draw.io MCP server | Apache-2.0 |
| [Model Context Protocol TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) | MCP transport and protocol | MIT |
| [pako](https://github.com/nodeca/pako) | draw.io compression | MIT |
| [libavoid](https://www.adaptagrams.org/) | Vendored connector routing inside `@drawio/mcp` | LGPL-2.1-or-later |
| [draw.io Desktop](https://github.com/jgraph/drawio-desktop) | Optional local editor and exporter | Apache-2.0 |

Exact installed versions and integrity hashes are recorded in
`runtime/bootstrap/package-lock.json`. Installed packages include their
upstream license files. The optional Desktop app remains separately installed
and licensed software.
