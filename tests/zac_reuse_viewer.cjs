// Fresh ZAC records and current shared viewer; offline DOM/Canvas checks.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
let pulses=0,retentions=0,recordings=0;
const suite=process.argv[2];
const roots=suite?JSON.parse(fs.readFileSync(`${suite}/benchmark.json`,'utf8')).cases.flatMap(c=>Object.entries(c.variants).filter(([m,v])=>v.result).map(([m])=>`${suite}/${c.id}/${m}`)):
 ['cross','repeat','eight','idle','tradeoff'].flatMap(name=>['no_reuse','reuse'].map(mode=>`artifacts/zac-reuse/${name}/${mode}`));
for(const root of roots){
 const html=fs.readFileSync(`${root}/physical.html`,'utf8');
 // Same optional presentation settings as the ZAC circuit report.
 const configured=html.replace(/\);\r?\n<\/script>/,",{gridStepUm:10,showCandidateSites:false,compact:true});\n</script>");
 assert.notEqual(configured,html,'Viewer options must be injected into this test fixture');
 const h=harness(configured),{get,el}=h;
 const original=get('JSON.stringify(data)');
 const recording=JSON.parse(original),result=JSON.parse(fs.readFileSync(`${root}/result.json`,'utf8'));
 assert.equal(el('labels').value,'focus');
 assert(recording.scene.candidates.length>1000); // still retained in source data
 assert(!h.arcs.some(a=>a[2]===1.4)); // unconfigured candidates only hidden by display option
 for(const op of recording.operations.filter(o=>o.kind==='entangling_pulse')){
  get(`seek(${(op.start+op.end)/2})`);
  assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),op.gate_ids.length*2);
  assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
  assert.equal(get('operationsAt(ui.time).length'),1,'CZ pulse is active at its midpoint');
  const atoms=JSON.parse(get('JSON.stringify(current.atoms)'));
  for(const pair of op.intended_pairs){
   const [a,b]=pair.map(q=>atoms.find(a=>a.id===q).position);
   assert(Math.abs(Math.hypot(a.x_um-b.x_um,a.y_um-b.y_um)-2)<1e-8);
  }
  pulses++;
 }
 for(const r of result.reuse_audit){
  get(`seek(${(r.start_us+r.end_us)/2})`);
  const atom=JSON.parse(get(`JSON.stringify(current.atoms.find(a=>a.id===${JSON.stringify(r.atom)}))`));
  assert.equal(atom.holder.holder_type,'static');assert.equal(atom.holder.holder_id,r.holder);
  retentions++;
 }
 for(const playback of ['keyframe','physical']){
  el('mode').value=playback;el('mode').onchange();el('speed').value='32';
  el('reset').onclick();el('play').onclick();
  for(let t=0;t<=1000000&&get('ui.playing');t+=1000)get(`tick(${t})`);
  assert.equal(get('ui.time'),recording.duration);assert.equal(get('ui.playing'),false);
  assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
  assert.equal(get('operationsAt(ui.time).length'),0,'No operation remains active at a completed record boundary');
  assert.match(el('axis-live-summary').textContent,/静止/);
  assert.match(el('operation-title').textContent,/记录结束/);
 }
 assert.equal(get('JSON.stringify(data)'),original);recordings++;
}
console.log(`PASS: ${recordings} current recordings, ${pulses} real pulses, ${retentions} retained atom intervals, both modes at 32x, immutable source and display sampling`);
