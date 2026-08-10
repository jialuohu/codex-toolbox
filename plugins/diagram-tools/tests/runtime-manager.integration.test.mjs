import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import test from 'node:test';

const enabled = process.env.DIAGRAM_TOOLS_INTEGRATION === '1';
const manager = resolve('skills/pretty-mermaid/scripts/runtime-manager.mjs');
const cli = resolve('skills/pretty-mermaid/scripts/pretty-mermaid.mjs');

function runCli(root, args, extraEnv = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [cli, ...args], {
      env: { ...process.env, PRETTY_MERMAID_RUNTIME_ROOT: root, ...extraEnv },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));
    child.once('error', reject);
    child.once('close', (code) => resolvePromise({ code, stdout, stderr }));
  });
}

function runManager(root, extraEnv = {}, command = 'update') {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [manager, command], {
      env: { ...process.env, PRETTY_MERMAID_RUNTIME_ROOT: root, ...extraEnv },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));
    child.once('error', reject);
    child.once('close', (code) => {
      if (code !== 0) reject(new Error(stderr || stdout));
      else resolvePromise(JSON.parse(stdout));
    });
  });
}

test('promotes latest, is idempotent, and rolls back', { skip: !enabled, timeout: 60_000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'diagram-tools-integration-'));
  const first = await runManager(root);
  assert.equal(first.status, 'promoted');
  const unrelatedRelease = join(root, 'releases', 'user-not-owned');
  await mkdir(unrelatedRelease);
  await writeFile(join(unrelatedRelease, 'keep.txt'), 'preserve');
  const second = await runManager(root);
  assert.equal(second.status, 'current');
  assert.equal(await readFile(join(unrelatedRelease, 'keep.txt'), 'utf8'), 'preserve');

  const activePath = join(root, 'active.json');
  const active = JSON.parse(await readFile(activePath, 'utf8'));
  const interruptedManifest = `${activePath}.tmp-999-123456789`;
  await writeFile(interruptedManifest, '{"partial":');
  const interruptedCandidate = join(root, 'candidates', 'candidate-stale');
  await mkdir(interruptedCandidate, { recursive: true });
  await writeFile(join(interruptedCandidate, 'partial'), 'incomplete');
  const doctor = await runCli(root, ['doctor', '--json'], {
    npm_config_registry: 'http://127.0.0.1:9',
  });
  assert.equal(doctor.code, 0);
  assert.equal(JSON.parse(doctor.stdout).status, 'ready');

  const offlinePng = join(root, 'offline.png');
  const offlineRender = await runCli(
    root,
    [
      'render',
      '--input',
      resolve('skills/pretty-mermaid/assets/fixtures/sequence.mmd'),
      '--output',
      offlinePng,
      '--format',
      'png',
      '--theme',
      'tokyo-night',
    ],
    { npm_config_registry: 'http://127.0.0.1:9' },
  );
  assert.equal(offlineRender.code, 0, offlineRender.stderr);
  assert.deepEqual(
    (await readFile(offlinePng)).subarray(0, 8),
    Buffer.from('89504e470d0a1a0a', 'hex'),
  );

  const retained = await runManager(root, {
    PRETTY_MERMAID_TEST_CANDIDATE_VERSION: '99.99.98',
    PRETTY_MERMAID_TEST_CANDIDATE_INTEGRITY: `sha512-${Buffer.alloc(64, 1).toString('base64')}`,
  });
  assert.equal(retained.status, 'retained-active');
  assert.equal(JSON.parse(await readFile(activePath, 'utf8')).releaseId, active.releaseId);
  await assert.rejects(readFile(interruptedManifest), (error) => error.code === 'ENOENT');
  await assert.rejects(readFile(join(interruptedCandidate, 'partial')), (error) => error.code === 'ENOENT');

  const strictRejection = await runCli(root, ['update', '--strict'], {
    PRETTY_MERMAID_TEST_CANDIDATE_VERSION: 'not-a-stable-version',
    PRETTY_MERMAID_TEST_CANDIDATE_INTEGRITY: `sha512-${Buffer.alloc(64, 2).toString('base64')}`,
  });
  assert.equal(strictRejection.code, 5);
  assert.equal(JSON.parse(strictRejection.stdout).status, 'retained-active');
  assert.equal(JSON.parse(await readFile(activePath, 'utf8')).releaseId, active.releaseId);

  const rollbackReleaseId = 'rollback-contract-copy';
  await cp(
    join(root, 'releases', active.releaseId),
    join(root, 'releases', rollbackReleaseId),
    { recursive: true },
  );
  const previous = { ...active, releaseId: rollbackReleaseId };
  await writeFile(
    join(root, 'releases', rollbackReleaseId, 'runtime.json'),
    `${JSON.stringify(previous, null, 2)}\n`,
  );
  await writeFile(join(root, 'previous.json'), `${JSON.stringify(previous, null, 2)}\n`);
  const rolledBack = await runManager(root, {}, 'rollback');
  assert.equal(rolledBack.status, 'rolled-back');
  assert.equal(rolledBack.releaseId, rollbackReleaseId);
});

test('fresh install uses approved fallback after a rejected candidate', {
  skip: !enabled,
  timeout: 60_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'diagram-tools-fallback-'));
  const result = await runManager(root, {
    PRETTY_MERMAID_TEST_CANDIDATE_VERSION: 'not-a-stable-version',
    PRETTY_MERMAID_TEST_CANDIDATE_INTEGRITY: `sha512-${Buffer.alloc(64).toString('base64')}`,
  });
  assert.equal(result.status, 'fallback-installed');
  assert.equal(result.rejectedVersion, null);
  const active = JSON.parse(await readFile(join(root, 'active.json'), 'utf8'));
  assert.equal(active.channel, 'approved-fallback');
  assert.notEqual(active.version, 'not-a-stable-version');
});

test('a live updater lock is never stolen, even when its timestamp is old', {
  skip: !enabled,
  timeout: 10_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'diagram-tools-lock-'));
  await writeFile(
    join(root, 'update.lock'),
    `${JSON.stringify({ token: 'test', pid: process.pid, acquiredAt: '2000-01-01T00:00:00.000Z' })}\n`,
  );
  await assert.rejects(runManager(root), /already running under PID/);
});

test('public rollback command uses the documented failure exit code', {
  skip: !enabled,
  timeout: 10_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'diagram-tools-no-rollback-'));
  const result = await runCli(root, ['rollback']);
  assert.equal(result.code, 5);
  assert.match(result.stderr, /No previous Pretty Mermaid runtime/);
});
