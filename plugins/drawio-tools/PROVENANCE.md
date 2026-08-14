# Provenance

This plugin is a toolbox-owned integration around JGraph's official
[`@drawio/mcp`](https://www.npmjs.com/package/@drawio/mcp) server. The runtime
is installed from npm during explicit toolbox setup and is not vendored in the
plugin. Version `1.4.0` is pinned with npm integrity
`sha512-DRg8oveMZSN5rgH6TAtkfaGSm364GzJV53uqJE9ug4EYCORjCgEpapFr0XLi037kq2OXdM2Z/vgAyj7N6vbjiA==`.
The extracted package tree (excluding the separately verified shape index) is
also pinned to SHA-256
`9b8fed587fd1bc61041c4a57ec536ad653673e8f413141d7ff6ef0b03754ac6d`.

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
