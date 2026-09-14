// DOM/Canvas contract using an actual Executor recording supplied by pytest.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs')(fs.readFileSync(process.argv[2],'utf8'));
const {get,el,arcs}=harness;
const op=JSON.parse(get('JSON.stringify(data.operations.find(o=>o.kind==="raman_rotation"))'));
const before=get('JSON.stringify(data)');
for(const id of ['slm','aod','grid','planned-path','clearance','zones'])el(id).checked=false;
arcs.length=0;get(`seek(${(op.start+op.end)/2})`);
const actual=op.applied_gate_ids.flatMap(id=>op.gate_qubits[id]);
const illumination=arcs.filter(a=>a[2]===13);
assert.equal(illumination.length,actual.length,'One actual target arc, none for false conditions');
for(const q of actual){
 const xy=JSON.parse(get(`JSON.stringify((()=>{const p=current.atoms.find(a=>a.id===${JSON.stringify(q)}).position,proj=projection();return [proj.X(p.x_um),proj.Y(p.y_um)]})())`));
 assert(illumination.some(a=>Math.abs(a[0]-xy[0])<1e-9&&Math.abs(a[1]-xy[1])<1e-9));
}
for(const q of op.qubit_ids){
 const activity=get(`current.atoms.find(a=>a.id===${JSON.stringify(q)}).activity`);
 assert.equal(activity,actual.includes(q)?'gating':'controlling');
}
if(actual.length===0)assert(el('operation-caption').textContent.includes('未施加激光'));
else if(actual.length<op.qubit_ids.length)assert(el('operation-caption').textContent.includes('条件为假、不打光'));
assert.equal(get('JSON.stringify(data)'),before,'Viewer must never mutate physical recording');
// Old single-target recordings omit the new metadata; preserve their light display.
get(`var oldPayload=JSON.parse(JSON.stringify(data));var oldOp=oldPayload.operations.find(o=>o.kind==='raman_rotation');oldOp.gate_ids=['x0'];oldOp.gate_id='x0';oldOp.qubit_ids=['q0'];oldOp.applied=true;delete oldOp.applied_gate_ids;delete oldOp.applied_by_gate;delete oldOp.gate_qubits;var oldRoot=newContainer();var legacy=window.NeutralAtomViewer.mount(oldRoot,oldPayload);`);
arcs.length=0;get(`legacy.setTime(${(op.start+op.end)/2})`);
assert.equal(arcs.filter(a=>a[2]===13).length,1);
get('legacy.destroy()');
console.log('PASS native batch actual target arcs, false controls, legacy fallback, immutable data');
