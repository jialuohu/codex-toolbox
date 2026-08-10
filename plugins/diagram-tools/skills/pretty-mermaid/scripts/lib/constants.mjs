export const CONTRACT_VERSION = 1;
export const RUNTIME_SCHEMA_VERSION = 1;
export const MIN_NODE_MAJOR = 20;
export const MAX_WORKERS = 16;

export const WRAPPER_DEPENDENCIES = Object.freeze([
  '@resvg/resvg-js',
  '@xmldom/xmldom',
  'culori',
  'pngjs',
  'postcss',
  'postcss-value-parser',
]);

export const SUPPORTED_FORMATS = Object.freeze(['svg', 'png', 'ascii']);
export const COLOR_OPTION_NAMES = Object.freeze([
  'bg',
  'fg',
  'line',
  'accent',
  'muted',
  'surface',
  'border',
]);

export const SETUP_HINT =
  'Run scripts/setup-diagram-tools.sh --update from the codex-toolbox checkout, or rerun scripts/setup-codex-toolbox.sh.';
