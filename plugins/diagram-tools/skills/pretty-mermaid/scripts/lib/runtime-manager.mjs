import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  lstat,
  mkdir,
  mkdtemp,
  open,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { join } from 'node:path';
import { resolveActiveRelease, resolveManifestRelease } from './active-runtime.mjs';
import { CONTRACT_VERSION, MIN_NODE_MAJOR, RUNTIME_SCHEMA_VERSION } from './constants.mjs';
import { readJson, readJsonOrNull, safeError, writeJsonAtomic } from './io.mjs';
import { bootstrapDirectory, runtimePaths, scriptsDirectory } from './paths.mjs';

const COMMAND_TIMEOUT_MS = 120_000;
const MAX_COMMAND_OUTPUT = 2 * 1024 * 1024;

function assertNodeVersion() {
  const major = Number(process.versions.node.split('.')[0]);
  if (!Number.isInteger(major) || major < MIN_NODE_MAJOR) {
    throw new Error(`Pretty Mermaid setup requires Node.js ${MIN_NODE_MAJOR} or newer`);
  }
}

function validateStableVersion(version) {
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error(`npm latest is not a stable semantic version: ${String(version)}`);
  }
}

function validateIntegrity(integrity) {
  if (typeof integrity !== 'string' || !/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(integrity)) {
    throw new Error('npm metadata has no valid sha512 integrity');
  }
}

async function runCommand(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const output = { stdout: '', stderr: '' };
    let exceeded = false;
    const collect = (key) => (chunk) => {
      output[key] += chunk.toString('utf8');
      if (output.stdout.length + output.stderr.length > MAX_COMMAND_OUTPUT) {
        exceeded = true;
        child.kill('SIGKILL');
      }
    };
    child.stdout.on('data', collect('stdout'));
    child.stderr.on('data', collect('stderr'));
    const timer = setTimeout(() => child.kill('SIGKILL'), options.timeout ?? COMMAND_TIMEOUT_MS);
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('close', (code, signal) => {
      clearTimeout(timer);
      const result = { ...output, code: code ?? 1, signal };
      if (exceeded) reject(new Error(`${command} exceeded the output limit`));
      else if (result.code !== 0 && !options.allowFailure) {
        const detail = output.stderr.trim() || output.stdout.trim();
        reject(new Error(`${command} failed (${result.code}): ${detail.slice(-2000)}`));
      } else resolvePromise(result);
    });
  });
}

async function acquireLock(paths) {
  await mkdir(paths.root, { recursive: true, mode: 0o700 });
  const token = randomUUID();
  const create = async () => {
    const handle = await open(paths.lock, 'wx', 0o600);
    await handle.writeFile(
      `${JSON.stringify({ token, pid: process.pid, acquiredAt: new Date().toISOString() })}\n`,
    );
    await handle.close();
  };
  try {
    await create();
  } catch (error) {
    if (!error || error.code !== 'EEXIST') throw error;
    const current = await readJsonOrNull(paths.lock);
    let alive = false;
    if (current && Number.isInteger(current.pid)) {
      try {
        process.kill(current.pid, 0);
        alive = true;
      } catch (probeError) {
        if (probeError && probeError.code === 'EPERM') alive = true;
      }
    }
    if (alive) {
      throw new Error(`Diagram runtime update is already running under PID ${current.pid}`);
    }
    await unlink(paths.lock);
    await create();
  }
  return token;
}

async function releaseLock(paths, token) {
  try {
    const current = await readJsonOrNull(paths.lock);
    if (current?.token === token) await unlink(paths.lock);
  } catch (error) {
    if (!error || error.code !== 'ENOENT') throw error;
  }
}

async function cleanupInterruptedState(paths) {
  await mkdir(paths.candidates, { recursive: true, mode: 0o700 });
  const candidateEntries = await readdir(paths.candidates, { withFileTypes: true });
  for (const entry of candidateEntries) {
    if (!/^candidate-[0-9A-Za-z_-]+$/.test(entry.name)) continue;
    if (!entry.isDirectory() || entry.isSymbolicLink()) {
      throw new Error(`Refusing to remove unsafe interrupted candidate: ${entry.name}`);
    }
    await rm(join(paths.candidates, entry.name), { recursive: true, force: false });
  }

  const rootEntries = await readdir(paths.root, { withFileTypes: true });
  for (const entry of rootEntries) {
    if (!/^(?:active|previous)\.json\.tmp-\d+-\d+$/.test(entry.name)) continue;
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error(`Refusing to remove unsafe interrupted manifest: ${entry.name}`);
    }
    await unlink(join(paths.root, entry.name));
  }
}

async function bootstrapReceipt() {
  const packageJson = await readJson(join(bootstrapDirectory, 'package.json'));
  const lock = await readJson(join(bootstrapDirectory, 'package-lock.json'));
  const version = packageJson.dependencies?.['beautiful-mermaid'];
  const locked = lock.packages?.['node_modules/beautiful-mermaid'];
  if (!locked || locked.version !== version) {
    throw new Error('Approved fallback package and lock are inconsistent');
  }
  validateStableVersion(version);
  validateIntegrity(locked.integrity);
  return { version, integrity: locked.integrity, packageJson };
}

async function latestReceipt() {
  if (process.env.PRETTY_MERMAID_TEST_CANDIDATE_VERSION) {
    const version = process.env.PRETTY_MERMAID_TEST_CANDIDATE_VERSION;
    const integrity = process.env.PRETTY_MERMAID_TEST_CANDIDATE_INTEGRITY;
    validateStableVersion(version);
    validateIntegrity(integrity);
    return { version, integrity };
  }
  const result = await runCommand('npm', [
    'view',
    'beautiful-mermaid@latest',
    'version',
    'dist.integrity',
    '--json',
  ], { timeout: 30_000 });
  const metadata = JSON.parse(result.stdout);
  validateStableVersion(metadata.version);
  validateIntegrity(metadata['dist.integrity']);
  return { version: metadata.version, integrity: metadata['dist.integrity'] };
}

function releaseId(receipt) {
  const digest = createHash('sha256').update(receipt.integrity).digest('hex').slice(0, 12);
  return `beautiful-mermaid-${receipt.version}-${digest}`;
}

async function installedReceipt(directory) {
  const packageJson = await readJson(join(directory, 'package.json'));
  const lock = await readJson(join(directory, 'package-lock.json'));
  const locked = lock.packages?.['node_modules/beautiful-mermaid'];
  if (!locked || packageJson.dependencies?.['beautiful-mermaid'] !== locked.version) {
    throw new Error('Candidate package and lock disagree');
  }
  return { version: locked.version, integrity: locked.integrity };
}

async function runAudit(directory) {
  const result = await runCommand(
    'npm',
    ['audit', '--omit=dev', '--audit-level=high', '--json'],
    { cwd: directory, allowFailure: true, timeout: 60_000 },
  );
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    throw new Error(`npm audit returned invalid JSON: ${result.stderr.trim().slice(-1000)}`);
  }
  const vulnerabilities = report.metadata?.vulnerabilities ?? {};
  const high = Number(vulnerabilities.high ?? 0);
  const critical = Number(vulnerabilities.critical ?? 0);
  if (high > 0 || critical > 0) {
    throw new Error(`npm audit found ${high} high and ${critical} critical vulnerabilities`);
  }
  return vulnerabilities;
}

async function runContractSubprocess(directory) {
  const result = await runCommand(
    process.execPath,
    ['--max-old-space-size=512', join(scriptsDirectory, 'contract-cli.mjs'), directory],
    { timeout: COMMAND_TIMEOUT_MS, allowFailure: true },
  );
  const lines = result.stdout.trim().split('\n').filter(Boolean);
  let report = null;
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      report = JSON.parse(lines[index]);
      break;
    } catch {
      // Ignore upstream diagnostic output and continue to the contract JSON line.
    }
  }
  if (!report || !report.ok || result.code !== 0) {
    const detail = report?.error?.message ?? result.stderr.trim() ?? 'unknown conformance failure';
    throw new Error(`Candidate failed conformance: ${detail}`);
  }
  return report;
}

async function stageRelease(paths, receipt, channel) {
  await mkdir(paths.candidates, { recursive: true, mode: 0o700 });
  await mkdir(paths.releases, { recursive: true, mode: 0o700 });
  const candidate = await mkdtemp(join(paths.candidates, 'candidate-'));
  try {
    const bootstrap = await bootstrapReceipt();
    const packageJson = structuredClone(bootstrap.packageJson);
    packageJson.dependencies['beautiful-mermaid'] = receipt.version;
    const packageLock = await readJson(join(bootstrapDirectory, 'package-lock.json'));
    packageLock.packages[''].dependencies['beautiful-mermaid'] = receipt.version;
    await writeFile(join(candidate, 'package.json'), `${JSON.stringify(packageJson, null, 2)}\n`, {
      mode: 0o600,
    });
    await writeFile(
      join(candidate, 'package-lock.json'),
      `${JSON.stringify(packageLock, null, 2)}\n`,
      { mode: 0o600 },
    );
    await runCommand(
      'npm',
      ['install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund'],
      { cwd: candidate },
    );
    await runCommand(
      'npm',
      ['ci', '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund'],
      { cwd: candidate },
    );
    const installed = await installedReceipt(candidate);
    if (installed.version !== receipt.version || installed.integrity !== receipt.integrity) {
      throw new Error('Installed package does not match resolved npm version and integrity');
    }
    const audit = await runAudit(candidate);
    const conformance = await runContractSubprocess(candidate);
    const id = releaseId(receipt);
    const destination = join(paths.releases, id);
    const manifest = {
      schemaVersion: RUNTIME_SCHEMA_VERSION,
      releaseId: id,
      version: receipt.version,
      integrity: receipt.integrity,
      contractVersion: CONTRACT_VERSION,
      installedAt: new Date().toISOString(),
      channel,
      capabilities: conformance.capabilities,
      conformance: {
        durationMs: conformance.durationMs,
        probes: conformance.probes,
      },
      audit,
    };
    await writeFile(join(candidate, 'runtime.json'), `${JSON.stringify(manifest, null, 2)}\n`, {
      mode: 0o600,
    });

    try {
      const existing = await lstat(destination);
      if (!existing.isDirectory() || existing.isSymbolicLink()) {
        throw new Error(`Refusing to replace unsafe release path: ${destination}`);
      }
      const existingManifest = await readJsonOrNull(join(destination, 'runtime.json'));
      if (
        existingManifest?.releaseId !== id ||
        existingManifest.version !== receipt.version ||
        existingManifest.integrity !== receipt.integrity
      ) {
        throw new Error(`Refusing to replace release not owned by diagram-tools: ${destination}`);
      }
      await rm(destination, { recursive: true, force: false });
    } catch (error) {
      if (!error || error.code !== 'ENOENT') throw error;
    }
    await rename(candidate, destination);
    return { manifest, releaseDirectory: destination, conformance };
  } catch (error) {
    await rm(candidate, { recursive: true, force: true });
    throw error;
  }
}

async function validateRelease(manifest, root) {
  const release = await resolveManifestRelease(manifest, root);
  const conformance = await runContractSubprocess(release.releaseDirectory);
  return { ...release, conformance };
}

async function validActive(root) {
  try {
    const active = await resolveActiveRelease(root);
    const conformance = await runContractSubprocess(active.releaseDirectory);
    return { ...active, conformance };
  } catch {
    return null;
  }
}

async function promote(paths, staged) {
  const current = await readJsonOrNull(paths.active);
  if (current && current.releaseId !== staged.manifest.releaseId) {
    await writeJsonAtomic(paths.previous, current);
  }
  await writeJsonAtomic(paths.active, staged.manifest);
}

async function pruneReleases(paths, fallbackVersion) {
  const active = await readJsonOrNull(paths.active);
  const previous = await readJsonOrNull(paths.previous);
  const keep = new Set([active?.releaseId, previous?.releaseId].filter(Boolean));
  let entries = [];
  try {
    entries = await readdir(paths.releases, { withFileTypes: true });
  } catch (error) {
    if (error && error.code === 'ENOENT') return;
    throw error;
  }
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    if (!/^beautiful-mermaid-\d+\.\d+\.\d+-[0-9a-f]{12}$/.test(entry.name)) continue;
    const directory = join(paths.releases, entry.name);
    const manifest = await readJsonOrNull(join(directory, 'runtime.json'));
    if (
      manifest?.releaseId !== entry.name ||
      typeof manifest.version !== 'string' ||
      typeof manifest.integrity !== 'string' ||
      releaseId({ version: manifest.version, integrity: manifest.integrity }) !== entry.name
    ) {
      continue;
    }
    if (manifest?.version === fallbackVersion) keep.add(entry.name);
    candidates.push({ entry, manifest });
  }
  const newest = candidates
    .filter(({ manifest }) => manifest?.installedAt)
    .sort((a, b) => Date.parse(b.manifest.installedAt) - Date.parse(a.manifest.installedAt))
    .slice(0, 3);
  for (const { entry } of newest) keep.add(entry.name);
  for (const { entry } of candidates) {
    if (!keep.has(entry.name)) {
      await rm(join(paths.releases, entry.name), { recursive: true, force: false });
    }
  }
}

async function recordFailure(paths, receipt, error) {
  await mkdir(paths.reports, { recursive: true, mode: 0o700 });
  await writeJsonAtomic(join(paths.reports, 'latest-failure.json'), {
    attemptedAt: new Date().toISOString(),
    receipt,
    contractVersion: CONTRACT_VERSION,
    error: safeError(error),
  });
}

async function recoverFromCandidateFailure(paths, fallback, active, receipt, error, strict) {
  await recordFailure(paths, receipt, error);
  if (active) {
    const result = {
      ok: !strict,
      status: 'retained-active',
      version: active.manifest.version,
      rejectedVersion: receipt.version ?? null,
      error: safeError(error),
    };
    if (strict) {
      throw Object.assign(new Error(error.message), { result, exitCode: 5 });
    }
    return result;
  }

  let stagedFallback;
  try {
    stagedFallback = await stageRelease(paths, fallback, 'approved-fallback');
    await promote(paths, stagedFallback);
  } catch (fallbackError) {
    throw new Error(
      `Newest candidate failed (${error.message}); approved fallback also failed (${fallbackError.message})`,
    );
  }
  const result = {
    ok: !strict,
    status: 'fallback-installed',
    version: stagedFallback.manifest.version,
    rejectedVersion: receipt.version ?? null,
    error: safeError(error),
  };
  if (strict) {
    throw Object.assign(new Error(error.message), { result, exitCode: 5 });
  }
  return result;
}

export async function updateRuntime(options = {}) {
  assertNodeVersion();
  const paths = runtimePaths(options.root);
  const token = await acquireLock(paths);
  let newest = null;
  try {
    await cleanupInterruptedState(paths);
    const fallback = await bootstrapReceipt();
    const active = await validActive(paths.root);
    try {
      newest = await latestReceipt();
    } catch (resolutionError) {
      return await recoverFromCandidateFailure(
        paths,
        fallback,
        active,
        { source: 'npm:beautiful-mermaid@latest', version: null, integrity: null },
        resolutionError,
        Boolean(options.strict),
      );
    }
    if (
      active &&
      active.manifest.version === newest.version &&
      active.manifest.integrity === newest.integrity
    ) {
      await pruneReleases(paths, fallback.version);
      return {
        ok: true,
        status: 'current',
        version: active.manifest.version,
        releaseId: active.manifest.releaseId,
      };
    }

    try {
      const staged = await stageRelease(paths, newest, 'latest');
      await promote(paths, staged);
      await pruneReleases(paths, fallback.version);
      return {
        ok: true,
        status: 'promoted',
        version: staged.manifest.version,
        releaseId: staged.manifest.releaseId,
        previousVersion: active?.manifest.version ?? null,
      };
    } catch (candidateError) {
      return await recoverFromCandidateFailure(
        paths,
        fallback,
        active,
        newest,
        candidateError,
        Boolean(options.strict),
      );
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
    const previous = await readJsonOrNull(paths.previous);
    if (!previous) throw new Error('No previous Pretty Mermaid runtime is available');
    await validateRelease(previous, paths.root);
    const active = await readJsonOrNull(paths.active);
    await writeJsonAtomic(paths.active, previous);
    if (active) await writeJsonAtomic(paths.previous, active);
    return {
      ok: true,
      status: 'rolled-back',
      version: previous.version,
      releaseId: previous.releaseId,
    };
  } finally {
    await releaseLock(paths, token);
  }
}
