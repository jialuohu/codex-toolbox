import { homedir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleDirectory = dirname(fileURLToPath(import.meta.url));

export const scriptsDirectory = resolve(moduleDirectory, '..');
export const skillDirectory = resolve(scriptsDirectory, '..');
export const pluginDirectory = resolve(skillDirectory, '..', '..');
export const releasePinPath = join(pluginDirectory, 'runtime', 'archify', 'release.json');

export function runtimeRoot() {
  if (process.env.ARCHIFY_RUNTIME_ROOT) return resolve(process.env.ARCHIFY_RUNTIME_ROOT);
  const codexHome = process.env.CODEX_HOME ? resolve(process.env.CODEX_HOME) : join(homedir(), '.codex');
  return join(codexHome, 'runtime', 'diagram-tools', 'archify');
}

export function runtimePaths(root = runtimeRoot()) {
  const resolvedRoot = resolve(root);
  return {
    root: resolvedRoot,
    releases: join(resolvedRoot, 'releases'),
    staging: join(resolvedRoot, 'staging'),
    reports: join(resolvedRoot, 'reports'),
    state: join(resolvedRoot, 'state.json'),
    lock: join(resolvedRoot, 'install.lock'),
  };
}

export function assertContained(parent, child, { allowRoot = false } = {}) {
  const resolvedParent = resolve(parent);
  const resolvedChild = resolve(child);
  const relation = relative(resolvedParent, resolvedChild);
  if (
    (!allowRoot && !relation) ||
    relation === '..' ||
    relation.startsWith(`..${sep}`) ||
    relation.startsWith(sep)
  ) {
    throw new Error(`Path escapes its managed directory: ${resolvedChild}`);
  }
  return resolvedChild;
}
