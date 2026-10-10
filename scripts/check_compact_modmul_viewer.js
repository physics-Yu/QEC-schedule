const fs=require('node:fs'),path=require('node:path');
let harness=fs.readFileSync(path.join(__dirname,'check_component_gallery.js'),'utf8').split('assert.equal(api.manifest.components.length,')[0];
harness=harness.replace('requestAnimationFrame:f=>frame=f,','queueMicrotask,requestAnimationFrame:f=>frame=f,');
harness+=`
const row=api.manifest.components[0];assert.equal(api.manifest.components.length,1);api.showRow(row);
const until=Date.now()+60000;while(api.data?.id!==row.id){if(Date.now()>until)throw Error('load timeout');await new Promise(r=>setTimeout(r,10));}
const d=api.data;assert.equal(d.atoms.length,697);assert.equal(d.logical_calls.length,60);assert.equal(d.actions.length,141709);
assert.equal(api.schedule.source.id,d.id);assert.equal(d.production.length,6);assert.equal(d.tokens.length,24);
const pos=d.atoms.map(a=>a.slice(2,4)),sites=d.atoms.map(a=>a[6]);let paths=0;
for(const a of d.actions)if(a[7]==='completed'){
 for(const tr of a[4]){assert.deepEqual(pos[tr[0]],tr.slice(1,3));pos[tr[0]]=tr.slice(3,5);assert(a[0]<a[1]);assert(tr[1]===tr[3]||tr[2]===tr[4]);paths++;}
 for(const [i,oldSite,newSite]of a[9]){assert.equal(sites[i],oldSite);sites[i]=newSite;}
}
api.setTime(d.end);const final=api.stateAt(d.end);
for(const [i,a]of final.entries()){assert(Math.abs(a.x-pos[i][0])<1e-8);assert(Math.abs(a.y-pos[i][1])<1e-8);assert.equal(a.carrier,'SLM');assert.equal(a.owner,d.atoms[i][5]);assert.equal(a.site,d.final_sites[a.id]);}
assert(get('logic-progress').textContent.includes('60 / 60'));assert(get('magic-stock').textContent.includes('消费 21 / 21'));
get('arith-c').value='0';get('arith-x').value='7';get('arith-c').onchange();assert(get('arith-result').textContent.includes('|0,7⟩ → |0,7⟩'));
get('arith-c').value='1';get('arith-c').onchange();assert(get('arith-result').textContent.includes('|1,7⟩ → |1,14⟩'));
get('overview').onclick();assert.equal(get('timebase').value,'100000');
const report={passed:true,logical_calls:60,actions:d.actions.length,atoms:697,axis_trajectories:paths,final_sites_and_owners_checked:697,consumed_tokens:21,ready_tokens:3,scope:'functional DOM and full endpoint replay; browser and user review separate'};
fs.writeFileSync(path.join(out,'viewer-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','process',harness)(require,process);
