import assert from 'node:assert/strict';
import { copyFile, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { inspectReleaseReceipt } from '../skills/pretty-mermaid/scripts/lib/active-runtime.mjs';

test('runtime receipts cover renderer and wrapper infrastructure dependencies', async () => {
  const bootstrap = resolve('runtime/bootstrap');
  const release = await mkdtemp(join(tmpdir(), 'diagram-tools-receipt-'));
  await copyFile(join(bootstrap, 'package.json'), join(release, 'package.json'));
  await copyFile(join(bootstrap, 'package-lock.json'), join(release, 'package-lock.json'));
  const lock = JSON.parse(await readFile(join(release, 'package-lock.json'), 'utf8'));
  const renderer = lock.packages['node_modules/beautiful-mermaid'];
  const manifest = { version: renderer.version, integrity: renderer.integrity };
  await inspectReleaseReceipt(release, manifest);

  const packageJson = JSON.parse(await readFile(join(release, 'package.json'), 'utf8'));
  packageJson.dependencies.postcss = '0.0.0';
  await writeFile(join(release, 'package.json'), `${JSON.stringify(packageJson, null, 2)}\n`);
  await assert.rejects(
    inspectReleaseReceipt(release, manifest),
    /Runtime package and lock disagree on postcss/,
  );
});
