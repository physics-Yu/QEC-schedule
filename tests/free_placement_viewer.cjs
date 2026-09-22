// Reuse the physical viewer contract harness; GUI acceptance is separately logged.
const fs=require('node:fs'),assert=require('node:assert/strict'),harness=require('./viewer_harness.cjs');
const root=process.argv[2]||'artifacts/free-placement/default',report=JSON.parse(fs.readFileSync(`${root}/comparison.json`,'utf8'));
assert.equal(report.status,'completed');assert(report.diagnostics.free_placement);
if(!process.argv[2]){assert(report.diagnostics.selected_changed_shape);assert.equal(report.diagnostics.allowed_site_count,32);}
const terminalMode=report.terminal_mode||report.options?.terminal_mode;
const sourceSites=report.source_sites||report.candidate_sites;
let pulses=0;const final=[];
for(const mode of ['baseline','optimized']){
 const h=harness(fs.readFileSync(`${root}/${mode}.html`,'utf8')),{get,el}=h;
 const raw=get('JSON.stringify(data)'),data=JSON.parse(raw);
 const initial=JSON.parse(get('JSON.stringify(current.atoms)'));
 assert.equal(initial.length,report.input.atom_count);
 const mapping=mode==='baseline'?report.baseline.mapping:report.selected.mapping;
 for(const [q,s] of mapping){const atom=initial.find(a=>a.id===q),site=sourceSites.find(a=>a.id===s);assert.deepEqual(atom.position,{x_um:site.x_um,y_um:site.y_um});}
 const seen=new Set();
 for(const op of data.operations.filter(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind))){
  for(const id of op.gate_ids){assert(!seen.has(id));seen.add(id);}
  get(`seek(${(op.start+op.end)/2})`);
  if(op.kind==='entangling_pulse'){
   const atoms=JSON.parse(get('JSON.stringify(current.atoms)'));
   assert.equal(atoms.filter(a=>a.activity==='gating').length,2*op.gate_ids.length);
   for(const [a,b] of op.intended_pairs){const p=atoms.find(q=>q.id===a).position,t=atoms.find(q=>q.id===b).position;assert(Math.abs(Math.hypot(p.x_um-t.x_um,p.y_um-t.y_um)-2)<1e-7);}
   pulses++;
  }
 }
 assert.deepEqual([...seen].sort(),report.input.gates.map(g=>g.id).sort());
 for(const playback of ['keyframe','physical']){
  el('mode').value=playback;el('mode').onchange();el('speed').value='32';el('reset').onclick();el('play').onclick();
  for(let t=0;t<1000000&&get('ui.playing');t+=1000)get(`tick(${t})`);
  assert.equal(get('ui.time'),data.duration);assert.equal(get('ui.playing'),false);
 }
 final.push(JSON.parse(get('JSON.stringify(current.atoms.map(a=>[a.id,a.holder,a.position]))')));
 assert.equal(get('JSON.stringify(data)'),raw);
}
if(terminalMode!=='stable')assert.deepEqual(final[0],final[1]);
else {
 assert(report.stable_completion_verified||(report.options?.terminal_mode==='stable'&&report.baseline.evaluation.valid&&report.selected.evaluation.valid));
 for(const mode of ['baseline','optimized']){
  const data=JSON.parse(fs.readFileSync(`${root}/${mode}.json`,'utf8'));
  assert(!data.operations.some(op=>/Return to initial SLM/.test(op.label||op.name||'')));
 }
}
console.log(`PASS: ${root}, ${report.input.atom_count} atoms, ${report.input.gates.length} gates, 2 full circuits, ${pulses} CZ pulses, 2 modes at 32x, ${terminalMode==='stable'?'stable completion':'identical terminal holders/coordinates'}, immutable recording`);
