import { isMainThread } from 'node:worker_threads';

// Consume the launch marker before application code can spawn a worker or fork.
// They inherit --import through execArgv, but do not own this parent's channel.
const ownsConnection = process.env.ARCHIFY_TOOLBOX_LIFETIME_GUARD === '1';
delete process.env.ARCHIFY_TOOLBOX_LIFETIME_GUARD;
if (isMainThread && ownsConnection) {
  let stopping = false;
  function stopOnce(signal) {
    if (stopping) return;
    stopping = true;
    process.kill(process.pid, signal);
  }

  process.on('message', (message) => {
    if (message && Object.keys(message).length === 2
        && message.type === 'codex-toolbox.archify.cancel.v1'
        && ['SIGINT', 'SIGTERM'].includes(message.signal)) {
      stopOnce(message.signal);
    }
  });
  process.once('disconnect', () => stopOnce('SIGTERM'));
  // Listening for parent death must not keep a completed CLI command alive.
  process.channel?.unref();
  if (!process.connected) stopOnce('SIGTERM');
}
