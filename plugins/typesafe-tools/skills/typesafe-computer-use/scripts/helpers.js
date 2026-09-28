// cu-helpers-begin
function cuSelectExcerpt(state, { terms = [], required = [], full = false, budget = 80 } = {}) {
  const lines = state.split("\n"), lower = state.toLowerCase();
  const missing = required.filter(term => !lower.includes(term.toLowerCase()));
  const partial = lines.some(line => {
    const range = /\bshowing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\s+items\b/i.exec(line);
    return range && (Number(range[1]) > 0 || Number(range[2]) < Number(range[3]));
  });
  const damaged = partial || lines.some(line => /^\s*(?:\.{3}|…|\[?truncated\b|\d+\s+lines?\s+omitted\b)/i.test(line));
  if (!full && (missing.length || damaged)) return { needsFull: true, reason: partial ? "partial tree" : damaged ? "truncated" : "missing context" };
  const direct = incomplete => ({ needsFull: false, direct: true, incomplete, text: state,
    total_lines: lines.length, shown_lines: lines.length, omitted_lines: 0 });
  if (damaged || missing.length || lines.length <= budget) return direct(!!(damaged || missing.length));
  const hits = lines.map((line, i) => terms.some(term => term && line.toLowerCase().includes(term.toLowerCase())) ? i : -1).filter(i => i >= 0);
  if (!hits.length) return direct(true);
  const keep = new Set();
  for (const i of hits) {
    for (let j = Math.max(0, i - 2); j <= Math.min(lines.length - 1, i + 2); j++) keep.add(j);
    let depth = lines[i].match(/^\s*/)[0].length;
    for (let j = i - 1; j >= 0 && depth > 0; j--) {
      const indent = lines[j].match(/^\s*/)[0].length;
      if (indent < depth && /^\s*\d+\s+/.test(lines[j])) { keep.add(j); depth = indent; }
    }
  }
  const selected = [...keep].sort((a, b) => a - b);
  if (selected.length > budget) return direct(false); // Soft budget: retain all relevant context.
  return { needsFull: false, direct: false, incomplete: false, total_lines: lines.length,
    shown_lines: selected.length, omitted_lines: lines.length - selected.length,
    text: selected.map(i => `L${i + 1}: ${lines[i]}`).join("\n") };
}

function cuMatchUnique(state, spec) {
  const unbound = reason => ({ status: "unbound", reason });
  if (typeof state !== "string" || !spec || spec.stateKind !== "full" ||
      typeof spec.role !== "string" || typeof spec.label !== "string" || !spec.label.trim() ||
      !Array.isArray(spec.context) || !spec.context.length ||
      spec.context.some(t => typeof t !== "string" || !t.trim()) ||
      !Array.isArray(spec.preconditions) || !spec.preconditions.length) return unbound("incomplete binding");
  const roles = { click: ["button", "tab", "link", "checkbox", "radio", "menuitem", "option", "combobox"],
    setValue: ["textfield", "searchfield", "textarea", "combobox"] };
  if (!Array.isArray(roles[spec.operation]) || !roles[spec.operation].includes(spec.role.toLowerCase()) ||
      spec.preconditions.some(p => !["present", "enabled", "selected", "not_selected"].includes(p))) return unbound("unsupported operation or precondition");
  if (state.split("\n").some(line => {
    const range = /\bshowing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\s+items\b/i.exec(line);
    return /^\s*(?:\.{3}|…|\[?truncated\b|\d+\s+lines?\s+omitted\b)/i.test(line) ||
      (range && (Number(range[1]) > 0 || Number(range[2]) < Number(range[3])));
  })) return unbound("incomplete state");
  const nodes = state.split("\n").map(line => {
    const match = /^(\s*)(\d+)\s+([A-Za-z][\w]*)\s*(.*)$/.exec(line);
    if (!match) return null;
    return { indent: match[1].length, index: Number(match[2]), role: match[3].toLowerCase(),
      label: match[4].replace(/,\s*(?:Value|Description|ID|Enabled|Disabled|Actions|Selected|Checked|Expanded)\s*:\s*.*$/i, "").trim(), raw: line };
  });
  const matches = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    if (!node || node.role !== spec.role.toLowerCase() || node.label !== spec.label) continue;
    if (/\bdisabled\b|\benabled\s*:\s*false\b|\bnot enabled\b/i.test(node.raw)) continue;
    const selected = /\bSelected\s*:\s*(true|false)\b/i.exec(node.raw);
    if (spec.preconditions.includes("selected") && selected?.[1].toLowerCase() !== "true") continue;
    if (spec.preconditions.includes("not_selected") && selected?.[1].toLowerCase() !== "false") continue;
    const context = [];
    let j = i - 1, siblings = 0;
    for (; j >= 0 && nodes[j]?.indent >= node.indent; j--) {
      if (nodes[j].indent === node.indent) {
        if (!["text", "statictext"].includes(nodes[j].role)) break;
        context.push(nodes[j].label);
        if (++siblings === 2) break; // Fixture rows expose name and metadata immediately before Open.
      }
    }
    let depth = node.indent;
    for (; j >= 0 && depth > 0; j--) {
      if (nodes[j] && nodes[j].indent < depth) { context.push(nodes[j].label); depth = nodes[j].indent; }
    }
    if (spec.context.every(term => context.includes(term))) matches.push(node.index);
  }
  return matches.length === 1 ? { status: "bound", index: matches[0] } : unbound(matches.length ? "ambiguous" : "missing");
}
// cu-helpers-end
