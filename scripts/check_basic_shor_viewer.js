// Exercise the existing canvas DOM adapter against the actual pipeline calls.
const nodeFs=require('node:fs'),nodePath=require('node:path');
let harness=nodeFs.readFileSync(nodePath.join(__dirname,'check_component_gallery.js'),'utf8').split('assert.equal(api.manifest.components.length,')[0];
harness=harness.replace('requestAnimationFrame:f=>frame=f,','queueMicrotask,requestAnimationFrame:f=>frame=f,');
harness+=`
assert(api.manifest.components.length>0);
assert.equal(document.querySelectorAll().length,api.manifest.components.length);
async function loaded(id){const until=Date.now()+30000;while(api.data?.id!==id){if(Date.now()>until)throw Error('Load timeout '+id);await new Promise(r=>setTimeout(r,3));}}
let comparisons=0,moves=0,paths=0,fallbacks=0;
const movement=require('../viewer/motion-preview.js');
for(const row of api.manifest.components){
 api.showRow(row);await loaded(row.id);
 const d=api.data;assert.equal(d.actions.length,row.action_count);assert.equal(api.schedule.source.id,row.id);
 const positions=d.atoms.map(a=>a.slice(2,4));
 for(const a of d.actions)if(a[7]==='completed')for(const tr of a[4])positions[tr[0]]=tr.slice(3,5);
 api.setTime(d.end);for(const [i,a]of api.stateAt(d.end).entries()){assert(Math.abs(a.x-positions[i][0])<1e-8);assert(Math.abs(a.y-positions[i][1])<1e-8);comparisons++;}
 assert(get('pipeline-clock').textContent.includes('全程'));
 const engine=movement.create(d);
 for(const a of engine.moves){const route=engine.routeFor(a);moves++;if(route.fallback)fallbacks++;else assert(route.passed);
  for(const tr of a[4]){const ps=route.paths.get(tr[0]);assert.deepEqual(ps[0],[a[0],tr[1],tr[2]]);assert.deepEqual(ps.at(-1),[a[1],tr[3],tr[4]]);paths++;
   if(!route.fallback)for(let k=1;k<ps.length;k++){assert(ps[k][0]>ps[k-1][0]);assert(Math.abs(ps[k][1]-ps[k-1][1])<1e-8||Math.abs(ps[k][2]-ps[k-1][2])<1e-8);}}
 }
}
const first=api.manifest.components[0];api.showRow(first);await loaded(first.id);
if(api.manifest.components.length>1){get('call-next').onclick();await loaded(api.manifest.components[1].id);get('call-prev').onclick();await loaded(first.id);
 get('follow-calls').checked=true;api.setTime(api.data.end-0.01);get('play').onclick();frame(1000);frame(3000);await loaded(api.manifest.components[1].id);}
get('back').onclick();assert(!get('landing').hidden);api.showRow(first);await loaded(first.id);
const result={passed:true,calls:api.manifest.components.length,position_comparisons:comparisons,moves,atom_paths:paths,original_fallbacks:fallbacks,
 checks:['all_calls_load','resource_schedule_matches_each_call','all_final_positions','call_navigation_and_return','continuous_playback_across_calls','absolute_pipeline_clock','display_XY_endpoints_times_clearance'],
 scope:'functional DOM and display paths; browser rendering and user visual acceptance pending'};
fs.writeFileSync(path.join(out,'pipeline-viewer-checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','process',harness)(require,process);
