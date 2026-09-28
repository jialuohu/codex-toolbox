#!/usr/bin/env node
import { runChild } from './lib/child.mjs';
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
      try {
        const { code, signal, pid } = await runChild(process.execPath, [release.cliPath, ...args], {
          onCancel: ({ pid, signal }) => process.stderr.write(
            `Stopping Archify runtime PID ${pid} after ${signal}; waiting for cleanup.\n`,
          ),
        });
        if (signal) {
          if (code !== null && code !== 0) await new Promise(resolve => process.stderr.write(
            `Archify runtime PID ${pid} exited with code ${code} during ${signal} cleanup.\n`, resolve,
          ));
          process.kill(process.pid, signal);
        } else process.exitCode = code ?? 4;
      } catch (error) {
        process.stderr.write(`${error.message}\n`);
        process.exitCode = 4;
      }
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
