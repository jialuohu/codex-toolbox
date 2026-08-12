import assert from 'node:assert/strict';
import test from 'node:test';
import { selectRendererApi, selectTheme } from '../skills/pretty-mermaid/scripts/lib/adapter.mjs';
import * as incompatibleRenderer from './fixtures/incompatible-renderer.mjs';
import * as legacyRenderer from './fixtures/legacy-renderer.mjs';
import * as modernRenderer from './fixtures/modern-renderer.mjs';

test('selects modern renderer exports and discovers added themes', () => {
  const api = selectRendererApi(modernRenderer);
  assert.equal(api.svg.name, 'renderMermaidSVGAsync');
  assert.equal(api.ascii.name, 'renderMermaidASCII');
  assert.deepEqual(api.themeNames, ['future-theme', 'github-light']);
});

test('accepts legacy aliases without checking a package version', () => {
  const api = selectRendererApi(legacyRenderer);
  assert.equal(api.svg.name, 'renderMermaid');
  assert.equal(api.ascii.name, 'renderMermaidAscii');
});

test('defaults to github-light while honoring explicit themes', () => {
  const api = selectRendererApi(modernRenderer);
  assert.equal(selectTheme(api).name, 'github-light');
  assert.equal(selectTheme(api, 'future-theme').name, 'future-theme');
  assert.throws(() => selectTheme(api, 'missing-theme'), /Unknown theme/);
});

test('rejects an incompatible renderer module', () => {
  assert.throws(
    () => selectRendererApi(incompatibleRenderer),
    /no supported SVG renderer/,
  );
});
