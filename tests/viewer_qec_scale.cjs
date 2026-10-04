// Real Executor recording; Canvas doubles verify proportional geometry and role truth.
// This does not replace the separate real-browser visual acceptance.
const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8'),h=require('./viewer_harness.cjs')(html);
const before=h.get('JSON.stringify(data)'),near=(a,b)=>assert(Math.abs(a-b)<1e-9,`${a} != ${b}`);
let width=900,height=650;
h.el('canvas').getBoundingClientRect=()=>({left:0,top:0,width,height});
h.get('resize()');h.el('fit-atoms').onclick();
h.el('labels').value='none';
const strokes=[];let path=[];
Object.assign(h.context,{beginPath(){path=[]},moveTo(x,y){path.push(['M',x,y])},lineTo(x,y){path.push(['L',x,y])},stroke(){strokes.push({color:h.context.strokeStyle,width:h.context.lineWidth,path:[...path]})}});
function snapshot(){
 h.arcs.length=0;strokes.length=0;h.get('draw()');
 const geometry=JSON.parse(h.get('JSON.stringify(markerGeometry())'));
 const glyphs=strokes.filter(s=>s.color==='#fff');
 const atoms=h.arcs.filter(a=>Math.abs(a[2]-geometry.atom)<1e-9);
 const traps=h.arcs.filter(a=>Math.abs(a[2]-geometry.trap)<1e-9);
 assert(atoms.length>0&&traps.length>0,'Rendered geometry must use projected marker sizes');
 near(geometry.atom/geometry.trap,1.15);
 assert.equal(glyphs.length,104,'48 X + 48 Z algorithm roles, plus 8 explicitly unencoded resource template roles');
 assert(glyphs.every(s=>s.path.length===4&&s.width>0),'Every role has a persistent vector glyph even with labels hidden');
 return {geometry,glyphs:JSON.parse(JSON.stringify(glyphs)),scale:h.get('projection().scale')};
}
const initial=snapshot();
h.el('zoomout').onclick();const smaller=snapshot();
for(const key of ['trap','atom','stroke','selection','hit'])near(smaller.geometry[key]/initial.geometry[key],smaller.scale/initial.scale);
near(smaller.glyphs[0].width/initial.glyphs[0].width,smaller.scale/initial.scale);
near(Math.hypot(smaller.glyphs[0].path[1][1]-smaller.glyphs[0].path[0][1],smaller.glyphs[0].path[1][2]-smaller.glyphs[0].path[0][2])/
 Math.hypot(initial.glyphs[0].path[1][1]-initial.glyphs[0].path[0][1],initial.glyphs[0].path[1][2]-initial.glyphs[0].path[0][2]),smaller.scale/initial.scale);
width=390;height=420;h.get('resize()');const narrow=snapshot();
assert(narrow.geometry.atom<smaller.geometry.atom,'Responsive canvas shrinks atoms together with coordinates');
for(const key of ['trap','atom','stroke','selection','hit'])near(narrow.geometry[key]/smaller.geometry[key],narrow.scale/smaller.scale);
assert.equal(h.get('stabilizerBasis("Q009")'),'X');assert.equal(h.get('stabilizerBasis("Q013")'),'Z');
assert.equal(h.get('stabilizerBasis("Q000")'),null);assert.equal(h.get('stabilizerBasis("Q204")'),null);
assert.match(h.get('stabilizerRoleLabel("Q213")'),/资源模板 X.*未编码/);
assert.match(h.get('stabilizerRoleLabel("Q009")'),/X 稳定子/);
h.get('viewer.selectAtom("Q013")');assert.equal(h.el('atom-inspector-details').open,true);
assert.equal(h.el('individual-details').open,true,'Selection opens the collapsed ancestor as well as the inspector');
assert.match(h.el('details').innerHTML,/Z 稳定子辅助位/);
assert.match(h.el('canvas').root.innerHTML,/<details open="" class="panel" id="primary-summary/);
assert.match(h.el('summary').innerHTML,/<details class="resource-details"[^>]*><summary>逐资源/);
assert(!/<details[^>]*\bopen\b[^>]*>\s*<summary>逐资源/.test(h.el('summary').innerHTML));
assert(!/>null<\/text>/.test(h.el('summary').innerHTML),'Batch CZ pulses have no single gate ID label');
assert(h.el('summary').innerHTML.indexOf('id="schedule"')<h.el('summary').innerHTML.indexOf('id="resource-schedule"'));
assert(h.nodes.has('device-schedule'),'Primary statistics include actual device lanes');
// Empty and occupied AOD traps follow each real device's axes and projection too.
const move=h.get('data.operations.find(o=>o.kind==="aod_move"&&o.moving_count>0)');
h.get(`seek(${(move.start+move.end)/2})`);h.arcs.length=0;h.get('draw()');
const trapRadius=h.get('markerGeometry().trap');
const aodIntersections=JSON.parse(h.get('JSON.stringify(Object.values(current.arrays).flatMap(a=>a.aod.enabled_rows.flatMap((on,row)=>on?a.aod.enabled_columns.flatMap((enabled,col)=>enabled?[[projection().X(a.columns[col]),projection().Y(a.rows[row])]]:[]):[])))'));
assert(aodIntersections.length>0);
for(const [x,y] of aodIntersections)assert(h.arcs.some(a=>Math.abs(a[0]-x)<1e-9&&Math.abs(a[1]-y)<1e-9&&Math.abs(a[2]-trapRadius)<1e-9));
const pulse=h.get('data.operations.find(o=>o.kind==="entangling_pulse")');
h.get(`seek(${(pulse.start+pulse.end)/2})`);snapshot();
assert(h.colors.includes(h.get('data.theme.active_color')),'QEC glyphs retain actual red gate activity fill');
assert.equal(h.get('JSON.stringify(data)'),before,'Presentation must not mutate any recording truth');
console.log('PASS full12 proportional atoms/traps/AOD geometry, responsive size, independent X/Z roles, unencoded-resource caveat, primary summary hierarchy, and immutable recording');
