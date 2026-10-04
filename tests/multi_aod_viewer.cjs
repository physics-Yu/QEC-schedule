// Canvas/DOM contract over a real two-lane Executor recording; GUI acceptance is separate.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
const v=harness(fs.readFileSync(process.argv[2],'utf8'));
const before=v.get('JSON.stringify(data)');
const ops=JSON.parse(v.get('JSON.stringify(data.operations.filter(o=>o.kind==="aod_move"))'));
assert.equal(ops.length,2);
const time=Math.min(...ops.map(o=>o.end))/2;
v.get(`seek(${time})`);
const sampled=JSON.parse(v.get('JSON.stringify(current)'));
assert.deepEqual(Object.keys(sampled.arrays).sort(),['AOD_0','AOD_MAGIC']);
for(const op of ops){
 const p=sampled.atoms.find(a=>a.id===op.moving_atom_ids[0]).position;
 const u=(time-op.start)/(op.end-op.start);
 const x=op.source_axes.x_um[0]+u*(op.target_axes.x_um[0]-op.source_axes.x_um[0]);
 const y=op.source_axes.y_um[0]+u*(op.target_axes.y_um[0]-op.source_axes.y_um[0]);
 assert(Math.abs(p.x_um-x)<1e-9&&Math.abs(p.y_um-y)<1e-9);
}
assert(sampled.atoms[1].position.x_um-sampled.atoms[0].position.x_um>90,
 'Equal (0,0) indices must not alias independent device coordinates');
assert.match(v.el('axis-live-summary').textContent,/算法 AOD.*魔态 AOD/);
v.get('viewer.selectAtom("Q001")');
assert.match(v.el('details').innerHTML,/魔态 AOD · row 0, col 0/);
v.get('seek(data.duration);seek(0)');
assert.equal(v.get('current.atoms.find(a=>a.id==="Q001").position.x_um'),120);
assert.equal(v.get('JSON.stringify(data)'),before,'Viewer must not mutate recording');
// A historical one-array view keeps the same serialized primary fields.
v.get(`var legacy=JSON.parse(JSON.stringify(data));legacy.frames=legacy.frames.map(f=>{delete f.aods;delete f.axes_by_aod;delete f.movements;f.atom_updates=f.atom_updates.filter(a=>a.id==='Q000');return f;});legacy.operations=legacy.operations.filter(o=>o.aod_id==='AOD_0');var old=window.NeutralAtomViewer.mount(newContainer(),legacy);old.setTime(${time});`);
assert.equal(v.get('old.getStatus().time_us'),time);
console.log('PASS two real AOD lanes, distinct equal-index cells, per-lane interpolation, reverse seek, read-only data and legacy primary fields');
