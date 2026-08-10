import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

export async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function readJsonOrNull(path) {
  try {
    return await readJson(path);
  } catch (error) {
    if (error && error.code === 'ENOENT') return null;
    throw error;
  }
}

export async function writeJsonAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path);
}

export function safeError(error) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      ...(error.code ? { code: String(error.code) } : {}),
    };
  }
  return { name: 'Error', message: String(error) };
}
