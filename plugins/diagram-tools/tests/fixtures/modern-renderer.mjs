export function renderMermaidSVGAsync() {
  return Promise.resolve('<svg/>');
}

export function renderMermaidASCII() {
  return 'diagram';
}

export const THEMES = {
  'github-light': { bg: '#fff', fg: '#000' },
  'future-theme': { bg: '#123', fg: '#eee' },
};
