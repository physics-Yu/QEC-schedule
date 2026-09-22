// Real exported viewer, DOM/Canvas doubles. Physical coordinates for all 85 atoms.
const fs=require('node:fs'),assert=require('node:assert/strict');
const folder=process.argv[2],report=JSON.parse(fs.readFileSync(folder+'/result.json','utf8'));
assert.equal(report.status,'completed');assert.equal(report.input.rows,10);assert.equal(report.input.columns,10);
assert.equal(report.pickup.transfer_events,10);assert(Object.values(report.validation).every(Boolean));
const v=require('./viewer_harness.cjs')(fs.readFileSync(folder+'/animation.html','utf8'));
const before=v.get('JSON.stringify(data)'),near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
for(const [time,dx,dy] of [[0,0,0],[report.pickup.duration_us,2.5,2.5],[report.recording.duration,142.5,42.5]]){
 v.get(`seek(${time})`);const atoms=v.get('current.atoms');assert.equal(atoms.length,85);
 let loaded=0;
 for(let r=0;r<10;r++)for(let c=0;c<10;c++){
  const kind=report.input.cells[r][c];if(!kind)continue;
  const atom=atoms.find(a=>a.id==='Q'+String(r*10+c).padStart(3,'0'));
  near(atom.position.x_um,c*10+(kind===2?dx:0));near(atom.position.y_um,r*10+(kind===2?dy:0));
  if(atom.holder.holder_type==='mobile')loaded++;
  if(kind===1)assert.equal(atom.holder.holder_type,'static');
 }
 assert.equal(loaded,time===0?0:43);
}
assert.equal(v.get('JSON.stringify(data)'),before);
console.log('PASS 10x10 actual replay: 85 atoms, 43 targets loaded in 10 groups, 42 fixed atoms preserved, exact parked and remote endpoints');
