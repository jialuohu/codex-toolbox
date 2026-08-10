import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadRenderer, renderAscii, renderSvg, selectTheme } from './adapter.mjs';
import { CONTRACT_VERSION } from './constants.mjs';
import { fixturesDirectory } from './paths.mjs';
import { loadRuntimeDependencies } from './runtime-deps.mjs';
import { inspectPng, normalizeSvg, renderPng, svgDimensions } from './svg-normalizer.mjs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function themePair(api) {
  const light =
    api.themeNames.find((name) => /light/i.test(name)) ??
    api.themeNames.find((name) => !/dark|dracula|mocha|night/i.test(name)) ??
    api.themeNames[0];
  const dark =
    api.themeNames.find((name) => /dark|dracula|mocha|night/i.test(name)) ??
    api.themeNames.at(-1);
  return [...new Set([light, dark])];
}

function svgText(svg, dependencies) {
  return new dependencies.DOMParser().parseFromString(svg, 'image/svg+xml').documentElement.textContent;
}

function validatePng(png, dimensions, dependencies, fixtureName) {
  const inspection = inspectPng(png, dependencies);
  assert(Math.abs(inspection.width - Math.round(dimensions.width)) <= 2, `${fixtureName}: PNG width drift`);
  assert(
    Math.abs(inspection.height - Math.round(dimensions.height)) <= 2,
    `${fixtureName}: PNG height drift`,
  );
  assert(inspection.sampledColors >= 2, `${fixtureName}: PNG has too few colors`);
  assert(inspection.differentPixels >= 10, `${fixtureName}: PNG is blank`);
  if (inspection.foregroundBounds) {
    const bounds = inspection.foregroundBounds;
    assert(
      bounds.minX > 0 &&
        bounds.minY > 0 &&
        bounds.maxX < inspection.width - 1 &&
        bounds.maxY < inspection.height - 1,
      `${fixtureName}: PNG foreground touches its canvas edge`,
    );
  }
  return inspection;
}

export async function runContract(releaseDirectory) {
  const started = Date.now();
  const manifest = JSON.parse(await readFile(join(fixturesDirectory, 'manifest.json'), 'utf8'));
  const api = await loadRenderer(releaseDirectory);
  const dependencies = loadRuntimeDependencies(releaseDirectory);
  const themes = themePair(api);
  const fixtureResults = [];

  for (const fixture of manifest.fixtures) {
    const source = await readFile(join(fixturesDirectory, fixture.file), 'utf8');
    const themeResults = [];
    for (const themeName of themes) {
      const selected = selectTheme(api, themeName);
      const raw = await renderSvg(api, source, selected.options);
      const normalized = normalizeSvg(
        raw,
        { transparent: false, background: selected.options.bg },
        dependencies,
      );
      assert(!/\b(?:NaN|Infinity)\b/.test(normalized.svg), `${fixture.file}: non-finite SVG output`);
      const text = svgText(normalized.svg, dependencies);
      for (const label of fixture.labels) {
        assert(text.includes(label), `${fixture.file}: SVG is missing label '${label}'`);
      }
      const dimensions = svgDimensions(normalized.svg, dependencies);
      const png = renderPng(
        normalized.svg,
        { scale: 1, background: normalized.background },
        dependencies,
      );
      const pngInspection = validatePng(png, dimensions, dependencies, fixture.file);
      themeResults.push({ theme: themeName, dimensions, png: pngInspection });
    }

    const ascii = await renderAscii(api, source, { useAscii: false, colorMode: 'none' });
    for (const label of fixture.labels.slice(0, 2)) {
      assert(ascii.includes(label), `${fixture.file}: ASCII is missing label '${label}'`);
    }
    assert(!/\b(?:undefined|NaN)\b/.test(ascii), `${fixture.file}: malformed ASCII output`);
    fixtureResults.push({ file: fixture.file, themes: themeResults, asciiLines: ascii.split('\n').length });
  }

  const themeSource = 'flowchart LR\n  Alpha[Alpha] --> Beta[Beta]';
  for (const themeName of api.themeNames) {
    const selected = selectTheme(api, themeName);
    const raw = await renderSvg(api, themeSource, selected.options);
    const normalized = normalizeSvg(
      raw,
      { transparent: false, background: selected.options.bg },
      dependencies,
    );
    const text = svgText(normalized.svg, dependencies);
    assert(text.includes('Alpha') && text.includes('Beta'), `Theme ${themeName} failed a smoke render`);
  }

  const malicious =
    'flowchart LR\n  A["<img src=x onerror=alert(1)>"] --> B["safe & sound"]';
  const maliciousRaw = await renderSvg(api, malicious, selectTheme(api).options);
  const maliciousNormalized = normalizeSvg(
    maliciousRaw,
    { transparent: false },
    dependencies,
  );
  assert(!/<(?:script|foreignObject|img)\b/i.test(maliciousNormalized.svg), 'Unsafe label became markup');

  let cjkAsciiProbe = { ok: true };
  try {
    const value = await renderAscii(api, 'flowchart LR\n  A[你好🙂] --> B[完成]', {
      useAscii: false,
      colorMode: 'none',
    });
    cjkAsciiProbe = { ok: value.includes('你好') && value.includes('完成') };
  } catch (error) {
    cjkAsciiProbe = { ok: false, detail: error instanceof Error ? error.message : String(error) };
  }

  return {
    ok: true,
    contractVersion: CONTRACT_VERSION,
    beautifulMermaidVersion: api.packageVersion,
    durationMs: Date.now() - started,
    capabilities: {
      formats: ['svg', 'png', 'ascii'],
      exports: { svg: api.svg.name, ascii: api.ascii.name },
      themes: api.themeNames,
      coreFixtures: manifest.fixtures.map((fixture) => fixture.file),
    },
    fixtures: fixtureResults,
    probes: { cjkAscii: cjkAsciiProbe },
  };
}
