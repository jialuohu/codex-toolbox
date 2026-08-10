import { parentPort, workerData } from 'node:worker_threads';
import { loadToolchain, renderFile } from './lib/render.mjs';
import { safeError } from './lib/io.mjs';

try {
  const toolchain = await loadToolchain(workerData.runtimeRoot);
  const result = await renderFile(
    toolchain,
    workerData.input,
    workerData.output,
    workerData.options,
  );
  parentPort.postMessage({ ok: true, result });
} catch (error) {
  parentPort.postMessage({ ok: false, error: safeError(error), input: workerData.input });
}
