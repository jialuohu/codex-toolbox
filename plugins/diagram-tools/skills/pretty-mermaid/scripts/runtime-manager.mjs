#!/usr/bin/env node
import { rollbackRuntime, updateRuntime } from './lib/runtime-manager.mjs';
import { safeError } from './lib/io.mjs';

const command = process.argv[2] ?? 'update';
const strict = process.argv.includes('--strict');

try {
  let result;
  if (command === 'update') result = await updateRuntime({ strict });
  else if (command === 'rollback') result = await rollbackRuntime();
  else throw Object.assign(new Error(`Unknown runtime command: ${command}`), { exitCode: 2 });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} catch (error) {
  process.stdout.write(
    `${JSON.stringify(error?.result ?? { ok: false, status: 'failed', error: safeError(error) }, null, 2)}\n`,
  );
  process.exitCode = error?.exitCode ?? (strict || command === 'rollback' ? 5 : 3);
}
