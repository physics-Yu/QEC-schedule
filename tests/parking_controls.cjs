// Real generated records; DOM/Canvas doubles, not a browser visual acceptance.
const fs=require('node:fs'),assert=require('node:assert/strict');
const createHarness=require('./viewer_harness.cjs');
const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const pair=createHarness(fs.readFileSync('artifacts/rigid-parking-pair/index.html','utf8'));
const {get,el}=pair,original=get('JSON.stringify(data)');
get('seek(230)'); // Midway through AOD -> SLM handoff, not yet committed.
assert.equal(get('transferAt(ui.time).ids.join(",")'),'Q000');
near(get('transferAt(ui.time).mobileMix'),.5);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'mobile');
assert.equal(get('current.atoms.find(a=>a.id==="Q001").holder.holder_type'),'mobile');
get('seek(288)'); // Only Q001 moves after Q000 is parked.
near(get('current.atoms.find(a=>a.id==="Q000").position.x_um'),5);
near(get('current.atoms.find(a=>a.id==="Q001").position.x_um'),11);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_id'),'EZ_PARK');
assert.equal(get('current.atoms.find(a=>a.id==="Q000").activity'),'idle');
get('seek(296)');assert.equal(get('current.f.gate_status'),'running');
near(get('current.atoms.find(a=>a.id==="Q001").position.x_um'),7);
get('seek(362.3)'); // Midway through SLM -> AOD recapture.
assert.equal(get('transferAt(ui.time).ids.join(",")'),'Q000');
near(get('transferAt(ui.time).mobileMix'),.5);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'static');
get('seek(412.3)');assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),2);
near(get('current.atoms[1].position.x_um-current.atoms[0].position.x_um'),10);
get('seek(data.duration)');assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="static").length'),2);
assert.equal(get('JSON.stringify(data)'),original);
assert(el('backend-caption').textContent.includes('SZ 同运'));

const circuit=createHarness(fs.readFileSync('artifacts/rigid-parking/index.html','utf8'));
const operations=JSON.parse(circuit.get('JSON.stringify(data.operations)'));
assert.equal(operations.filter(op=>op.kind==='entangling_pulse').length,6);
for(const op of operations){
 circuit.get(`seek(${op.start})`);
 if(op.kind==='entangling_pulse'){
  assert.equal(circuit.get('current.atoms.filter(a=>a.activity==="gating").length'),2);
  assert.equal(circuit.get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),3);
 }
 if(op.kind==='aod_park'||op.kind==='aod_recapture')assert.equal(circuit.get('transferAt(ui.time).ids.length'),1);
 near(circuit.get('current.columns[1]-current.columns[0]'),10);
 near(circuit.get('current.rows[1]-current.rows[0]'),10);
}
console.log('PASS rigid parking: selective handoff preview, committed holders, static parked atom, local CZ, restored pair, six-gate circuit, rigid axes, immutable record');
