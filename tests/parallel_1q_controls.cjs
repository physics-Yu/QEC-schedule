const fs=require('node:fs'),assert=require('node:assert/strict');
const h=require('./viewer_harness.cjs')(fs.readFileSync(process.argv[2]||'artifacts/m4-1q-preview.html','utf8'));
const before=h.get('JSON.stringify(data)');h.el('pulse').onclick();
assert.equal(h.get('ui.time'),.5,'Pulse button selects an actual interval, not a zero-time completion frame');
assert.equal(h.get('current.atoms.filter(a=>a.activity==="gating").length'),4);
assert.equal(h.el('status').textContent,'执行中 4 门');
for(const q of ['Q000','Q001','Q002','Q003']){
 assert(h.el('gate').textContent.includes(q));
 assert(h.el('summary').innerHTML.includes('Raman '+q));
}
assert.equal(h.get('operationsAt(.5).length'),4);
assert(h.arcs.filter(a=>a[2]===13).length>=4,'Four independent Raman pulse rings');
h.get('seek(data.duration)');assert.equal(h.get('current.f.gate_counts.completed'),4);
assert.equal(h.get('JSON.stringify(data)'),before);
console.log('PASS four simultaneous 1Q effects, pulse rings, labels, per-qubit resource rows and terminal');
