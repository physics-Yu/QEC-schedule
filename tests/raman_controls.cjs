// Offline component controls using actual mixed physical execution, not a browser.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {get,el}=require('./viewer_harness.cjs')(fs.readFileSync(process.argv[2]||'artifacts/circuit-workbench-demo/index.html','utf8'));
const original=get('JSON.stringify(data)'),ops=JSON.parse(get('JSON.stringify(data.operations)'));
assert.equal(ops.filter(o=>o.kind==='raman_rotation').length,3);
assert.equal(ops.filter(o=>o.kind==='entangling_pulse').length,1);
for(const op of ops.filter(o=>o.kind==='raman_rotation')){
 get(`seek(${(op.start+op.end)/2})`);
 assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),1);
 assert.equal(get('current.atoms.find(a=>a.activity==="gating").holder.holder_type'),'static');
 assert(el('operation-caption').textContent.includes('Raman 单比特'));
 assert(el('operation-caption').textContent.includes('1.00 μs'));
 assert(el('route-caption').textContent.includes('无运输路径'));
 assert.equal(get('current.atoms.some(a=>a.activity==="moving")'),false);
}
assert.equal(get('data.summary.categories.find(r=>r.key==="raman").duration_us'),3);
get('seek(data.duration)');assert.equal(get('current.f.gate_counts.completed'),4);
assert.equal(get('JSON.stringify(data)'),original);
console.log('PASS Raman controls: actual mixed execution, stationary SLM, gate parameters, timing, category, completion, immutable payload');
