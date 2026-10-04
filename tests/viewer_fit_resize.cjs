// Camera regression over an actual Executor recording. Geometry and physical time stay unchanged.
const fs=require('node:fs'),assert=require('node:assert/strict');
const h=require('./viewer_harness.cjs')(fs.readFileSync(process.argv[2],'utf8'));
const before=h.get('JSON.stringify(data)');
let width=871.3334,height=420;
h.el('canvas').getBoundingClientRect=()=>({left:0,top:0,width,height});
h.get('resize()');h.el('fit-atoms').onclick();
function visible(){
 const pixels=JSON.parse(h.get('JSON.stringify(current.atoms.filter(a=>a.position).map(a=>[projection().X(a.position.x_um),projection().Y(a.position.y_um)]))'));
 for(const [x,y] of pixels){assert(x>=32&&x<=width-32,`Horizontal clip at ${width}×${height}: ${x}`);assert(y>=32&&y<=height-32,`Vertical clip at ${width}×${height}: ${y}`);}
}
visible();
// The regression happened after fitting the compact canvas, then resizing for a screenshot.
for(const dimensions of [[871.3334,650],[390,420],[320,420],[871.3334,420]]){
 [width,height]=dimensions;h.get('resize()');visible();
}
const pulse=h.get(`data.operations.find(o=>o.kind==='entangling_pulse')`);
if(pulse){h.get(`seek(${(pulse.start+pulse.end)/2})`);h.el('fit-atoms').onclick();visible();height=650;h.get('resize()');visible();}
// User camera gestures cancel automatic fitting, preserving intentional zoom and pan.
h.el('zoomout').onclick();const manual=h.get('JSON.stringify(view)');
height=420;h.get('resize()');assert.equal(h.get('JSON.stringify(view)'),manual);
h.el('fit-atoms').onclick();
const canvas=h.el('canvas');canvas.listeners.pointerdown({button:0,clientX:100,clientY:100,pointerId:1});
canvas.listeners.pointermove({clientX:140,clientY:120,pointerId:1});
canvas.listeners.pointerup({clientX:140,clientY:120,pointerId:1});
const dragged=h.get('JSON.stringify(view)');height=650;h.get('resize()');assert.equal(h.get('JSON.stringify(view)'),dragged);
assert.equal(h.get('JSON.stringify(data)'),before,'Camera fitting must not mutate recording');
console.log('PASS atom fit remains visible through compact/desktop/narrow resize; user zoom/pan stays intentional; recording unchanged');
