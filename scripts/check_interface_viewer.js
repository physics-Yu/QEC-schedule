const fs = require('node:fs'), path = require('node:path');
let harness = fs.readFileSync(path.join(__dirname, 'check_component_gallery.js'), 'utf8').split('assert.equal(api.manifest.components.length,')[0];
harness += `
assert.equal(api.manifest.components.length,12);
async function loaded(id){const until=Date.now()+30000;while(api.data?.id!==id){if(Date.now()>until)throw Error('Load timeout '+id);await new Promise(r=>setTimeout(r,3));}}
let positions=0,paths=0,fallbacks=0;
const movement=require('../viewer/motion-preview.js');
for(const row of api.manifest.components){
 api.showRow(row);await loaded(row.id);const d=api.data;
 assert.equal(d.actions.length,row.action_count);assert.equal(api.schedule.source.id,row.id);
 assert.equal(get('timebase').value,'100');
 const final=d.atoms.map(a=>a.slice(2,4));
 for(const a of d.actions)if(a[7]==='completed')for(const tr of a[4])final[tr[0]]=tr.slice(3,5);
 api.setTime(d.end);for(const [i,a]of api.stateAt(d.end).entries()){assert(Math.abs(a.x-final[i][0])<1e-8);assert(Math.abs(a.y-final[i][1])<1e-8);positions++;}
 for(const width of [320,1024]){get('scene').width=width;api.setTime(0);assert.equal(descend(get('scene')).filter(e=>'data-atom' in e.attrs).length,d.atoms.length);}
 const engine=movement.create(d);
 for(const a of engine.moves){const route=engine.routeFor(a);if(route.fallback)fallbacks++;else assert(route.passed);
  for(const tr of a[4]){const ps=route.paths.get(tr[0]);assert.deepEqual(ps[0],[a[0],tr[1],tr[2]]);assert.deepEqual(ps.at(-1),[a[1],tr[3],tr[4]]);paths++;
   if(!route.fallback)for(let k=1;k<ps.length;k++){assert(ps[k][0]>ps[k-1][0]);assert(Math.abs(ps[k][1]-ps[k-1][1])<1e-8||Math.abs(ps[k][2]-ps[k-1][2])<1e-8);}}
 }
 if(row.id.startsWith('CONSUME_'))assert.equal(d.atoms.length,205);
}
get('back').onclick();assert(!get('landing').hidden);
const result={passed:true,calls:12,position_checks:positions,atom_paths:paths,original_fallbacks:fallbacks,mode:standalone?'standalone':'external',
 checks:['all_calls_load','actual_final_positions','all_world_atoms_render','device_schedules','100us_per_second_default','XY_endpoints_timing_clearance','return_to_catalog'],
 browser_rendering:'not_verified',user_visual_acceptance:'pending'};
fs.writeFileSync(path.join(out,standalone?'standalone-checks.json':'viewer-checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','process',harness)(require,process);
