import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { lstat, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const enabled = process.env.DIAGRAM_TOOLS_ARCHIFY_INTEGRATION === '1';
const testDirectory = dirname(fileURLToPath(import.meta.url));
const pluginDirectory = resolve(testDirectory, '..');
const setup = resolve(pluginDirectory, '..', '..', 'scripts', 'setup-archify-tools.sh');

function run(command, args, env) {
  return new Promise((resolvePromise, reject) => {
    const startedAt = performance.now();
    const child = spawn(command, args, { env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));
    child.once('error', reject);
    child.once('close', (code) => resolvePromise({
      code,
      stdout,
      stderr,
      durationMs: performance.now() - startedAt,
    }));
  });
}

function fetchCapableOrigins(html) {
  const origins = new Set();
  const patterns = [
    /\b(?:href|src|action)\s*=\s*["'](https?:\/\/[^"']+)/giu,
    /\b(?:fetch|importScripts)\s*\(\s*["'](https?:\/\/[^"']+)/giu,
    /@import\s+(?:url\(\s*)?["']?(https?:\/\/[^"')\s;]+)/giu,
    /\burl\(\s*["']?(https?:\/\/[^"')\s]+)/giu,
  ];
  for (const pattern of patterns) {
    for (const match of html.matchAll(pattern)) origins.add(new URL(match[1]).origin);
  }
  return [...origins].sort();
}

test('pinned release installs, checks offline, remains idempotent, and renders', {
  skip: !enabled,
  timeout: 120_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-real-runtime-'));
  const bin = await mkdtemp(join(tmpdir(), 'archify-real-bin-'));
  const env = {
    ARCHIFY_RUNTIME_ROOT: root,
    CODEX_LOCAL_BIN_DIR: bin,
    ...(process.env.ARCHIFY_TEST_ARCHIVE_PATH
      ? { ARCHIFY_TEST_ARCHIVE_PATH: process.env.ARCHIFY_TEST_ARCHIVE_PATH }
      : {}),
  };
  const install = await run('bash', [setup, '--install'], env);
  assert.equal(install.code, 0, install.stderr);
  const launcher = join(bin, 'archify');
  assert.equal((await lstat(launcher)).isSymbolicLink(), true);
  const firstReceipt = await readFile(join(root, 'state.json'), 'utf8');

  const preload = join(root, 'block-network.cjs');
  const cache = await mkdtemp(join(tmpdir(), 'archify-update-cache-'));
  await writeFile(preload, `
const blocked = () => { throw new Error('network disabled by Archify integration test'); };
Object.defineProperty(globalThis, 'fetch', { value: blocked, configurable: false, writable: false });
for (const moduleName of ['node:http', 'node:https']) {
  const client = require(moduleName);
  client.request = blocked;
  client.get = blocked;
}
`);
  const blockedEnv = {
    ...env,
    NODE_OPTIONS: `${process.env.NODE_OPTIONS ?? ''} --require=${preload}`.trim(),
    XDG_CACHE_HOME: cache,
  };

  const check = await run('bash', [setup, '--check'], blockedEnv);
  assert.equal(check.code, 0, check.stderr);
  const repeat = await run('bash', [setup, '--install'], env);
  assert.equal(repeat.code, 0, repeat.stderr);
  assert.equal(await readFile(join(root, 'state.json'), 'utf8'), firstReceipt);

  const infoResult = await run(launcher, ['runtime-info', '--json'], blockedEnv);
  assert.equal(infoResult.code, 0, infoResult.stderr);
  const info = JSON.parse(infoResult.stdout);
  assert.equal(info.version, '2.16.0');
  assert.equal(info.sha256, '4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46');
  const output = join(root, 'integration.architecture.html');
  const delivered = await run(launcher, [
    'deliver',
    'architecture',
    info.examplePaths.architecture,
    output,
    '--json',
    '--quality',
    'showcase',
  ], blockedEnv);
  assert.equal(delivered.code, 0, delivered.stderr);
  assert.equal(JSON.parse(delivered.stdout).ok, true);
  assert.equal((await lstat(output)).isFile(), true);

  const disabledUpdateCheck = await run(process.execPath, [info.updateCheckerPath], {
    ...blockedEnv,
    ARCHIFY_UPDATE_CHECK_DISABLED: '1',
  });
  assert.equal(disabledUpdateCheck.code, 0, disabledUpdateCheck.stderr);
  assert.equal(JSON.parse(disabledUpdateCheck.stdout).reason, 'disabled');

  const updateDriver = join(root, 'check-update-offline.mjs');
  await writeFile(updateDriver, `
import { pathToFileURL } from 'node:url';
const updateChecker = await import(pathToFileURL(process.argv[2]).href);
const result = await updateChecker.checkForUpdate({
  cacheDirectory: process.argv[3],
  timeoutMs: 100,
});
process.stdout.write(JSON.stringify(result) + '\\n');
`);
  const updateCheck = await run(
    process.execPath,
    [updateDriver, info.updateCheckerPath, cache],
    blockedEnv,
  );
  assert.equal(updateCheck.code, 0, updateCheck.stderr);
  assert.equal(updateCheck.stderr, '');
  assert.equal(JSON.parse(updateCheck.stdout).status, 'silent');
  assert.ok(updateCheck.durationMs < 5_000, `offline update check took ${updateCheck.durationMs}ms`);

  const discoveredOrigins = fetchCapableOrigins(await readFile(output, 'utf8'));
  assert.deepEqual(
    discoveredOrigins,
    ['https://fonts.googleapis.com', 'https://fonts.gstatic.com'],
    `discovered fetch-capable origins: ${discoveredOrigins.join(', ')}`,
  );

  const brokenInput = join(root, 'broken.architecture.json');
  await writeFile(brokenInput, '{"schema_version":');
  const malformed = await run(launcher, [
    'validate', 'architecture', brokenInput, '--json', '--quality', 'showcase',
  ], blockedEnv);
  assert.notEqual(malformed.code, 0);
  const malformedReceipt = JSON.parse(malformed.stdout);
  assert.equal(malformedReceipt.ok, false);
  assert.equal(malformedReceipt.command, 'validate');

  const collisionInput = join(root, 'collision.architecture.json');
  const collisionSpec = JSON.parse(await readFile(info.examplePaths.architecture, 'utf8'));
  collisionSpec.components[1].pos = [...collisionSpec.components[0].pos];
  await writeFile(collisionInput, `${JSON.stringify(collisionSpec, null, 2)}\n`);
  const protectedOutput = join(root, 'protected.architecture.html');
  const trustedArtifact = '<!doctype html><title>trusted artifact</title>\n';
  await writeFile(protectedOutput, trustedArtifact);
  const collision = await run(launcher, [
    'deliver',
    'architecture',
    collisionInput,
    protectedOutput,
    '--json',
    '--quality',
    'showcase',
  ], blockedEnv);
  assert.notEqual(collision.code, 0);
  assert.equal(JSON.parse(collision.stdout).ok, false);
  assert.equal(await readFile(protectedOutput, 'utf8'), trustedArtifact);
});
