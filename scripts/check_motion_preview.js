// Geometric counterexamples and time mapping checks, independent of circuit compilation.
const assert=require('node:assert/strict'),fs=require('node:fs');
const M=require('../viewer/motion-preview.js');
function atom(i,x,y){return['a'+i,'q'+i,x,y,'SLM','data'];}
function move(start,end,trs){return[start,end,'move',trs.map(t=>t[0]),trs,[],'','completed',[]];}
function scene(atoms,actions){return{atoms,actions,end:Math.max(...actions.map(a=>a[1]))};}
const checks=[];
// X then Y passes through (2,0); the Y-first alternative remains separated.
let d=scene([atom(0,0,0),atom(1,2,0)],[move(0,8,[[0,0,0,4,4]])]);
let engine=M.create(d),r=engine.routeFor(d.actions[0]);
assert.equal(r.type,'yx');assert(r.passed);assert.equal(r.minGap,2);checks.push('blocked_X_first_selects_clear_Y_first');
// Both simple elbows are blocked, so choose a three-segment side corridor.
d=scene([atom(0,0,0),atom(1,2,0),atom(2,0,2)],[move(0,8,[[0,0,0,4,4]])]);
engine=M.create(d);r=engine.routeFor(d.actions[0]);assert(r.type.startsWith('corridor'));assert(r.passed);checks.push('blocked_elbows_use_side_corridor');
// Crossing movers on independent batches must be checked against each other.
d=scene([atom(0,-2,0),atom(1,0,-2)],[move(0,8,[[0,-2,0,2,0]]),move(0,8,[[1,0,-2,0,2]])]);
engine=M.create(d);r=engine.routeFor(d.actions[0]);assert(r.passed&&!r.fallback);assert.equal(engine.clusters.length,1);
for(let t=0;t<=8;t+=.01){const a=engine.point(0,t),b=engine.point(1,t);assert(Math.hypot(a[0]-b[0],a[1]-b[1])>=1-1e-8);}
checks.push('concurrent_batches_avoid_between_frame_crossing');
// An invalid starting clearance cannot be repaired by drawing a prettier path.
d=scene([atom(0,0,0),atom(1,.2,0)],[move(0,8,[[0,0,0,4,4]])]);
engine=M.create(d);r=engine.routeFor(d.actions[0]);assert(r.fallback&&!r.passed);checks.push('unsafe_endpoint_keeps_explicit_unqualified_original');
// A rigid four-atom batch remains rigid throughout every axis step.
const starts=[[0,0],[4,0],[0,4],[4,4]];
d=scene(starts.map((p,i)=>atom(i,...p)),[move(1,11,starts.map((p,i)=>[i,...p,p[0]+8,p[1]+6]))]);
engine=M.create(d);for(let t=1;t<=11;t+=.1){const p=engine.point(0,t);for(let i=1;i<4;i++){const q=engine.point(i,t);assert(Math.abs(q[0]-p[0]-starts[i][0])<1e-8);assert(Math.abs(q[1]-p[1]-starts[i][1])<1e-8);}}
checks.push('rigid_batch_shape_and_shared_axis_progress_preserved');
const c=M.timeline(d);for(const t of [0,.3,1,4,10.9,11])assert(Math.abs(c.modelAt(c.displayAt(t))-t)<1e-8);
assert.equal(M.advance(0,1,{mode:'physical',speed:1,usPerSecond:1000000,stop:2000,clock:c}),1000);
assert.equal(M.advance(0,50,{mode:'physical',speed:2,usPerSecond:100,stop:2000,clock:c}),10);
assert.equal(M.advance(0,100000,{mode:'keyframe',stop:11,clock:c}),11);
checks.push('clock_round_trip_original_time_and_large_frame_delta');
const result={passed:true,checks,scope:'synthetic display geometry and clocks; no hardware-route qualification or compilation'};
const out=process.argv[2];if(out)fs.writeFileSync(out,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
