import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { loadRuntimeDependencies } from '../skills/pretty-mermaid/scripts/lib/runtime-deps.mjs';
import {
  inspectPng,
  normalizeSvg,
  renderPng,
} from '../skills/pretty-mermaid/scripts/lib/svg-normalizer.mjs';

const bootstrap = resolve('runtime/bootstrap');
const dependencies = loadRuntimeDependencies(bootstrap);

test('materializes CSS variables and color-mix into a self-contained SVG', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" style="--bg:#ffffff;--fg:#000000;background:var(--bg)">
    <style>@import url('https://example.invalid/font.css');svg{--fill:color-mix(in srgb,var(--fg) 10%,var(--bg))}text{fill:var(--fg)}</style>
    <rect x="20" y="20" width="80" height="40" fill="var(--fill)" stroke="var(--fg)"/>
    <text x="60" y="45">Healthy</text>
  </svg>`;
  const result = normalizeSvg(input, { transparent: false }, dependencies);
  assert.doesNotMatch(result.svg, /@import|\bvar\s*\(|color-mix\s*\(/i);
  assert.match(result.svg, /data-pretty-mermaid-background="true"/);
  const png = renderPng(result.svg, { scale: 1, background: result.background }, dependencies);
  const inspection = inspectPng(png, dependencies);
  assert.equal(inspection.width, 120);
  assert.equal(inspection.height, 80);
  assert.ok(inspection.differentPixels > 10);
});

test('rejects executable SVG attributes', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect onload="alert(1)" width="10" height="10"/></svg>`;
  assert.throws(
    () => normalizeSvg(input, { transparent: false }, dependencies),
    /Unsafe SVG event attribute/,
  );
});

test('rejects unsupported dynamic CSS instead of emitting a broken PNG', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect fill="var(--missing)" width="10" height="10"/></svg>`;
  assert.throws(
    () => normalizeSvg(input, { transparent: false }, dependencies),
    /Unresolved CSS custom property/,
  );
});

test('rejects external paint resources and active data images', () => {
  const remote = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect fill="url(https://example.invalid/paint.svg#x)" width="10" height="10"/></svg>`;
  assert.throws(
    () => normalizeSvg(remote, { transparent: false }, dependencies),
    /External CSS URL is not allowed/,
  );

  const activeData = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><image href="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9J2FsZXJ0KDEpJy8+"/></svg>`;
  assert.throws(
    () => normalizeSvg(activeData, { transparent: false }, dependencies),
    /External SVG reference is not allowed/,
  );
});

test('rejects CSS at-rules the normalizer cannot safely materialize', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>@supports (display:grid){rect{fill:red}}</style><rect width="10" height="10"/></svg>`;
  assert.throws(
    () => normalizeSvg(input, { transparent: false }, dependencies),
    /Unsupported CSS at-rule/,
  );
});

test('materializes underspecified color mixes with the required alpha multiplier', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect fill="color-mix(in srgb,red 20%,blue 20%)" width="10" height="10"/></svg>`;
  const result = normalizeSvg(input, { transparent: true }, dependencies);
  assert.match(result.svg, /rgba\(128,0,128,0\.4\)/);
});

test('does not mistake literal CSS syntax in accessible text for active CSS', () => {
  const input = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20" aria-label="Use var(--token)"><text y="15">Use var(--token) and @import</text></svg>`;
  const result = normalizeSvg(input, { transparent: false }, dependencies);
  assert.match(result.svg, /Use var\(--token\) and @import/);
  assert.match(result.svg, /aria-label="Use var\(--token\)"/);
});

test('rejects scoped custom properties and active SVG animation', () => {
  const scoped = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>.node{--paint:red;fill:var(--paint)}</style><rect class="node" width="10" height="10"/></svg>`;
  assert.throws(
    () => normalizeSvg(scoped, { transparent: false }, dependencies),
    /Scoped CSS custom property is not supported/,
  );
  const animated = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"><set attributeName="fill" to="red"/></rect></svg>`;
  assert.throws(
    () => normalizeSvg(animated, { transparent: false }, dependencies),
    /Unsafe SVG element: set/,
  );
});
