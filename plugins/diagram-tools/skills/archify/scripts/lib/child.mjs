import { spawn } from 'node:child_process';

const lifetimeGuard = new URL('./parent-lifetime.mjs', import.meta.url).href;

// Keep the child referenced until it finishes; never leave preview shutdown to
// a detached background process. Only the exact spawned child receives signals.
export function runChild(command, args, { onCancel = () => {} } = {}) {
  let child;
  const completion = new Promise((resolve, reject) => {
    // This helper runs Node runtimes, whose argv is unchanged by --import.
    child = spawn(command, ['--import', lifetimeGuard, ...args], {
      cwd: process.cwd(),
      env: { ...process.env, ARCHIFY_TOOLBOX_LIFETIME_GUARD: '1' },
      stdio: ['inherit', 'inherit', 'inherit', 'ipc'],
      // The pinned preview force-stops on a second signal. A separate POSIX
      // process group prevents terminal Ctrl-C plus forwarding from doubling it.
      detached: process.platform !== 'win32',
    });
    let requestedSignal = null;
    let settled = false;
    const handlers = new Map();
    const cleanup = () => {
      for (const [signal, handler] of handlers) process.off(signal, handler);
    };
    const signals = process.platform === 'win32'
      ? ['SIGINT', 'SIGTERM'] : ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT'];
    for (const signal of signals) {
      const handler = () => {
        if (requestedSignal || settled || !child.pid
            || child.exitCode !== null || child.signalCode !== null) return;
        requestedSignal = signal;
        onCancel({ pid: child.pid, signal });
        if (child.connected) child.send({
          type: 'codex-toolbox.archify.cancel.v1',
          signal: signal === 'SIGINT' ? 'SIGINT' : 'SIGTERM',
        }, (error) => {
          // A failed send must not abandon a live child. Disconnect asks the
          // preload guard to drain, using the same stop-once state.
          if (error && child.connected) child.disconnect();
        });
      };
      handlers.set(signal, handler);
      process.on(signal, handler);
    }
    child.once('error', (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    });
    // Streams are inherited, not captured: exit proves this child was reaped.
    // It also remains reliable when an explicit IPC disconnect precedes exit.
    child.once('exit', (code, signal) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve({ code, signal: requestedSignal ?? signal, pid: child.pid });
    });
  });
  completion.pid = child?.pid;
  return completion;
}
