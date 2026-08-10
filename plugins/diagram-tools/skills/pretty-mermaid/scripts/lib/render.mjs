import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, extname, resolve } from 'node:path';
import { COLOR_OPTION_NAMES, CONTRACT_VERSION, SUPPORTED_FORMATS } from './constants.mjs';
import {
  loadRenderer,
  renderAscii as renderAsciiWithAdapter,
  renderSvg as renderSvgWithAdapter,
  selectTheme,
} from './adapter.mjs';
import { resolveActiveRelease } from './active-runtime.mjs';
import { loadRuntimeDependencies } from './runtime-deps.mjs';
import { inspectPng, normalizeSvg, renderPng, svgDimensions } from './svg-normalizer.mjs';

function expectedExtension(format) {
  return format === 'ascii' ? '.txt' : `.${format}`;
}

function validateOutputPath(format, output) {
  if (!output && format !== 'ascii') throw new Error(`${format.toUpperCase()} output requires --output`);
  if (!output) return;
  const actual = extname(output).toLowerCase();
  const expected = expectedExtension(format);
  if (actual !== expected) {
    throw new Error(`${format} output must use the ${expected} extension, not ${actual || '(none)'}`);
  }
}

async function writeAtomic(path, content) {
  const absolute = resolve(path);
  await mkdir(dirname(absolute), { recursive: true });
  const temporary = `${absolute}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, content);
  await rename(temporary, absolute);
}

export async function loadToolchain(runtimeRoot) {
  const { manifest, releaseDirectory } = await resolveActiveRelease(runtimeRoot);
  const api = await loadRenderer(releaseDirectory);
  if (api.packageVersion !== manifest.version) {
    throw new Error('Loaded Beautiful Mermaid version does not match the active receipt');
  }
  const dependencies = loadRuntimeDependencies(releaseDirectory);
  return { manifest, releaseDirectory, api, dependencies };
}

export function rendererCapabilities(toolchain) {
  return {
    contractVersion: CONTRACT_VERSION,
    beautifulMermaidVersion: toolchain.api.packageVersion,
    integrity: toolchain.manifest.integrity,
    formats: [...SUPPORTED_FORMATS],
    exports: {
      svg: toolchain.api.svg.name,
      ascii: toolchain.api.ascii.name,
    },
    themes: [...toolchain.api.themeNames],
    coreFixtures: [...(toolchain.manifest.capabilities?.coreFixtures ?? [])],
  };
}

function svgOptions(toolchain, options) {
  const { api } = toolchain;
  const theme = selectTheme(api, options.theme);
  const result = { ...theme.options };
  for (const name of COLOR_OPTION_NAMES) {
    if (options[name] !== undefined) {
      if (!toolchain.dependencies.parseColor(options[name])) {
        throw new Error(`--${name} must be a concrete CSS color`);
      }
      result[name] = options[name];
    }
  }
  if (options.font) {
    if (!/^[\p{L}\p{N} ._-]{1,80}$/u.test(options.font)) {
      throw new Error('--font must be one plain font-family name');
    }
    result.font = options.font;
  }
  result.transparent = Boolean(options.transparent);
  return { theme: theme.name, options: result };
}

export async function renderSource(toolchain, source, options) {
  if (!SUPPORTED_FORMATS.includes(options.format)) {
    throw new Error(`Unsupported format: ${options.format}`);
  }
  if (options.format === 'ascii') {
    if (options.theme) throw new Error('--theme is not supported for ASCII output');
    const text = await renderAsciiWithAdapter(toolchain.api, source, {
      useAscii: Boolean(options.useAscii),
      colorMode: 'none',
    });
    return { format: 'ascii', content: text, metadata: {} };
  }

  const selected = svgOptions(toolchain, options);
  const rendered = await renderSvgWithAdapter(toolchain.api, source, selected.options);
  const normalized = normalizeSvg(
    rendered,
    {
      transparent: Boolean(options.transparent),
      background: selected.options.bg,
    },
    toolchain.dependencies,
  );
  const dimensions = svgDimensions(normalized.svg, toolchain.dependencies);
  if (options.format === 'svg') {
    return {
      format: 'svg',
      content: `${normalized.svg}\n`,
      metadata: { ...dimensions, theme: selected.theme },
    };
  }

  const scale = options.scale ?? 2;
  if (!Number.isInteger(scale) || scale < 1 || scale > 4) {
    throw new Error('--scale must be an integer from 1 through 4');
  }
  const png = renderPng(
    normalized.svg,
    { scale, background: normalized.background },
    toolchain.dependencies,
  );
  const pngInspection = inspectPng(png, toolchain.dependencies);
  if (pngInspection.differentPixels < 10 || pngInspection.sampledColors < 2) {
    throw new Error('PNG rendering produced a blank or nearly blank image');
  }
  return {
    format: 'png',
    content: png,
    metadata: { ...dimensions, ...pngInspection, scale, theme: selected.theme },
  };
}

export async function renderFile(toolchain, input, output, options) {
  const absoluteInput = resolve(input);
  if (extname(absoluteInput).toLowerCase() !== '.mmd') {
    throw new Error('Input must be a .mmd file');
  }
  validateOutputPath(options.format, output);
  if (output && resolve(output) === absoluteInput) throw new Error('Output must not overwrite Mermaid source');
  const source = await readFile(absoluteInput, 'utf8');
  if (!source.trim()) throw new Error('Mermaid source is empty');
  const rendered = await renderSource(toolchain, source, options);
  if (output) await writeAtomic(output, rendered.content);
  return {
    input: absoluteInput,
    output: output ? resolve(output) : null,
    ...rendered.metadata,
    format: rendered.format,
    ...(output ? {} : { content: rendered.content }),
  };
}
