#!/usr/bin/env node

import assert from "node:assert/strict";
import { chmod, copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { deflateRawSync, inflateRawSync } from "node:zlib";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const codexHome = process.env.CODEX_HOME;
if (!codexHome) throw new Error("CODEX_HOME must point to the staged Draw.io runtime");

const runtimeRoot = join(codexHome, "runtime", "drawio-tools", "active");
const sdkRoot = join(runtimeRoot, "node_modules", "@modelcontextprotocol", "sdk", "dist", "esm", "client");
const { Client } = await import(pathToFileURL(join(sdkRoot, "index.js")));
const { StdioClientTransport } = await import(pathToFileURL(join(sdkRoot, "stdio.js")));

const tempRoot = await mkdtemp(join(tmpdir(), "drawio-mcp-smoke-"));
const fakeBin = join(tempRoot, "bin");
await mkdir(fakeBin);
const openerName = process.platform === "darwin" ? "open" : "xdg-open";
const openerPath = join(fakeBin, openerName);
await writeFile(openerPath, "#!/bin/sh\nexit 0\n", { mode: 0o755 });
await chmod(openerPath, 0o755);

// Exercise hostile inherited settings and caches without sending requests or
// evaluating external code. A test-only node executable injects observation
// explicitly; inherited NODE_OPTIONS/NODE_PATH must be cleared by the real
// shell launcher. The accessor survives the runtime's fetch-deny assignment.
const policyLog = join(tempRoot, "policy.jsonl");
const preload = join(tempRoot, "observe-policy.mjs");
await writeFile(policyLog, "");
await writeFile(preload, `import { appendFileSync } from "node:fs";
const log = (event) => appendFileSync(${JSON.stringify(policyLog)}, JSON.stringify(event) + "\\n");
appendFileSync(${JSON.stringify(policyLog + ".instrumented")}, "loaded\\n");
if (process.env.NODE_OPTIONS || process.env.NODE_PATH) log({ inheritedNodeSettings: true });
globalThis.recordUnsafeCode = () => log({ unsafeCode: true });
let implementation = async () => { throw new Error("Test forbids network"); };
Object.defineProperty(globalThis, "fetch", {
  get() { return (...args) => { log({ fetch: String(args[0]) }); return implementation(...args); }; },
  set(value) { implementation = value; },
});
`);
const shellQuote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
await writeFile(join(fakeBin, "node"), "#!/bin/sh\nexec " + shellQuote(process.execPath)
  + " --import " + shellQuote(pathToFileURL(preload).href) + ' "$@"\n', { mode: 0o755 });
const hostilePreload = join(tempRoot, "hostile-preload.mjs");
await writeFile(hostilePreload, `import { appendFileSync } from "node:fs";
appendFileSync(${JSON.stringify(policyLog)}, "inherited preload executed\\n");
`);
const cacheHome = join(tempRoot, "cache");
const upstreamCache = join(cacheHome, "drawio-mcp");
await mkdir(upstreamCache, { recursive: true });
const hostileSource = "globalThis.recordUnsafeCode(); throw new Error('unreviewed code');";
const hostileElk = join(tempRoot, "unreviewed-elk.js");
await writeFile(hostileElk, hostileSource);
for (const filename of ["libavoid-routing.json", "drawio-elk.json"]) {
  await writeFile(join(upstreamCache, filename), JSON.stringify({ src: hostileSource, etag: "hostile" }));
}

const pageOne = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="a" value="Uncompressed" parent="1" vertex="1"><mxGeometry x="10" y="10" width="120" height="40" as="geometry"/></mxCell></root></mxGraphModel>';
const pageTwo = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="b" value="Compressed" parent="1" vertex="1"><mxGeometry x="20" y="20" width="120" height="40" as="geometry"/></mxCell></root></mxGraphModel>';
const compressedPageTwo = deflateRawSync(Buffer.from(encodeURIComponent(pageTwo))).toString("base64");
const sourcePath = join(tempRoot, "multi-page.drawio");
await writeFile(
  sourcePath,
  `<mxfile><diagram id="one" name="Overview">${pageOne}</diagram><diagram id="two" name="Details">${compressedPageTwo}</diagram></mxfile>`,
);

const transportOptions = {
  command: "/bin/sh",
  args: [join(pluginRoot, "scripts", "run-drawio-mcp.sh")],
  cwd: pluginRoot,
  env: {
    ...process.env,
    PATH: `${fakeBin}${delimiter}${process.env.PATH || ""}`,
    DRAWIO_BASE_URL: "https://app.diagrams.net/",
    DRAWIO_ICON_SERVICE_URL: "http://127.0.0.1:1/private-query-must-not-leave",
    DRAWIO_ELK_URL: hostileElk,
    XDG_CACHE_HOME: cacheHome,
    NODE_OPTIONS: `--import=${pathToFileURL(hostilePreload).href}`,
    NODE_PATH: join(tempRoot, "unreviewed-modules"),
  },
};
const transport = new StdioClientTransport(transportOptions);
const client = new Client({ name: "drawio-tools-smoke", version: "1.0.0" });

function textResult(result) {
  const item = result.content?.find((entry) => entry.type === "text");
  assert.ok(item?.text, "tool result must contain text");
  assert.equal(result.isError, undefined, item.text);
  return item.text;
}

function openedSource(text) {
  const url = new URL(text.split("\n")[1]);
  const payload = JSON.parse(decodeURIComponent(url.hash.slice("#create=".length)));
  return decodeURIComponent(inflateRawSync(Buffer.from(payload.data, "base64")).toString());
}

try {
  await client.connect(transport);
  const listed = await client.listTools();
  assert.deepEqual(
    listed.tools.map((tool) => tool.name).sort(),
    [
      "get_page",
      "list_pages",
      "open_drawio_csv",
      "open_drawio_mermaid",
      "open_drawio_xml",
      "search_shapes",
      "set_page",
    ].sort(),
  );
  const xmlTool = listed.tools.find((tool) => tool.name === "open_drawio_xml");
  assert.deepEqual(xmlTool.inputSchema.properties.routing.enum, ["libavoid"]);
  assert.deepEqual(xmlTool.inputSchema.properties.postLayout.enum, ["elk"]);
  assert.deepEqual(xmlTool.inputSchema.properties.direction.enum, ["vertical", "horizontal"]);

  const pages = JSON.parse(textResult(await client.callTool({
    name: "list_pages",
    arguments: { path: sourcePath },
  })));
  assert.deepEqual(pages.map(({ id, name }) => ({ id, name })), [
    { id: "one", name: "Overview" },
    { id: "two", name: "Details" },
  ]);

  const firstBefore = textResult(await client.callTool({
    name: "get_page",
    arguments: { path: sourcePath, page: "Overview" },
  }));
  assert.match(firstBefore, /Uncompressed/);
  const secondBefore = textResult(await client.callTool({
    name: "get_page",
    arguments: { path: sourcePath, page: "two" },
  }));
  assert.match(secondBefore, /Compressed/);

  const replacement = pageTwo.replace("Compressed", "Updated compressed page");
  textResult(await client.callTool({
    name: "set_page",
    arguments: { path: sourcePath, page: "Details", content: replacement },
  }));
  const secondAfter = textResult(await client.callTool({
    name: "get_page",
    arguments: { path: sourcePath, page: "1" },
  }));
  assert.match(secondAfter, /Updated compressed page/);
  assert.equal(
    textResult(await client.callTool({
      name: "get_page",
      arguments: { path: sourcePath, page: "0" },
    })),
    firstBefore,
    "set_page must preserve unrelated pages",
  );
  const stored = await readFile(sourcePath, "utf8");
  assert.doesNotMatch(stored, /Updated compressed page/, "a compressed page must remain compressed");

  for (const filename of [
    "architecture-overview.drawio",
    "execution-timeline.drawio",
    "cache-memory-mechanism.drawio",
  ]) {
    const templatePath = join(pluginRoot, "assets", "research-templates", filename);
    const copiedPath = join(tempRoot, filename);
    await copyFile(templatePath, copiedPath);
    const [page] = JSON.parse(textResult(await client.callTool({
      name: "list_pages",
      arguments: { path: copiedPath },
    })));
    assert.ok(page?.id, `${filename}: native page ID must survive copy`);
    const before = textResult(await client.callTool({
      name: "get_page",
      arguments: { path: copiedPath, page: page.id },
    }));
    assert.match(before, /<mxGraphModel\b/, `${filename}: editable model expected`);
    textResult(await client.callTool({
      name: "set_page",
      arguments: { path: copiedPath, page: page.id, content: before },
    }));
    const after = textResult(await client.callTool({
      name: "get_page",
      arguments: { path: copiedPath, page: page.id },
    }));
    assert.equal(after, before, `${filename}: source must round-trip through get/set_page`);
    assert.match(await readFile(copiedPath, "utf8"), /Cobalt #2148B8/,
      `${filename}: source-local palette provenance must survive page edit`);
  }

  const shapes = JSON.parse(textResult(await client.callTool({
    name: "search_shapes",
    arguments: { query: "aws lambda", limit: 3 },
  })));
  assert.ok(shapes.length > 0 && shapes.length <= 3, "offline shape search must return bounded results");
  const noMatch = textResult(await client.callTool({
    name: "search_shapes",
    arguments: { query: "zqxvprivatesentinelnoiconmatch", limit: 3 },
  }));
  assert.match(noMatch, /No shapes found/);

  const routingSource = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    + '<mxCell id="a" parent="1" vertex="1"><mxGeometry x="0" y="20" width="80" height="40" as="geometry"/></mxCell>'
    + '<mxCell id="b" parent="1" vertex="1"><mxGeometry x="400" y="20" width="80" height="40" as="geometry"/></mxCell>'
    + '<mxCell id="obstacle" parent="1" vertex="1"><mxGeometry x="180" y="0" width="80" height="80" as="geometry"/></mxCell>'
    + '<mxCell id="edge" parent="1" edge="1" source="a" target="b"><mxGeometry relative="1" as="geometry"/></mxCell>'
    + '</root></mxGraphModel>';
  const routed = textResult(await client.callTool({
    name: "open_drawio_xml",
    arguments: { content: routingSource, routing: "libavoid" },
  }));
  assert.match(openedSource(routed), /<Array as="points"><mxPoint/,
    "verified bundled routing must compute real waypoints");
  const layout = textResult(await client.callTool({
    name: "open_drawio_xml",
    arguments: { content: routingSource, postLayout: "elk" },
  }));
  assert.match(layout, /NOTE: the ELK layout pass could not run.*Server-side ELK layout is unavailable/);
  assert.equal(openedSource(layout), routingSource, "unsupported XML layout must retain supplied coordinates");

  const opened = textResult(await client.callTool({
    name: "open_drawio_mermaid",
    arguments: { content: "flowchart LR; A-->B;" },
  }));
  assert.match(opened, /^Draw\.io Editor URL:\nhttps:\/\/app\.diagrams\.net\//);

  // A rejected layout must not break the server. Also cover the HTTP form of
  // the inherited ELK override in a fresh process before any module is cached.
  assert.equal((await client.listTools()).tools.length, 7);
  const httpClient = new Client({ name: "drawio-http-override-smoke", version: "1.0.0" });
  try {
    await httpClient.connect(new StdioClientTransport({
      ...transportOptions,
      env: { ...transportOptions.env, DRAWIO_ELK_URL: "http://127.0.0.1:1/unreviewed-elk.js" },
    }));
    const blocked = textResult(await httpClient.callTool({
      name: "open_drawio_xml",
      arguments: { content: routingSource, postLayout: "elk" },
    }));
    assert.match(blocked, /Server-side ELK layout is unavailable/);
    assert.equal(openedSource(blocked), routingSource);
  } finally {
    await httpClient.close();
  }
  assert.equal(await readFile(policyLog, "utf8"), "",
    "routing, weak search and XML layout must not fetch or evaluate hostile cache/override code");
  assert.ok((await readFile(policyLog + ".instrumented", "utf8")).split("loaded").length >= 5,
    "both production launcher invocations must run instrumented verification and server processes");

  console.log("Draw.io MCP handshake, seven tools, offline routing/search, ELK denial, and page/template round-trips passed");
} finally {
  await client.close().catch(() => {});
  await rm(tempRoot, { recursive: true, force: true });
}
