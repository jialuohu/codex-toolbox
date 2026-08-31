import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

export async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function readJsonOrNull(path) {
  try {
    return await readJson(path);
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

export async function writeJsonAtomic(path, value, options = {}) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.tmp-${process.pid}-${randomUUID()}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600, flag: 'wx' });
  if (options.beforeRename) await options.beforeRename(temporary);
  await rename(temporary, path);
}

export function safeError(error) {
  return {
    name: error?.name || 'Error',
    message: error?.message || String(error),
    ...(error?.code ? { code: error.code } : {}),
  };
}
