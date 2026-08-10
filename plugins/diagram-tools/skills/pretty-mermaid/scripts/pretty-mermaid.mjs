#!/usr/bin/env node
import { availableParallelism } from 'node:os';
import { mkdir, readdir } from 'node:fs/promises';
import { basename, extname, join, resolve } from 'node:path';
import { Worker } from 'node:worker_threads';
import { doctorRuntime } from './lib/active-runtime.mjs';
import { COLOR_OPTION_NAMES, MAX_WORKERS, SETUP_HINT, SUPPORTED_FORMATS } from './lib/constants.mjs';
import { safeError } from './lib/io.mjs';
import { runtimeRoot } from './lib/paths.mjs';
import { loadToolchain, renderFile, rendererCapabilities } from './lib/render.mjs';
import { rollbackRuntime, updateRuntime } from './lib/runtime-manager.mjs';

const BOOLEAN_FLAGS = new Set(['transparent', 'use-ascii', 'strict', 'json']);
const VALUE_FLAGS = new Set([
  'input',
  'output',
  'input-dir',
  'output-dir',
  'format',
  'theme',
  'scale',
  'workers',
  'font',
  ...COLOR_OPTION_NAMES,
]);

class UsageError extends Error {
  constructor(message) {
    super(message);
    this.name = 'UsageError';
  }
}

function parseOptions(args) {
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (!argument.startsWith('--')) throw new UsageError(`Unexpected argument: ${argument}`);
    const equals = argument.indexOf('=');
    const name = argument.slice(2, equals === -1 ? undefined : equals);
    if (BOOLEAN_FLAGS.has(name)) {
      if (equals !== -1) throw new UsageError(`--${name} does not take a value`);
      options[name] = true;
      continue;
    }
    if (!VALUE_FLAGS.has(name)) throw new UsageError(`Unknown option: --${name}`);
    const value = equals === -1 ? args[++index] : argument.slice(equals + 1);
    if (value === undefined || value.startsWith('--')) {
      throw new UsageError(`--${name} requires a value`);
    }
    options[name] = value;
  }
  if (options.scale !== undefined) options.scale = Number(options.scale);
  if (options.workers !== undefined) options.workers = Number(options.workers);
  options.useAscii = Boolean(options['use-ascii']);
  delete options['use-ascii'];
  return options;
}

function renderOptions(options) {
  if (!options.format || !SUPPORTED_FORMATS.includes(options.format)) {
    throw new UsageError(`--format must be one of: ${SUPPORTED_FORMATS.join(', ')}`);
  }
  if (
    options.scale !== undefined &&
    (!Number.isInteger(options.scale) || options.scale < 1 || options.scale > 4)
  ) {
    throw new UsageError('--scale must be an integer from 1 through 4');
  }
  return {
    format: options.format,
    theme: options.theme,
    scale: options.scale,
    transparent: Boolean(options.transparent),
    useAscii: Boolean(options.useAscii),
    font: options.font,
    ...Object.fromEntries(COLOR_OPTION_NAMES.map((name) => [name, options[name]])),
  };
}

function print(value, json = false) {
  if (json || typeof value !== 'string') process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
  else process.stdout.write(`${value}\n`);
}

function runWorker(task) {
  return new Promise((resolvePromise, reject) => {
    const worker = new Worker(new URL('./batch-worker.mjs', import.meta.url), { workerData: task });
    worker.once('message', resolvePromise);
    worker.once('error', reject);
    worker.once('exit', (code) => {
      if (code !== 0) reject(new Error(`Batch worker exited with code ${code}`));
    });
  });
}

async function batch(options) {
  if (!options['input-dir'] || !options['output-dir']) {
    throw new UsageError('batch requires --input-dir and --output-dir');
  }
  const formatOptions = renderOptions(options);
  const inputDirectory = resolve(options['input-dir']);
  const outputDirectory = resolve(options['output-dir']);
  if (inputDirectory === outputDirectory) {
    throw new UsageError('Batch input and output directories must differ');
  }
  const workers = options.workers ?? Math.min(4, availableParallelism());
  if (!Number.isInteger(workers) || workers < 1 || workers > MAX_WORKERS) {
    throw new UsageError(`--workers must be an integer from 1 through ${MAX_WORKERS}`);
  }
  const files = (await readdir(inputDirectory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && extname(entry.name).toLowerCase() === '.mmd')
    .map((entry) => entry.name)
    .sort();
  if (files.length === 0) throw new UsageError('Batch input directory contains no .mmd files');
  await mkdir(outputDirectory, { recursive: true });
  const extension = formatOptions.format === 'ascii' ? '.txt' : `.${formatOptions.format}`;
  const tasks = files.map((file) => ({
    runtimeRoot: runtimeRoot(),
    input: join(inputDirectory, file),
    output: join(outputDirectory, `${basename(file, '.mmd')}${extension}`),
    options: formatOptions,
  }));
  let cursor = 0;
  const results = [];
  const loops = Array.from({ length: Math.min(workers, tasks.length) }, async () => {
    while (cursor < tasks.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await runWorker(tasks[index]);
    }
  });
  await Promise.all(loops);
  const failures = results.filter((result) => !result.ok);
  if (failures.length > 0) {
    const detail = failures.map((failure) => `${failure.input}: ${failure.error.message}`).join('; ');
    throw new Error(`Batch rendering failed: ${detail}`);
  }
  return {
    ok: true,
    count: results.length,
    workers: Math.min(workers, tasks.length),
    outputs: results.map((result) => result.result.output),
  };
}

async function main() {
  const [command = 'help', ...args] = process.argv.slice(2);
  const options = parseOptions(args);
  if (command === 'help' || command === '--help') {
    print(
      'Usage: pretty-mermaid <render|batch|themes|capabilities|doctor|update|rollback> [options]',
    );
    return;
  }
  if (command === 'doctor') {
    const report = await doctorRuntime(runtimeRoot());
    if (options.json) print(report, true);
    else print(report.ok ? `ready: beautiful-mermaid ${report.version}` : `${report.error}\n${SETUP_HINT}`);
    if (!report.ok) process.exitCode = 3;
    return;
  }
  if (command === 'update') {
    const result = await updateRuntime({ root: runtimeRoot(), strict: Boolean(options.strict) });
    print(result, true);
    return;
  }
  if (command === 'rollback') {
    print(await rollbackRuntime({ root: runtimeRoot() }), true);
    return;
  }
  if (command === 'batch') {
    print(await batch(options), Boolean(options.json));
    return;
  }

  const toolchain = await loadToolchain(runtimeRoot());
  if (command === 'themes') {
    const themes = [...toolchain.api.themeNames];
    if (options.json) print({ themes }, true);
    else print(themes.join('\n'));
    return;
  }
  if (command === 'capabilities') {
    print(rendererCapabilities(toolchain), true);
    return;
  }
  if (command === 'render') {
    if (!options.input) throw new UsageError('render requires --input');
    const result = await renderFile(
      toolchain,
      options.input,
      options.output,
      renderOptions(options),
    );
    if (result.content !== undefined) process.stdout.write(result.content);
    else print(result, true);
    return;
  }
  throw new UsageError(`Unknown command: ${command}`);
}

try {
  await main();
} catch (error) {
  const detail = safeError(error);
  if (error?.result) process.stdout.write(`${JSON.stringify(error.result, null, 2)}\n`);
  process.stderr.write(`${detail.message}\n`);
  if (error instanceof UsageError) process.exitCode = 2;
  else if (error?.exitCode) process.exitCode = error.exitCode;
  else if (process.argv[2] === 'rollback') process.exitCode = 5;
  else if (/runtime|setup|installed|receipt/i.test(detail.message)) process.exitCode = 3;
  else if (/candidate|rollback|conformance/i.test(detail.message)) process.exitCode = 5;
  else process.exitCode = 4;
}
