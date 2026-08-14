#!/usr/bin/env node

import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { deflateRawSync } from "node:zlib";

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

const pageOne = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="a" value="Uncompressed" parent="1" vertex="1"><mxGeometry x="10" y="10" width="120" height="40" as="geometry"/></mxCell></root></mxGraphModel>';
const pageTwo = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="b" value="Compressed" parent="1" vertex="1"><mxGeometry x="20" y="20" width="120" height="40" as="geometry"/></mxCell></root></mxGraphModel>';
const compressedPageTwo = deflateRawSync(Buffer.from(encodeURIComponent(pageTwo))).toString("base64");
const sourcePath = join(tempRoot, "multi-page.drawio");
await writeFile(
  sourcePath,
  `<mxfile><diagram id="one" name="Overview">${pageOne}</diagram><diagram id="two" name="Details">${compressedPageTwo}</diagram></mxfile>`,
);

const transport = new StdioClientTransport({
  command: "/bin/zsh",
  args: [join(pluginRoot, "scripts", "run-drawio-mcp.sh")],
  cwd: pluginRoot,
  env: {
    ...process.env,
    PATH: `${fakeBin}${delimiter}${process.env.PATH || ""}`,
    DRAWIO_BASE_URL: "https://app.diagrams.net/",
  },
});
const client = new Client({ name: "drawio-tools-smoke", version: "1.0.0" });

function textResult(result) {
  const item = result.content?.find((entry) => entry.type === "text");
  assert.ok(item?.text, "tool result must contain text");
  assert.equal(result.isError, undefined, item.text);
  return item.text;
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

  const shapes = JSON.parse(textResult(await client.callTool({
    name: "search_shapes",
    arguments: { query: "aws lambda", limit: 3 },
  })));
  assert.ok(shapes.length > 0 && shapes.length <= 3, "offline shape search must return bounded results");

  const opened = textResult(await client.callTool({
    name: "open_drawio_mermaid",
    arguments: { content: "flowchart LR; A-->B;" },
  }));
  assert.match(opened, /^Draw\.io Editor URL:\nhttps:\/\/app\.diagrams\.net\//);

  console.log("Draw.io MCP handshake, tool inventory, browser URL, shape search, and page operations passed");
} finally {
  await client.close().catch(() => {});
  await rm(tempRoot, { recursive: true, force: true });
}
