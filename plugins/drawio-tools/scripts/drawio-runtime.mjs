#!/usr/bin/env node

// The shell launcher verifies the package tree before loading this entrypoint.
// Keep the upstream package unchanged: configure its shared module objects
// before importing the server, whose layout/search work is lazy.
import { realpathSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

if (!process.argv[2]) throw new Error("Draw.io runtime directory is required");
const runtimeDir = realpathSync(process.argv[2]);
const packageDir = join(runtimeDir, "node_modules", "@drawio", "mcp");
const moduleUrl = (name) => pathToFileURL(join(packageDir, "src", name)).href;

process.env.DRAWIO_ICON_SERVICE_URL = "off";
delete process.env.DRAWIO_ELK_URL;
// A backstop for the pinned server's fetch paths, including a shape index
// removed after verification. Browser/editor interaction remains explicit.
globalThis.fetch = async () => {
  throw new Error("Network access is disabled in the toolbox Draw.io MCP runtime");
};

const { ROUTING_CORE, ELK_BUNDLE } = await import(moduleUrl("cdn-cache.js"));
if (JSON.stringify(Object.keys(ROUTING_CORE).sort()) !== '["file","url"]'
    || ROUTING_CORE.url !== "https://viewer.diagrams.net/js/libavoid-js/libavoid-routing.js"
    || ROUTING_CORE.file !== "libavoid-routing.json"
    || JSON.stringify(Object.keys(ELK_BUNDLE).sort()) !== '["file","timeoutMs","url"]'
    || ELK_BUNDLE.url !== "https://viewer.diagrams.net/js/elk/drawio-elk.min.js"
    || ELK_BUNDLE.file !== "drawio-elk.json"
    || ELK_BUNDLE.timeoutMs !== 20000) {
  throw new Error("Draw.io CDN source contract differs from the reviewed runtime");
}

// A local source bypasses loadCachedSource's network AND per-user cache paths.
ROUTING_CORE.url = join(packageDir, "vendor", "libavoid", "libavoid-routing.js");
Object.freeze(ROUTING_CORE);
// Upstream catches this rejection and returns an explicit note while retaining
// the supplied XML coordinates. No local or remote ELK code is evaluated.
Object.defineProperty(ELK_BUNDLE, "url", {
  get() {
    throw new Error("Server-side ELK layout is unavailable in the offline toolbox runtime; supply XML coordinates");
  },
});
Object.freeze(ELK_BUNDLE);

// The upstream CLI parses process.argv; the runtime directory belongs only to
// this wrapper and must not be forwarded as an unknown server argument.
process.argv = [process.argv[0], join(packageDir, "src", "index.js")];
await import(moduleUrl("index.js"));
