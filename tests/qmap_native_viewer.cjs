// Checks the shared renderer against every saved physical operation; GUI separate.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
const root=process.argv[2]||'artifacts/qmap-native/original-acceptance';
const report=JSON.parse(fs.readFileSync(path.join(root,'summary.json'),'utf8'));
for(const [name,r] of Object.entries(report)){
 assert.equal(r.status,'completed');assert(r.effects_once&&r.replay_equal&&r.terminal_verified);
 const {get,el}=harness(fs.readFileSync(path.join(root,name,'physical.html'),'utf8'));
 const data=JSON.parse(get('JSON.stringify(data)')),seen=new Set();let max=0;
 for(const op of data.operations.filter(o=>['raman_rotation','entangling_pulse'].includes(o.kind))){
  for(const id of op.gate_ids){assert(!seen.has(id));seen.add(id);}
  get(`seek(${(op.start+op.end)/2})`);
  if(op.kind==='entangling_pulse'){
   const atoms=JSON.parse(get('JSON.stringify(current.atoms)'));
   assert.equal(atoms.filter(a=>a.activity==='gating').length,2*op.gate_ids.length);
   for(const [a,b] of op.intended_pairs){const p=atoms.find(q=>q.id===a).position,t=atoms.find(q=>q.id===b).position;assert(Math.abs(Math.hypot(p.x_um-t.x_um,p.y_um-t.y_um)-2)<1e-7);}
   max=Math.max(max,op.gate_ids.length);
  }
 }
 assert.equal(seen.size,r.original_gate_count);assert.equal(max,r.author_metrics.max_parallel_cz);
 if(name==='current9'){
  get("ui.selected='Q005';seek(500)");
  assert(el('details').innerHTML.includes('<dd>Q003</dd>'));
  assert(!el('details').innerHTML.includes('Q000, Q001'));
 }
 for(const mode of ['keyframe','physical']){
  el('mode').value=mode;el('mode').onchange();el('speed').value='32';el('reset').onclick();el('play').onclick();
  for(let t=0;t<10000000&&get('ui.playing');t+=1000)get(`tick(${t})`);
  assert.equal(get('ui.time'),data.duration);assert.equal(get('ui.playing'),false);
 }
 console.log(name,'PASS all gates/CZ geometry/two playback modes');
}
