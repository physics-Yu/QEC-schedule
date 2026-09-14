// Actual task recordings in a DOM/Canvas double; not browser visual acceptance.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
for(const [path,transport] of [['artifacts/m3-task-program/index.html',false],['artifacts/m3-task-transport/index.html',true]]){
 const {get,el}=harness(fs.readFileSync(path,'utf8'));
 const initial=get('JSON.stringify(data)');
 const ops=JSON.parse(get('JSON.stringify(data.operations)'));
 assert(el('backend-caption').textContent.includes('独立任务'));
 for(const op of ops){
  get(`seek(${(op.start+op.end)/2})`);
  assert(!el('route-caption').textContent.includes('null'));
  if(op.task_phase!=='effect')assert.notEqual(get('current.f.gate_status'),'running');
  else assert.equal(get('current.f.gate_status'),'running');
 }
 assert.equal(get('data.plans.every(p=>p.task_id&&p.operation_intervals.length)'),true);
 if(transport){
  assert(ops.every(o=>o.gate_id===null&&o.effect_gate_id===null));
  assert.equal(el('pulse').disabled,true);
  get('seek(data.duration)');
  assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_id'),'EZ0');
  assert.equal(get('data.summary.metrics.completed_gate_count'),0);
 }else{
  const effects=ops.filter(o=>o.task_phase==='effect');
  assert.equal(effects.length,4);
  assert.equal(new Set(effects.map(o=>o.effect_gate_id)).size,4);
  assert(ops.some(o=>o.task_phase==='cleanup'&&o.category==='return'));
  assert.equal(get('data.summary.metrics.completed_plan_count'),6);
 }
 assert.equal(get('JSON.stringify(data)'),initial);
}
console.log('PASS task recordings: real gateless transport, split effects, cleanup categories, task labels and immutable playback');
