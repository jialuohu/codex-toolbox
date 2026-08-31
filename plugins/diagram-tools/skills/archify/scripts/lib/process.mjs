import { spawn } from 'node:child_process';

const DEFAULT_TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;

export function runCommand(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let exceeded = false;
    const collect = (key) => (chunk) => {
      if (key === 'stdout') stdout += chunk.toString('utf8');
      else stderr += chunk.toString('utf8');
      if (Buffer.byteLength(stdout) + Buffer.byteLength(stderr) > MAX_OUTPUT_BYTES) {
        exceeded = true;
        child.kill('SIGKILL');
      }
    };
    child.stdout.on('data', collect('stdout'));
    child.stderr.on('data', collect('stderr'));
    const timer = setTimeout(() => child.kill('SIGKILL'), options.timeout ?? DEFAULT_TIMEOUT_MS);
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('close', (code, signal) => {
      clearTimeout(timer);
      if (exceeded) {
        reject(new Error(`${command} exceeded the output limit`));
        return;
      }
      const result = { code: code ?? 1, signal, stdout, stderr };
      if (result.code !== 0 && !options.allowFailure) {
        const detail = stderr.trim() || stdout.trim() || `signal ${signal}`;
        reject(new Error(`${command} failed (${result.code}): ${detail.slice(-3000)}`));
      } else {
        resolvePromise(result);
      }
    });
  });
}
