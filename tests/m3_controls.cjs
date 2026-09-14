// Real physical recording, offline DOM/Canvas contract; browser QA is separate.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
for(const path of ['artifacts/m3-resident/index.html','artifacts/m3-scale-256/index.html']){
 const {get,el}=harness(fs.readFileSync(path,'utf8')),original=get('JSON.stringify(data)');
 const ops=JSON.parse(get('JSON.stringify(data.operations)'));
 const raman=ops.find(o=>o.kind==='raman_rotation'&&ops.some(m=>m.kind==='aod_move'&&m.moving_count>0&&m.start<=o.start&&m.end>o.end));
 assert(raman,'A real move must span a complete Raman pulse');
 const t=(raman.start+raman.end)/2;get(`seek(${t})`);
 assert.equal(get(`operationsAt(${t}).length`),2);
 assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),1);
 assert.equal(get('current.atoms.filter(a=>a.activity==="moving").length'),1);
 const atom=get('current.atoms.find(a=>a.activity==="moving").id');
 const first=get(`JSON.stringify(current.atoms.find(a=>a.id==="${atom}").position)`);
 get(`seek(${raman.end+.1})`);
 assert.equal(get('current.atoms.some(a=>a.activity==="gating")'),false);
 assert.equal(get('current.atoms.some(a=>a.activity==="moving")'),true);
 assert.notEqual(get(`JSON.stringify(current.atoms.find(a=>a.id==="${atom}").position)`),first);
 const duration=get('data.duration');let last=-1;
 for(let i=0;i<=200;i++){
  const time=duration*i/200,display=get(`displayAt(${time})`);
  assert(display>=last);last=display;
  assert(Math.abs(get(`simulationAt(${display})`)-time)<1e-7);
 }
 assert(Math.abs(get('data.summary.resource_busy_us.RAMAN_0')-4)<1e-8);
 assert(get('data.summary.overlap_time_us')>0);
 el('resource-schedule').onclick({target:{getAttribute:key=>key==='data-start'?String(t):null}});
 assert.equal(get('ui.time'),t);
 // All handoffs retain their source holder until the real completion event.
 for(const op of ops){
  get(`seek(${(op.start+op.end)/2})`);
  if(op.kind==='aod_move'&&op.moving_count===0)assert.equal(get('current.f.aod.enabled_rows.some(Boolean)&&current.f.aod.enabled_columns.some(Boolean)'),false);
  if(['aod_load','aod_offload'].includes(op.kind)){
   const q=op.captured[0],loading=op.kind==='aod_load';
   assert.equal(get('current.f.transfer.stage'),'target_supported');
   assert.equal(get(`current.atoms.find(a=>a.id==='${q}').holder.holder_type`),loading?'static':'mobile');
   assert.equal(get('current.f.scene.traps.find(t=>t.id===current.f.transfer.bindings[0].static_trap_id).enabled'),true);
   get(`seek(${op.end})`);
   assert.equal(get(`current.atoms.find(a=>a.id==='${q}').holder.holder_type`),loading?'mobile':'static');
  }
 }
 if(path.includes('256')){
  get('seek(data.duration)');assert.equal(get('current.atoms.length'),256);
  assert(el('atoms-page').textContent.includes('1/8'));
  el('atoms-next').onclick();assert(el('atoms-page').textContent.includes('2/8'));
  el('atom-search').value='Q255';el('atom-search').oninput();
  assert(el('atoms-page').textContent.includes('1 原子'));
  assert.equal(get('current.f.gate_counts.completed'),8);
 }
 assert.equal(get('JSON.stringify(data)'),original);
}
console.log('PASS M3: true concurrent motion/Raman, independent release, shared time mapping, union metrics, 256-atom pagination and immutable replay');
