// Native details/fieldset structure plus offline controls. Not a browser screenshot test.
const fs=require('node:fs'),assert=require('node:assert/strict');
for(const path of ['artifacts/motion-planner/dense_right/animation.html','artifacts/row_column/incidental/animation.html']){
 const html=fs.readFileSync(path,'utf8');const {get,el}=require('./viewer_harness.cjs')(html);
 assert(html.includes('布局与陷阱')&&html.includes('编号与轨迹')&&html.includes('动效与安全边界'));
 assert(html.includes('虚线边界按 μm 绘制'));
 assert.equal(get('data.scene.aod_minimum_spacing_um'),1.01);
 assert.equal(el('display-summary').textContent,'6 / 8 图层开启');
 assert(el('spacing-readout').textContent.includes('5.000 μm'));
 const source=get('JSON.stringify(data)'),before=get('JSON.stringify(current.atoms)');
 for(const id of ['zones','grid','slm','aod','planned-path','trails','effects','clearance']){
  el(id).checked=false;el(id).onchange();assert.equal(get('JSON.stringify(current.atoms)'),before);
 }
 assert.equal(el('display-summary').textContent,'0 / 8 图层开启');
 el('clearance').checked=true;el('clearance').onchange();
 assert.equal(el('display-summary').textContent,'1 / 8 图层开启');
 el('pulse').onclick();assert.equal(get('current.f.gate_status'),'running');
 const expected=path.includes('incidental')?'2.000 μm':'5.000 μm';
 assert(el('spacing-readout').textContent.includes(expected));
 assert(el('spacing-readout').textContent.includes('> 1.01 μm'));
 assert.equal(get('JSON.stringify(data)'),source);
 console.log('PASS display groups, layer count, live all-trap separation, immutable physics: '+path);
}
