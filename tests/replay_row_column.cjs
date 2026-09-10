// Offline DOM/Canvas execution, not browser visual acceptance. Generate row_column report first.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const scenario of ['pair_compression','incidental','mobile_static']){
    const html=fs.readFileSync(`artifacts/row_column/${scenario}/animation.html`,'utf8');
    const {arcs,nodes,get}=require('./viewer_harness.cjs')(html);
    const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
    const original=get('JSON.stringify(data)');assert.equal(get('data.backend'),'row_column');
    if(scenario!=='mobile_static'){
        const t=get("(()=>{const op=data.operations.find(o=>o.label==='Reconfigure axes');return op.start+.25*(op.end-op.start)})()");
        get(`seek(${t})`);
        near(get('current.columns[0]'),2.734375);near(get('current.columns[1]'),7.265625);near(get('current.columns[2]'),11.796875);
        near(get('current.atoms.find(a=>a.id==="Q000").position.x_um'),2.734375);
        if(scenario==='incidental')assert.equal(get('current.atoms.find(a=>a.id==="Q002").activity'),'moving');
        // Empty traps follow the axes too; equal-size rings occupy the new intersections.
        arcs.length=0;get('draw()');
        const expected=JSON.parse(get('JSON.stringify([projection().X(2.734375),projection().Y(-20)])'));
        assert(arcs.some(a=>a[2]===7&&Math.abs(a[0]-expected[0])<1e-7&&Math.abs(a[1]-expected[1])<1e-7));
        nodes.get('mode').value='physical';nodes.get('mode').onchange();near(get('ui.time'),t);
        nodes.get('mode').value='keyframe';nodes.get('mode').onchange();near(get('simulationAt(displayAt(ui.time))'),t);
    }
    nodes.get('pulse').onclick();assert.equal(get('current.f.gate_status'),'running');
    nodes.get('play').onclick();get('tick(0);tick(900)');assert.equal(get('current.f.gate_status'),'running');
    if(scenario!=='mobile_static')near(get('current.atoms.find(a=>a.id==="Q001").position.x_um-current.atoms.find(a=>a.id==="Q000").position.x_um'),2);
    get('seek(data.duration)');assert.equal(get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
    assert.equal(get('JSON.stringify(data)'),original);
    console.log(`PASS row_column/${scenario}: cubic axes, shapes, empty traps, modes, pulse, source immutability`);
}
