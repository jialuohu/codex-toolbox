#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const EXPECTED = Object.freeze({
  packageVersion: "1.4.0",
  packageIntegrity: "sha512-DRg8oveMZSN5rgH6TAtkfaGSm364GzJV53uqJE9ug4EYCORjCgEpapFr0XLi037kq2OXdM2Z/vgAyj7N6vbjiA==",
  packageTreeSha256: "9b8fed587fd1bc61041c4a57ec536ad653673e8f413141d7ff6ef0b03754ac6d",
  shapeIndexCommit: "9ce8dc19caa8861315337ec91f3ac7c0df8e0978",
  shapeIndexSha256: "09b84516025e46238e5dd47465cc96ecfd96134ea853ace1063e1ca19dd34601",
  shapeIndexBytes: 4_776_086,
  shapeIndexEntries: 10_446,
});

function fail(message) {
  throw new Error(message);
}

function readJson(path, label) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    fail(`${label} is unreadable: ${error.message}`);
  }
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function requireRegular(path, label) {
  if (!existsSync(path)) fail(`${label} is missing`);
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink()) fail(`${label} must be a regular non-symlink file`);
}

function requireDirectory(path, label) {
  if (!existsSync(path)) fail(`${label} is missing`);
  const stat = lstatSync(path);
  if (!stat.isDirectory() || stat.isSymbolicLink()) fail(`${label} must be a non-symlink directory`);
}

function packageTreeSha256(packageDir) {
  const files = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, entry.name);
      const stat = lstatSync(path);
      if (stat.isSymbolicLink()) fail(`installed package contains a symlink: ${relative(packageDir, path)}`);
      if (stat.isDirectory()) {
        walk(path);
      } else if (stat.isFile()) {
        const relativePath = relative(packageDir, path).replaceAll("\\", "/");
        if (relativePath !== "src/search-index.json") files.push({ path, relativePath });
      } else {
        fail(`installed package contains an unsupported entry: ${relative(packageDir, path)}`);
      }
    }
  }
  walk(packageDir);
  const hash = createHash("sha256");
  for (const file of files.sort((a, b) => a.relativePath.localeCompare(b.relativePath))) {
    hash.update(file.relativePath);
    hash.update("\0");
    hash.update(readFileSync(file.path));
    hash.update("\0");
  }
  return hash.digest("hex");
}

if (process.argv[2] === "--package-tree-sha256") {
  try {
    if (!process.argv[3]) fail("--package-tree-sha256 requires a package directory");
    const packageDir = resolve(process.argv[3]);
    requireDirectory(packageDir, "@drawio/mcp package directory");
    console.log(packageTreeSha256(packageDir));
    process.exit(0);
  } catch (error) {
    console.error(`Draw.io runtime verification failed: ${error.message}`);
    process.exit(1);
  }
}

const [runtimeArg, lockArg] = process.argv.slice(2);
if (!runtimeArg || !lockArg) {
  console.error("Usage: verify-drawio-runtime.mjs RUNTIME_DIR BOOTSTRAP_LOCK");
  process.exit(2);
}

try {
  const runtimeDir = resolve(runtimeArg);
  const sourceLock = resolve(lockArg);
  const receiptPath = `${runtimeDir}/.drawio-tools-runtime.json`;
  const runtimeLockPath = `${runtimeDir}/package-lock.json`;
  const packageDir = `${runtimeDir}/node_modules/@drawio/mcp`;
  const packagePath = `${packageDir}/package.json`;
  const shapeIndexPath = `${packageDir}/src/search-index.json`;

  requireDirectory(runtimeDir, "runtime directory");
  requireRegular(sourceLock, "bootstrap lockfile");
  requireRegular(receiptPath, "runtime receipt");
  requireRegular(runtimeLockPath, "runtime lockfile");
  requireDirectory(packageDir, "@drawio/mcp package directory");
  requireRegular(packagePath, "@drawio/mcp package manifest");
  requireRegular(`${packageDir}/src/index.js`, "@drawio/mcp entrypoint");
  requireRegular(`${packageDir}/src/libavoid-routing.js`, "vendored routing adapter");
  requireRegular(`${packageDir}/vendor/libavoid/libavoid.wasm`, "vendored libavoid runtime");
  requireRegular(`${packageDir}/vendor/libavoid/LICENSE`, "vendored libavoid license");
  requireRegular(shapeIndexPath, "offline shape index");
  requireDirectory(`${runtimeDir}/node_modules`, "runtime node_modules directory");
  requireDirectory(`${runtimeDir}/node_modules/@drawio`, "runtime @drawio scope directory");

  if (existsSync(`${packageDir}/src/routing-core-cache.js`)) {
    fail("unexpected downloaded routing-core cache is present");
  }

  const lockSha256 = sha256(sourceLock);
  if (sha256(runtimeLockPath) !== lockSha256) fail("runtime lockfile differs from the approved bootstrap lockfile");

  const lock = readJson(sourceLock, "bootstrap lockfile");
  const rootPackage = lock.packages?.[""];
  const lockedPackage = lock.packages?.["node_modules/@drawio/mcp"];
  if (rootPackage?.dependencies?.["@drawio/mcp"] !== EXPECTED.packageVersion) fail("bootstrap dependency is not exactly pinned");
  if (lockedPackage?.version !== EXPECTED.packageVersion) fail("locked @drawio/mcp version is unexpected");
  if (lockedPackage?.integrity !== EXPECTED.packageIntegrity) fail("locked @drawio/mcp integrity is unexpected");

  const packageJson = readJson(packagePath, "@drawio/mcp manifest");
  if (packageJson.version !== EXPECTED.packageVersion) fail("installed @drawio/mcp version is unexpected");
  if (packageJson.scripts?.postinstall) fail("installed @drawio/mcp unexpectedly defines postinstall");
  if (packageTreeSha256(packageDir) !== EXPECTED.packageTreeSha256) fail("installed @drawio/mcp package tree hash is unexpected");

  const shapeStat = lstatSync(shapeIndexPath);
  if (shapeStat.size !== EXPECTED.shapeIndexBytes) fail("offline shape index size is unexpected");
  if (sha256(shapeIndexPath) !== EXPECTED.shapeIndexSha256) fail("offline shape index hash is unexpected");
  const shapeIndex = readJson(shapeIndexPath, "offline shape index");
  if (!Array.isArray(shapeIndex) || shapeIndex.length !== EXPECTED.shapeIndexEntries) fail("offline shape index inventory is unexpected");

  const receipt = readJson(receiptPath, "runtime receipt");
  const expectedReceipt = {
    schemaVersion: 1,
    packageVersion: EXPECTED.packageVersion,
    packageIntegrity: EXPECTED.packageIntegrity,
    packageTreeSha256: EXPECTED.packageTreeSha256,
    lockSha256,
    shapeIndexCommit: EXPECTED.shapeIndexCommit,
    shapeIndexSha256: EXPECTED.shapeIndexSha256,
    shapeIndexBytes: EXPECTED.shapeIndexBytes,
    shapeIndexEntries: EXPECTED.shapeIndexEntries,
  };
  for (const [key, value] of Object.entries(expectedReceipt)) {
    if (receipt[key] !== value) fail(`runtime receipt field ${key} is unexpected`);
  }

  console.log(JSON.stringify({ ok: true, runtimeDir, ...expectedReceipt }));
} catch (error) {
  console.error(`Draw.io runtime verification failed: ${error.message}`);
  process.exit(1);
}
