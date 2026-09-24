// Toolbox-owned, opt-in CUA controller. Paste once into a persistent cua_repl task.
// The bounded-loop design was informed by Jev-cu 52d32ac (MIT); no upstream code
// was copied: https://github.com/Sac-Y/Jev-cu/tree/52d32ac24e2cea29c63d9d7c4bd6d4c401111f56
// It uses only documented Target methods; it never performs provider or network calls.
var cuController = (() => {
  const sessions = new WeakMap();
  const roles = ["standard window", "split group", "scroll area", "html content", "content list",
    "menu bar", "radio button", "search field", "text field", "pop up button", "combo box",
    "menu item", "list item", "text area", "static text", "axwebarea", "container", "textfield", "searchfield",
    "textarea", "combobox", "menuitem", "checkbox", "button", "option", "heading",
    "window", "toolbar", "tab", "link", "text", "row", "list", "grid"];
  const aliases = { "标准窗口": "standardwindow", "分离组": "splitgroup", "滚动区": "scrollarea",
    "文本": "text", "按钮": "button", "搜索框": "searchfield", "文本框": "textfield",
    "选项卡": "tab", "复选框": "checkbox" };
  const clickable = new Set(["button", "tab", "link", "checkbox", "radiobutton", "menuitem",
    "option", "combobox", "popupbutton"]);
  const editable = new Set(["textfield", "searchfield", "textarea", "combobox"]);
  const keyPattern = /^(?:Return|Escape|Tab|Up|Down|Left|Right|BackSpace|space|super\+[a-z]|ctrl\+[a-z])$/;
  const maxActions = 8, deadlineMs = 120000;
  const now = () => typeof performance !== "undefined" && typeof performance.now === "function" ?
    performance.now() : Date.now();
  const asRole = value => String(value).toLowerCase().replace(/\s+/g, "");
  const string = (value, max = 500) => typeof value === "string" && value.length > 0 &&
    value.length <= max && value.trim() === value;
  const list = value => Array.isArray(value) && value.length > 0 && value.length <= 15;
  const serial = () => Math.random().toString(36).slice(2, 10);
  function utf8Bytes(value) {
    let size = 0;
    for (const char of value) {
      const cp = char.codePointAt(0);
      size += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    }
    return size;
  }

  function validateRule(rule) {
    if (!rule || !string(rule.role, 40) || !string(rule.label, 500) ||
        (rule.context !== undefined && (!Array.isArray(rule.context) ||
          rule.context.some(item => !string(item, 500)))) ||
        (rule.id !== undefined && !string(rule.id, 128)) ||
        (rule.value !== undefined && !string(rule.value, 500)) ||
        (rule.preconditions !== undefined && (!Array.isArray(rule.preconditions) ||
          rule.preconditions.some(p => !["selected", "not_selected", "enabled", "settable"].includes(p)))))
      throw Error("invalid observation rule");
    return { role: asRole(rule.role), label: rule.label, context: [...(rule.context || [])],
      nodeId: rule.id || null, value: rule.value || null,
      preconditions: [...(rule.preconditions || [])] };
  }
  function validateGroup(group) {
    if (!group || !list(group.required)) throw Error("observation rules required");
    return { required: group.required.map(validateRule), sameParent: group.sameParent === true,
      allowPartialList: group.allowPartialList === true };
  }
  function validateTransition(step, surface) {
    if (!step || !string(step.id, 64) ||
        !/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(step.id) || step.id === "abstain" ||
        !string(step.role, 40) ||
        !string(step.label, 500) || !list(step.context) ||
        (step.targetAxId !== undefined && !string(step.targetAxId, 128)) ||
        (step.rowId !== undefined && !string(step.rowId, 128)) ||
        step.context.some(item => !string(item, 500)) ||
        !string(step.intendedResult, 500) ||
        !Array.isArray(step.preconditions) || !step.preconditions.length ||
        step.preconditions.some(p => !["present", "enabled", "selected", "not_selected", "settable"].includes(p)) ||
        !step.preconditions.includes("enabled"))
      throw Error("invalid transition");
    const operation = step.operation;
    if (!["click", "setValue", "typeText", "pressKey", "scroll"].includes(operation))
      throw Error("unsupported operation");
    const role = asRole(step.role);
    if (operation === "click" && !clickable.has(role) ||
        ["setValue", "typeText"].includes(operation) && !editable.has(role) &&
          !(operation === "setValue" && role === "popupbutton" &&
            step.preconditions.includes("settable")) ||
        operation === "scroll" && role !== "scrollarea" ||
        operation === "typeText" && surface !== "browser" ||
        operation === "pressKey" && surface !== "browser") throw Error("unsupported target operation");
    const args = step.arguments || {};
    if (operation === "click" && Object.keys(args).length ||
        ["setValue", "typeText"].includes(operation) &&
          (!string(args.text, 500) || Object.keys(args).length !== 1) ||
        operation === "pressKey" &&
          (!keyPattern.test(args.key || "") || Object.keys(args).length !== 1) ||
        operation === "scroll" &&
          (!["up", "down", "left", "right"].includes(args.direction) ||
           !Number.isInteger(args.pages) || args.pages < 1 || args.pages > 3 ||
           Object.keys(args).length !== 2)) throw Error("invalid operation arguments");
    return { id: step.id, role, label: step.label, context: [...step.context], operation,
      nodeId: step.targetAxId || null, rowId: step.rowId || null,
      arguments: { ...args }, preconditions: [...step.preconditions],
      intendedResult: step.intendedResult };
  }
  function createSession(manifest, target) {
    if (!manifest || !target || typeof target.getAXState !== "function" ||
        !string(manifest.scopeId, 128) ||
        !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(manifest.scopeId) ||
        !["browser", "native"].includes(manifest.surface) || !string(manifest.objective, 500) ||
        utf8Bytes(manifest.objective) > 1500 ||
        (manifest.targetId !== undefined &&
          (!string(manifest.targetId, 128) || String(target.id) !== manifest.targetId)) ||
        !Array.isArray(manifest.stages) || !manifest.stages.length || manifest.stages.length > 8)
      throw Error("invalid session manifest");
    const stages = manifest.stages.map(stage => {
      if (!stage || !string(stage.id, 64) || !list(stage.transitions))
        throw Error("invalid stage");
      const transitions = stage.transitions.map(t => validateTransition(t, manifest.surface));
      if (new Set(transitions.map(t => t.id)).size !== transitions.length ||
          stage.automatic === true && transitions.length !== 1) throw Error("ambiguous stage");
      const expectedAfter = validateGroup(stage.expectedAfter);
      return { id: stage.id, automatic: stage.automatic === true, transitions, expectedAfter };
    });
    if (new Set(stages.map(s => s.id)).size !== stages.length) throw Error("duplicate stage");
    const session = Object.freeze({ kind: "cu-controller-session", scopeId: manifest.scopeId });
    sessions.set(session, { target, targetId: manifest.targetId || null,
      surface: manifest.surface, objective: manifest.objective,
      scope: validateGroup(manifest.scope), initial: validateGroup(manifest.initial),
      verification: validateGroup(manifest.verification),
      stages, startedAt: now(), stageIndex: 0, actionsUsed: 0, noProgress: 0,
      initialized: false, pending: null, terminal: null, handoff: null,
      counter: 0, salt: serial(), inFlight: false,
      forceAdvice: false });
    return session;
  }

  function parse(state) {
    const nodes = [], stack = [], lines = state.split(/\r?\n/);
    for (let lineNumber = 0; lineNumber < lines.length; lineNumber++) {
      const match = /^(\s*)(\d+)\s+(.+)$/.exec(lines[lineNumber]);
      if (!match) continue;
      const rest = match[3], roleText = roles.find(r =>
        rest.toLowerCase().startsWith(r) && (rest.length === r.length || /\s/.test(rest[r.length]))) ||
        Object.keys(aliases).find(r => rest.startsWith(r) &&
          (rest.length === r.length || /\s/.test(rest[r.length])));
      const role = roleText ? aliases[roleText] || asRole(roleText) : null;
      let rawLabel = roleText ? rest.slice(roleText.length).trim() : rest;
      let qualifiers = [];
      const prefix = /^\(([^)]*)\)\s*/.exec(rawLabel);
      if (prefix && prefix[1].split(/,\s*/).every(item =>
        /^(?:selected|selectable|settable|boolean|collapsed|expanded|disabled|enabled|focused)$/.test(item))) {
        qualifiers = prefix[1].split(/,\s*/).map(item => item.toLowerCase());
        rawLabel = rawLabel.slice(prefix[0].length);
      }
      const label = rawLabel.replace(/^Description:\s*/i, "")
        .replace(/,\s*(?:Value|Description|ID|Enabled|Disabled|Actions|Selected|Checked|Expanded)\s*:\s*.*$/i, "").trim();
      const value = /,\s*Value:\s*(.*?)(?=,\s*(?:Description|ID|Enabled|Disabled|Actions|Selected|Checked|Expanded)\s*:|$)/i.exec(rawLabel)?.[1].trim() || null;
      const selectedField = /,\s*Selected:\s*(true|false)(?=,|$)/i.exec(rawLabel);
      // A description can contain arbitrary text, including "Selected: true".
      const selectedState = selectedField &&
        !/,\s*Description\s*:/i.test(rawLabel.slice(0, selectedField.index)) ?
        selectedField[1].toLowerCase() === "true" : null;
      const indent = match[1].length;
      while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
      const parent = stack.length ? stack[stack.length - 1] : null;
      const node = { role, label, value, qualifiers, selectedState,
        index: Number(match[2]), indent, parent,
        raw: lines[lineNumber], rawLabel, lineNumber };
      nodes.push(node);
      stack.push(node);
    }
    return { nodes, lines, state };
  }
  function incomplete(parsed) {
    const partial = parsed.nodes.filter(node => {
      const found = /\bshowing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\s+items\b/i.exec(node.raw);
      return found && (Number(found[1]) > 0 || Number(found[2]) < Number(found[3]));
    });
    const truncated = parsed.lines.some(line => /^\s*(?:\.{3}|…|\[?truncated\b|\d+\s+lines?\s+omitted\b)/i.test(line));
    return { partial, truncated };
  }
  function adjacentText(parsed, node) {
    const labels = [];
    for (let prior = parsed.nodes.indexOf(node) - 1; prior >= 0; prior--) {
      const sibling = parsed.nodes[prior];
      if (sibling.indent !== node.indent || sibling.parent !== node.parent ||
          !["text", "statictext"].includes(sibling.role)) break;
      labels.push(sibling.label);
      if (labels.length > 2) return { labels, overflow: true };
    }
    return { labels, overflow: false };
  }
  function contextOf(parsed, node) {
    const context = [...adjacentText(parsed, node).labels];
    for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) context.push(ancestor.label);
    return context;
  }
  function hasAxId(node, id) {
    return new RegExp(`(?:^|,)\\s*ID:\\s*${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:,|\\s*$)`).test(node.raw);
  }
  function within(node, ancestor) {
    for (let current = node; current; current = current.parent)
      if (current === ancestor) return true;
    return false;
  }
  function structuralRow(parsed, node, rule) {
    for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
      const explicitRow = ["row", "listitem"].includes(ancestor.role);
      const identifiedContainer = rule.rowId && ancestor.role === "container" &&
        hasAxId(ancestor, rule.rowId) && ancestor.parent &&
        parsed.nodes.some(peer => peer !== ancestor && peer.parent === ancestor.parent &&
          peer.role === "container" && /,\s*ID:\s*[^,]+/.test(peer.raw));
      if (!explicitRow && !identifiedContainer) continue;
      const targets = parsed.nodes.filter(other => other.role === node.role &&
        other.label === node.label && within(other, ancestor));
      const rowText = parsed.nodes.filter(other => ["text", "statictext"].includes(other.role) &&
        within(other, ancestor)).map(other => other.label);
      return targets.length === 1 && rule.context.some(term =>
        term === ancestor.label || rowText.includes(term));
    }
    return false;
  }
  function find(parsed, rule, preconditions = [], requireComplete = true) {
    const coverage = incomplete(parsed);
    if (coverage.truncated || requireComplete && coverage.partial.length)
      return { status: "unbound", reason: "incomplete state" };
    const hits = parsed.nodes.filter(node => {
      if (node.role !== rule.role || node.label !== rule.label ||
          rule.value && node.value !== rule.value ||
          rule.nodeId && !hasAxId(node, rule.nodeId) ||
          !rule.context.every(term => contextOf(parsed, node).includes(term))) return false;
      if (rule.operation) {
        const adjacent = adjacentText(parsed, node);
        const row = structuralRow(parsed, node, rule);
        const intrinsic = /\S+\s+\S+/.test(node.label) &&
          parsed.nodes.filter(other => other.role === node.role && other.label === node.label).length === 1;
        const ancestors = [];
        for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent)
          ancestors.push(ancestor.label);
        const usesSiblingText = rule.context.some(term => !ancestors.includes(term));
        const siblingNamedInLabel = rule.context.some(term => !ancestors.includes(term) &&
          term.length >= 3 && node.label.toLowerCase().includes(term.toLowerCase()));
        if (!rule.nodeId && !intrinsic &&
            (adjacent.overflow || adjacent.labels.some(label =>
              rule.context.filter(term => term === label).length <
              adjacent.labels.filter(term => term === label).length))) return false;
        if (!row && !rule.nodeId &&
            (usesSiblingText && !(intrinsic && siblingNamedInLabel) ||
             node.role === "button" && !intrinsic)) return false;
      }
      if (/\bdisabled\b|\benabled\s*:\s*false\b|\bnot enabled\b/i.test(node.raw)) return false;
      const selectionHints = [];
      if (node.qualifiers.includes("selected")) selectionHints.push(true);
      if (node.selectedState !== null) selectionHints.push(node.selectedState);
      if (/^(?:1|true)$/i.test(node.value || "")) selectionHints.push(true);
      if (/^(?:0|false)$/i.test(node.value || "")) selectionHints.push(false);
      const selected = selectionHints.length > 0 && selectionHints.every(Boolean);
      const notSelected = selectionHints.length > 0 && selectionHints.every(hint => !hint);
      if (preconditions.includes("settable") && !node.qualifiers.includes("settable") ||
          preconditions.includes("selected") && !selected ||
          preconditions.includes("not_selected") && !notSelected)
        return false;
      if (!requireComplete && coverage.partial.some(partial => {
        for (let ancestor = node; ancestor; ancestor = ancestor.parent)
          if (ancestor === partial) return true;
        return false;
      })) return false;
      return true;
    });
    return hits.length === 1 ? { status: "bound", node: hits[0] } :
      { status: "unbound", reason: hits.length ? "ambiguous" : "missing" };
  }
  function groupMatches(parsed, group) {
    const hits = group.required.map(rule => find(parsed, rule, rule.preconditions,
      !group.allowPartialList));
    if (hits.some(hit => hit.status !== "bound")) return false;
    return !group.sameParent || hits.every(hit => hit.node.parent === hits[0].node.parent);
  }
  function excerpt(parsed, terms) {
    const lines = parsed.lines;
    const bounded = (text, shown) => {
      const size = utf8Bytes(text);
      if (size > 16 * 1024) return { text: "", total_lines: lines.length,
        shown_lines: 0, omitted_lines: lines.length, omitted_bytes: utf8Bytes(parsed.state),
        oversize: true };
      return { text, total_lines: lines.length, shown_lines: shown,
        omitted_lines: lines.length - shown, omitted_bytes: 0, oversize: false };
    };
    if (lines.length <= 80 || incomplete(parsed).truncated)
      return bounded(parsed.state, lines.length);
    const keep = new Set();
    for (let i = 0; i < lines.length; i++) {
      if (!terms.some(term => term && lines[i].includes(term))) continue;
      for (let j = Math.max(0, i - 2); j <= Math.min(lines.length - 1, i + 2); j++) keep.add(j);
      let node = parsed.nodes.find(n => n.lineNumber === i)?.parent;
      while (node) { keep.add(node.lineNumber); node = node.parent; }
    }
    if (!keep.size || keep.size > 80) return bounded(parsed.state, lines.length);
    const selected = [...keep].sort((a, b) => a - b);
    return bounded(selected.map(i => `L${i + 1}: ${lines[i]}`).join("\n"), selected.length);
  }
  const summary = state => ({ stage: state.stages[state.stageIndex]?.id || null,
    actionsUsed: state.actionsUsed, remainingMs: Math.max(0, deadlineMs - (now() - state.startedAt)) });
  function terminal(state, status, reason, parsed = null, extra = {}) {
    const safeExtra = { ...extra };
    for (const key of ["actionError", "observationError"]) {
      if (typeof safeExtra[key] !== "string") continue;
      const size = utf8Bytes(safeExtra[key]);
      if (size > 512) {
        safeExtra[key] = "[error text omitted]";
        safeExtra[`${key}Truncated`] = true;
        safeExtra[`${key}Bytes`] = size;
      }
    }
    const result = { status, reason, ...summary(state), ...safeExtra };
    if (parsed) result.observation = excerpt(parsed,
      [...state.verification.required.map(r => r.label), state.stages[state.stageIndex]?.id]);
    if (status === "verified" || status === "stopped") state.terminal = result;
    if (status === "handoff") state.handoff = result;
    return result;
  }
  function budget(state) {
    if (now() - state.startedAt >= deadlineMs) return terminal(state, "stopped", "deadline");
    if (state.actionsUsed >= maxActions) return terminal(state, "stopped", "action_budget");
    return null;
  }
  async function observe(state) {
    const text = await state.target.getAXState({ emit: false, disableDiffing: true });
    if (typeof text !== "string" || !text) throw Error("empty observation");
    return parse(text);
  }
  function advice(state, parsed, choices) {
    const nonce = `${state.salt}-${++state.counter}`;
    const snapshotId = `cu_${nonce}`;
    const stage = state.stages[state.stageIndex];
    const candidates = choices.map(step => ({ id: step.id,
      target: `${step.role} ${step.label} in ${step.context.join(" / ")}`,
      operation: step.operation,
      arguments: step.operation === "click" ? "none" : JSON.stringify(step.arguments),
      preconditions: step.preconditions.join(", "), intended_result: step.intendedResult }));
    const observation = excerpt(parsed,
      [...choices.flatMap(c => [c.label, ...c.context]), ...state.verification.required.map(r => r.label)]);
    if (observation.oversize || candidates.some(c =>
        !/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(c.id) || c.id === "abstain" ||
        utf8Bytes(c.target) > 300 || utf8Bytes(c.arguments) > 512 ||
        utf8Bytes(c.preconditions) > 512 || utf8Bytes(c.intended_result) > 300))
      return terminal(state, "handoff", "provider_payload_too_large", parsed);
    state.pending = { nonce, snapshotId, fullState: parsed.state,
      ids: new Set(choices.map(c => c.id)), stageIndex: state.stageIndex };
    return { status: "awaiting_advice", turnNonce: nonce, snapshotId,
      surface: state.surface, objective: state.objective, observation: excerpt(parsed,
        [...choices.flatMap(c => [c.label, ...c.context]), ...state.verification.required.map(r => r.label)]),
      candidates, ...summary(state) };
  }
  async function perform(state, step, index) {
    const args = step.arguments;
    switch (step.operation) {
      case "click": return state.target.click(index);
      case "setValue": return state.target.setValue(index, args.text);
      case "typeText": return state.target.typeText(index, args.text);
      case "pressKey": return state.target.pressKey(index, args.key);
      case "scroll": return state.target.scroll(index, args.direction, args.pages);
      default: throw Error("unsupported operation");
    }
  }
  async function drive(state, parsed) {
    for (;;) {
      if (!groupMatches(parsed, state.scope) ||
          state.targetId && String(state.target.id) !== state.targetId)
        return terminal(state, "handoff", "scope_changed", parsed);
      if (now() - state.startedAt >= deadlineMs)
        return terminal(state, "stopped", "deadline", parsed,
          { uiVerified: groupMatches(parsed, state.verification) });
      if (state.stages.slice(0, state.stageIndex).some(stage =>
          !groupMatches(parsed, stage.expectedAfter)))
        return terminal(state, "handoff", "prior_stage_regressed", parsed);
      if (groupMatches(parsed, state.verification))
        return terminal(state, "verified", "observed_completion", parsed);
      const over = budget(state);
      if (over) return over;
      const stage = state.stages[state.stageIndex];
      if (!stage) return terminal(state, "handoff", "verification_missing", parsed);
      if (groupMatches(parsed, stage.expectedAfter)) {
        state.stageIndex++;
        state.noProgress = 0;
        state.forceAdvice = false;
        continue;
      }
      if (incomplete(parsed).partial.length || incomplete(parsed).truncated)
        return terminal(state, "handoff", "incomplete_binding_state", parsed);
      const choices = stage.transitions.filter(step => find(parsed, step, step.preconditions).status === "bound");
      if (!choices.length) return terminal(state, "handoff", "target_unbound", parsed);
      if (!stage.automatic || state.forceAdvice) return advice(state, parsed, choices);
      const step = choices[0];
      const binding = find(parsed, step, step.preconditions);
      if (binding.status !== "bound") return terminal(state, "handoff", "target_unbound", parsed);
      const result = await act(state, parsed, stage, step, binding.node.index);
      if (result.done) return result.value;
      parsed = result.parsed;
    }
  }
  async function act(state, before, stage, step, index) {
    if (budget(state)) return { done: true, value: state.terminal };
    state.actionsUsed++;
    let actionError = null;
    try { await perform(state, step, index); } catch (error) { actionError = String(error); }
    let after;
    try { after = await observe(state); }
    catch (error) { return { done: true, value: terminal(state, "handoff",
      "post_action_observation_failed", null, { actionError, observationError: String(error) }) }; }
    if (!groupMatches(after, state.scope) ||
        state.targetId && String(state.target.id) !== state.targetId)
      return { done: true, value: terminal(state, "handoff", "scope_changed", after,
        { actionError }) };
    if (now() - state.startedAt >= deadlineMs)
      return { done: true, value: terminal(state, "stopped", "deadline", after,
        { actionError, uiVerified: groupMatches(after, state.verification) }) };
    if (state.stages.slice(0, state.stageIndex).some(prior =>
        !groupMatches(after, prior.expectedAfter)))
      return { done: true, value: terminal(state, "handoff", "prior_stage_regressed", after,
        { actionError }) };
    if (groupMatches(after, state.verification))
      return { done: true, value: terminal(state, "verified", "observed_completion", after,
        { actionError }) };
    const progress = !groupMatches(before, stage.expectedAfter) &&
      groupMatches(after, stage.expectedAfter);
    if (progress) { state.stageIndex++; state.noProgress = 0; state.forceAdvice = false; }
    else { state.noProgress++; state.forceAdvice = true; }
    if (actionError) return { done: true, value: terminal(state, "handoff", "action_error",
      after, { actionError, progress }) };
    if (state.noProgress >= 2) return { done: true,
      value: terminal(state, "stopped", "no_progress", after) };
    if (!progress) {
      // The first no-progress handoff permits one explicit, fresh retry.
      const retry = advice(state, after, [step]);
      if (retry.status !== "awaiting_advice") return { done: true, value: retry };
      return { done: true, value: terminal(state, "handoff", "no_progress", after,
        { turnNonce: retry.turnNonce, candidateId: step.id }) };
    }
    return { done: false, parsed: after };
  }
  function lookup(session) {
    const state = sessions.get(session);
    if (!state) throw Error("invalid or reset session");
    return state;
  }
  async function advance(session) {
    const state = lookup(session);
    if (state.inFlight) return { status: "handoff", reason: "in_flight", ...summary(state) };
    state.inFlight = true;
    try {
      if (state.terminal) return state.terminal;
      if (state.handoff) return state.handoff;
      const over = budget(state);
      if (over) return over;
      if (state.pending) return { status: "awaiting_advice", turnNonce: state.pending.nonce,
        snapshotId: state.pending.snapshotId, reason: "pending_choice", ...summary(state) };
      let parsed;
      try { parsed = await observe(state); }
      catch (error) { return terminal(state, "handoff", "observation_failed", null,
        { observationError: String(error) }); }
      if (now() - state.startedAt >= deadlineMs)
        return terminal(state, "stopped", "deadline", parsed,
          { uiVerified: state.initialized && groupMatches(parsed, state.scope) &&
            (!state.targetId || String(state.target.id) === state.targetId) &&
            groupMatches(parsed, state.verification) });
      if (!state.initialized) {
        state.initialized = true;
        if (!groupMatches(parsed, state.scope) ||
            !groupMatches(parsed, state.initial) || groupMatches(parsed, state.verification))
          return terminal(state, "stopped", "reset_not_verified", parsed);
      }
      return await drive(state, parsed);
    } finally {
      state.inFlight = false;
    }
  }
  async function resume(session, choice) {
    const state = lookup(session);
    if (state.inFlight) return { status: "handoff", reason: "in_flight", ...summary(state) };
    state.inFlight = true;
    try {
      if (state.terminal) return { status: "handoff", reason: "session_finished", ...summary(state) };
      const over = budget(state);
      if (over) return over;
      const pending = state.pending;
      if (state.handoff && state.handoff.reason !== "no_progress") return state.handoff;
      if (!pending || !choice || Object.keys(choice).length !== 2 ||
          !Object.prototype.hasOwnProperty.call(choice, "turnNonce") ||
          !Object.prototype.hasOwnProperty.call(choice, "candidateId") ||
          choice.turnNonce !== pending.nonce ||
          !pending.ids.has(choice.candidateId) || pending.stageIndex !== state.stageIndex)
        return { status: "handoff", reason: "invalid_choice", ...summary(state) };
      state.pending = null; // A choice is single use, even if fresh observation fails.
      state.handoff = null;
      let parsed;
      try { parsed = await observe(state); }
      catch (error) { return terminal(state, "handoff", "observation_failed", null,
        { observationError: String(error) }); }
      if (now() - state.startedAt >= deadlineMs)
        return terminal(state, "stopped", "deadline", parsed,
          { uiVerified: groupMatches(parsed, state.scope) &&
            (!state.targetId || String(state.target.id) === state.targetId) &&
            groupMatches(parsed, state.verification) });
      if (!groupMatches(parsed, state.scope) ||
          state.targetId && String(state.target.id) !== state.targetId)
        return terminal(state, "handoff", "scope_changed", parsed);
      if (state.stages.slice(0, state.stageIndex).some(prior =>
          !groupMatches(parsed, prior.expectedAfter)))
        return terminal(state, "handoff", "prior_stage_regressed", parsed);
      if (parsed.state !== pending.fullState) {
        if (groupMatches(parsed, state.verification))
          return terminal(state, "verified", "observed_completion", parsed);
        const changedStage = state.stages[state.stageIndex];
        if (groupMatches(parsed, changedStage.expectedAfter))
          return terminal(state, "handoff", "state_changed_after_advice", parsed);
        const choices = changedStage.transitions.filter(step =>
          find(parsed, step, step.preconditions).status === "bound");
        if (!choices.length) return terminal(state, "handoff", "target_unbound", parsed);
        state.forceAdvice = true;
        return advice(state, parsed, choices);
      }
      if (groupMatches(parsed, state.verification))
        return terminal(state, "verified", "observed_completion", parsed);
      const stage = state.stages[state.stageIndex];
      const step = stage.transitions.find(t => t.id === choice.candidateId);
      const binding = find(parsed, step, step.preconditions);
      if (binding.status !== "bound") return terminal(state, "handoff", "target_unbound", parsed);
      const result = await act(state, parsed, stage, step, binding.node.index);
      return result.done ? result.value : await drive(state, result.parsed);
    } finally {
      state.inFlight = false;
    }
  }
  return Object.freeze({ createSession, advance, resume });
})();
