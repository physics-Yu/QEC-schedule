// Schedule geometry and navigation, using actual generated event data.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {get,el}=require('./viewer_harness.cjs')(fs.readFileSync('artifacts/visualization/index.html','utf8'));
const html=el('summary').innerHTML;
const bars=[...html.matchAll(/data-start="([^"]+)" data-end="([^"]+)" data-category="([^"]+)" x="([^"]+)" y="([^"]+)" width="([^"]+)"/g)].map(m=>({start:+m[1],end:+m[2],category:m[3],x:+m[4],y:+m[5],width:+m[6]}));
assert.equal(bars.length,37);
const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const pulses=bars.filter(b=>b.category==='pulse');
assert.equal(pulses.length,3);
near(pulses[2].start,890.6);near(pulses[2].x,150+700*890.6/1116.9);
assert.equal(pulses[2].width,2); // Visible marker does not alter the real interval.
near(pulses[2].end-pulses[2].start,.3);
near(bars[0].width,700*100/1116.9);
assert.equal(new Set(bars.map(b=>b.y)).size,6); // No synthetic idle when there is no gap.
const before=get('JSON.stringify(data)');
el('schedule').onclick({target:{getAttribute:key=>key==='data-start'?'890.6':null}});
near(get('ui.time'),890.6);assert.equal(get('current.f.gate_status'),'running');
assert.equal(get('current.f.requested.join(",")'),'Q001,Q003');
near(el('schedule-playhead').attrs.x1,pulses[2].x);
assert(el('schedule-current').textContent.includes('890.60–890.90'));
let prevented=false;
el('schedule').onkeydown({key:'Enter',preventDefault(){prevented=true},target:{getAttribute:()=> '0'}});
assert(prevented);near(get('ui.time'),0);
assert.equal(get('JSON.stringify(data)'),before);
console.log('PASS schedule: real interval geometry, three short pulses, totals unchanged, click/keyboard seek, synchronized playhead');
