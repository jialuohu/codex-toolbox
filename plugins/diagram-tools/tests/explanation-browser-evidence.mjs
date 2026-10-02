#!/usr/bin/env node
// Optional fixture-only browser checks. Uses the already-pinned Archify CDP
// test helper; no production dependency, installation, or publishing behavior.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const plugin = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const fixture = join(plugin, 'tests/fixtures/explanation-artifacts');

async function main() {
  const [runtimePath, outputPath, ...extra] = process.argv.slice(2);
  assert(runtimePath && outputPath && extra.length === 0,
    'Usage: explanation-browser-evidence.mjs RUNTIME_INFO_JSON NEW_OUTPUT_DIRECTORY');
  const runtime = JSON.parse(await readFile(runtimePath, 'utf8'));
  const pin = JSON.parse(await readFile(join(plugin, 'runtime/archify/release.json'), 'utf8'));
  assert(runtime.ok && runtime.status === 'ready', 'Archify helper runtime is unavailable');
  assert.equal(runtime.version, pin.version);
  assert.equal(runtime.sha256, pin.archive.sha256);
  const { ChromeVisualBrowser, findChrome } = await import(pathToFileURL(join(dirname(runtime.cliPath), 'visual-check.mjs')).href);
  assert.equal(typeof ChromeVisualBrowser, 'function');
  const chrome = findChrome();
  assert(chrome, 'Chrome/Chromium is required; browser interaction remains unverified');
  const output = resolve(outputPath);
  await mkdir(output); // Fresh output only; never accept stale screenshots.
  const files = new Map(await Promise.all([
    ['/', 'queue.html', 'text/html; charset=utf-8'],
    ['/queue-model.mjs', 'queue-model.mjs', 'text/javascript; charset=utf-8'],
  ].map(async ([url, filename, contentType]) => [url, { bytes: await readFile(join(fixture, filename)), contentType }])));
  const server = createServer((request, response) => {
    const file = files.get(request.url);
    if (!file) { response.writeHead(404); response.end(); return; }
    response.writeHead(200, { 'Content-Type': file.contentType, 'Cache-Control': 'no-store' });
    response.end(file.bytes);
  });
  await new Promise((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolveListen);
  });
  let browser;
  const captures = [];
  try {
    browser = new ChromeVisualBrowser(chrome);
    const session = await browser.sessionPromise;
    const send = (method, params = {}) => browser.cdp.send(method, params, session);
    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
      return result.result?.value;
    };
    const loaded = browser.cdp.waitFor('Page.loadEventFired', session);
    const navigation = await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
    assert(!navigation.errorText, navigation.errorText);
    await loaded;
    for (const width of [320, 736]) {
      for (const theme of ['light', 'dark']) {
        await send('Emulation.setDeviceMetricsOverride', { width, height: 520, deviceScaleFactor: 1, mobile: false });
        await send('Emulation.setEmulatedMedia', { features: [
          { name: 'prefers-color-scheme', value: theme },
          { name: 'prefers-reduced-motion', value: 'reduce' },
        ] });
        await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
        assert.equal(await evaluate("document.getElementById('summary').textContent"),
          'B starts at 3 s, finishes at 5 s, and waits 2 s.');
        await evaluate("document.getElementById('arrival').focus()");
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
        assert.equal(await evaluate("document.getElementById('arrival').value"), '2');
        assert.equal(await evaluate("document.getElementById('summary').textContent"),
          'B starts at 3 s, finishes at 5 s, and waits 1 s.');
        // Boundary: keyboard End moves B after A finishes, eliminating its wait.
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'End', code: 'End', windowsVirtualKeyCode: 35 });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'End', code: 'End', windowsVirtualKeyCode: 35 });
        assert.equal(await evaluate("document.getElementById('summary').textContent"),
          'B starts at 5 s, finishes at 7 s, and waits 0 s.');
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
        assert.equal(await evaluate('document.activeElement.id'), 'reset');
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r', unmodifiedText: '\r' });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
        await evaluate("new Promise(resolve => requestAnimationFrame(resolve))");
        assert.equal(await evaluate("document.getElementById('arrival').value"), '1');
        assert.equal(await evaluate("document.getElementById('summary').textContent"),
          'B starts at 3 s, finishes at 5 s, and waits 2 s.');
        const layout = await evaluate(`(() => {
          const labels = [...document.querySelectorAll('svg text')].map(element => {
            const box = element.getBoundingClientRect();
            return {left: box.left, right: box.right, width: box.width};
          });
          return {width: innerWidth, scroll: document.documentElement.scrollWidth, labels,
            animations: document.getAnimations().length,
            textAlternative: document.getElementById('timeline-description').textContent,
            live: document.getElementById('summary').getAttribute('aria-live')};
        })()`);
        assert(layout.scroll <= width, 'Unexpected horizontal overflow');
        assert(layout.labels.every(label => label.width > 0 && label.left >= 0 && label.right <= width), 'SVG text clips the viewport');
        assert.equal(layout.animations, 0);
        assert.equal(layout.live, 'polite');
        assert(layout.textAlternative.includes('waits 2 s'));
        const filename = `queue-${width}-${theme}.png`;
        const capture = await send('Page.captureScreenshot', { format: 'png' });
        assert(capture.data, 'Empty browser capture');
        const bytes = Buffer.from(capture.data, 'base64');
        await writeFile(join(output, filename), bytes, { flag: 'wx' });
        captures.push({ file: filename, width, theme, sha256: createHash('sha256').update(bytes).digest('hex') });
      }
    }
    const receipt = { status: 'passed', scope: 'synthetic_fixture_only', browser_interaction: 'passed',
      checks: ['ordinary input', 'idle-server boundary', 'keyboard range', 'keyboard reset', 'narrow layout', 'light/dark', 'reduced motion', 'text alternative'],
      captures, visual_review: 'pending', learning_effectiveness: 'unverified' };
    await writeFile(join(output, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`, { flag: 'wx' });
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
  } finally {
    try {
      if (browser) await browser.close();
    } finally {
      await new Promise((resolveClose, reject) => server.close(error => error ? reject(error) : resolveClose()));
    }
  }
}

main().catch(error => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
