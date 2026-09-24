"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, "fixture script must exist");

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.value = "";
    this.disabled = false;
    this._text = "";
  }

  set textContent(value) {
    this._text = value;
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map(child => child.textContent).join("");
  }

  setAttribute(key, value) {
    this.attributes[key] = value;
    if (key === "disabled") this.disabled = true;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
    this._text = "";
  }

  addEventListener(event, listener) {
    this.listeners[event] = listener;
  }

  click() {
    if (!this.disabled) this.listeners.click?.();
  }

  change(value) {
    this.value = value;
    this.listeners.change?.();
  }
}

function load(caseId) {
  const ids = ["case-label", "goal", "workspace", "result", "wrong-actions"];
  const elements = Object.fromEntries(ids.map(id => [id, new Element("div")]));
  const document = {
    getElementById: id => elements[id],
    createElement: tag => new Element(tag),
    body: new Element("body")
  };
  vm.runInNewContext(script, {
    document,
    location: { search: `?case_id=${caseId}` },
    URLSearchParams
  });
  return elements;
}

function findAll(root, predicate) {
  return [root, ...root.children.flatMap(child => findAll(child, predicate))].filter(predicate);
}

function rows(workspace) {
  return findAll(workspace, element => element.attributes.class === "row");
}

function rowNamed(workspace, name) {
  return rows(workspace).find(row => row.children[0].children[0].textContent === name);
}

const caseId = "browser-long_tree-0";
const initial = load(caseId);
const firstRows = rows(initial.workspace);
assert.equal(firstRows.length, 37);
assert.equal(new Set(firstRows.map(row => row.children[1].textContent)).size, 1);
assert.equal(firstRows[0].children[1].textContent, "Open");
assert.equal(firstRows.findIndex(row => row.children[0].children[0].textContent === "Quartz"), 25);
assert.equal(rowNamed(initial.workspace, "Quartz").children[1].disabled, true);
assert.equal(initial.result.textContent, "Task incomplete");

rowNamed(initial.workspace, "Quartz").children[1].click();
assert.equal(initial["wrong-actions"].textContent, "Wrong actions: 0");
firstRows[0].children[1].click();
assert.equal(initial["wrong-actions"].textContent, "Wrong actions: 1");
assert.equal(initial.result.textContent, "Opened Request 01 before reaching the requested state.");

findAll(initial.workspace, element => element.tag === "button" && element.textContent === "Research")[0].click();
assert.equal(rowNamed(initial.workspace, "Quartz").children[1].disabled, true);
const afterQueueIndex = rows(initial.workspace).findIndex(row => row.children[0].children[0].textContent === "Quartz");
assert.notEqual(afterQueueIndex, 25, "queue selection should invalidate the prior row index");
findAll(initial.workspace, element => element.tag === "select")[0].change("Ready");
assert.equal(rowNamed(initial.workspace, "Quartz").children[1].disabled, false);
const finalIndex = rows(initial.workspace).findIndex(row => row.children[0].children[0].textContent === "Quartz");
assert.notEqual(finalIndex, afterQueueIndex, "status selection should invalidate the prior row index");
rowNamed(initial.workspace, "Quartz").children[1].click();
assert.equal(initial.result.textContent, `PASS ${caseId}`);
assert.equal(initial.result.dataset.result, "pass");
assert.equal(initial["wrong-actions"].textContent, "Wrong actions: 1");

const fresh = load(caseId);
assert.equal(fresh.result.textContent, "Task incomplete");
assert.equal(fresh["wrong-actions"].textContent, "Wrong actions: 0");
assert.equal(rowNamed(fresh.workspace, "Quartz").children[1].disabled, true);
const invalid = load("browser-long_tree-1");
assert.equal(invalid.workspace.textContent, "No task loaded.");

console.log("browser-long_tree-0: state, wrong action, fresh binding, pass, reset, invalid variant OK");
