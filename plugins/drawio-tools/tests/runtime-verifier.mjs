#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
assert.ok(process.env.CODEX_HOME, "CODEX_HOME must identify a staged runtime");
const original = join(process.env.CODEX_HOME, "runtime", "drawio-tools", "active");
const temp = await mkdtemp(join(tmpdir(), "drawio-verifier-"));
const runtime = join(temp, "runtime");
const packageDir = join(runtime, "node_modules", "@drawio", "mcp");

function verify() {
  return spawnSync(process.execPath, [
    join(pluginRoot, "scripts", "verify-drawio-runtime.mjs"), runtime,
    join(pluginRoot, "runtime", "bootstrap", "package-lock.json"),
  ], { encoding: "utf8" });
}

async function mutateFile(relativePath, transform, expected) {
  const path = join(packageDir, relativePath);
  const before = await readFile(path);
  try {
    await writeFile(path, transform(before));
    const result = verify();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, expected);
  } finally {
    await writeFile(path, before);
  }
}

try {
  await mkdir(dirname(packageDir), { recursive: true });
  await cp(join(original, "node_modules", "@drawio", "mcp"), packageDir, { recursive: true });
  for (const filename of ["package-lock.json", ".drawio-tools-runtime.json"]) {
    await cp(join(original, filename), join(runtime, filename));
  }
  assert.equal(verify().status, 0, "reviewed postinstall may exist without being executed");
  await mutateFile("package.json", (bytes) => {
    const manifest = JSON.parse(bytes);
    manifest.scripts.postinstall = "node unreviewed.js";
    return JSON.stringify(manifest);
  }, /postinstall differs from the reviewed script/);
  for (const filename of ["src/postinstall.js", "src/cdn-cache.js", "vendor/libavoid/libavoid-routing.js"]) {
    await mutateFile(filename, (bytes) => `${bytes}\n// unreviewed change\n`, /package tree hash is unexpected/);
  }
  for (const sibling of ["shared", "shape-search"]) {
    const shadow = join(runtime, "node_modules", "@drawio", sibling);
    await mkdir(shadow);
    assert.match(verify().stderr, /can shadow verified package assets/);
    await rm(shadow, { recursive: true });
  }
  const modulePath = join(packageDir, "src", "cdn-cache.js");
  const moduleBytes = await readFile(modulePath);
  await rm(modulePath);
  await symlink(join(original, "node_modules", "@drawio", "mcp", "src", "cdn-cache.js"), modulePath);
  const linkedModule = verify();
  assert.notEqual(linkedModule.status, 0);
  assert.match(linkedModule.stderr, /installed package contains a symlink: src\/cdn-cache.js/);
  await rm(modulePath);
  await writeFile(modulePath, moduleBytes);
  const linkedRuntime = join(temp, "linked-runtime");
  await symlink(runtime, linkedRuntime);
  const linked = spawnSync(process.execPath, [
    join(pluginRoot, "scripts", "verify-drawio-runtime.mjs"), linkedRuntime,
    join(pluginRoot, "runtime", "bootstrap", "package-lock.json"),
  ], { encoding: "utf8" });
  assert.notEqual(linked.status, 0);
  assert.match(linked.stderr, /runtime directory must be a non-symlink directory/);
  assert.equal(verify().status, 0, "restored runtime must still validate");
  console.log("Draw.io verifier rejects changed scripts/routing, shadow assets, and symlinked runtimes");
} finally {
  await rm(temp, { recursive: true, force: true });
}
