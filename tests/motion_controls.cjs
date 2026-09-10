// Offline interaction contract for new route/clearance layers, not browser visual QA.
const fs=require('node:fs'),assert=require('node:assert/strict');
for(const scenario of ['row_column','dense_right','dense_left']){
 const h=require('./viewer_harness.cjs')(fs.readFileSync(`artifacts/motion-planner/${scenario}/animation.html`,'utf8'));
 const {get,el}=h,source=get('JSON.stringify(data)');
 assert.equal(get('data.plans.length'),1);
 assert.equal(get('Object.keys(data.plans[0].paths).length'),scenario==='row_column'?3:16);
 assert.equal(get('data.scene.slm_clearance_um'),1);
 assert(el('planned-path').checked);
 el('next').onclick();assert(el('route-caption').textContent.includes('Q000'));
 el('atom-Q002').onclick();assert(el('route-caption').textContent.includes('Q002'));
 const before=get('JSON.stringify(current.atoms)');
 for(const id of ['planned-path','clearance']){
  for(const enabled of [true,false]){el(id).checked=enabled;el(id).onchange();assert.equal(get('JSON.stringify(current.atoms)'),before)}
 }
 el('pulse').onclick();assert.equal(get('current.f.gate_status'),'running');
 el('mode').value='physical';el('mode').onchange();const time=get('ui.time');
 el('mode').value='keyframe';el('mode').onchange();assert.equal(get('ui.time'),time);
 assert.equal(get('JSON.stringify(data)'),source);
 console.log(`PASS ${scenario}: per-atom planned route, clearance switches, clocks, immutable recording`);
}
