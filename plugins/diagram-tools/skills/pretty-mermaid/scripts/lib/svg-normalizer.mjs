const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const MAX_RESOLUTION_PASSES = 64;
const ACTIVE_SVG_ELEMENTS = new Set(['animate', 'animatemotion', 'animatetransform', 'discard', 'set']);
const CSS_VALUE_ATTRIBUTES = new Set([
  'clip-path',
  'color',
  'cursor',
  'fill',
  'fill-opacity',
  'filter',
  'flood-color',
  'flood-opacity',
  'font-family',
  'font-size',
  'font-style',
  'font-weight',
  'lighting-color',
  'marker-end',
  'marker-mid',
  'marker-start',
  'mask',
  'opacity',
  'paint-order',
  'stop-color',
  'stop-opacity',
  'stroke',
  'stroke-dasharray',
  'stroke-dashoffset',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-opacity',
  'stroke-width',
  'text-anchor',
]);

function splitTopLevel(nodes) {
  const parts = [[]];
  for (const node of nodes) {
    if (node.type === 'div' && node.value === ',') parts.push([]);
    else parts.at(-1).push(node);
  }
  return parts;
}

function replaceFunctionWithWord(node, value) {
  node.type = 'word';
  node.value = value;
  delete node.nodes;
  delete node.before;
  delete node.after;
  delete node.unclosed;
}

function colorPart(valueParser, nodes) {
  const text = valueParser.stringify(nodes).trim();
  const match = text.match(/^(.*?)(?:\s+([0-9]+(?:\.[0-9]+)?)%)?$/s);
  if (!match || !match[1].trim()) throw new Error(`Invalid color-mix component: ${text}`);
  return {
    color: match[1].trim(),
    weight: match[2] === undefined ? null : Number(match[2]) / 100,
  };
}

function byteNumber(value) {
  return Math.max(0, Math.min(255, Math.round(value * 255)));
}

function byteHex(value) {
  return byteNumber(value).toString(16).padStart(2, '0');
}

function mixColors(dependencies, first, second) {
  let firstWeight = first.weight;
  let secondWeight = second.weight;
  if (firstWeight === null && secondWeight === null) {
    firstWeight = 0.5;
    secondWeight = 0.5;
  } else if (firstWeight === null) {
    firstWeight = 1 - secondWeight;
  } else if (secondWeight === null) {
    secondWeight = 1 - firstWeight;
  }

  if (
    !Number.isFinite(firstWeight) ||
    !Number.isFinite(secondWeight) ||
    firstWeight < 0 ||
    secondWeight < 0 ||
    firstWeight + secondWeight <= 0
  ) {
    throw new Error('Invalid color-mix percentages');
  }
  const weightSum = firstWeight + secondWeight;
  const alphaMultiplier = Math.min(1, weightSum);
  firstWeight /= weightSum;
  secondWeight /= weightSum;

  const firstColor = dependencies.toRgb(dependencies.parseColor(first.color));
  const secondColor = dependencies.toRgb(dependencies.parseColor(second.color));
  if (!firstColor || !secondColor) {
    throw new Error(`Unsupported color-mix colors: ${first.color}, ${second.color}`);
  }
  const firstAlpha = firstColor.alpha ?? 1;
  const secondAlpha = secondColor.alpha ?? 1;
  const mixedAlpha = firstAlpha * firstWeight + secondAlpha * secondWeight;
  const alpha = mixedAlpha * alphaMultiplier;
  const channel = (name) => {
    if (mixedAlpha === 0) return 0;
    return (
      (firstColor[name] * firstAlpha * firstWeight +
        secondColor[name] * secondAlpha * secondWeight) /
      mixedAlpha
    );
  };
  const red = channel('r');
  const green = channel('g');
  const blue = channel('b');
  if (alpha >= 0.9999) return `#${byteHex(red)}${byteHex(green)}${byteHex(blue)}`;
  return `rgba(${byteNumber(red)},${byteNumber(green)},${byteNumber(blue)},${Number(
    alpha.toFixed(4),
  )})`;
}

function createValueResolver(dependencies, variables) {
  const { valueParser } = dependencies;
  const cache = new Map();

  function resolveVariable(name, stack) {
    if (cache.has(name)) return cache.get(name);
    if (stack.includes(name)) {
      throw new Error(`CSS custom property cycle: ${[...stack, name].join(' -> ')}`);
    }
    if (!variables.has(name)) throw new Error(`Unresolved CSS custom property: ${name}`);
    const resolved = resolveValue(variables.get(name), [...stack, name]);
    cache.set(name, resolved);
    return resolved;
  }

  function replaceVariables(value, stack) {
    const parsed = valueParser(value);
    let changed = false;
    const visit = (nodes) => {
      for (const node of nodes) {
        if (node.type !== 'function') continue;
        if (node.value.toLowerCase() === 'var') {
          const parts = splitTopLevel(node.nodes ?? []);
          const name = valueParser.stringify(parts[0] ?? []).trim();
          if (!name.startsWith('--')) throw new Error(`Invalid CSS var() name: ${name}`);
          let replacement;
          if (variables.has(name)) replacement = resolveVariable(name, stack);
          else if (parts.length > 1) {
            replacement = resolveValue(
              valueParser.stringify(parts.slice(1).flat()).trim(),
              stack,
            );
          } else throw new Error(`Unresolved CSS custom property: ${name}`);
          replaceFunctionWithWord(node, replacement);
          changed = true;
        } else if (node.nodes) visit(node.nodes);
      }
    };
    visit(parsed.nodes);
    return { value: parsed.toString(), changed };
  }

  function replaceColorMix(value) {
    const parsed = valueParser(value);
    let changed = false;
    const visit = (nodes) => {
      for (const node of nodes) {
        if (node.type !== 'function') continue;
        if (node.nodes) visit(node.nodes);
        if (node.value.toLowerCase() !== 'color-mix') continue;
        const parts = splitTopLevel(node.nodes ?? []);
        if (parts.length !== 3) throw new Error('Only two-color color-mix() is supported');
        const colorSpace = valueParser.stringify(parts[0]).trim().toLowerCase();
        if (colorSpace !== 'in srgb') {
          throw new Error(`Unsupported color-mix color space: ${colorSpace}`);
        }
        const replacement = mixColors(
          dependencies,
          colorPart(valueParser, parts[1]),
          colorPart(valueParser, parts[2]),
        );
        replaceFunctionWithWord(node, replacement);
        changed = true;
      }
    };
    visit(parsed.nodes);
    return { value: parsed.toString(), changed };
  }

  function assertLocalUrls(value) {
    const parsed = valueParser(value);
    parsed.walk((node) => {
      if (node.type !== 'function' || node.value.toLowerCase() !== 'url') return;
      const target = valueParser.stringify(node.nodes ?? []).trim().replace(/^['"]|['"]$/g, '');
      if (!isSafeResourceTarget(target)) {
        throw new Error(`External CSS URL is not allowed: ${target}`);
      }
    });
  }

  function resolveValue(input, stack = []) {
    let value = String(input).trim();
    for (let pass = 0; pass < MAX_RESOLUTION_PASSES; pass += 1) {
      const variablesResult = replaceVariables(value, stack);
      value = variablesResult.value;
      const mixResult = replaceColorMix(value);
      value = mixResult.value;
      if (!variablesResult.changed && !mixResult.changed) {
        if (/\bvar\s*\(|\bcolor-mix\s*\(/i.test(value)) {
          throw new Error(`Unresolved CSS value: ${value}`);
        }
        assertLocalUrls(value);
        return value;
      }
    }
    throw new Error(`CSS value did not converge: ${input}`);
  }

  return { resolveValue, resolveVariable };
}

function isSafeResourceTarget(value) {
  return (
    value.startsWith('#') ||
    /^data:image\/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=]+$/i.test(value)
  );
}

function parseInlineRule(postcss, value) {
  const root = postcss.parse(`svg{${value ?? ''}}`, { from: undefined });
  const rule = root.first;
  if (!rule || rule.type !== 'rule') throw new Error('Invalid inline SVG style');
  return rule;
}

function serializeInlineRule(rule) {
  return (rule.nodes ?? [])
    .filter((node) => node.type === 'decl')
    .map((node) => `${node.prop}:${node.value}${node.important ? '!important' : ''}`)
    .join(';');
}

function elementList(root) {
  const elements = [];
  const pending = [root];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node.nodeType === 1) elements.push(node);
    for (let index = node.childNodes.length - 1; index >= 0; index -= 1) {
      pending.push(node.childNodes.item(index));
    }
  }
  return elements;
}

function inspectSecurity(elements) {
  for (const element of elements) {
    const name = element.nodeName.toLowerCase();
    if (name === 'script' || name === 'foreignobject' || ACTIVE_SVG_ELEMENTS.has(name)) {
      throw new Error(`Unsafe SVG element: ${element.nodeName}`);
    }
    for (const attribute of Array.from(element.attributes ?? [])) {
      const attributeName = attribute.name.toLowerCase();
      const value = attribute.value.trim();
      if (attributeName.startsWith('on')) {
        throw new Error(`Unsafe SVG event attribute: ${attribute.name}`);
      }
      if (['href', 'xlink:href', 'src'].includes(attributeName)) {
        if (!isSafeResourceTarget(value)) {
          throw new Error(`External SVG reference is not allowed: ${value}`);
        }
      }
    }
  }
}

export function normalizeSvg(svg, options, dependencies) {
  if (/<!DOCTYPE\b|<!ENTITY\b/i.test(svg)) {
    throw new Error('SVG document type and entity declarations are not allowed');
  }
  const parseMessages = [];
  const parser = new dependencies.DOMParser({
    onError: (level, message) => {
      if (level !== 'warning') parseMessages.push(`${level}: ${message}`);
    },
  });
  const document = parser.parseFromString(svg, 'image/svg+xml');
  if (parseMessages.length > 0) {
    throw new Error(`Invalid SVG XML: ${parseMessages.join('; ')}`);
  }
  const root = document.documentElement;
  if (!root || root.nodeName.toLowerCase() !== 'svg') {
    throw new Error('Renderer output has no SVG root');
  }

  const elements = elementList(root);
  inspectSecurity(elements);
  const styleElements = elements.filter((element) => element.nodeName.toLowerCase() === 'style');
  const styleRoots = styleElements.map((element) => {
    const cssRoot = dependencies.postcss.parse(element.textContent ?? '', { from: undefined });
    cssRoot.walkAtRules((rule) => {
      const name = rule.name.toLowerCase();
      if (name === 'import' || name === 'font-face') {
        rule.remove();
        return;
      }
      throw new Error(`Unsupported CSS at-rule: @${rule.name}`);
    });
    return { element, cssRoot };
  });
  const inlineRoot = parseInlineRule(dependencies.postcss, root.getAttribute('style') ?? '');

  const variables = new Map();
  for (const { cssRoot } of styleRoots) {
    cssRoot.walkDecls(/^--/, (declaration) => {
      const parent = declaration.parent;
      const selectors = parent?.type === 'rule'
        ? parent.selector.split(',').map((selector) => selector.trim().toLowerCase())
        : [];
      if (
        selectors.length === 0 ||
        selectors.some((selector) => ![':root', 'svg', 'svg:root'].includes(selector))
      ) {
        throw new Error(`Scoped CSS custom property is not supported: ${declaration.prop}`);
      }
      variables.set(declaration.prop, declaration.value);
    });
  }
  inlineRoot.walkDecls(/^--/, (declaration) => variables.set(declaration.prop, declaration.value));
  const resolver = createValueResolver(dependencies, variables);

  const resolveDeclarations = (container) => {
    container.walkDecls((declaration) => {
      declaration.value = resolver.resolveValue(declaration.value);
      if (declaration.prop.toLowerCase() === 'font-family') {
        const lower = declaration.value.toLowerCase();
        if (!lower.includes('system-ui')) declaration.value += ',ui-sans-serif,system-ui';
        if (!lower.includes('-apple-system')) declaration.value += ',-apple-system,BlinkMacSystemFont';
        if (!lower.includes('segoe ui')) declaration.value += ",'Segoe UI'";
        if (!/(^|,)\s*sans-serif\s*(,|$)/i.test(declaration.value)) {
          declaration.value += ',sans-serif';
        }
      }
    });
  };

  for (const { element, cssRoot } of styleRoots) {
    resolveDeclarations(cssRoot);
    element.textContent = cssRoot.toString();
  }
  resolveDeclarations(inlineRoot);
  if (options.transparent) {
    let background = inlineRoot.nodes.find(
      (node) => node.type === 'decl' && node.prop.toLowerCase() === 'background',
    );
    if (!background) {
      background = dependencies.postcss.decl({ prop: 'background', value: 'transparent' });
      inlineRoot.append(background);
    } else background.value = 'transparent';
  }
  root.setAttribute('style', serializeInlineRule(inlineRoot));

  for (const element of elements) {
    for (const attribute of Array.from(element.attributes ?? [])) {
      const name = attribute.name.toLowerCase();
      if (name === 'style') {
        const rule = parseInlineRule(dependencies.postcss, attribute.value);
        resolveDeclarations(rule);
        element.setAttribute(attribute.name, serializeInlineRule(rule));
      } else if (
        CSS_VALUE_ATTRIBUTES.has(name) &&
        /\bvar\s*\(|\bcolor-mix\s*\(|\burl\s*\(/i.test(attribute.value)
      ) {
        element.setAttribute(attribute.name, resolver.resolveValue(attribute.value));
      }
    }
  }

  let background = options.background;
  if (!background && variables.has('--bg')) background = resolver.resolveVariable('--bg', []);
  if (!options.transparent) {
    background ||= '#ffffff';
    const rectangle = document.createElementNS(SVG_NAMESPACE, 'rect');
    rectangle.setAttribute('data-pretty-mermaid-background', 'true');
    rectangle.setAttribute('x', '0');
    rectangle.setAttribute('y', '0');
    rectangle.setAttribute('width', '100%');
    rectangle.setAttribute('height', '100%');
    rectangle.setAttribute('fill', background);
    root.insertBefore(rectangle, root.firstChild);
  }

  for (const { cssRoot } of styleRoots) {
    if (/\bvar\s*\(|\bcolor-mix\s*\(|@import\b/i.test(cssRoot.toString())) {
      throw new Error('Normalized SVG still contains dynamic or external CSS');
    }
  }
  for (const element of elementList(root)) {
    for (const attribute of Array.from(element.attributes ?? [])) {
      if (
        (attribute.name.toLowerCase() === 'style' ||
          CSS_VALUE_ATTRIBUTES.has(attribute.name.toLowerCase())) &&
        /\bvar\s*\(|\bcolor-mix\s*\(/i.test(attribute.value)
      ) {
        throw new Error('Normalized SVG still contains dynamic CSS');
      }
    }
  }
  const normalized = new dependencies.XMLSerializer().serializeToString(document);
  return { svg: normalized, background: options.transparent ? null : background };
}

export function svgDimensions(svg, dependencies) {
  const document = new dependencies.DOMParser().parseFromString(svg, 'image/svg+xml');
  const root = document.documentElement;
  const viewBox = (root.getAttribute('viewBox') ?? '')
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (viewBox.length !== 4 || viewBox.some((value) => !Number.isFinite(value))) {
    throw new Error('SVG has no finite four-number viewBox');
  }
  const [, , width, height] = viewBox;
  if (width <= 0 || height <= 0 || width > 20000 || height > 20000) {
    throw new Error(`SVG viewBox is outside safe bounds: ${width}x${height}`);
  }
  return { width, height, viewBox };
}

export function renderPng(svg, options, dependencies) {
  const scale = options.scale ?? 2;
  const renderer = new dependencies.Resvg(svg, {
    fitTo: { mode: 'zoom', value: scale },
    font: {
      loadSystemFonts: true,
      defaultFontFamily: 'Arial',
      sansSerifFamily: 'Arial',
    },
    ...(options.background ? { background: options.background } : {}),
  });
  return renderer.render().asPng();
}

export function inspectPng(buffer, dependencies) {
  if (!Buffer.isBuffer(buffer) || !buffer.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) {
    throw new Error('PNG output has an invalid signature');
  }
  const png = dependencies.PNG.sync.read(buffer);
  const corner = [png.data[0], png.data[1], png.data[2], png.data[3]];
  let differentPixels = 0;
  const sampledColors = new Set();
  let minX = png.width;
  let minY = png.height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < png.height; y += 1) {
    for (let x = 0; x < png.width; x += 1) {
      const offset = (y * png.width + x) * 4;
      const color = [
        png.data[offset],
        png.data[offset + 1],
        png.data[offset + 2],
        png.data[offset + 3],
      ];
      if ((x + y * png.width) % Math.max(1, Math.floor((png.width * png.height) / 4096)) === 0) {
        sampledColors.add(color.join(','));
      }
      const distance = color.reduce(
        (total, channel, index) => total + Math.abs(channel - corner[index]),
        0,
      );
      if (distance > 20) {
        differentPixels += 1;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }
  return {
    width: png.width,
    height: png.height,
    differentPixels,
    sampledColors: sampledColors.size,
    foregroundBounds:
      maxX >= 0 ? { minX, minY, maxX, maxY } : null,
  };
}
