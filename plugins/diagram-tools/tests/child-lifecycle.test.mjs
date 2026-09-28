import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { runChild } from '../skills/archify/scripts/lib/child.mjs';

const moduleUrl = new URL('../skills/archify/scripts/lib/child.mjs', import.meta.url).href;
const guardUrl = new URL('../skills/archify/scripts/lib/parent-lifetime.mjs', import.meta.url).href;
const runnerSource = `
import { runChild } from ${JSON.stringify(moduleUrl)};
import { writeFileSync } from 'node:fs';
try {
  const completion = runChild(process.execPath, process.argv.slice(2));
  writeFileSync(process.env.ARCHIFY_TEST_CHILD_PID_FILE, String(completion.pid));
  const { code, signal } = await completion;
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code;
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 4;
}
`;

async function fixture(t, source) {
  const directory = await mkdtemp(join(tmpdir(), 'archify child lifecycle '));
  const runner = join(directory, 'runner.mjs');
  const child = join(directory, 'child.mjs');
  await writeFile(runner, runnerSource);
  await writeFile(child, source);
  return { directory, runner, child, pidFile: join(directory, 'child.pid') };
}

function alive(pid) {
  if (!Number.isInteger(pid)) return false;
  try { process.kill(pid, 0); return true; } catch (error) {
    if (error.code === 'ESRCH') return false;
    throw error;
  }
}

async function recordedPid(path) {
  try { return Number(await readFile(path, 'utf8')); } catch { return null; }
}

async function cleanupSynthetic(proc, result, files) {
  if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGTERM');
  const closed = result.then(() => true);
  if (!await Promise.race([closed, delay(500, false, { ref: false })])) {
    const pid = await recordedPid(files.pidFile);
    // Test-only fallback: never depend on the wrapper under test for teardown.
    if (alive(pid)) process.kill(pid, 'SIGKILL');
    if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
    assert.equal(await Promise.race([closed, delay(1000, false, { ref: false })]), true,
      'synthetic process did not close after bounded teardown');
  }
  await rm(files.directory, { recursive: true, force: true });
}

function start(t, files, args = [], extra = {}) {
  const proc = spawn(process.execPath, [files.runner, files.child, ...args], {
    cwd: files.directory,
    env: { ...process.env, ARCHIFY_CHILD_TEST: 'synthetic value',
      ARCHIFY_TEST_CHILD_PID_FILE: files.pidFile },
    stdio: ['pipe', 'pipe', 'pipe'],
    ...extra,
  });
  let stdout = '';
  let stderr = '';
  proc.stdout.on('data', (chunk) => { stdout += chunk; });
  proc.stderr.on('data', (chunk) => { stderr += chunk; });
  const result = once(proc, 'close').then(([code, signal]) => ({ code, signal, stdout, stderr }));
  t.after(() => cleanupSynthetic(proc, result, files));
  return { proc, result, output: () => stdout };
}

async function ready(output) {
  for (let i = 0; i < 250; i += 1) {
    if (output().includes('READY\n')) return;
    await delay(20);
  }
  assert.fail('synthetic child did not become ready');
}

test('child preserves argv, cwd, environment, all streams and nonzero exit', async (t) => {
  const files = await fixture(t, `
    let input = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => input += chunk);
    process.stdin.on('end', () => {
      process.stdout.write(JSON.stringify({args:process.argv.slice(2),cwd:process.cwd(),
        env:process.env.ARCHIFY_CHILD_TEST,input}));
      process.stderr.write('synthetic stderr');
      process.exitCode = 7;
    });
  `);
  const args = ['space path', '', '; literal $()'];
  const { proc, result } = start(t, files, args);
  proc.stdin.end('synthetic stdin\n');
  const outcome = await result;
  assert.equal(outcome.code, 7);
  assert.equal(outcome.signal, null);
  assert.equal(outcome.stderr, 'synthetic stderr');
  assert.deepEqual(JSON.parse(outcome.stdout), {
    args, cwd: await realpath(files.directory), env: 'synthetic value', input: 'synthetic stdin\n',
  });
});

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT']) {
  for (const processGroup of [false, true]) {
    test(`parent ${signal} ${processGroup ? 'process group' : 'PID'} drains child once`,
      { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
        const files = await fixture(t, `
          let count = 0;
          for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
            process.stdout.write('RECEIVED ' + signal + '\\n');
            if (++count === 1) setTimeout(() => {
              process.stdout.write('CLEANED\\n'); process.exit(0);
            }, 200);
            else process.exit(91);
          });
          process.stdout.write('READY\\n');
          setInterval(() => {}, 1000);
        `);
        const { proc, result, output } = start(t, files, [], { detached: true });
        await ready(output);
        if (processGroup) process.kill(-proc.pid, signal);
        else proc.kill(signal);
        // Repeated signals to the wrapper must not activate upstream force-stop.
        await delay(50);
        proc.kill(signal);
        const outcome = await result;
        assert.equal(outcome.signal, signal);
        assert.equal(outcome.code, null);
        assert.equal(outcome.stderr, '');
        const childSignal = signal === 'SIGINT' ? 'SIGINT' : 'SIGTERM';
        assert.equal(outcome.stdout, `READY\nRECEIVED ${childSignal}\nCLEANED\n`);
      });
  }
}

test('child signal exit propagates after forwarding handlers are removed',
  { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
    const files = await fixture(t, `process.kill(process.pid, 'SIGTERM');`);
    const outcome = await start(t, files).result;
    assert.equal(outcome.signal, 'SIGTERM');
    assert.equal(outcome.code, null);
  });

test('forwarding listeners are removed after normal exit and spawn failure', async () => {
  const signals = ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT'];
  const counts = signals.map(signal => process.listenerCount(signal));
  const completion = runChild(process.execPath, ['-e', 'process.exit(0)']);
  assert.ok(Number.isInteger(completion.pid));
  assert.deepEqual(await completion, { code: 0, signal: null, pid: completion.pid });
  await assert.rejects(runChild('/nonexistent/archify-test-executable', []), { code: 'ENOENT' });
  assert.deepEqual(signals.map(signal => process.listenerCount(signal)), counts);
});

for (const processGroup of [false, true]) {
  test(`parent SIGKILL ${processGroup ? 'process group' : 'PID'} drains child on disconnect`,
    { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
      const files = await fixture(t, `
        process.on('SIGTERM', () => {
          process.stdout.write('RECEIVED SIGTERM\\n');
          setTimeout(() => { process.stdout.write('CLEANED\\n'); process.exit(0); }, 100);
        });
        process.stdout.write('READY\\n'); setInterval(() => {}, 1000);
      `);
      const { proc, result, output } = start(t, files, [], { detached: true });
      await ready(output);
      if (processGroup) process.kill(-proc.pid, 'SIGKILL');
      else proc.kill('SIGKILL');
      const outcome = await result;
      assert.equal(outcome.signal, 'SIGKILL');
      assert.equal(outcome.stdout, 'READY\nRECEIVED SIGTERM\nCLEANED\n');
      assert.equal(outcome.stderr, '');
    });
}

test('parent death during drain does not deliver a second shutdown signal',
  { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
    const files = await fixture(t, `
      let count = 0;
      process.on('SIGTERM', () => {
        process.stdout.write('RECEIVED SIGTERM\\n');
        if (++count > 1) { process.stdout.write('FORCED\\n'); process.exit(91); }
        setTimeout(() => { process.stdout.write('CLEANED\\n'); process.exit(0); }, 200);
      });
      process.stdout.write('READY\\n'); setInterval(() => {}, 1000);
    `);
    const { proc, result, output } = start(t, files);
    await ready(output);
    proc.kill('SIGTERM');
    for (let i = 0; i < 250 && !output().includes('RECEIVED'); i += 1) await delay(10);
    assert.match(output(), /RECEIVED SIGTERM/);
    proc.kill('SIGKILL');
    const outcome = await result;
    assert.equal(outcome.signal, 'SIGKILL');
    assert.equal(outcome.stdout, 'READY\nRECEIVED SIGTERM\nCLEANED\n');
  });

test('test teardown bounds a child that ignores graceful cancellation',
  { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
    const files = await fixture(t, `
      process.on('SIGTERM', () => {});
      process.stdout.write('READY\\n'); setInterval(() => {}, 1000);
    `);
    const { proc, result, output } = start(t, files);
    await ready(output);
    const pid = await recordedPid(files.pidFile);
    const started = Date.now();
    await cleanupSynthetic(proc, result, files);
    assert.ok(Date.now() - started < 3000);
    for (let i = 0; i < 100 && alive(pid); i += 1) await delay(10);
    assert.equal(alive(pid), false);
  });

test('inherited preload leaves workers, forks, and Node descendants independent',
  { timeout: 10000 }, async (t) => {
    const files = await fixture(t, `
      import { Worker } from 'node:worker_threads';
      import { fork, spawn } from 'node:child_process';
      import { once } from 'node:events';
      import { fileURLToPath } from 'node:url';
      if (process.env.ARCHIFY_TOOLBOX_LIFETIME_GUARD !== undefined) throw new Error('marker leaked');
      const source = new URL('./descendant.mjs', import.meta.url);
      const worker = new Worker(source);
      const forked = fork(source, [], { stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
      forked.once('message', () => forked.disconnect());
      const spawned = spawn(process.execPath, [...process.execArgv, fileURLToPath(source)], { stdio: 'inherit' });
      const outcomes = await Promise.all([once(worker, 'exit'), once(forked, 'exit'), once(spawned, 'close')]);
      if (outcomes.some(([code]) => code !== 0)) throw new Error('descendant failed');
    `);
    await writeFile(join(files.directory, 'descendant.mjs'), `
      import { isMainThread } from 'node:worker_threads';
      if (process.env.ARCHIFY_TOOLBOX_LIFETIME_GUARD !== undefined) throw new Error('marker leaked');
      if (process.send) {
        process.once('disconnect', () => setTimeout(() => process.stdout.write('FORKED\\n'), 20));
        process.send('ready');
      } else process.stdout.write(isMainThread ? 'SPAWNED\\n' : 'WORKER\\n');
    `);
    const outcome = await start(t, files).result;
    assert.equal(outcome.code, 0);
    assert.equal(outcome.stderr, '');
    assert.deepEqual(outcome.stdout.trim().split('\n').sort(), ['FORKED', 'SPAWNED', 'WORKER']);
  });

test('guard observes a parent disconnect that happened before it loaded',
  { skip: process.platform === 'win32', timeout: 10000 }, async (t) => {
    const files = await fixture(t, `
      process.on('SIGTERM', () => { process.stdout.write('CLEANED\\n'); process.exit(0); });
      process.once('disconnect', () => setTimeout(() => import(${JSON.stringify(guardUrl)}), 30));
      process.stdout.write('READY\\n'); setInterval(() => {}, 1000);
    `);
    const proc = spawn(process.execPath, [files.child], {
      env: { ...process.env, ARCHIFY_TOOLBOX_LIFETIME_GUARD: '1' },
      stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
    });
    await writeFile(files.pidFile, String(proc.pid));
    let stdout = '';
    proc.stdout.on('data', chunk => { stdout += chunk; });
    proc.stderr.resume();
    const result = Promise.all([once(proc, 'exit'), once(proc.stdout, 'end'), once(proc.stderr, 'end')])
      .then(([exit]) => exit);
    t.after(() => cleanupSynthetic(proc, result, files));
    await ready(() => stdout);
    proc.disconnect();
    assert.deepEqual(await result, [0, null]);
    assert.equal(stdout, 'READY\nCLEANED\n');
  });
