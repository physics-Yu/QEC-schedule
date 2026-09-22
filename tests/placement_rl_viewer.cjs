// Independent saved-witness ledger for the discrete RL placement inspector.
// No compiler, exporter, browser shim, or physical trajectory implementation is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { replayState } = require('../src/neutral_atom_app/visualization/placement_rl_inline.js');

const runRoot = path.resolve(process.argv[2] || 'artifacts/placement-rl/pilot-20260922-attempt2');
const counts = { witnesses: 0, seeks: 0, events: 0, pulses: 0, gates: 0, reversedSeeks: 0 };
let randomState = 20260922;
function random() {
  randomState ^= randomState << 13;
  randomState ^= randomState >>> 17;
  randomState ^= randomState << 5;
  return (randomState >>> 0) / 4294967296;
}
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function compact(event) {
  const item = { k: event.kind, t: event.start_us, d: event.duration_us };
  for (const [key, short] of Object.entries({
    group: 'g', qubits: 'q', positions: 'p', sources: 's', phase: 'ph',
    layer: 'l', gate_indices: 'gi', pairs: 'pairs',
  })) if (event[key] !== undefined) item[short] = clone(event[key]);
  return item;
}
function pairKey(pair) { return [...pair].sort((a, b) => a - b).join(':'); }
function sortedDone(done) { return [...done].sort(); }

function checkWitness(filename) {
  const witness = JSON.parse(fs.readFileSync(filename, 'utf8'));
  assert.equal(witness.result.status, 'completed', filename);
  assert.equal(witness.audit.ok, true, filename);
  const { circuit, hardware, mapping } = witness;
  const circuitCase = { circuit, hardware };
  const events = witness.result.trace;
  const replay = { mapping, duration_us: witness.result.duration_us, events: events.map(compact) };
  const originalInputs = JSON.stringify({ circuitCase, replay });
  const positions = mapping.map(index => clone(hardware.storage[index]));
  const holders = Array(circuit.n_qubits).fill('SLM');
  const done = [];
  const snapshots = [{ positions: clone(positions), holders: [...holders], done: [] }];
  const gateIds = circuit.layers.flatMap((layer, li) => layer.map((_, gi) => `${li}:${gi}`));
  const seenGates = new Set();
  const storage = new Set(hardware.storage.map(point => JSON.stringify(point)));
  const pulseEnds = new Map();
  const times = new Set([0, replay.duration_us, replay.duration_us + 1]);
  let priorEnd = 0;

  // Build each expected committed snapshot once, from the original verbose trace.
  events.forEach((event, index) => {
    const start = event.start_us;
    const end = start + event.duration_us;
    assert(Number.isFinite(start) && Number.isFinite(end) && event.duration_us > 0, filename);
    assert(start >= priorEnd, `overlapping serialized trace: ${filename} event ${index}`);
    priorEnd = end;
    for (const time of [start, (start + end) / 2, end - Math.max(1, Math.abs(end)) * 1e-12, end]) {
      times.add(time);
    }
    if (event.kind === 'pulse') {
      counts.pulses++;
      assert.equal(event.pairs.length, event.gate_indices.length, filename);
      const touched = new Set();
      event.gate_indices.forEach((gi, pairIndex) => {
        const id = `${event.layer}:${gi}`;
        assert(!seenGates.has(id), `duplicate CZ ${id}: ${filename}`);
        assert.deepEqual(pairKey(event.pairs[pairIndex]), pairKey(circuit.layers[event.layer][gi]), filename);
        event.pairs[pairIndex].forEach(qubit => {
          assert.equal(holders[qubit], 'SLM', `CZ holder ${id}: ${filename}`);
          assert(!touched.has(qubit), `overlapping pulse atoms ${id}: ${filename}`);
          touched.add(qubit);
        });
        const [a, b] = event.pairs[pairIndex];
        assert(hardware.entangling.some(site =>
          (JSON.stringify(positions[a]) === JSON.stringify(site[0]) && JSON.stringify(positions[b]) === JSON.stringify(site[1])) ||
          (JSON.stringify(positions[a]) === JSON.stringify(site[1]) && JSON.stringify(positions[b]) === JSON.stringify(site[0]))
        ), `CZ site ${id}: ${filename}`);
        seenGates.add(id);
        done.push(id);
        pulseEnds.set(id, end);
      });
    } else {
      assert(['load', 'move', 'unload'].includes(event.kind), filename);
      assert.equal(event.qubits.length, event.positions.length, filename);
      event.qubits.forEach((qubit, j) => {
        assert(Number.isInteger(qubit) && qubit >= 0 && qubit < circuit.n_qubits, filename);
        if (event.kind === 'move') {
          assert.equal(holders[qubit], 'AOD', filename);
          assert.deepEqual(positions[qubit], event.sources[j], `move source: ${filename}`);
          positions[qubit] = clone(event.positions[j]);
        } else {
          assert.deepEqual(positions[qubit], event.positions[j], `transfer location: ${filename}`);
          assert.equal(holders[qubit], event.kind === 'load' ? 'SLM' : 'AOD', filename);
          holders[qubit] = event.kind === 'load' ? 'AOD' : 'SLM';
        }
      });
    }
    snapshots.push({ positions: clone(positions), holders: [...holders], done: [...done] });
  });

  assert.equal(priorEnd, replay.duration_us, filename);
  assert.deepEqual(sortedDone(seenGates), sortedDone(gateIds), `complete CZ circuit: ${filename}`);
  assert.deepEqual(positions, witness.result.final_positions, `saved final positions: ${filename}`);
  assert(holders.every(holder => holder === 'SLM'), `terminal AOD not empty: ${filename}`);
  assert(positions.every(point => storage.has(JSON.stringify(point))), `terminal outside storage: ${filename}`);

  function checkTime(time) {
    // Derive the ledger prefix using original event ends, independently of viewer internals.
    const prefix = events.filter(event => event.start_us + event.duration_us <= time).length;
    const expected = snapshots[prefix];
    const activeIndex = events.findIndex(event => event.start_us <= time && time < event.start_us + event.duration_us);
    const actual = replayState(circuitCase, replay, time);
    const label = `${path.relative(runRoot, filename)} @ ${time}`;
    assert.deepEqual(actual.positions, expected.positions, `positions ${label}`);
    assert.deepEqual(actual.holders, expected.holders, `holders ${label}`);
    assert.deepEqual(sortedDone(actual.done), sortedDone(expected.done), `CZ completion ${label}`);
    assert.equal(actual.completedGates, expected.done.length, `CZ count ${label}`);
    assert.equal(actual.eventIndex, prefix, `event prefix ${label}`);
    assert.deepEqual(actual.active, activeIndex < 0 ? null : replay.events[activeIndex], `active operation ${label}`);
    for (const id of gateIds) {
      assert.equal(actual.done.includes(id), pulseEnds.get(id) <= time, `pulse finish ${id}: ${label}`);
    }
    counts.seeks++;
  }

  const ascendingTimes = [...times].sort((a, b) => a - b);
  ascendingTimes.forEach(checkTime);
  // Repeat every sample in deterministic shuffled order; previous seeks must not leak state.
  const shuffled = [...ascendingTimes];
  for (let i = shuffled.length - 1; i > 0; --i) {
    const j = Math.floor(random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  let previousTime = Infinity;
  shuffled.forEach(time => {
    if (time < previousTime) counts.reversedSeeks++;
    checkTime(time);
    previousTime = time;
  });
  assert.equal(JSON.stringify({ circuitCase, replay }), originalInputs, `read-only inputs: ${filename}`);
  counts.witnesses++;
  counts.events += events.length;
  counts.gates += gateIds.length;
}

for (const mode of ['adversarial', 'uniform']) {
  for (const seed of [11, 29]) {
    const witnessRoot = path.join(runRoot, `${mode}-seed-${seed}`, 'witnesses');
    const cases = fs.readdirSync(witnessRoot).filter(name => /^(test|size_holdout)-\d+$/.test(name)).sort();
    assert.equal(cases.length, 10, witnessRoot);
    for (const caseId of cases) {
      for (const method of ['interaction', 'trained_greedy']) {
        for (let scenario = 0; scenario < 5; ++scenario) {
          checkWitness(path.join(witnessRoot, caseId, `${method}-${scenario}.json`));
        }
      }
    }
  }
}
assert.equal(counts.witnesses, 400);
console.log(JSON.stringify({ status: 'passed', ...counts, scope: 'discrete trace state only; physical validation and GUI separate' }, null, 2));
