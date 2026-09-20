import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
import { bootstrapReceipt, releaseId } from '../skills/pretty-mermaid/scripts/lib/runtime-manager.mjs';

test('bootstrap receipt identifies the externally verifiable raw lockfile bytes', async () => {
  const lockBytes = await readFile(resolve('runtime/bootstrap/package-lock.json'));
  const receipt = await bootstrapReceipt();
  assert.equal(receipt.bootstrapLockSha256, createHash('sha256').update(lockBytes).digest('hex'));
  assert.notEqual(receipt.bootstrapLockSha256,
    createHash('sha256').update(JSON.stringify(JSON.parse(lockBytes))).digest('hex'));
});

test('support lock changes create distinct immutable runtime generation names', () => {
  const renderer = { version: '1.1.3', integrity: 'sha512-example' };
  const legacy = releaseId(renderer);
  assert.match(legacy, /^beautiful-mermaid-1\.1\.3-[0-9a-f]{12}$/);
  const first = releaseId(renderer, 'a'.repeat(64));
  const second = releaseId(renderer, 'b'.repeat(64));
  assert.notEqual(first, second);
  assert.notEqual(first, legacy);
  assert.equal(releaseId(renderer, 'a'.repeat(64)), first);
  assert.throws(() => releaseId(renderer, '../not-a-digest'), /lock identity/);
});
