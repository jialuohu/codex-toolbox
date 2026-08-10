import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

function firstFunction(module, names) {
  for (const name of names) {
    if (typeof module[name] === 'function') return { name, fn: module[name] };
  }
  return null;
}

export function selectRendererApi(module) {
  if (!module || typeof module !== 'object') {
    throw new Error('Beautiful Mermaid did not expose a module object');
  }

  const svg = firstFunction(module, [
    'renderMermaidSVG',
    'renderMermaidSVGAsync',
    'renderMermaid',
  ]);
  const ascii = firstFunction(module, ['renderMermaidASCII', 'renderMermaidAscii']);
  if (!svg) throw new Error('Beautiful Mermaid exposes no supported SVG renderer');
  if (!ascii) throw new Error('Beautiful Mermaid exposes no supported ASCII renderer');

  const themes = module.THEMES;
  if (!themes || typeof themes !== 'object' || Array.isArray(themes)) {
    throw new Error('Beautiful Mermaid exposes no THEMES object');
  }
  const themeNames = Object.keys(themes).filter((name) => {
    const theme = themes[name];
    return theme && typeof theme === 'object';
  });
  if (themeNames.length === 0) throw new Error('Beautiful Mermaid exposes no usable themes');

  return {
    svg,
    ascii,
    themes,
    themeNames: themeNames.sort(),
    defaults:
      module.DEFAULTS && typeof module.DEFAULTS === 'object' ? module.DEFAULTS : {},
  };
}

export async function loadRenderer(releaseDirectory) {
  const packageRoot = join(resolve(releaseDirectory), 'node_modules', 'beautiful-mermaid');
  const packageMetadata = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
  if (packageMetadata.name !== 'beautiful-mermaid') {
    throw new Error('Could not locate Beautiful Mermaid package metadata');
  }
  const exportEntry =
    packageMetadata.exports?.['.']?.import ??
    packageMetadata.exports?.['.'] ??
    packageMetadata.module ??
    packageMetadata.main;
  if (typeof exportEntry !== 'string' || !exportEntry.startsWith('./')) {
    throw new Error('Beautiful Mermaid exposes no importable package entry');
  }
  const entry = resolve(packageRoot, exportEntry);
  if (!entry.startsWith(`${packageRoot}/`)) {
    throw new Error('Beautiful Mermaid package entry escapes its package root');
  }
  const module = await import(`${pathToFileURL(entry).href}?release=${encodeURIComponent(packageMetadata.version)}`);
  const api = selectRendererApi(module);

  return {
    ...api,
    module,
    packageVersion: packageMetadata.version,
    packageEntry: entry,
  };
}

export function selectTheme(api, requestedName) {
  if (requestedName) {
    if (!Object.hasOwn(api.themes, requestedName)) {
      throw new Error(
        `Unknown theme '${requestedName}'. Available themes: ${api.themeNames.join(', ')}`,
      );
    }
    return { name: requestedName, options: { ...api.themes[requestedName] } };
  }

  const preferred = ['github-light', 'zinc-light'].find((name) =>
    Object.hasOwn(api.themes, name),
  );
  const name = preferred ?? api.themeNames[0];
  return { name, options: { ...api.themes[name] } };
}

export async function renderSvg(api, source, options) {
  const result = await Promise.resolve(api.svg.fn(source, options));
  if (typeof result !== 'string' || !result.trimStart().startsWith('<svg')) {
    throw new Error(`${api.svg.name} did not return an SVG string`);
  }
  return result;
}

export async function renderAscii(api, source, options) {
  const result = await Promise.resolve(api.ascii.fn(source, options));
  if (typeof result !== 'string' || !result.trim()) {
    throw new Error(`${api.ascii.name} did not return nonempty text`);
  }
  return result;
}
