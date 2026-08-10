import { homedir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleDirectory = dirname(fileURLToPath(import.meta.url));

export const scriptsDirectory = resolve(moduleDirectory, '..');
export const skillDirectory = resolve(scriptsDirectory, '..');
export const pluginDirectory = resolve(skillDirectory, '..', '..');
export const bootstrapDirectory = join(pluginDirectory, 'runtime', 'bootstrap');
export const fixturesDirectory = join(skillDirectory, 'assets', 'fixtures');

export function runtimeRoot() {
  if (process.env.PRETTY_MERMAID_RUNTIME_ROOT) {
    return resolve(process.env.PRETTY_MERMAID_RUNTIME_ROOT);
  }
  const codexHome = process.env.CODEX_HOME
    ? resolve(process.env.CODEX_HOME)
    : join(homedir(), '.codex');
  return join(codexHome, 'runtime', 'diagram-tools');
}

export function runtimePaths(root = runtimeRoot()) {
  return {
    root,
    releases: join(root, 'releases'),
    candidates: join(root, 'candidates'),
    reports: join(root, 'reports'),
    active: join(root, 'active.json'),
    previous: join(root, 'previous.json'),
    lock: join(root, 'update.lock'),
  };
}

export function assertOwnedPath(parent, child) {
  const resolvedParent = resolve(parent);
  const resolvedChild = resolve(child);
  const relation = relative(resolvedParent, resolvedChild);
  if (!relation || relation.startsWith(`..${sep}`) || relation === '..' || relation.startsWith(sep)) {
    throw new Error(`Path escapes its managed directory: ${resolvedChild}`);
  }
  return resolvedChild;
}
