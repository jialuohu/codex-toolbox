#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { safeError } from './lib/io.mjs';
import { resolveActiveRuntime } from './lib/runtime-manager.mjs';
import { runtimeInfo } from './lib/release.mjs';

const args = process.argv.slice(2);
const runtimeInfoCommand = args[0] === 'runtime-info';

if (runtimeInfoCommand && (args.length !== 2 || args[1] !== '--json')) {
  process.stderr.write('Usage: archify runtime-info --json\n');
  process.exitCode = 2;
} else {
  try {
    const release = await resolveActiveRuntime({
      verifyTree: true,
      doctor: runtimeInfoCommand,
    });
    if (runtimeInfoCommand) {
      process.stdout.write(`${JSON.stringify(runtimeInfo(release), null, 2)}\n`);
    } else {
      const child = spawn(process.execPath, [release.cliPath, ...args], {
        cwd: process.cwd(),
        env: process.env,
        stdio: 'inherit',
      });
      child.once('error', (error) => {
        process.stderr.write(`${error.message}\n`);
        process.exitCode = 4;
      });
      child.once('close', (code, signal) => {
        if (signal) process.kill(process.pid, signal);
        else process.exitCode = code ?? 4;
      });
    }
  } catch (error) {
    if (runtimeInfoCommand) {
      process.stdout.write(`${JSON.stringify({
        ok: false,
        status: 'unavailable',
        error: safeError(error),
      }, null, 2)}\n`);
    } else {
      process.stderr.write(`${error.message}\nRun scripts/setup-archify-tools.sh --install.\n`);
    }
    process.exitCode = 3;
  }
}
