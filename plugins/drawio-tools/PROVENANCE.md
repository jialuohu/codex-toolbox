# Provenance

This plugin is a toolbox-owned integration around JGraph's official
[`@drawio/mcp`](https://www.npmjs.com/package/@drawio/mcp) server. The runtime
is installed from npm during explicit toolbox setup and is not vendored in the
plugin. Version `1.6.0` is pinned with npm integrity
`sha512-4gVsfbkYAc1HzhPEQEsEk7cWPr5i6HIn/syjc6OUYnqDZOCP7pYsVSgiOq49IjNY5BvARSN2uPejQ8Bk8GY/og==`.
The extracted package tree (excluding the separately verified shape index) is
also pinned to SHA-256
`8ec16714a64760022d45737080e8702030f12a2c307c6fe93a5d8ec202224c73`.
The package manifest, CDN/cache loaders, postinstall, server entrypoint, routing
pass, and vendored routing/WASM match upstream commit
[`10e588e85a41595e4d35e81ab7a172c7f7e4fd70`](https://github.com/jgraph/drawio-mcp/commit/10e588e85a41595e4d35e81ab7a172c7f7e4fd70).
The production lock pins the security-fixed compatible transitive releases
`fast-uri@3.1.7`, `qs@6.16.0`, and `hono@4.13.10`; setup audits the complete
production tree before promotion. The Hono patch addresses
[static output traversal](https://github.com/advisories/GHSA-gqvv-2mrq-wpjv),
[body-parser memory exhaustion](https://github.com/advisories/GHSA-g6gw-c38x-mqfc),
and [query parsing after URL fragments](https://github.com/advisories/GHSA-crvj-82cr-hjcx).

The offline shape search index is fetched only during setup from upstream
commit `9ce8dc19caa8861315337ec91f3ac7c0df8e0978`. Setup requires SHA-256
`09b84516025e46238e5dd47465cc96ecfd96134ea853ace1063e1ca19dd34601`
before promotion. It is installed into the isolated runtime and is not stored
in this repository.

The skill and wrappers are original toolbox code informed by the official
[draw.io MCP documentation](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/)
and upstream command-line skill. Local changes add exact dependency receipts,
disabled lifecycle scripts, production audit gating, an offline shape index,
atomic promotion, MCP tool policy, and optional Desktop export verification.

Upstream 1.6.0 adds `node src/postinstall.js`, which fetches mutable routing
JavaScript into a per-user cache. It remains present in the verified package
but never runs during toolbox setup. Upstream also evaluates CDN/cache routing
code on first routing use, downloads/evaluates ELK for server-side XML layout,
and sends sparse shape queries to an icon service. The toolbox entrypoint binds
the shared routing source to the verified vendored file before loading the
server, rejects server-side ELK with an explicit result note, and disables icon
supplementation. It ignores inherited ELK/icon overrides, bypasses user caches,
and denies server-side `fetch` as a backstop. Mermaid ELK selection is a local
source transformation; the requested editor performs that layout. Browser and
Desktop opens retain their existing behavior and approval policy.
The managed launcher clears inherited `NODE_OPTIONS` and `NODE_PATH` before
running Node, so preload code and alternate module-search paths cannot run
before verification or change the managed server.
