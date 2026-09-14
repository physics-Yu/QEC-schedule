// Canvas/DOM assertions on a real physical recording; not screenshot acceptance.
const fs=require('fs'),assert=require('assert');
const {get,el,arcs}=require('./viewer_harness.cjs')(fs.readFileSync(process.argv[2],'utf8'));
const original=get('JSON.stringify(data)');
const move=JSON.parse(get('JSON.stringify(data.operations.find(o=>o.kind==="aod_move"&&o.captured.length))'));
assert(move,'Fixture must contain a real loaded move');
get(`seek(${(move.start+move.end)/2})`);
for(const id of ['grid','zones','planned-path','trails','effects','clearance'])el(id).checked=false;
const before=get('JSON.stringify(current.atoms)');
const atomCount=get('current.atoms.length');
const activeAod=get('current.f.aod.enabled_rows.filter(Boolean).length*current.f.aod.enabled_columns.filter(Boolean).length');
const mobile=get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length');
assert(activeAod>=mobile&&mobile>0,'Fixture must include actual AOD-held atoms');
const on=get('current.f.scene.traps.filter(t=>t.enabled).length');
const off=get('current.f.scene.traps.filter(t=>!t.enabled).length');
const occupiedOn=get('current.f.scene.traps.filter(t=>t.enabled&&current.atoms.some(a=>a.holder.holder_type==="static"&&a.holder.holder_id===t.id)).length');
assert(on>occupiedOn&&off>0);
function redraw(){arcs.length=0;get('draw()');assert.equal(get('hits.length'),atomCount);assert.equal(get('JSON.stringify(current.atoms)'),before);}
function rings(){return arcs.filter(a=>a[2]===7).length;}
function dots(){return arcs.filter(a=>a[2]===1.6).length;}
redraw();assert.equal(rings(),on+activeAod);assert.equal(dots(),off);
const offPosition=JSON.parse(get('JSON.stringify((()=>{const t=current.f.scene.traps.find(t=>t.id==="empty_off"),p=projection();return [p.X(t.position.x_um),p.Y(t.position.y_um)]})())'));
assert(arcs.some(a=>a[2]===1.6&&a[0]===offPosition[0]&&a[1]===offPosition[1]),'Closed marker remains at actual SLM coordinates');
el('slm-off').checked=false;el('slm-off').onchange();redraw();assert.equal(dots(),0);assert.equal(rings(),on+activeAod);
el('slm-empty').checked=false;el('slm-empty').onchange();redraw();assert.equal(rings(),occupiedOn+activeAod);
el('slm-off').checked=true;el('slm-off').onchange();redraw();assert.equal(dots(),0,'Empty filter also applies to closed SLM');
el('slm-empty').checked=true;el('slm-empty').onchange();redraw();assert.equal(dots(),off);
el('slm').checked=false;el('slm').onchange();redraw();assert.equal(rings(),activeAod);assert.equal(dots(),0);
assert(el('slm-empty').disabled&&el('slm-off').disabled);
el('grid').checked=true;el('grid').onchange();redraw();
assert(!arcs.some(a=>a[2]===1.4&&a[0]===offPosition[0]&&a[1]===offPosition[1]),'Grid must not redraw a hidden configured SLM as a candidate dot');
el('grid').checked=false;el('grid').onchange();
el('aod').checked=false;el('aod').onchange();redraw();assert.equal(rings(),0);
assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),mobile);
el('slm').checked=true;el('slm').onchange();assert(!el('slm-empty').disabled&&!el('slm-off').disabled);
// During real loading, destination support is on before holder transfer commits.
const load=JSON.parse(get('JSON.stringify(data.operations.find(o=>o.kind==="aod_load"))'));
el('slm').checked=false;el('aod').checked=true;arcs.length=0;
get(`seek(${(load.start+load.end)/2})`);
const loadingActive=get('current.f.aod.enabled_rows.filter(Boolean).length*current.f.aod.enabled_columns.filter(Boolean).length');
const loadingMobile=get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length');
assert(loadingActive>loadingMobile,'Real load must retain visible empty active AOD intersections');
assert.equal(rings(),loadingActive);
assert.equal(get('hits.length'),atomCount);
assert.equal(get('JSON.stringify(data)'),original,'Display never mutates recording, masks or holders');
console.log('PASS small closed markers, independent empty/closed SLM filters, exact coordinates, atoms and every active empty AOD intersection');
