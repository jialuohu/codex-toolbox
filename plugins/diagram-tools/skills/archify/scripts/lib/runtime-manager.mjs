import { createHash, randomUUID } from 'node:crypto';
import {
  lstat,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { join } from 'node:path';
import { extractZipArchive } from './archive.mjs';
import { readJson, safeError, writeJsonAtomic } from './io.mjs';
import { releasePinPath, runtimePaths } from './paths.mjs';
import {
  resolveRelease,
  runDoctor,
  smokeRelease,
  validateReleasePin,
  verifyPackagedRelease,
} from './release.mjs';

const MIN_NODE_MAJOR = 20;
const ALLOWED_DOWNLOAD_HOSTS = new Set(['github.com', 'release-assets.githubusercontent.com']);
const MAX_DOWNLOAD_REDIRECTS = 3;

function assertNodeVersion() {
  const major = Number(process.versions.node.split('.')[0]);
  if (!Number.isInteger(major) || major < MIN_NODE_MAJOR) {
    throw new Error(`Archify setup requires Node.js ${MIN_NODE_MAJOR} or newer`);
  }
}

function archiveSha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function ensureManagedDirectory(path, label) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const metadata = await lstat(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error(`${label} is not a regular directory: ${path}`);
  }
}

async function readManagedJsonOrNull(path, label) {
  try {
    const metadata = await lstat(path);
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new Error(`${label} is not a regular file: ${path}`);
    }
    return await readJson(path);
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

export async function loadReleasePin(path = releasePinPath) {
  return validateReleasePin(await readJson(path));
}

function validTimestamp(value) {
  if (typeof value !== 'string') return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString() === value;
}

function validateRuntimeReceipt(receipt, label) {
  if (
    !receipt ||
    receipt.schemaVersion !== 1 ||
    typeof receipt.releaseId !== 'string' ||
    !/^archify-\d+\.\d+\.\d+-[0-9a-f]{12}$/.test(receipt.releaseId) ||
    typeof receipt.version !== 'string' ||
    !/^\d+\.\d+\.\d+$/.test(receipt.version) ||
    !/^[0-9a-f]{64}$/.test(receipt.sha256) ||
    receipt.releaseId !== `archify-${receipt.version}-${receipt.sha256.slice(0, 12)}` ||
    !/^[0-9a-f]{64}$/.test(receipt.treeSha256) ||
    !validTimestamp(receipt.activatedAt) ||
    Object.keys(receipt).some((key) => ![
      'schemaVersion', 'releaseId', 'version', 'sha256', 'treeSha256', 'activatedAt',
    ].includes(key))
  ) {
    throw new Error(`${label} is invalid`);
  }
  return receipt;
}

export function validateRuntimeState(state) {
  if (
    !state ||
    state.schemaVersion !== 1 ||
    !Number.isSafeInteger(state.generation) ||
    state.generation < 1 ||
    !validTimestamp(state.updatedAt) ||
    Object.keys(state).some((key) => ![
      'schemaVersion', 'generation', 'active', 'previous', 'updatedAt',
    ].includes(key))
  ) {
    throw new Error('Archify runtime state is invalid');
  }
  validateRuntimeReceipt(state.active, 'Archify active receipt');
  if (state.previous !== null) {
    validateRuntimeReceipt(state.previous, 'Archify previous receipt');
    if (state.previous.releaseId === state.active.releaseId) {
      throw new Error('Archify active and previous receipts must identify different releases');
    }
  }
  return state;
}

async function readRuntimeStateOrNull(paths) {
  const state = await readManagedJsonOrNull(paths.state, 'Archify runtime state');
  return state === null ? null : validateRuntimeState(state);
}

async function readRuntimeState(paths) {
  const state = await readRuntimeStateOrNull(paths);
  if (!state) throw Object.assign(
    new Error(`Archify runtime state is not installed: ${paths.state}`),
    { code: 'ENOENT' },
  );
  return state;
}

async function writeRuntimeState(paths, state, beforeRename) {
  validateRuntimeState(state);
  await readManagedJsonOrNull(paths.state, 'Archify runtime state');
  await writeJsonAtomic(paths.state, state, { beforeRename });
}

async function acquireLock(paths) {
  await ensureManagedDirectory(paths.root, 'Archify runtime root');
  const token = randomUUID();
  const create = async () => {
    const handle = await open(paths.lock, 'wx', 0o600);
    await handle.writeFile(`${JSON.stringify({ token, pid: process.pid })}\n`);
    await handle.close();
  };
  try {
    await create();
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error;
    const current = await readManagedJsonOrNull(paths.lock, 'Archify install lock');
    let alive = false;
    if (Number.isInteger(current?.pid)) {
      try {
        process.kill(current.pid, 0);
        alive = true;
      } catch (probeError) {
        if (probeError?.code === 'EPERM') alive = true;
      }
    }
    if (alive) throw new Error(`Archify runtime install is already running under PID ${current.pid}`);
    const lockMetadata = await lstat(paths.lock);
    if (!lockMetadata.isFile() || lockMetadata.isSymbolicLink()) {
      throw new Error('Refusing to replace an unsafe Archify install lock');
    }
    await unlink(paths.lock);
    await create();
  }
  return token;
}

async function releaseLock(paths, token) {
  try {
    const current = await readManagedJsonOrNull(paths.lock, 'Archify install lock');
    if (current?.token === token) await unlink(paths.lock);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

async function cleanupInterruptedStaging(paths) {
  await ensureManagedDirectory(paths.staging, 'Archify staging directory');
  const entries = await readdir(paths.staging, { withFileTypes: true });
  for (const entry of entries) {
    if (!/^(?:candidate|smoke)-[0-9A-Za-z_-]+$/.test(entry.name)) continue;
    if (!entry.isDirectory() || entry.isSymbolicLink()) {
      throw new Error(`Refusing to remove unsafe Archify staging entry: ${entry.name}`);
    }
    await rm(join(paths.staging, entry.name), { recursive: true, force: false });
  }
  const rootEntries = await readdir(paths.root, { withFileTypes: true });
  for (const entry of rootEntries) {
    if (!/^state\.json\.tmp-\d+-[0-9a-f-]+$/.test(entry.name)) continue;
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error(`Refusing to remove unsafe Archify temporary receipt: ${entry.name}`);
    }
    await unlink(join(paths.root, entry.name));
  }
}

async function readArchiveFromFile(path, maxBytes) {
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error('Archify test archive path must be a regular file');
  }
  if (metadata.size > maxBytes) throw new Error('Archify archive exceeds the compressed-size limit');
  return readFile(path);
}

export function assertArchiveDownloadUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error('Archify download URL is invalid');
  }
  if (
    url.protocol !== 'https:' ||
    (url.port && url.port !== '443') ||
    url.username ||
    url.password ||
    !ALLOWED_DOWNLOAD_HOSTS.has(url.hostname)
  ) {
    throw new Error(`Archify download redirect is not allowed: ${url.origin}`);
  }
  return url;
}

async function downloadArchive(url, maxBytes) {
  let current = assertArchiveDownloadUrl(url);
  let response;
  for (let redirects = 0; redirects <= MAX_DOWNLOAD_REDIRECTS; redirects += 1) {
    response = await fetch(current, {
      redirect: 'manual',
      headers: { 'user-agent': 'codex-toolbox-archify-runtime-manager/1' },
      signal: AbortSignal.timeout(60_000),
    });
    if (![301, 302, 303, 307, 308].includes(response.status)) break;
    if (redirects === MAX_DOWNLOAD_REDIRECTS) {
      await response.body?.cancel();
      throw new Error('Archify download exceeded the redirect limit');
    }
    const location = response.headers.get('location');
    await response.body?.cancel();
    if (!location) throw new Error('Archify download redirect omitted its destination');
    current = assertArchiveDownloadUrl(new URL(location, current).href);
  }
  if (!response.ok || !response.body) throw new Error(`Archify download failed with HTTP ${response.status}`);
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) {
    await response.body.cancel();
    throw new Error('Archify archive exceeds the compressed-size limit');
  }
  const chunks = [];
  let bytes = 0;
  for await (const chunk of response.body) {
    bytes += chunk.length;
    if (bytes > maxBytes) {
      await response.body.cancel();
      throw new Error('Archify archive exceeds the compressed-size limit');
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks, bytes);
}

async function obtainArchive(pin, archivePath) {
  const buffer = archivePath
    ? await readArchiveFromFile(archivePath, pin.archive.maxBytes)
    : await downloadArchive(pin.archive.url, pin.archive.maxBytes);
  if (buffer.length !== pin.archive.bytes) {
    throw new Error(`Archify archive byte count mismatch: expected ${pin.archive.bytes}, received ${buffer.length}`);
  }
  const digest = archiveSha256(buffer);
  if (digest !== pin.archive.sha256) throw new Error('Archify archive SHA-256 mismatch');
  return buffer;
}

function runtimeReceipt(manifest) {
  return {
    schemaVersion: 1,
    releaseId: manifest.releaseId,
    version: manifest.version,
    sha256: manifest.sha256,
    treeSha256: manifest.treeSha256,
    activatedAt: new Date().toISOString(),
  };
}

async function stageRelease(paths, pin, archivePath) {
  await ensureManagedDirectory(paths.releases, 'Archify releases directory');
  await ensureManagedDirectory(paths.staging, 'Archify staging directory');
  const candidate = await mkdtemp(join(paths.staging, 'candidate-'));
  const smokeDirectory = await mkdtemp(join(paths.staging, 'smoke-'));
  try {
    const archive = await obtainArchive(pin, archivePath);
    const extracted = await extractZipArchive(archive, candidate, pin.archive);
    await verifyPackagedRelease(candidate, pin);
    const smoke = await smokeRelease(candidate, smokeDirectory);
    const manifest = {
      schemaVersion: 1,
      releaseId: pin.releaseId,
      version: pin.version,
      tag: pin.tag,
      sourceUrl: pin.archive.url,
      archiveName: pin.archive.name,
      sha256: pin.archive.sha256,
      archiveBytes: pin.archive.bytes,
      fileCount: extracted.fileCount,
      expandedBytes: extracted.expandedBytes,
      treeSha256: extracted.treeSha256,
      updateManifestUrl: pin.updateManifestUrl,
      installedAt: new Date().toISOString(),
      conformance: smoke,
    };
    await writeFile(join(candidate, 'runtime.json'), `${JSON.stringify(manifest, null, 2)}\n`, {
      mode: 0o600,
      flag: 'wx',
    });
    return { candidate, manifest };
  } catch (error) {
    await rm(candidate, { recursive: true, force: true });
    throw error;
  } finally {
    await rm(smokeDirectory, { recursive: true, force: true });
  }
}

async function promote(paths, staged, currentState, beforeStateRename) {
  const destination = join(paths.releases, staged.manifest.releaseId);
  let releaseDirectory = destination;
  try {
    const existing = await lstat(destination);
    if (!existing.isDirectory() || existing.isSymbolicLink()) {
      throw new Error(`Refusing to replace unsafe Archify release path: ${destination}`);
    }
    const existingManifest = await readManagedJsonOrNull(
      join(destination, 'runtime.json'),
      'Archify immutable release receipt',
    );
    if (
      existingManifest?.releaseId !== staged.manifest.releaseId ||
      existingManifest.sha256 !== staged.manifest.sha256 ||
      existingManifest.treeSha256 !== staged.manifest.treeSha256
    ) {
      throw new Error(`Refusing to replace Archify release not owned by diagram-tools: ${destination}`);
    }
    await resolveRelease(runtimeReceipt(existingManifest), paths.root, { verifyTree: true, doctor: true });
    await rm(staged.candidate, { recursive: true, force: true });
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    await rename(staged.candidate, destination);
  }

  const next = runtimeReceipt(staged.manifest);
  const state = {
    schemaVersion: 1,
    generation: (currentState?.generation ?? 0) + 1,
    active: next,
    previous: currentState?.active ?? null,
    updatedAt: new Date().toISOString(),
  };
  await writeRuntimeState(paths, state, beforeStateRename);
  return { receipt: next, releaseDirectory, state };
}

async function recordFailure(paths, pin, error, active) {
  await ensureManagedDirectory(paths.reports, 'Archify reports directory');
  await writeJsonAtomic(join(paths.reports, 'latest-failure.json'), {
    attemptedAt: new Date().toISOString(),
    releaseId: pin.releaseId,
    version: pin.version,
    activeReleaseId: active?.receipt?.releaseId ?? null,
    error: safeError(error),
  });
}

export async function resolveActiveRuntime(options = {}) {
  const paths = runtimePaths(options.root);
  const state = await readRuntimeState(paths);
  return resolveRelease(state.active, paths.root, {
    verifyTree: options.verifyTree ?? true,
    doctor: options.doctor ?? false,
  });
}

export async function checkRuntime(options = {}) {
  assertNodeVersion();
  const release = await resolveActiveRuntime({ ...options, verifyTree: true, doctor: true });
  return {
    ok: true,
    status: 'ready',
    version: release.receipt.version,
    releaseId: release.receipt.releaseId,
    sha256: release.receipt.sha256,
  };
}

export async function installRuntime(options = {}) {
  assertNodeVersion();
  const pin = validateReleasePin(options.pin ?? await loadReleasePin(options.pinPath));
  const paths = runtimePaths(options.root);
  const token = await acquireLock(paths);
  let active = null;
  try {
    await cleanupInterruptedStaging(paths);
    const state = await readRuntimeStateOrNull(paths);
    active = state
      ? await resolveRelease(state.active, paths.root, { verifyTree: true, doctor: true })
      : null;
    if (
      active?.receipt.releaseId === pin.releaseId &&
      active.receipt.sha256 === pin.archive.sha256
    ) {
      return {
        ok: true,
        status: 'current',
        version: active.receipt.version,
        releaseId: active.receipt.releaseId,
      };
    }
    try {
      const staged = await stageRelease(paths, pin, options.archivePath);
      const promoted = await promote(paths, staged, state, options.beforeStateRename);
      return {
        ok: true,
        status: 'installed',
        version: promoted.receipt.version,
        releaseId: promoted.receipt.releaseId,
        previousReleaseId: active?.receipt.releaseId ?? null,
      };
    } catch (error) {
      await recordFailure(paths, pin, error, active);
      const result = {
        ok: false,
        status: active ? 'retained-active' : 'install-failed',
        version: active?.receipt.version ?? null,
        releaseId: active?.receipt.releaseId ?? null,
        rejectedReleaseId: pin.releaseId,
        error: safeError(error),
      };
      throw Object.assign(new Error(error.message), { result, exitCode: 5 });
    }
  } finally {
    await releaseLock(paths, token);
  }
}

export async function rollbackRuntime(options = {}) {
  assertNodeVersion();
  const paths = runtimePaths(options.root);
  const token = await acquireLock(paths);
  try {
    await cleanupInterruptedStaging(paths);
    const state = await readRuntimeState(paths);
    const currentReceipt = state.active;
    const previousReceipt = state.previous;
    if (!previousReceipt) throw Object.assign(new Error('No previous Archify runtime is available'), { exitCode: 5 });
    await resolveRelease(currentReceipt, paths.root, { verifyTree: true, doctor: true });
    const previous = await resolveRelease(previousReceipt, paths.root, { verifyTree: true, doctor: true });
    const nextState = {
      schemaVersion: 1,
      generation: state.generation + 1,
      active: { ...previousReceipt, activatedAt: new Date().toISOString() },
      previous: currentReceipt,
      updatedAt: new Date().toISOString(),
    };
    await writeRuntimeState(paths, nextState, options.beforeStateRename);
    return {
      ok: true,
      status: 'rolled-back',
      version: previous.receipt.version,
      releaseId: previous.receipt.releaseId,
      previousReleaseId: currentReceipt.releaseId,
    };
  } finally {
    await releaseLock(paths, token);
  }
}
