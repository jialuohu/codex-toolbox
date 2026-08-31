import { createHash } from 'node:crypto';
import {
  lstat,
  mkdir,
  readFile,
  readdir,
  realpath,
} from 'node:fs/promises';
import { join, relative, resolve, sep } from 'node:path';
import { readJson } from './io.mjs';
import { runCommand } from './process.mjs';
import { assertContained, runtimePaths } from './paths.mjs';

export const DIAGRAM_TYPES = Object.freeze([
  'architecture',
  'workflow',
  'sequence',
  'dataflow',
  'lifecycle',
]);

export const EXAMPLE_FILES = Object.freeze({
  architecture: 'web-app.architecture.json',
  workflow: 'agent-tool-call.workflow.json',
  sequence: 'async-job-roundtrip.sequence.json',
  dataflow: 'product-analytics.dataflow.json',
  lifecycle: 'agent-run.lifecycle.json',
});

const STABLE_UPDATE_MANIFEST_URL = 'https://tt-a1i.github.io/archify/skill-updates/archify/stable.json';

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function expectedReleaseId(pin) {
  return `archify-${pin.version}-${pin.archive.sha256.slice(0, 12)}`;
}

export function validateReleasePin(pin) {
  if (pin?.schemaVersion !== 1 || pin.name !== 'archify') throw new Error('Invalid Archify release pin');
  if (!/^\d+\.\d+\.\d+$/.test(pin.version) || pin.tag !== `v${pin.version}`) {
    throw new Error('Archify release pin has an invalid version or tag');
  }
  if (pin.releaseId !== expectedReleaseId(pin)) throw new Error('Archify release pin has an invalid releaseId');
  const archive = pin.archive;
  if (
    archive?.name !== 'archify.zip' ||
    archive.url !== `https://github.com/tt-a1i/archify/releases/download/${pin.tag}/archify.zip` ||
    !/^[0-9a-f]{64}$/.test(archive.sha256) ||
    !Number.isSafeInteger(archive.bytes) || archive.bytes < 1 ||
    !Number.isSafeInteger(archive.maxBytes) || archive.maxBytes < archive.bytes ||
    !Number.isSafeInteger(archive.maxExpandedBytes) || archive.maxExpandedBytes < archive.bytes ||
    !Number.isSafeInteger(archive.maxEntries) || archive.maxEntries < 1 || archive.maxEntries > 4096
  ) {
    throw new Error('Archify release pin has an invalid archive contract');
  }
  if (pin.updateManifestUrl !== STABLE_UPDATE_MANIFEST_URL) {
    throw new Error('Archify release pin has an invalid update manifest URL');
  }
  return pin;
}

async function regularFileWithin(releaseDirectory, path, label = path) {
  const resolved = assertContained(releaseDirectory, path);
  const metadata = await lstat(resolved);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error(`${label} is not a regular file`);
  const canonicalRoot = await realpath(releaseDirectory);
  const canonical = await realpath(resolved);
  const relation = relative(canonicalRoot, canonical);
  if (!relation || relation === '..' || relation.startsWith(`..${sep}`) || relation.startsWith(sep)) {
    throw new Error(`${label} resolves outside the active release`);
  }
  return canonical;
}

async function collectTree(directory, relativeDirectory = '') {
  const current = relativeDirectory ? join(directory, ...relativeDirectory.split('/')) : directory;
  const entries = await readdir(current, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink()) throw new Error(`Archify runtime contains a symlink: ${entry.name}`);
    const path = relativeDirectory ? `${relativeDirectory}/${entry.name}` : entry.name;
    if (path === 'runtime.json') continue;
    if (entry.isDirectory()) files.push(...await collectTree(directory, path));
    else if (entry.isFile()) {
      const contents = await readFile(join(directory, ...path.split('/')));
      files.push({ path, bytes: contents.length, sha256: sha256(contents) });
    } else throw new Error(`Archify runtime contains a special entry: ${path}`);
  }
  return files;
}

function digestTree(files) {
  const hash = createHash('sha256');
  for (const file of files.sort((left, right) => left.path.localeCompare(right.path, 'en'))) {
    hash.update(file.path);
    hash.update('\0');
    hash.update(String(file.bytes));
    hash.update('\0');
    hash.update(file.sha256);
    hash.update('\n');
  }
  return hash.digest('hex');
}

export async function verifyReleaseTree(releaseDirectory, manifest) {
  const files = await collectTree(releaseDirectory);
  const expandedBytes = files.reduce((sum, file) => sum + file.bytes, 0);
  if (
    files.length !== manifest.fileCount ||
    expandedBytes !== manifest.expandedBytes ||
    digestTree(files) !== manifest.treeSha256
  ) {
    throw new Error('Archify runtime tree differs from its immutable receipt');
  }
  return { fileCount: files.length, expandedBytes, treeSha256: manifest.treeSha256 };
}

export async function runDoctor(cliPath, cwd) {
  const result = await runCommand(process.execPath, [cliPath, 'doctor'], { cwd, timeout: 30_000 });
  if (!/Archify is ready\./.test(result.stdout)) throw new Error('Archify doctor did not report ready');
  return { ok: true, command: 'doctor' };
}

export async function smokeRelease(releaseDirectory, smokeDirectory) {
  const cliPath = join(releaseDirectory, 'bin', 'archify.mjs');
  await runDoctor(cliPath, releaseDirectory);
  await mkdir(smokeDirectory, { recursive: true, mode: 0o700 });
  const modes = {};
  for (const type of DIAGRAM_TYPES) {
    const input = join(releaseDirectory, 'examples', EXAMPLE_FILES[type]);
    const output = join(smokeDirectory, `${type}.html`);
    const validate = await runCommand(
      process.execPath,
      [cliPath, 'validate', type, input, '--json', '--quality', 'showcase'],
      { cwd: releaseDirectory },
    );
    const validateReceipt = JSON.parse(validate.stdout);
    if (!validateReceipt.ok || validateReceipt.type !== type || validateReceipt.command !== 'validate') {
      throw new Error(`Archify ${type} validation smoke returned an invalid receipt`);
    }
    const deliver = await runCommand(
      process.execPath,
      [cliPath, 'deliver', type, input, output, '--json', '--quality', 'showcase'],
      { cwd: releaseDirectory },
    );
    const deliverReceipt = JSON.parse(deliver.stdout);
    if (!deliverReceipt.ok || deliverReceipt.type !== type || deliverReceipt.command !== 'deliver') {
      throw new Error(`Archify ${type} delivery smoke returned an invalid receipt`);
    }
    const artifact = await lstat(output);
    if (!artifact.isFile() || artifact.isSymbolicLink() || artifact.size < 1) {
      throw new Error(`Archify ${type} delivery smoke did not create a regular HTML artifact`);
    }
    modes[type] = {
      validationChecks: validateReceipt.checks?.length ?? null,
      artifactBytes: artifact.size,
      artifactSha256: sha256(await readFile(output)),
    };
  }
  return { ok: true, quality: 'showcase', modes };
}

export async function verifyPackagedRelease(releaseDirectory, pin) {
  const packageJson = await readJson(
    await regularFileWithin(releaseDirectory, join(releaseDirectory, 'package.json'), 'package.json'),
  );
  if (
    packageJson.name !== 'archify' ||
    packageJson.version !== pin.version ||
    packageJson.license !== 'MIT' ||
    Object.keys(packageJson.dependencies ?? {}).length !== 0
  ) {
    throw new Error('Archify packaged release identity is invalid');
  }
  const skillRelease = await readJson(
    await regularFileWithin(
      releaseDirectory,
      join(releaseDirectory, 'skill-release.json'),
      'skill-release.json',
    ),
  );
  if (
    skillRelease.schemaVersion !== 1 ||
    skillRelease.skillId !== 'archify' ||
    skillRelease.channel !== 'stable' ||
    skillRelease.version !== pin.version ||
    skillRelease.updateManifestUrl !== pin.updateManifestUrl
  ) {
    throw new Error('Archify skill release identity is invalid');
  }
  const license = await readFile(
    await regularFileWithin(releaseDirectory, join(releaseDirectory, 'LICENSE'), 'LICENSE'),
    'utf8',
  );
  for (const notice of [
    'Copyright (c) 2026 tt-a1i (Archify)',
    'Copyright (c) 2025 Cocoon AI',
  ]) {
    if (!license.includes(notice)) throw new Error(`Archify packaged LICENSE is missing: ${notice}`);
  }
  return { packageJson, skillRelease };
}

export async function resolveRelease(receipt, root, options = {}) {
  const paths = runtimePaths(root);
  if (
    receipt?.schemaVersion !== 1 ||
    typeof receipt.releaseId !== 'string' ||
    !/^archify-\d+\.\d+\.\d+-[0-9a-f]{12}$/.test(receipt.releaseId) ||
    typeof receipt.version !== 'string' ||
    !/^[0-9a-f]{64}$/.test(receipt.sha256)
  ) {
    throw new Error('Archify runtime receipt is invalid');
  }
  const releaseDirectory = assertContained(paths.releases, join(paths.releases, receipt.releaseId));
  const directoryMetadata = await lstat(releaseDirectory);
  if (!directoryMetadata.isDirectory() || directoryMetadata.isSymbolicLink()) {
    throw new Error('Archify active release is not a regular directory');
  }
  const releaseRoot = await realpath(paths.releases);
  const canonicalRelease = await realpath(releaseDirectory);
  assertContained(releaseRoot, canonicalRelease);
  const manifestPath = await regularFileWithin(canonicalRelease, join(canonicalRelease, 'runtime.json'), 'runtime.json');
  const manifest = await readJson(manifestPath);
  if (
    manifest.schemaVersion !== 1 ||
    manifest.releaseId !== receipt.releaseId ||
    manifest.version !== receipt.version ||
    manifest.sha256 !== receipt.sha256 ||
    manifest.treeSha256 !== receipt.treeSha256
  ) {
    throw new Error('Archify active receipt and immutable release receipt disagree');
  }
  if (options.verifyTree) await verifyReleaseTree(canonicalRelease, manifest);

  const cliPath = await regularFileWithin(canonicalRelease, join(canonicalRelease, 'bin', 'archify.mjs'), 'Archify CLI');
  const skillPath = await regularFileWithin(canonicalRelease, join(canonicalRelease, 'SKILL.md'), 'Archify skill contract');
  const commonSchemaPath = await regularFileWithin(
    canonicalRelease,
    join(canonicalRelease, 'schemas', 'common.schema.json'),
    'Archify common schema',
  );
  const updateCheckerPath = await regularFileWithin(
    canonicalRelease,
    join(canonicalRelease, 'scripts', 'check-update.mjs'),
    'Archify update checker',
  );
  const typeSchemaPaths = {};
  const examplePaths = {};
  for (const type of DIAGRAM_TYPES) {
    typeSchemaPaths[type] = await regularFileWithin(
      canonicalRelease,
      join(canonicalRelease, 'schemas', `${type}.schema.json`),
      `Archify ${type} schema`,
    );
    examplePaths[type] = await regularFileWithin(
      canonicalRelease,
      join(canonicalRelease, 'examples', EXAMPLE_FILES[type]),
      `Archify ${type} example`,
    );
  }
  await verifyPackagedRelease(canonicalRelease, {
    version: receipt.version,
    updateManifestUrl: manifest.updateManifestUrl,
  });
  if (options.doctor) await runDoctor(cliPath, canonicalRelease);
  return {
    receipt,
    manifest,
    releaseDirectory: canonicalRelease,
    cliPath,
    skillPath,
    commonSchemaPath,
    typeSchemaPaths,
    examplePaths,
    updateCheckerPath,
  };
}

export function runtimeInfo(release) {
  return {
    ok: true,
    status: 'ready',
    version: release.receipt.version,
    releaseDirectory: release.releaseDirectory,
    sha256: release.receipt.sha256,
    cliPath: release.cliPath,
    skillPath: release.skillPath,
    commonSchemaPath: release.commonSchemaPath,
    typeSchemaPaths: release.typeSchemaPaths,
    examplePaths: release.examplePaths,
    updateCheckerPath: release.updateCheckerPath,
    updateManifestUrl: release.manifest.updateManifestUrl,
  };
}
