import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { crc32, extractZipArchive, inspectZipArchive } from '../skills/archify/scripts/lib/archive.mjs';
import {
  assertArchiveDownloadUrl,
  installRuntime,
  rollbackRuntime,
  validateRuntimeState,
} from '../skills/archify/scripts/lib/runtime-manager.mjs';
import { validateReleasePin } from '../skills/archify/scripts/lib/release.mjs';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const pluginDirectory = resolve(testDirectory, '..');
const wrapper = join(pluginDirectory, 'skills', 'archify', 'scripts', 'archify.mjs');
const setup = resolve(pluginDirectory, '..', '..', 'scripts', 'setup-archify-tools.sh');

function zipArchive(entries) {
  const localRecords = [];
  const centralRecords = [];
  let localOffset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8');
    const contents = Buffer.from(entry.contents ?? '');
    const flags = entry.flags ?? 0x0800;
    const checksum = entry.crcOverride ?? crc32(contents);
    const mode = entry.mode ?? 0o100644;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(flags, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(contents.length, 18);
    local.writeUInt32LE(contents.length, 22);
    local.writeUInt16LE(name.length, 26);
    const localRecord = Buffer.concat([local, name, contents]);
    localRecords.push(localRecord);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE((3 << 8) | 20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(flags, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(contents.length, 20);
    central.writeUInt32LE(contents.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE((mode << 16) >>> 0, 38);
    central.writeUInt32LE(localOffset, 42);
    centralRecords.push(Buffer.concat([central, name]));
    localOffset += localRecord.length;
  }
  const centralDirectory = Buffer.concat(centralRecords);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(localOffset, 16);
  return Buffer.concat([...localRecords, centralDirectory, end]);
}

function fakeCli({ failDoctor = false } = {}) {
  return `#!/usr/bin/env node
import { writeFileSync } from 'node:fs';
const [command, type, input, output] = process.argv.slice(2);
if (command === 'doctor') {
  ${failDoctor ? "process.stderr.write('doctor failed\\n'); process.exit(1);" : "process.stdout.write('Archify doctor\\n\\nArchify is ready.\\n');"}
} else if (command === 'validate') {
  process.stdout.write(JSON.stringify({schemaVersion:1,ok:true,command,type,input,checks:[{name:'fake',ok:true}]}) + '\\n');
} else if (command === 'deliver') {
  writeFileSync(output, '<!doctype html><title>' + type + '</title>');
  process.stdout.write(JSON.stringify({schemaVersion:1,ok:true,command,type,input,output}) + '\\n');
} else {
  process.stdout.write(JSON.stringify({ok:true,command,type,input}) + '\\n');
}
`;
}

function fakeRelease(version, options = {}) {
  const updateManifestUrl = 'https://tt-a1i.github.io/archify/skill-updates/archify/stable.json';
  const examples = {
    architecture: 'web-app.architecture.json',
    workflow: 'agent-tool-call.workflow.json',
    sequence: 'async-job-roundtrip.sequence.json',
    dataflow: 'product-analytics.dataflow.json',
    lifecycle: 'agent-run.lifecycle.json',
  };
  const entries = [
    { name: 'archify/LICENSE', contents: 'MIT License\nCopyright (c) 2026 tt-a1i (Archify)\nCopyright (c) 2025 Cocoon AI\n' },
    { name: 'archify/SKILL.md', contents: '# Archify\n' },
    { name: 'archify/bin/archify.mjs', contents: fakeCli(options) },
    { name: 'archify/package.json', contents: JSON.stringify({ name: 'archify', version, private: true, type: 'module', license: 'MIT' }) },
    { name: 'archify/schemas/common.schema.json', contents: '{}' },
    { name: 'archify/scripts/check-update.mjs', contents: 'export default true;\n' },
    { name: 'archify/skill-release.json', contents: JSON.stringify({ schemaVersion: 1, skillId: 'archify', channel: 'stable', version, updateManifestUrl }) },
  ];
  for (const [type, example] of Object.entries(examples)) {
    entries.push({ name: `archify/schemas/${type}.schema.json`, contents: '{}' });
    entries.push({ name: `archify/examples/${example}`, contents: JSON.stringify({ schemaVersion: type === 'workflow' ? 2 : 1, type }) });
  }
  const archive = zipArchive(entries);
  const sha256 = createHash('sha256').update(archive).digest('hex');
  return {
    archive,
    pin: {
      schemaVersion: 1,
      name: 'archify',
      version,
      tag: `v${version}`,
      releaseId: `archify-${version}-${sha256.slice(0, 12)}`,
      archive: {
        name: 'archify.zip',
        url: `https://github.com/tt-a1i/archify/releases/download/v${version}/archify.zip`,
        bytes: archive.length,
        sha256,
        maxBytes: 1024 * 1024,
        maxExpandedBytes: 4 * 1024 * 1024,
        maxEntries: 128,
      },
      updateManifestUrl,
    },
  };
}

async function writeArchive(directory, name, archive) {
  const path = join(directory, name);
  await writeFile(path, archive);
  return path;
}

function run(command, args, env = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      env: { ...process.env, ...env },
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

test('ZIP inspection accepts a regular package and rejects unsafe entries', async (t) => {
  const limits = { maxBytes: 1024 * 1024, maxExpandedBytes: 1024 * 1024, maxEntries: 20 };
  const valid = zipArchive([{ name: 'archify/bin/archify.mjs', contents: 'ok' }]);
  assert.equal(inspectZipArchive(valid, limits).entries.length, 1);
  const destination = await mkdtemp(join(tmpdir(), 'archify-zip-'));
  assert.equal((await extractZipArchive(valid, destination, limits)).fileCount, 1);

  const cases = [
    ['traversal', { name: 'archify/../escape', contents: 'x' }, /unsafe path segment/],
    ['absolute', { name: '/archify/escape', contents: 'x' }, /absolute path/],
    ['drive absolute', { name: 'C:/archify/escape', contents: 'x' }, /absolute path/],
    ['backslash', { name: 'archify\\escape', contents: 'x' }, /backslash/],
    ['symlink', { name: 'archify/link', contents: 'target', mode: 0o120777 }, /not a regular file/],
    ['encrypted', { name: 'archify/secret', contents: 'x', flags: 0x0801 }, /encrypted/],
  ];
  for (const [name, entry, pattern] of cases) {
    await t.test(name, () => assert.throws(() => inspectZipArchive(zipArchive([entry]), limits), pattern));
  }
  assert.throws(
    () => inspectZipArchive(zipArchive([
      { name: 'archify/File', contents: 'a' },
      { name: 'archify/file', contents: 'b' },
    ]), limits),
    /case-colliding/,
  );
  assert.throws(
    () => inspectZipArchive(valid, { ...limits, maxBytes: valid.length - 1 }),
    /compressed-size limit/,
  );
  assert.throws(
    () => inspectZipArchive(valid, { ...limits, maxExpandedBytes: 1 }),
    /too large|expansion limit/,
  );
  const badCrc = zipArchive([{ name: 'archify/file', contents: 'x', crcOverride: 0 }]);
  await assert.rejects(
    extractZipArchive(badCrc, await mkdtemp(join(tmpdir(), 'archify-crc-')), limits),
    /CRC is wrong/,
  );
});

test('release downloads permit only bounded GitHub HTTPS hosts', () => {
  assert.equal(assertArchiveDownloadUrl('https://github.com/example').hostname, 'github.com');
  assert.equal(
    assertArchiveDownloadUrl('https://release-assets.githubusercontent.com/example').hostname,
    'release-assets.githubusercontent.com',
  );
  for (const url of [
    'http://github.com/example',
    'https://github.com.evil.invalid/example',
    'https://objects.githubusercontent.com/example',
    'https://user@github.com/example',
    'https://github.com:444/example',
  ]) assert.throws(() => assertArchiveDownloadUrl(url), /not allowed/);
});

test('release pin binds the archive and stable update URLs to the exact release', () => {
  const release = fakeRelease('1.3.0');
  assert.equal(validateReleasePin(release.pin), release.pin);
  assert.throws(
    () => validateReleasePin({
      ...release.pin,
      archive: { ...release.pin.archive, url: `${release.pin.archive.url}?unexpected=1` },
    }),
    /invalid archive contract/,
  );
  assert.throws(
    () => validateReleasePin({
      ...release.pin,
      updateManifestUrl: 'https://tt-a1i.github.io/archify/skill-updates/archify/beta.json',
    }),
    /invalid update manifest URL/,
  );
});

test('runtime install is idempotent, rolls back, and retains the last good release', async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-runtime-'));
  const sources = await mkdtemp(join(tmpdir(), 'archify-sources-'));
  const first = fakeRelease('1.0.0');
  const second = fakeRelease('1.0.1');
  const broken = fakeRelease('1.0.2', { failDoctor: true });
  const firstPath = await writeArchive(sources, 'first.zip', first.archive);
  const secondPath = await writeArchive(sources, 'second.zip', second.archive);
  const brokenPath = await writeArchive(sources, 'broken.zip', broken.archive);

  const installed = await installRuntime({ root, pin: first.pin, archivePath: firstPath });
  assert.equal(installed.status, 'installed');
  const statePath = join(root, 'state.json');
  const firstState = await readFile(statePath, 'utf8');
  const interrupted = join(root, 'staging', 'candidate-interrupted');
  const interruptedReceipt = join(
    root,
    'state.json.tmp-999-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  );
  await mkdir(interrupted, { recursive: true });
  await writeFile(join(interrupted, 'partial'), 'partial');
  await writeFile(interruptedReceipt, '{"partial":');
  const current = await installRuntime({ root, pin: first.pin, archivePath: join(sources, 'missing.zip') });
  assert.equal(current.status, 'current');
  assert.equal(await readFile(statePath, 'utf8'), firstState);
  await assert.rejects(access(interrupted), (error) => error.code === 'ENOENT');
  await assert.rejects(access(interruptedReceipt), (error) => error.code === 'ENOENT');

  await assert.rejects(
    installRuntime({
      root,
      pin: second.pin,
      archivePath: secondPath,
      beforeStateRename: async () => { throw new Error('injected state rename interruption'); },
    }),
    (error) => error.result?.status === 'retained-active',
  );
  assert.equal(await readFile(statePath, 'utf8'), firstState);
  assert.equal(
    (await readdir(root)).some((name) => name.startsWith('state.json.tmp-')),
    true,
  );
  await installRuntime({ root, pin: first.pin, archivePath: join(sources, 'missing.zip') });
  assert.equal(
    (await readdir(root)).some((name) => name.startsWith('state.json.tmp-')),
    false,
  );

  const upgraded = await installRuntime({ root, pin: second.pin, archivePath: secondPath });
  assert.equal(upgraded.previousReleaseId, first.pin.releaseId);
  const secondState = await readFile(statePath, 'utf8');
  const upgradedState = JSON.parse(secondState);
  assert.equal(upgradedState.generation, 2);
  assert.equal(upgradedState.active.releaseId, second.pin.releaseId);
  assert.equal(upgradedState.previous.releaseId, first.pin.releaseId);
  await assert.rejects(
    installRuntime({ root, pin: broken.pin, archivePath: brokenPath }),
    (error) => error.result?.status === 'retained-active',
  );
  assert.equal(await readFile(statePath, 'utf8'), secondState);

  const rolledBack = await rollbackRuntime({ root });
  assert.equal(rolledBack.releaseId, first.pin.releaseId);
  const rolledBackState = JSON.parse(await readFile(statePath, 'utf8'));
  assert.equal(rolledBackState.generation, 3);
  assert.equal(rolledBackState.active.releaseId, first.pin.releaseId);
  assert.equal(rolledBackState.previous.releaseId, second.pin.releaseId);
});

test('digest mismatch fails before promotion and preserves the active receipt', async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-digest-'));
  const sources = await mkdtemp(join(tmpdir(), 'archify-digest-source-'));
  const good = fakeRelease('1.1.0');
  const next = fakeRelease('1.1.1');
  const goodPath = await writeArchive(sources, 'good.zip', good.archive);
  const changed = Buffer.from(next.archive);
  changed[10] ^= 1;
  const changedPath = await writeArchive(sources, 'changed.zip', changed);
  await installRuntime({ root, pin: good.pin, archivePath: goodPath });
  const receipt = await readFile(join(root, 'state.json'), 'utf8');
  await assert.rejects(
    installRuntime({ root, pin: next.pin, archivePath: changedPath }),
    (error) => error.result?.error?.message === 'Archify archive SHA-256 mismatch',
  );
  assert.equal(await readFile(join(root, 'state.json'), 'utf8'), receipt);
});

test('corrupt combined runtime state is rejected without replacement', async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-corrupt-state-'));
  const sources = await mkdtemp(join(tmpdir(), 'archify-corrupt-state-source-'));
  const release = fakeRelease('1.1.2');
  const archivePath = await writeArchive(sources, 'release.zip', release.archive);
  await installRuntime({ root, pin: release.pin, archivePath });
  const validState = JSON.parse(await readFile(join(root, 'state.json'), 'utf8'));
  assert.throws(
    () => validateRuntimeState({
      ...validState,
      active: {
        ...validState.active,
        releaseId: `archify-${validState.active.version}-000000000000`,
      },
    }),
    /active receipt is invalid/,
  );
  const corrupt = '{"schemaVersion":1,"generation":0}\n';
  await writeFile(join(root, 'state.json'), corrupt);
  await assert.rejects(
    installRuntime({ root, pin: release.pin, archivePath }),
    /Archify runtime state is invalid/,
  );
  assert.equal(await readFile(join(root, 'state.json'), 'utf8'), corrupt);
});

test('wrapper reports path-complete runtime info and passes upstream commands through', async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-wrapper-'));
  const sources = await mkdtemp(join(tmpdir(), 'archify-wrapper-source-'));
  const release = fakeRelease('1.2.0');
  const archivePath = await writeArchive(sources, 'release.zip', release.archive);
  await installRuntime({ root, pin: release.pin, archivePath });
  const infoResult = await run(process.execPath, [wrapper, 'runtime-info', '--json'], {
    ARCHIFY_RUNTIME_ROOT: root,
  });
  assert.equal(infoResult.code, 0, infoResult.stderr);
  const info = JSON.parse(infoResult.stdout);
  assert.deepEqual(Object.keys(info.typeSchemaPaths), ['architecture', 'workflow', 'sequence', 'dataflow', 'lifecycle']);
  assert.deepEqual(Object.keys(info.examplePaths), ['architecture', 'workflow', 'sequence', 'dataflow', 'lifecycle']);
  for (const path of [info.cliPath, info.skillPath, info.commonSchemaPath, info.updateCheckerPath]) {
    assert.equal(path.startsWith(info.releaseDirectory), true);
  }
  const validate = await run(process.execPath, [wrapper, 'validate', 'architecture', info.examplePaths.architecture, '--json'], {
    ARCHIFY_RUNTIME_ROOT: root,
  });
  assert.equal(validate.code, 0, validate.stderr);
  assert.equal(JSON.parse(validate.stdout).command, 'validate');
  const usage = await run(process.execPath, [wrapper, 'runtime-info'], { ARCHIFY_RUNTIME_ROOT: root });
  assert.equal(usage.code, 2);
});

test('setup refuses a non-owned launcher before changing the runtime', async () => {
  const root = await mkdtemp(join(tmpdir(), 'archify-setup-root-'));
  const bin = await mkdtemp(join(tmpdir(), 'archify-setup-bin-'));
  await writeFile(join(bin, 'archify'), 'not owned');
  const result = await run('bash', [setup, '--install'], {
    ARCHIFY_RUNTIME_ROOT: root,
    CODEX_LOCAL_BIN_DIR: bin,
  });
  assert.equal(result.code, 3);
  assert.match(result.stderr, /Refusing to replace non-symlink launcher/);
  await assert.rejects(access(join(root, 'state.json')), (error) => error.code === 'ENOENT');

  const foreignRoot = await mkdtemp(join(tmpdir(), 'archify-setup-foreign-root-'));
  const foreignBin = await mkdtemp(join(tmpdir(), 'archify-setup-foreign-bin-'));
  await symlink('/not/owned/by/diagram-tools', join(foreignBin, 'archify'));
  const foreignResult = await run('bash', [setup, '--install'], {
    ARCHIFY_RUNTIME_ROOT: foreignRoot,
    CODEX_LOCAL_BIN_DIR: foreignBin,
  });
  assert.equal(foreignResult.code, 3);
  assert.match(foreignResult.stderr, /launcher not owned by diagram-tools/);
  await assert.rejects(access(join(foreignRoot, 'state.json')), (error) => error.code === 'ENOENT');

  const priorRoot = await mkdtemp(join(tmpdir(), 'archify-setup-prior-root-'));
  const priorBin = await mkdtemp(join(tmpdir(), 'archify-setup-prior-bin-'));
  await symlink(
    '/prior/checkout/plugins/diagram-tools/skills/archify/scripts/archify.mjs',
    join(priorBin, 'archify'),
  );
  const priorResult = await run('bash', [setup, '--check'], {
    ARCHIFY_RUNTIME_ROOT: priorRoot,
    CODEX_LOCAL_BIN_DIR: priorBin,
  });
  assert.equal(priorResult.code, 3);
  assert.match(priorResult.stderr, /launcher is not installed/);
  assert.doesNotMatch(priorResult.stderr, /launcher not owned/);
});
