import { createRequire } from 'node:module';
import { join } from 'node:path';

export function loadRuntimeDependencies(releaseDirectory) {
  const requireFromRelease = createRequire(join(releaseDirectory, 'package.json'));
  const postcss = requireFromRelease('postcss');
  const valueParser = requireFromRelease('postcss-value-parser');
  const xmldom = requireFromRelease('@xmldom/xmldom');
  const culori = requireFromRelease('culori');
  const { Resvg } = requireFromRelease('@resvg/resvg-js');
  const { PNG } = requireFromRelease('pngjs');

  return {
    postcss,
    valueParser,
    DOMParser: xmldom.DOMParser,
    XMLSerializer: xmldom.XMLSerializer,
    parseColor: culori.parse,
    toRgb: culori.converter('rgb'),
    Resvg,
    PNG,
  };
}
