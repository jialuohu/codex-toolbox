#!/usr/bin/env node
import { checkRuntime, installRuntime, rollbackRuntime } from './lib/runtime-manager.mjs';
import { safeError } from './lib/io.mjs';

const [command = 'check', ...extra] = process.argv.slice(2);

try {
  if (extra.length > 0 || !['check', 'install', 'rollback'].includes(command)) {
    throw Object.assign(new Error('Usage: runtime-manager.mjs check|install|rollback'), { exitCode: 2 });
  }
  let result;
  if (command === 'check') result = await checkRuntime();
  else if (command === 'install') {
    result = await installRuntime({ archivePath: process.env.ARCHIFY_TEST_ARCHIVE_PATH });
  } else result = await rollbackRuntime();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify(error?.result ?? {
    ok: false,
    status: command === 'check' ? 'unavailable' : 'failed',
    error: safeError(error),
  }, null, 2)}\n`);
  process.exitCode = error?.exitCode ?? (command === 'check' ? 3 : 5);
}
