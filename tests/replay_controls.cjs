// Offline control-logic check with DOM/canvas doubles; not a browser rendering test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const scenario of ['baseline','incidental','three_gate','join']){
const multi=['three_gate','join'].includes(scenario);
const html=fs.readFileSync(`artifacts/${multi?'milestone2':'milestone1'}/${scenario}/animation.html`,'utf8');
const {sandbox,texts,arcs,nodes,get,el}=require('./viewer_harness.cjs')(html);
if(multi){
 const source=get('JSON.stringify(data)');
 const ops=JSON.parse(get('JSON.stringify(data.operations)'));
 assert.equal(ops.length,37);
 for(const op of ops){
   get(`renderStages(${Math.floor(op.index/12)})`);el('stage-'+op.index).onclick();
   assert.equal(el('stage-'+op.index).attrs['aria-current'],'true');
   assert(el('gate').textContent.startsWith(op.gate_id));
   if(op.kind==='entangling_pulse'){
     assert.equal(get('current.f.gate_status'),'running');
     assert.equal(get('current.atoms.filter(a=>a.activity==="gating").length'),2);
     assert(texts.includes('2.00 μm'));
   }
   if(op.kind==='aod_load'||op.kind==='aod_offload'){
     assert.equal(get('JSON.stringify(transferAt(ui.time).ids)'),JSON.stringify(op.captured));
   }
   if(op.label.startsWith('Empty')){assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);assert(el('operation-caption').textContent.includes('空载平移'));}
   for(const fraction of [0,.5,.999]){
     const time=op.start+(op.end-op.start)*fraction;
     get(`seek(${time})`);
     assert(Math.abs(get(`simulationAt(displayAt(${time}))`)-time)<1e-7);
   }
 }
 get('seek(156.3)');
 assert(el('frontier').textContent.includes('G001'));
 if(scenario==='join')assert(!el('frontier').textContent.includes('G002'));
 const gate2=ops.find(o=>o.kind==='entangling_pulse'&&o.gate_id==='G001');
 get(`seek(${gate2.end})`);assert(el('frontier').textContent.includes('G002'));
 const pulse3=ops.find(o=>o.kind==='entangling_pulse'&&o.gate_id==='G002');
 get(`seek(${pulse3.start})`);
 const expected=scenario==='three_gate'?['Q001','Q003']:['Q000','Q002'];
 assert.deepEqual(JSON.parse(get('JSON.stringify(current.f.requested)')),expected);
 get('seek(data.duration)');
 assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
 assert.equal(get('Object.values(current.f.gate_statuses).every(s=>s==="completed")'),true);
 assert.equal(get('JSON.stringify(data)'),source);
 console.log(`PASS ${scenario}: multi-plan stages, actual pairs/capture sets, empty moves, frontier, clocks, final cleanup, immutable source`);
 continue;
}
assert.equal(el('canvas').width,1800);assert.equal(get('hits.length'),4);
assert.equal(get('ui.selected'),null);assert(!texts.includes('Q000'));
el('labels').value='all';texts.length=0;el('labels').onchange();assert(texts.includes('Q000'));
el('labels').value='none';texts.length=0;el('atom-Q000').onclick();assert(!texts.includes('Q000'));assert(el('details').innerHTML.includes('Q000'));
el('pulse').onclick();assert.equal(get('ui.time'),156);assert.equal(get('current.f.gate_status'),'running');
assert.equal(get("current.atoms.find(a=>a.id==='Q000').position.x_um"),3);assert.equal(get("current.atoms.find(a=>a.id==='Q001').position.x_um"),5);
assert(el('details').innerHTML.includes('AOD'));assert(texts.includes('2.00 μm'));
const physicalBefore=get('JSON.stringify(current.atoms)');
const slmCount=get('current.f.scene.traps.length');
arcs.length=0;el('aod').checked=true;el('aod').onchange();assert.equal(arcs.filter(a=>a[2]===7).length,6+slmCount);
arcs.length=0;el('aod').checked=false;el('aod').onchange();assert.equal(arcs.filter(a=>a[2]===7).length,slmCount);
arcs.length=0;el('slm').checked=false;el('slm').onchange();assert.equal(arcs.filter(a=>a[2]===7).length,0);
arcs.length=0;el('aod').checked=true;el('aod').onchange();assert.equal(arcs.filter(a=>a[2]===7).length,6);
arcs.length=0;el('slm').checked=true;el('slm').onchange();assert.equal(arcs.filter(a=>a[2]===7).length,6+slmCount);
assert.equal(get('JSON.stringify(current.atoms)'),physicalBefore);
assert.equal(el('atom-Q000').querySelector('.symbol').className,'symbol diamond');
el('trails').checked=true;el('trails').onchange();el('grid').checked=false;el('grid').onchange();
el('mode').value='physical';el('mode').onchange();el('slider').value='108';el('slider').oninput();assert.equal(get("current.atoms.find(a=>a.id==='Q000').position.x_um"),2.5);
const before=get('JSON.stringify(current.atoms)');el('zoomin').onclick();assert(get('view.zoom')>1);assert.equal(get('JSON.stringify(current.atoms)'),before);
el('canvas').listeners.wheel({clientX:200,clientY:200,deltaY:-100,preventDefault(){}});
el('canvas').listeners.pointerdown({clientX:100,clientY:100,button:0,pointerId:1});
el('canvas').listeners.pointermove({clientX:150,clientY:140});el('canvas').listeners.pointerup({clientX:150,clientY:140,pointerId:1});assert.notEqual(get('view.panX'),0);
el('fit').onclick();assert.equal(get('view.panX'),0);assert.equal(get('view.zoom'),1);
const hit=JSON.parse(get("JSON.stringify(hits.find(a=>a.id==='Q001'))"));
el('canvas').listeners.pointerdown({clientX:hit.x,clientY:hit.y,button:0,pointerId:1});el('canvas').listeners.pointerup({clientX:hit.x,clientY:hit.y,pointerId:1});assert.equal(get('ui.selected'),'Q001');
for(let i=0;i<9;i++){el('stage-'+i).onclick();assert.equal(el('stage-'+i).attrs['aria-current'],'true');}
el('next').onclick();assert.equal(get('ui.time'),312.3);assert(el('next').disabled);
el('previous').onclick();assert(get('ui.time')<312.3);
el('reset').onclick();assert.equal(get('ui.time'),0);assert.equal(el('atom-Q000').querySelector('.symbol').className,'symbol circle');
el('play').onclick();assert.equal(get('ui.playing'),true);get('tick(100);tick(1100)');assert.equal(get('ui.time'),25);
// Two clocks, one unchanged physical state. The presentation clock is never serialized.
const source=get('JSON.stringify(data)');
const near=(actual,expected)=>assert(Math.abs(actual-expected)<1e-7,`${actual} != ${expected}`);
assert.equal(get('presentationEnd'),12400);
assert.equal(get('data.captured.length'),scenario==='baseline'?1:2);
assert.equal(get('data.captured.includes("Q001")'),false);
for(const t of [0,50,99.999,100,108,133.5,156,156.15,156.3,212.3,262.3,312.3]){
    get(`seek(${t})`);const physical=get('JSON.stringify(current.atoms)');
    el('mode').value='keyframe';el('mode').onchange();
    near(get('ui.time'),t);assert.equal(get('ui.playing'),false);
    assert.equal(get('JSON.stringify(current.atoms)'),physical);
    near(get(`simulationAt(displayAt(${t}))`),t);
    el('slider').value=get('displayAt(ui.time)');el('slider').oninput();
    near(get('ui.time'),t);
    el('mode').value='physical';el('mode').onchange();near(get('ui.time'),t);
}
// Transfer preview cannot commit holders early or move atoms at load/offload.
get('seek(50)');assert.equal(get('transferAt(ui.time).mobileMix'),.5);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'static');
assert.equal(get('current.atoms.find(a=>a.id==="Q000").position.x_um'),0);
el('atom-Q000').onclick();assert(el('details').innerHTML.includes('交接预览'));
const halfway=get('JSON.stringify(current.atoms)');el('effects').checked=false;el('effects').onchange();
assert.equal(get('JSON.stringify(current.atoms)'),halfway);el('effects').checked=true;
get('seek(100)');assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'mobile');
get('seek(262.3)');near(get('transferAt(ui.time).mobileMix'),.5);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'mobile');
assert.equal(get('current.atoms.find(a=>a.id==="Q000").position.x_um'),0);
get('seek(312.3)');assert.equal(get('transferAt(ui.time)'),null);
assert.equal(get('current.atoms.find(a=>a.id==="Q000").holder.holder_type'),'static');
// At 1x, 900 display ms traverses half the real 0.3 us pulse, not 22.5 us.
el('mode').value='keyframe';el('mode').onchange();el('pulse').onclick();el('play').onclick();
get('tick(0);tick(900)');near(get('ui.time'),156.15);assert.equal(get('current.f.gate_status'),'running');
assert.equal(el('operation-progress').textContent,'50%');
el('play').onclick();get('tick(5900)');near(get('ui.time'),156.15);
el('play').onclick();get('tick(6000);tick(6900)');near(get('ui.time'),156.3);
assert.equal(get('current.f.gate_status'),'completed');
// Operation order survives both speeds, including the short pulse; fixed partner stays fixed.
for(const speed of [1,4]){
    el('speed').value=String(speed);el('reset').onclick();el('play').onclick();
    const seen=new Set();let runningFrames=0;
    get('tick(0)');
    for(let now=16;get('ui.playing')&&now<20000;now+=16){
        get(`tick(${now})`);const index=get('operationAt(ui.time)?.index');if(index!==undefined)seen.add(index);
        if(get('current.f.gate_status')==='running')runningFrames++;
        assert.equal(get('current.atoms.find(a=>a.id==="Q001").position.x_um'),5);
        assert.equal(get('current.atoms.find(a=>a.id==="Q001").position.y_um'),-25);
        texts.length=0;arcs.length=0;
    }
    assert.deepEqual([...seen],[0,1,2,3,4,5,6,7,8]);assert(runningFrames>=27);
    near(get('ui.time'),312.3);assert.equal(get('ui.playing'),false);
}
el('speed').value='1';el('reset').onclick();el('play').onclick();
get('document.hidden=true;document.visibilitychange();tick(99999)');
assert.equal(get('ui.playing'),false);assert.equal(get('ui.time'),0);
get('document.hidden=false');
// Mode change while playing pauses without losing the current physical instant.
el('play').onclick();get('tick(100000);tick(100900)');near(get('ui.time'),50);
el('mode').value='physical';el('mode').onchange();near(get('ui.time'),50);assert.equal(get('ui.playing'),false);
el('play').onclick();get('tick(101000);tick(102000)');near(get('ui.time'),75);
assert.equal(get('JSON.stringify(data)'),source);
console.log(`PASS ${scenario}: two clocks, capture/offload, short pulse, mode/pause/seek/end/visibility, immutable source; labels, selection, trap rings, holder markers, interpolation, layers, zoom/pan, event/phase controls, playback`);
}
