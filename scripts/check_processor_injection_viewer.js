const fs=require('node:fs'),path=require('node:path');
let harness=fs.readFileSync(path.join(__dirname,'check_component_gallery.js'),'utf8').split('assert.equal(api.manifest.components.length,')[0];
harness=harness.replace('requestAnimationFrame:f=>frame=f,','queueMicrotask,requestAnimationFrame:f=>frame=f,');
harness+=`
assert.equal(api.manifest.components.length,2);
async function loaded(id){const until=Date.now()+10000;while(api.data?.id!==id){if(Date.now()>until)throw Error('load timeout');await new Promise(r=>setTimeout(r,3));}}
let endpointChecks=0,moves=0;
for(const row of api.manifest.components){
 api.showRow(row);await loaded(row.id);const d=api.data;assert.equal(d.atoms.length,697);assert.equal(d.actions.length,row.action_count);
 assert.equal(api.schedule.source.id,d.id);
 const expected=d.atoms.map(a=>a.slice(2,4));
 for(const a of d.actions)if(a[7]==='completed')for(const tr of a[4]){
  assert.deepEqual(expected[tr[0]],tr.slice(1,3));expected[tr[0]]=tr.slice(3,5);
  assert(a[0]<a[1]);assert(tr[1]===tr[3]||tr[2]===tr[4]);moves++;
 }
 api.setTime(d.end);const final=api.stateAt(d.end);
 for(const [i,a] of final.entries()){
  assert(Math.abs(a.x-d.atoms[i][2])<1e-8);assert(Math.abs(a.y-d.atoms[i][3])<1e-8);
  assert.equal(a.carrier,'SLM');assert.equal(a.owner,d.atoms[i][5]);endpointChecks++;
 }
 const transfer=d.ownership_events[0];api.setTime(transfer.time_us+1);
 for(const i of transfer.atoms)assert.equal(api.stateAt(transfer.time_us+1)[i].owner,'data');
 api.setTime(d.injection.data_completed_us);assert(get('injection-status').textContent.includes('T 完成'));
 assert(d.actions.some(a=>a[6]==='CZ'&&a[5].length===9));
 assert.equal(d.injection.branch===1,Boolean(d.injection.correction));
 get('back').onclick();assert(!get('landing').hidden);
}
const report={passed:true,branches:2,atoms:697,final_atoms_checked:endpointChecks,axis_move_trajectories:moves,ownership_handoffs_checked:true,scope:'functional DOM, endpoints, actual ownership and final-state display; not a hardware qualification'};
fs.writeFileSync(path.join(out,'viewer-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','process',harness)(require,process);
