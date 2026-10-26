/* Execute with node --test modules/physical_compiler/tests_js/qec.test.cjs. */
const test = require('node:test');
const assert = require('node:assert/strict');
const {Overlay} = require('../src/nadit_physical_compiler/visualization/web/qec.js');

const record = {
  checks: [
    {id: 'X0', basis: 'X', ancilla: 50, data: [20, 70], data_qubits: [0, 1]},
    {id: 'Z0', basis: 'Z', ancilla: 90, data: [20, 70], data_qubits: [0, 1]},
  ],
  data: [{atom: 20, qubit: 0}, {atom: 70, qubit: 1}],
};
function frame() { return new Map([20, 70, 50, 90].map((id, i) => [id, {id, x: i * 10, y: 0}])); }

test('stabilizer links follow current atom positions without changing the replay', () => {
  const overlay = new Overlay(record), atoms = frame(), before = JSON.stringify(record);
  atoms.set(50, {id: 50, x: 13.5, y: 25});
  const scene = overlay.scene(atoms);
  assert.equal(scene.edges.length, 4);
  assert.deepEqual(scene.edges[0].from, {id: 50, x: 13.5, y: 25});
  assert.equal(scene.edges[0].to.id, 20);
  assert.deepEqual(scene.markers.map(m => m.label), ['X0', 'Z0', 'q0', 'q1']);
  assert.equal(JSON.stringify(record), before);
  assert.equal(atoms.size, 4);
});

test('X, Z and link visibility are independent; all off removes the overlay', () => {
  const overlay = new Overlay(record), atoms = frame();
  assert.deepEqual(overlay.scene(atoms, {Z: false}).edges.map(e => e.basis), ['X', 'X']);
  assert.deepEqual(overlay.scene(atoms, {X: false}).edges.map(e => e.basis), ['Z', 'Z']);
  assert.equal(overlay.scene(atoms, {links: false}).edges.length, 0);
  assert.equal(overlay.scene(atoms, {links: false}).markers.length, 4);
  assert.deepEqual(overlay.scene(atoms, {X: false, Z: false}), {markers: [], edges: []});
});

test('unannotated traces are empty and missing replay atoms never produce dangling links', () => {
  assert.deepEqual(new Overlay().scene(frame()), {markers: [], edges: []});
  const atoms = frame(); atoms.delete(50); atoms.delete(70);
  const scene = new Overlay(record).scene(atoms);
  assert.equal(scene.edges.length, 1);
  assert.equal(scene.edges[0].from.id, 90);
  assert.equal(scene.edges[0].to.id, 20);
});

test('the inspector states physical-qubit supports rather than atom-ID guesses', () => {
  const overlay = new Overlay(record);
  assert.deepEqual(overlay.describe(50), [['QEC role', 'X check X0'], ['Stabilizer', 'X(q0) X(q1)']]);
  assert.deepEqual(overlay.describe(20), [['QEC role', 'Data qubit'], ['Checks', 'X0, Z0']]);
  assert.deepEqual(overlay.describe(123), []);
});
