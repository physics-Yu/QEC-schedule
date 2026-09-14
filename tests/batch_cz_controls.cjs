// Offline DOM/canvas contract, not an actual-browser rendering claim.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {get,el,arcs}=require('./viewer_harness.cjs')(fs.readFileSync('artifacts/batch-cz-foundation/index.html','utf8'));
arcs.length=0;get('seek(.15)');
assert.equal(get('operationsAt(ui.time).length'),1);
assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),36);
assert.equal(el('status').textContent,'执行中 18 门');
assert(el('gate').textContent.includes('CZ × 18'));
assert.equal(arcs.filter(a=>a[2]===12&&a[3]===-Math.PI/2).length,36,'Both atoms of each physical pair need simultaneous pulse arcs');
get('ui.selected="Q000";seek(.15)');
assert(el('details').innerHTML.includes('<dt>目标伙伴</dt><dd>Q001</dd>'));
for(const mode of ['keyframe','proportional'])for(const time of [0,.075,.15,.299,.3]){
 get(`ui.mode=${JSON.stringify(mode)};seek(${time})`);
 assert(Math.abs(get(`simulationAt(displayAt(${time}))`)-time)<1e-7);
}
get('seek(.3)');assert.equal(get('current.f.gate_counts.completed'),18);
console.log('18 CZ gates share one pulse; all 18 pair visuals and terminal playback verified offline.');
