/* Viewer interaction tests with a DOM/canvas adapter, not browser rendering. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assets = path.resolve(__dirname, '../../src/nadit_physical_compiler/visualization/web');

function viewer() {
  let height = 600;
  const nodes = new Map(), timers = new Map(), frames = new Map(), rectangles = [];
  const circles = [], texts = [], resizeObservers = [];
  let serial = 0;
  const context = new Proxy({fillRect(...args) { rectangles.push([this.fillStyle, ...args]); },
    arc(x, y, radius) { circles.push({x, y, radius, lineWidth: this.lineWidth}); },
    fillText(text) { texts.push({text, font: this.font}); }},
    {get: (obj, key) => obj[key] ?? (() => {})});
  const document = {handlers: {}, fullscreenElement: null, activeElement: null,
    addEventListener(name, fn) { this.handlers[name] = fn; }};
  function element(id, tag = 'DIV') {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, {id, tagName: tag, value: '', textContent: '', hidden: false,
        checked: false, style: {}, dataset: {}, handlers: {}, attributes: {}, children: [],
        classList: {add: c => classes.add(c), remove: c => classes.delete(c),
          contains: c => classes.has(c), toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }},
        addEventListener(name, fn) { this.handlers[name] = fn; },
        setAttribute(k, v) { this.attributes[k] = v; },
        append(...children) { this.children.push(...children); },
        replaceChildren() { this.children = []; },
        focus() { document.activeElement = this; },
        click() { return this.handlers.click?.({target: this}); },
        getContext() { return context; },
        getBoundingClientRect() { return {left: 0, top: 0, width: 800, height: id === 'step-strip' ? 12 : height}; },
        parentElement: {clientWidth: 800}, setPointerCapture() {}});
    }
    return nodes.get(id);
  }
  const html = fs.readFileSync(path.join(assets, 'viewer.html'), 'utf8');
  for (const match of html.matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"/g)) element(match[2], match[1].toUpperCase());
  document.getElementById = id => nodes.get(id) || null;
  document.createElement = tag => element('new-' + serial++, tag.toUpperCase());
  document.body = element('body');
  const action = kind => ({kind, index: 0, duration_us: 10, text: kind, atoms: [], pairs: [], source_ids: [], patch: {atoms: []}});
  const trace = {title: 'Example', description: '', atom_ir: '', issues: [], duration_us: 45, program_duration_us: 40,
    device: {name: 'device', zones: [{id: 'storage', bounds: [0, 0, 20, 20], operations: ['load', 'store']}], slm_sites: [], aods: []},
    initial: {atoms: []}, steps: ['Load', 'Move', 'Store', 'CZPulse'].map((kind, i) => ({start_us: i * 10, duration_us: 10, actions: [action(kind)]}))};
  trace.initial.atoms = [{id: 0, qubit: 0, x: 5, y: 5, holder: {kind: 'slm', site_id: 's'}}];
  trace.device.slm_sites = [{id: 's', x: 5, y: 5}];
  trace.initial.grids = [{aod_id: 'a', rows: [{id: 0, coordinate: 6}], columns: [{id: 0, coordinate: 6}]}];
  trace.device.aods = [{id: 'a', workspace: [0, 0, 20, 20]}];
  element('sites-toggle').checked = true;
  element('grid-toggle').checked = true;
  element('labels-toggle').checked = true;
  element('atom-replay-data').textContent = JSON.stringify({traces: [trace]});
  for (const [id, value] of Object.entries({'path-select': 'direct', 'speed-select': '1', 'timing-select': 'step'})) element(id).value = value;
  class Replay {
    constructor(trace) { this.trace = trace; this.motion = 'direct'; }
    frame(step, fraction) {
      const s = this.trace.steps[step];
      return {actions: s?.actions || [], time_us: s ? s.start_us + fraction * 10 : this.trace.program_duration_us + fraction * 5,
        elapsed_us: fraction * 10, fraction, atoms: new Map(this.trace.initial.atoms.map(a => [a.id, a])), grids: new Map((this.trace.initial.grids || []).map(g => [g.aod_id, g])), measurements: [], movePaths: new Map()};
    }
  }
  const sandbox = {document, window: {devicePixelRatio: 1},
    AtomReplayQEC: require(path.join(assets, 'qec.js')),
    AtomReplayModel: {Replay, actionProgress: () => 0},
    AtomReplayAnalysis: {Analysis: class {}},
    AtomReplayDashboard: {Dashboard: class {load() {} update() {return null;}}},
    ResizeObserver: class {constructor(fn) {resizeObservers.push(fn);} observe() {}},
    requestAnimationFrame(fn) { const id = ++serial; frames.set(id, fn); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout(fn) {const id = ++serial; timers.set(id, fn); return id;},
    clearTimeout(id) {timers.delete(id);}};
  vm.runInNewContext(fs.readFileSync(path.join(assets, 'viewer.js'), 'utf8'), sandbox);
  return {element, rectangles, circles, texts,
    resize(nextHeight) {height = nextHeight; resizeObservers.forEach(fn => fn()); element('fit-button').click();},
    key(key, target = element('atom-canvas')) { document.handlers.keydown({key, code: key === ' ' ? 'Space' : key, target, preventDefault() {}}); },
    flush() { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn(0)); }};
}

test('atoms, SLM sites and AOD spots scale with scene geometry while labels remain fixed', async () => {
  const v = viewer(), canvas = v.element('atom-canvas');
  const sizes = () => ({
    marks: v.circles.slice(-3).map(({radius}) => radius),
    zoneWidth: v.rectangles.findLast(r => r[0] === '#24374802')[3],
    atomFont: v.texts.findLast(t => t.text === '0').font,
    zoneFont: v.texts.findLast(t => t.text === 'storage').font
  });
  const original = sizes(), initialPosition = v.circles.at(-1).x;
  function proportional() {
    const current = sizes(), ratio = current.zoneWidth / original.zoneWidth;
    current.marks.forEach((radius, i) => assert.ok(Math.abs(radius / original.marks[i] - ratio) < 1e-9));
    assert.equal(current.atomFont, original.atomFont);
    assert.equal(current.zoneFont, original.zoneFont);
  }
  canvas.handlers.wheel({deltaY: 1000, clientX: 400, clientY: 300, preventDefault() {}});
  proportional();
  assert.ok(sizes().marks.every((radius, i) => radius < original.marks[i]));
  assert.notEqual(v.circles.at(-1).x, initialPosition, 'world positions must still zoom');
  canvas.handlers.wheel({deltaY: -1000, clientX: 400, clientY: 300, preventDefault() {}});
  proportional();
  v.resize(300);
  proportional();
  await v.element('present-button').click(); v.flush();
  proportional();
  v.key('Escape'); v.flush();
  proportional();
});
