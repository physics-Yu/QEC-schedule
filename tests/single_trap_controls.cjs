// Actual compiled 12-CZ record, DOM/Canvas doubles; not a browser FPS test.
const fs=require('node:fs'),assert=require('node:assert/strict');
const createHarness=require('./viewer_harness.cjs');
const {get,el}=createHarness(fs.readFileSync(process.argv[2]||'artifacts/single-trap/index.html','utf8'));
const original=get('JSON.stringify(data)'),operations=JSON.parse(get('JSON.stringify(data.operations)'));
assert.equal(operations.filter(o=>o.kind==='entangling_pulse').length,12);
assert(el('backend-caption').textContent.includes('SINGLE TRAP'));
for(const op of operations){
 get(`seek(${(op.start+op.end)/2})`);
 assert.equal(get('current.columns.length*current.rows.length'),1);
 assert(get('current.f.aod.enabled_rows.filter(Boolean).length*current.f.aod.enabled_columns.filter(Boolean).length')<=1);
 if(op.kind==='aod_move'&&op.moving_count===0)assert.equal(get('current.f.aod.enabled_rows.filter(Boolean).length*current.f.aod.enabled_columns.filter(Boolean).length'),0);
 if(['aod_load','aod_offload'].includes(op.kind)){
  assert.equal(get('current.f.transfer.stage'),'target_supported');
  assert(get('current.f.aod.enabled_rows[0]&&current.f.aod.enabled_columns[0]'));
  const site=get('current.f.transfer.bindings[0].static_trap_id');
  assert(get(`current.f.scene.traps.find(t=>t.id===${JSON.stringify(site)}).enabled`));
 }
 assert(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length')<=1);
 if(['aod_load','aod_offload'].includes(op.kind)){
  assert.equal(get('transferAt(ui.time).ids.length'),1);
  assert.equal(get('transferAt(ui.time).ids[0]'),op.captured[0]);
 }
 if(op.kind==='entangling_pulse'){
  assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),2);
  assert.equal(get('current.atoms.filter(a=>a.activity==="gating"&&a.holder.holder_type==="static").length'),1);
 }
 if(op.label==='Transport partner to CZ'){
  assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="static"&&String(a.holder.holder_id).startsWith("EZ")).length'),1);
 }
}
get('seek(data.duration)');
assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
assert.equal(get('JSON.stringify(data)'),original);
console.log('PASS single trap: 12 CZ, dynamic masks, dual support handoffs, dark timed reposition, one active trap, per-operation handoffs, static EZ anchor, actual pulse, individual returns, immutable data');
