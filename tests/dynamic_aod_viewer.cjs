// Actual viewer JS with DOM/Canvas doubles; this is not browser GUI acceptance.
const fs=require('node:fs'),assert=require('node:assert/strict');
const harness=require('./viewer_harness.cjs');
const html=fs.readFileSync(process.argv[2],'utf8'),v=harness(html);
const before=v.get('JSON.stringify(data)');
const move=v.get(`data.operations.find(o=>o.kind==='aod_move'&&o.moving_count===3&&['x_um','y_um'].some(k=>o.source_axes[k].some((x,i)=>Math.abs((x-o.source_axes[k][0])-(o.target_axes[k][i]-o.target_axes[k][0]))>1e-7)))`);
assert(move,'Recorded loaded reshape must exist');
v.get(`seek(${move.start})`);
assert.match(v.el('axis-live-summary').textContent,/改变相对间距/);
assert.match(v.el('axis-live-coordinates').textContent,/当前相对首轴/);
v.get(`seek(${(move.start+move.end)/2})`);
const actual=JSON.parse(v.get('JSON.stringify(current.columns)'));
assert.deepEqual(actual,Array.from(move.source_axes.x_um,(x,i)=>(x+move.target_axes.x_um[i])/2));
v.get('seek(0)');v.el('axis-next-reshape').onclick();
assert.equal(v.get('ui.time'),(move.start+move.end)/2);
assert.match(v.el('axis-plan-summary').textContent,/承载原子/);
assert.equal(v.get('JSON.stringify(data)'),before,'UI must not mutate recording');
// Old recordings lack the new operation metadata: movement frames remain truth.
const old=JSON.parse(before);
for(const o of old.operations){delete o.source_axes;delete o.target_axes;delete o.moving_atom_ids;delete o.enabled_rows;delete o.enabled_columns;}
v.get(`var legacy=window.NeutralAtomViewer.mount(newContainer(),${JSON.stringify(old)});legacy.setTime(${(move.start+move.end)/2});`);
assert.equal(v.get('legacy.getStatus().time_us'),(move.start+move.end)/2);
console.log('PASS loaded reshape navigation, cubic midpoint axes, live offsets, read-only rendering, legacy recording fallback');
