#!/usr/bin/env node
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { basename, join, resolve } from 'node:path';
import { fixturesDirectory, runtimeRoot } from './lib/paths.mjs';
import { loadToolchain, renderSource } from './lib/render.mjs';
import { inspectPng, renderPng } from './lib/svg-normalizer.mjs';

const [outputArgument, requestedTheme] = process.argv.slice(2);
if (!outputArgument || process.argv.length > 4) {
  process.stderr.write('Usage: contact-sheet.mjs OUTPUT_DIR [THEME]\n');
  process.exit(2);
}

const outputDirectory = resolve(outputArgument);
const svgDirectory = join(outputDirectory, 'svg');
const pngDirectory = join(outputDirectory, 'png');
await mkdir(svgDirectory, { recursive: true });
await mkdir(pngDirectory, { recursive: true });

const toolchain = await loadToolchain(runtimeRoot());
const theme = requestedTheme ??
  (toolchain.api.themeNames.includes('tokyo-night') ? 'tokyo-night' : toolchain.api.themeNames[0]);
const manifest = JSON.parse(await readFile(join(fixturesDirectory, 'manifest.json'), 'utf8'));
const rendered = [];

for (const fixture of manifest.fixtures) {
  const source = await readFile(join(fixturesDirectory, fixture.file), 'utf8');
  const name = basename(fixture.file, '.mmd');
  const options = { theme, transparent: false };
  const svg = await renderSource(toolchain, source, { ...options, format: 'svg' });
  const png = await renderSource(toolchain, source, { ...options, format: 'png', scale: 1 });
  const svgPath = join(svgDirectory, `${name}.svg`);
  const pngPath = join(pngDirectory, `${name}.png`);
  await writeFile(svgPath, svg.content);
  await writeFile(pngPath, png.content);
  const decoded = toolchain.dependencies.PNG.sync.read(png.content);
  rendered.push({ name, svg: svg.content, png: png.content, width: decoded.width, height: decoded.height });
}

const columns = 2;
const padding = 28;
const labelHeight = 34;
const cellWidth = Math.max(...rendered.map((item) => item.width));
const rowCount = Math.ceil(rendered.length / columns);
const rowHeights = Array.from({ length: rowCount }, (_, row) =>
  Math.max(...rendered.slice(row * columns, row * columns + columns).map((item) => item.height)),
);
const sheetWidth = padding + columns * (cellWidth + padding);
const sheetHeight = padding + rowHeights.reduce((sum, height) => sum + labelHeight + height + padding, 0);
const rowOffsets = [];
let nextY = padding;
for (const height of rowHeights) {
  rowOffsets.push(nextY);
  nextY += labelHeight + height + padding;
}

const escapeXml = (value) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const cells = rendered.map((item, index) => {
  const column = index % columns;
  const row = Math.floor(index / columns);
  const x = padding + column * (cellWidth + padding) + (cellWidth - item.width) / 2;
  const y = rowOffsets[row];
  const encoded = item.png.toString('base64');
  return `<g><text x="${padding + column * (cellWidth + padding)}" y="${y + 22}">${escapeXml(item.name)}</text><image x="${x}" y="${y + labelHeight}" width="${item.width}" height="${item.height}" href="data:image/png;base64,${encoded}"/></g>`;
});
const contactSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${sheetWidth} ${sheetHeight}" width="${sheetWidth}" height="${sheetHeight}"><rect width="100%" height="100%" fill="#1a1b26"/><style>text{font:600 18px ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#c0caf5}</style>${cells.join('')}</svg>\n`;
const contactPng = renderPng(
  contactSvg,
  { scale: 1, background: '#1a1b26' },
  toolchain.dependencies,
);
const inspection = inspectPng(contactPng, toolchain.dependencies);
if (inspection.differentPixels < 100 || inspection.sampledColors < 2) {
  throw new Error('Contact sheet is blank or nearly blank');
}

const svgContactPath = join(outputDirectory, 'contact-sheet.svg');
const pngContactPath = join(outputDirectory, 'contact-sheet.png');
await writeFile(svgContactPath, contactSvg);
await writeFile(pngContactPath, contactPng);
process.stdout.write(`${JSON.stringify({
  ok: true,
  theme,
  fixtures: rendered.map((item) => item.name),
  svg: svgContactPath,
  png: pngContactPath,
  width: inspection.width,
  height: inspection.height,
}, null, 2)}\n`);
