import { lstat, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import {
  CONTRACT_VERSION,
  RUNTIME_SCHEMA_VERSION,
  SETUP_HINT,
  WRAPPER_DEPENDENCIES,
} from './constants.mjs';
import { readJsonOrNull } from './io.mjs';
import { assertOwnedPath, runtimePaths } from './paths.mjs';

function validReleaseId(value) {
  return typeof value === 'string' && /^[a-z0-9][a-z0-9._-]{0,127}$/i.test(value);
}

export async function inspectReleaseReceipt(releaseDirectory, manifest) {
  const packageJson = JSON.parse(await readFile(join(releaseDirectory, 'package.json'), 'utf8'));
  const lock = JSON.parse(await readFile(join(releaseDirectory, 'package-lock.json'), 'utf8'));
  const locked = lock.packages?.['node_modules/beautiful-mermaid'];
  if (!locked || typeof locked.version !== 'string' || typeof locked.integrity !== 'string') {
    throw new Error('Runtime package lock has no Beautiful Mermaid receipt');
  }
  if (packageJson.dependencies?.['beautiful-mermaid'] !== locked.version) {
    throw new Error('Runtime package and lock disagree on Beautiful Mermaid version');
  }
  for (const dependency of WRAPPER_DEPENDENCIES) {
    const specification = packageJson.dependencies?.[dependency];
    const lockedDependency = lock.packages?.[`node_modules/${dependency}`];
    if (
      typeof specification !== 'string' ||
      !/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(specification) ||
      lockedDependency?.version !== specification ||
      typeof lockedDependency.integrity !== 'string' ||
      !lockedDependency.integrity.startsWith('sha512-')
    ) {
      throw new Error(`Runtime package and lock disagree on ${dependency}`);
    }
  }
  if (manifest.version !== locked.version || manifest.integrity !== locked.integrity) {
    throw new Error('Active manifest does not match the runtime installation receipt');
  }
  return { version: locked.version, integrity: locked.integrity };
}

export async function resolveManifestRelease(manifest, root) {
  if (!manifest || manifest.schemaVersion !== RUNTIME_SCHEMA_VERSION) {
    throw new Error('Runtime manifest is missing or has an unsupported schema');
  }
  if (!validReleaseId(manifest.releaseId)) throw new Error('Runtime manifest has an invalid release ID');
  if (manifest.contractVersion !== CONTRACT_VERSION) {
    throw new Error(
      `Runtime contract ${manifest.contractVersion} does not match wrapper contract ${CONTRACT_VERSION}`,
    );
  }
  const paths = runtimePaths(root);
  const releaseDirectory = assertOwnedPath(paths.releases, join(paths.releases, manifest.releaseId));
  const metadata = await lstat(releaseDirectory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error('Active runtime release is not a regular managed directory');
  }
  await inspectReleaseReceipt(releaseDirectory, manifest);
  return { manifest, releaseDirectory };
}

export async function resolveActiveRelease(root) {
  const paths = runtimePaths(root);
  const manifest = await readJsonOrNull(paths.active);
  if (!manifest) throw new Error(`Pretty Mermaid runtime is not installed. ${SETUP_HINT}`);
  return resolveManifestRelease(manifest, root);
}

export async function doctorRuntime(root) {
  try {
    const { manifest, releaseDirectory } = await resolveActiveRelease(root);
    return {
      ok: true,
      status: 'ready',
      releaseDirectory,
      version: manifest.version,
      integrity: manifest.integrity,
      contractVersion: manifest.contractVersion,
      installedAt: manifest.installedAt,
      capabilities: manifest.capabilities,
      setupHint: SETUP_HINT,
    };
  } catch (error) {
    return {
      ok: false,
      status: 'unavailable',
      error: error instanceof Error ? error.message : String(error),
      setupHint: SETUP_HINT,
    };
  }
}
