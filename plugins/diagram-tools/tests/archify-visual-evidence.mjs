#!/usr/bin/env node
// CI-only evidence harness for one pinned Archify release. This deliberately
// imports upstream's internal bin/visual-check.mjs exports; it is not a product
// or runtime API and must fail closed when the digest, exports, or viewports move.
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const EXPECTED_VERSION = '2.16.0';
const EXPECTED_SHA256 = '4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46';
const TYPES = Object.freeze(['architecture', 'workflow', 'sequence', 'dataflow', 'lifecycle']);
const VIEWPORTS = Object.freeze([
  Object.freeze({ width: 1440, height: 900 }),
  Object.freeze({ width: 1600, height: 1000 }),
  Object.freeze({ width: 1920, height: 1080 }),
  Object.freeze({ width: 2048, height: 1320 }),
]);
const THEMES = Object.freeze(['light', 'dark']);
const EXPECTED_CAPTURE_COUNT = TYPES.length * VIEWPORTS.length * THEMES.length;

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
  return null;
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function regularFile(path, label) {
  if (!existsSync(path) || !lstatSync(path).isFile()) {
    throw new Error(`${label} is not a regular file: ${path}`);
  }
}

function assertEmptyOutputDirectory(path) {
  if (existsSync(path)) {
    throw new Error(`Evidence directory already exists; refusing stale output: ${path}`);
  }
  mkdirSync(path, { recursive: false });
}

function pngReceipt(path, expectedWidth, expectedHeight) {
  regularFile(path, 'Screenshot');
  const bytes = readFileSync(path);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(signature)) {
    throw new Error(`Screenshot is not a PNG: ${path}`);
  }
  const width = bytes.readUInt32BE(16);
  const height = bytes.readUInt32BE(20);
  if (width !== expectedWidth || height !== expectedHeight) {
    throw new Error(
      `Screenshot dimensions ${width}x${height} do not match ${expectedWidth}x${expectedHeight}: ${path}`,
    );
  }
  return { file: basename(path), bytes: bytes.length, sha256: sha256(bytes), width, height };
}

function fileReceipt(path, label) {
  regularFile(path, label);
  const contents = readFileSync(path);
  return { bytes: contents.length, sha256: sha256(contents) };
}

function writeAtomic(path, contents) {
  const temporary = `${path}.tmp-${process.pid}`;
  writeFileSync(temporary, contents, { flag: 'wx' });
  renameSync(temporary, path);
}

function contactSheet(captures) {
  const sections = TYPES.map((type) => {
    const rows = VIEWPORTS.map(({ width, height }) => {
      const cells = THEMES.map((theme) => {
        const capture = captures.find((entry) => (
          entry.type === type && entry.width === width && entry.height === height && entry.theme === theme
        ));
        return `<figure><img src="${capture.file}" alt="${type} ${theme} at ${width} by ${height}"><figcaption>${theme}</figcaption></figure>`;
      }).join('');
      return `<h3>${width}&times;${height}</h3><div class="pair">${cells}</div>`;
    }).join('');
    return `<section><h2>${type}</h2>${rows}</section>`;
  }).join('');

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Archify CI visual evidence</title><style>
body{font-family:system-ui,sans-serif;margin:24px;background:#f5f5f5;color:#171717}section{margin-block:32px 56px}
.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0;padding:10px;background:white;border:1px solid #ccc}
img{display:block;width:100%;height:auto}figcaption{text-align:center;margin-top:8px}@media(max-width:800px){.pair{grid-template-columns:1fr}}
</style></head><body><h1>Archify CI visual evidence</h1>${sections}</body></html>\n`;
}

async function main() {
  const [runtimeInfoArgument, artifactDirectoryArgument, ...extra] = process.argv.slice(2);
  if (!runtimeInfoArgument || !artifactDirectoryArgument || extra.length > 0) {
    throw new Error('Usage: archify-visual-evidence.mjs RUNTIME_INFO_JSON ARTIFACT_DIRECTORY');
  }

  const runtimeInfoPath = resolve(runtimeInfoArgument);
  const artifactDirectory = resolve(artifactDirectoryArgument);
  regularFile(runtimeInfoPath, 'Runtime info');
  if (!existsSync(artifactDirectory) || !lstatSync(artifactDirectory).isDirectory()) {
    throw new Error(`Artifact directory is unavailable: ${artifactDirectory}`);
  }

  const runtime = JSON.parse(readFileSync(runtimeInfoPath, 'utf8'));
  if (runtime.ok !== true || runtime.status !== 'ready') throw new Error('Archify runtime is not ready');
  if (runtime.version !== EXPECTED_VERSION || runtime.sha256 !== EXPECTED_SHA256) {
    throw new Error(`Unexpected Archify runtime identity: ${runtime.version} ${runtime.sha256}`);
  }
  if (!isAbsolute(runtime.cliPath)) throw new Error('Archify runtime-info cliPath must be absolute');
  regularFile(runtime.cliPath, 'Archify CLI');

  const visualCheckModulePath = join(dirname(runtime.cliPath), 'visual-check.mjs');
  regularFile(visualCheckModulePath, 'Pinned visual-check module');
  const visualCheck = await import(pathToFileURL(visualCheckModulePath).href);
  if (typeof visualCheck.ChromeVisualBrowser !== 'function' || typeof visualCheck.findChrome !== 'function') {
    throw new Error('Pinned visual-check module does not expose the expected Chrome helpers');
  }
  if (JSON.stringify(visualCheck.VISUAL_CHECK_VIEWPORTS) !== JSON.stringify(VIEWPORTS)) {
    throw new Error('Pinned visual-check viewports differ from the approved CI evidence matrix');
  }

  const chromePath = visualCheck.findChrome();
  if (!chromePath) throw new Error('Chrome or Chromium is required for Archify CI visual evidence');

  const evidenceDirectory = join(artifactDirectory, 'complete-theme-evidence');
  assertEmptyOutputDirectory(evidenceDirectory);
  const deliveredArtifactsBefore = TYPES.map((type) => {
    const path = join(artifactDirectory, `${type}.html`);
    return { type, path, file: basename(path), before: fileReceipt(path, `Delivered ${type} artifact`) };
  });
  const browser = new visualCheck.ChromeVisualBrowser(chromePath);
  const captures = [];
  try {
    for (const type of TYPES) {
      const artifactPath = deliveredArtifactsBefore.find((artifact) => artifact.type === type).path;
      for (const { width, height } of VIEWPORTS) {
        for (const theme of THEMES) {
          const screenshotPath = join(evidenceDirectory, `${type}.${width}x${height}.${theme}.png`);
          const metrics = await browser.inspect({ artifactPath, width, height, theme, screenshotPath });
          if (metrics.innerWidth !== width || metrics.innerHeight !== height || metrics.resolvedTheme !== theme) {
            throw new Error(
              `Chrome resolved ${type} as ${metrics.innerWidth}x${metrics.innerHeight} ${metrics.resolvedTheme}; expected ${width}x${height} ${theme}`,
            );
          }
          const overflowX = metrics.scrollWidth > metrics.innerWidth;
          const overflowY = metrics.scrollHeight > metrics.innerHeight;
          captures.push({
            type,
            theme,
            ...pngReceipt(screenshotPath, width, height),
            scrollWidth: metrics.scrollWidth,
            scrollHeight: metrics.scrollHeight,
            overflowX,
            overflowY,
          });
        }
      }
    }
  } finally {
    await browser.close();
  }

  if (captures.length !== EXPECTED_CAPTURE_COUNT) {
    throw new Error(`Expected ${EXPECTED_CAPTURE_COUNT} screenshots, captured ${captures.length}`);
  }
  const deliveredArtifacts = deliveredArtifactsBefore.map((artifact) => {
    const after = fileReceipt(artifact.path, `Delivered ${artifact.type} artifact after capture`);
    return {
      type: artifact.type,
      file: artifact.file,
      bytesBefore: artifact.before.bytes,
      bytesAfter: after.bytes,
      beforeSha256: artifact.before.sha256,
      afterSha256: after.sha256,
      unchanged: artifact.before.bytes === after.bytes && artifact.before.sha256 === after.sha256,
    };
  });
  const artifactMutations = deliveredArtifacts.filter((artifact) => !artifact.unchanged);
  const containmentFailures = captures.filter((capture) => capture.overflowX || capture.overflowY);
  const receipt = {
    ok: containmentFailures.length === 0 && artifactMutations.length === 0,
    command: 'archify-ci-visual-evidence',
    visualReview: 'pending',
    runtime: { version: runtime.version, sha256: runtime.sha256 },
    matrix: { types: TYPES, viewports: VIEWPORTS, themes: THEMES },
    deliveredArtifacts,
    containment: {
      ok: containmentFailures.length === 0,
      failures: containmentFailures.map((capture) => ({
        type: capture.type,
        theme: capture.theme,
        viewport: { width: capture.width, height: capture.height },
        scroll: { width: capture.scrollWidth, height: capture.scrollHeight },
        overflowX: capture.overflowX,
        overflowY: capture.overflowY,
      })),
    },
    captures,
  };
  writeAtomic(join(evidenceDirectory, 'manifest.json'), `${JSON.stringify(receipt, null, 2)}\n`);
  writeAtomic(join(evidenceDirectory, 'index.html'), contactSheet(captures));
  const gateFailures = [];
  if (artifactMutations.length > 0) {
    gateFailures.push(`delivered artifacts changed during capture: ${artifactMutations.map((artifact) => artifact.type).join(', ')}`);
  }
  if (containmentFailures.length > 0) {
    const summary = containmentFailures.map((capture) => (
      `${capture.type}/${capture.theme}/${capture.width}x${capture.height} `
      + `(scroll ${capture.scrollWidth}x${capture.scrollHeight})`
    )).join(', ');
    gateFailures.push(`viewport containment failed: ${summary}`);
  }
  if (gateFailures.length > 0) {
    throw new Error(`Archify visual evidence failed: ${gateFailures.join('; ')}`);
  }
  process.stdout.write(`${JSON.stringify({ ok: true, screenshots: captures.length, evidenceDirectory }, null, 2)}\n`);
}

try {
  await main();
} catch (error) {
  fail(error?.stack || error?.message || String(error));
}
