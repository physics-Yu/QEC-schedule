/* Canvas/DOM contract smoke test; does not claim browser visual acceptance.
   Usage: node this-file.cjs path/to/exported-trace.json */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const assets = path.resolve(__dirname, '../src/nadit_physical_compiler/visualization/web');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
payload.traces.push({...payload.traces[0], qec: undefined, title: 'No QEC annotation'});
const texts = [], strokes = [];
const context = new Proxy({
  measureText(text) { return {width: String(text).length * 6}; },
  fillText(text) { texts.push(String(text)); },
  stroke() { strokes.push(this.strokeStyle); },
}, {get(target, key) { return key in target ? target[key] : () => {}; }});
class Element {
  constructor(id = '') {
    this.id = id; this.value = '1'; this.checked = false; this.hidden = false;
    this.style = {}; this.dataset = {}; this.children = []; this.events = {};
    this.classList = {add() {}, remove() {}, toggle() {}, contains() { return false; }};
    this.parentElement = this;
  }
  getContext() { return context; }
  getBoundingClientRect() { return {width: 1000, height: 600, left: 0, top: 0}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute() {}
  append(...children) { this.children.push(...children); }
  add(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; }
  focus() {}
}
const nodes = new Map();
const html = fs.readFileSync(path.join(assets, 'viewer.html'), 'utf8');
for (const match of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {
  const element = new Element(match[1]);
  element.checked = /\bchecked\b/.test(match[0]);
  element.hidden = /\bhidden\b/.test(match[0]);
  nodes.set(match[1], element);
}
nodes.get('atom-replay-data').textContent = JSON.stringify(payload);
nodes.get('path-select').value = 'direct';
nodes.get('schedule-mode').value = 'all';
const document = {
  getElementById(id) { assert(nodes.has(id), `Unknown DOM ID ${id}`); return nodes.get(id); },
  createElement() { return new Element(); },
  addEventListener() {}, body: new Element(), activeElement: null,
};
const sandbox = {document, console, Map, Set, Math, JSON, Number, String, Object, Array,
  setTimeout, clearTimeout, requestAnimationFrame() { return 0; }, cancelAnimationFrame() {},
  ResizeObserver: class { observe() {} }, Option: class extends Element {},
  devicePixelRatio: 1, addEventListener() {},
};
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const name of ['paths.js', 'model.js', 'loss.js', 'analysis.js', 'loss-panel.js', 'dashboard.js', 'qec.js', 'viewer.js']) {
  vm.runInContext(fs.readFileSync(path.join(assets, name), 'utf8'), sandbox, {filename: name});
}
assert.equal(nodes.get('qec-controls').hidden, false);
assert(texts.includes('X0') && texts.includes('Z0') && texts.includes('q0'));
function toggle(id, checked) {
  texts.length = strokes.length = 0;
  const input = nodes.get(id); input.checked = checked; input.events.change({target: input});
}
toggle('qec-x-toggle', false);
assert(!texts.includes('X0') && texts.includes('Z0'));
toggle('qec-z-toggle', false);
assert(!texts.includes('X0') && !texts.includes('Z0') && !texts.includes('q0'));
toggle('qec-x-toggle', true);
const withLinks = strokes.filter(color => String(color).startsWith('#3966c6')).length;
toggle('qec-links-toggle', false);
const withoutLinks = strokes.filter(color => String(color).startsWith('#3966c6')).length;
assert(withLinks > withoutLinks && withoutLinks > 0);
for (const step of [4, 5, 18, 35, payload.traces[0].steps.length]) {
  const slider = nodes.get('step-slider'); slider.value = String(step); slider.events.input({target: slider});
}
const select = nodes.get('trace-select');
select.value = '1'; select.events.change({target: select});
assert.equal(nodes.get('qec-controls').hidden, true);
texts.length = 0;
select.value = '0'; select.events.change({target: select});
assert.equal(nodes.get('qec-controls').hidden, false);
assert(texts.includes('X0'));
console.log('PASS: viewer initialization, QEC toggles, links, and timeline scrubbing');
