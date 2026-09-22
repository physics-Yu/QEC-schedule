// Exercise the real exported renderer using DOM/Canvas doubles.
const fs=require('node:fs'),assert=require('node:assert/strict'),harness=require('./viewer_harness.cjs');
for(const folder of process.argv.slice(2)){
 const report=JSON.parse(fs.readFileSync(folder+'/result.json','utf8'));
 const v=harness(fs.readFileSync(folder+'/animation.html','utf8'));
 const original=v.get('JSON.stringify(data)'),near=(a,b)=>assert(Math.abs(a-b)<1e-7);
 for(const t of [0,report.pickup.duration_us,report.recording.duration]){
  v.get(`seek(${t})`);
  for(const [q,x,y] of [['Q002',20,0],['Q003',0,10]]){
   const atom=v.get(`current.atoms.find(a=>a.id==='${q}')`);
   assert.equal(atom.holder.holder_type,'static');near(atom.position.x_um,x);near(atom.position.y_um,y);
  }
 }
 v.get(`seek(${report.pickup.duration_us})`);
 assert.equal(v.get("current.atoms.filter(a=>a.holder.holder_type==='mobile').length"),4);
 near(v.get("current.atoms.find(a=>a.id==='Q000').position.x_um"),2.5);
 v.get('seek(data.duration)');near(v.get("current.atoms.find(a=>a.id==='Q000').position.x_um"),62.5);
 near(v.get("current.atoms.find(a=>a.id==='Q000').position.y_um"),32.5);
 const move=v.get("data.operations.find(o=>o.label==='集体运输 X')");
 v.get(`seek(${(move.start+move.end)/2})`);
 near(v.get("current.atoms.find(a=>a.id==='Q000').position.x_um"),32.5);
 near(v.get("current.atoms.find(a=>a.id==='Q000').position.y_um"),2.5);
 v.get('seek(0)');v.el('speed').value='32';v.el('play').onclick();
 v.get('tick(0);for(let i=1;i<=2000;i++)tick(i*100)');near(v.get('ui.time'),report.recording.duration);
 assert.equal(v.get('JSON.stringify(data)'),original);
 console.log('PASS '+report.input.strategy+': parked/transport/protected coordinates, cubic midpoint, 32x completion, read-only recording');
}
