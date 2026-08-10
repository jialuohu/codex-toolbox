#!/usr/bin/env node
import { resolve } from 'node:path';
import { runContract } from './lib/contract.mjs';
import { safeError } from './lib/io.mjs';

const release = process.argv[2];
if (!release) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: { message: 'Missing release directory' } })}\n`);
  process.exitCode = 2;
} else {
  try {
    const report = await runContract(resolve(release));
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ ok: false, error: safeError(error) })}\n`);
    process.exitCode = 1;
  }
}
