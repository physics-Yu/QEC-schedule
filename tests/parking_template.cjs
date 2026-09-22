// Independent geometric checks and optional equivalence to saved Executor recordings.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const E=require('../src/neutral_atom_strategies/motion/parking_template.js');
const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const pos=(a,s)=>s.loaded[a.id]?[s.x[s.loaded[a.id].c],s.y[s.loaded[a.id].r]]:[a.x,a.y];
function segmentDistance(a,b,p){const v=b.map((x,i)=>x-a[i]),w=p.map((x,i)=>x-a[i]),n=v[0]**2+v[1]**2,t=n?Math.max(0,Math.min(1,(v[0]*w[0]+v[1]*w[1])/n)):0;return Math.hypot(a[0]+t*v[0]-p[0],a[1]+t*v[1]-p[1]);}
function check(input){
 const serialized=JSON.stringify(input),p=E.compile(input);assert.equal(JSON.stringify(input),serialized);
 for(const o of p.operations){
  for(const s of [o.before,o.after])for(const axis of [s.x,s.y])for(let i=1;i<axis.length;i++)assert(axis[i]-axis[i-1]>1.01);
  for(const [id,cell] of Object.entries(o.before.loaded)){assert(o.after.loaded[id]);assert(o.after.rows[cell.r]&&o.after.cols[cell.c]);}
  if(o.type==='load'){
   const actual=[];
   for(const a of p.atoms)if(!o.before.loaded[a.id]){
    for(let r=0;r<o.after.y.length;r++)if(o.after.rows[r])for(let c=0;c<o.after.x.length;c++)if(o.after.cols[c]){
     const dist=Math.hypot(a.x-o.after.x[c],a.y-o.after.y[r]);
     if(dist<1e-8)actual.push(a.id);else assert(dist>1,'Unexpected close empty trap');
    }
   }
   assert.deepEqual(actual.sort(),[...o.ids].sort(),'Capture must include all active intersections');
   assert(actual.every(id=>p.atoms.find(a=>a.id===id).target));
   for(const id of actual)assert.equal(E.sample(p,(o.start+o.end)/2).atoms.find(a=>a.id===id).holder,'SLM');
  }
  if(o.type==='move'){
   const a=o.before,b=o.after;
   assert(a.x.every((v,i)=>v===b.x[i])||a.y.every((v,i)=>v===b.y[i]));
   // Analytic entire-segment sweep, including empty active intersections.
   const fixed=p.atoms.filter(atom=>!a.loaded[atom.id]);
   for(let r=0;r<a.y.length;r++)if(a.rows[r])for(let c=0;c<a.x.length;c++)if(a.cols[c])for(const atom of fixed)
    assert(segmentDistance([a.x[c],a.y[r]],[b.x[c],b.y[r]],[atom.x,atom.y])>1-1e-8,'SLM sweep collision');
   const carried=p.atoms.filter(atom=>a.loaded[atom.id]);
   for(let i=0;i<carried.length;i++)for(let j=0;j<i;j++){
    const p0=pos(carried[i],a),q0=pos(carried[j],a),p1=pos(carried[i],b),q1=pos(carried[j],b);
    assert(segmentDistance(p0.map((v,k)=>v-q0[k]),p1.map((v,k)=>v-q1[k]),[0,0])>1-1e-8);
   }
   for(const atom of carried){const midpoint=E.sample(p,(o.start+o.end)/2).atoms.find(t=>t.id===atom.id),a0=pos(atom,a),a1=pos(atom,b);near(midpoint.x,(a0[0]+a1[0])/2);near(midpoint.y,(a0[1]+a1[1])/2);}
  }
 }
 for(const a of E.sample(p,p.duration).atoms){near(a.x,a.c*input.spacing_um+(a.target?input.epsilon_x_um+input.shift_x_um:0));near(a.y,a.r*input.spacing_um+(a.target?input.epsilon_y_um+input.shift_y_um:0));assert.equal(a.holder,a.target?'AOD':'SLM');}
 return p;
}
let geometries=0;
for(const strategy of ['naive_rowwise','naive_columnwise','pattern_optimal']){
 for(let mask=0;mask<81;mask++){let n=mask;const s=E.preset('intro');Object.assign(s,{rows:2,columns:2,aod_rows:2,aod_columns:2,strategy});s.cells=Array.from({length:2},()=>Array.from({length:2},()=>{const x=n%3;n=Math.floor(n/3);return x;}));check(s);geometries++;}
 for(const spacing of [5,10,15,20])for(const seed of [7,19,23]){const s=E.preset('random',seed);Object.assign(s,{strategy,spacing_um:spacing,shift_x_um:9*spacing+50});check(s);geometries++;}
 const sparse=E.preset('intro');Object.assign(sparse,{strategy,aod_rows:4,aod_columns:5,cells:[[0,2,0],[1,0,2]]});check(sparse);geometries++;
}
for(const value of [undefined,null,[],{schema:'parking-lab/v1'}, {...E.preset(),obstacles:[{x:1,y:1}]},{...E.preset(),epsilon_x_um:1},{...E.preset(),epsilon_y_um:9},{...E.preset(),aod_rows:2},{...E.preset(),strategy:'optimized'},{...E.preset(),shift_x_um:20}])assert.throws(()=>E.compile(value));
let refs=0;
for(const folder of process.argv.slice(2)){
 const input=JSON.parse(fs.readFileSync(path.join(folder,'input.json'),'utf8')),recording=JSON.parse(fs.readFileSync(path.join(folder,'recording.json'),'utf8')),p=E.compile(input);
 assert.equal(p.operations.length,recording.operations.length);near(p.duration,recording.duration);
 for(let i=0;i<p.operations.length;i++){
  const a=p.operations[i],b=recording.operations[i];near(a.start,b.start);near(a.end,b.end);
  assert.equal(a.type,b.kind==='aod_move'?'move':b.kind==='trap_switch'?'switch':'load');
  if(a.type==='move')for(const axis of ['x','y']){assert.deepEqual(a.before[axis],b.source_axes[axis+'_um']);assert.deepEqual(a.after[axis],b.target_axes[axis+'_um']);}
 }
 refs++;
}
const timings=[];for(let i=0;i<100;i++){const t=performance.now();E.compile(E.preset('random',i));timings.push(performance.now()-t);}timings.sort((a,b)=>a-b);
console.log(JSON.stringify({status:'PASS',geometries,executor_reference_recordings:refs,compile_10x10_ms:{median:timings[50],p95:timings[95],max:timings[99]}},null,2));
