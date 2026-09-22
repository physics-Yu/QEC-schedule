// Actual shared renderer against the browser template timeline; DOM/Canvas doubles.
const fs=require('node:fs'),assert=require('node:assert/strict');
const E=require('../src/neutral_atom_strategies/motion/parking_template.js'),A=require('../src/neutral_atom_app/visualization/parking_recording.js');
const html=fs.readFileSync('demo/parking/index.html','utf8');
const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('const SHELL='));
assert(script);const near=(a,b)=>assert(Math.abs(a-b)<1e-6,`${a} vs ${b}`);
let frames=0;
for(const strategy of ['naive_rowwise','naive_columnwise','pattern_optimal']){
 const p=E.compile({...E.preset(),strategy}),r=A.recording(p),opts=A.options(p);
 const v=require('./viewer_harness.cjs')('<script>'+script+'\nconst viewer=window.NeutralAtomViewer.mount(document.getElementById("atom-viewer"),'+JSON.stringify(r)+','+JSON.stringify(opts)+');</script>');
 for(const t of [0,p.pickupEnd,p.duration,...p.operations.flatMap(o=>[o.start,(o.start+o.end)/2])]){
  v.get(`seek(${t})`);const actual=v.get('current.atoms'),expected=E.sample(p,t).atoms;
  for(const a of expected){const b=actual.find(b=>b.id===a.id);near(a.x,b.position.x_um);near(a.y,b.position.y_um);assert.equal(b.holder.holder_type,a.holder==='AOD'?'mobile':'static');}frames++;
  for(const a of expected)assert.equal(v.get(`current.f.scene.traps.find(t=>t.id==='S${a.r}_${a.c}').enabled`),a.holder==='SLM');
 }
 assert(v.colors.includes('#db4b50')&&v.colors.includes('#3879c7'));
 assert(v.get('data.scene.grid_x.length')>20);assert(v.get('data.scene.candidates.length')>200);
 v.el('speed').value='32';v.get('seek(0)');v.el('play').onclick();for(let t=0;t<=120000;t+=200)v.get(`tick(${t})`);near(v.get('ui.time'),p.duration);assert.equal(v.get('ui.playing'),false);
 v.get('seek(1)');v.el('next').onclick();assert(v.get('ui.time')>1);
}
console.log(`PASS shared QEC renderer: ${frames} samples, all 85 atom positions/holders, role colors, grid, controls and 32x endpoints in three strategies.`);
// With no options the existing activity-based presentation must stay unchanged.
const baseline=E.compile(E.preset()),normal=require('./viewer_harness.cjs')('<script>'+script+'\nconst viewer=window.NeutralAtomViewer.mount(document.getElementById("atom-viewer"),'+JSON.stringify(A.recording(baseline))+');</script>');
assert(normal.colors.includes('#5364bc'));assert(!normal.colors.includes('#db4b50'));
const move=baseline.operations.find(o=>o.type==='move'&&Object.keys(o.before.loaded).length);
normal.get(`seek(${(move.start+move.end)/2})`);assert(normal.colors.includes('#e89438'));
console.log('PASS unconfigured shared viewer keeps original static/moving color semantics.');
