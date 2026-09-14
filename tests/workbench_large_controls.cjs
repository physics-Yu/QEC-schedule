// Actual editor handlers with DOM/HTTP doubles: pagination/input/log rendering,
// not physical compilation or real-browser visual acceptance.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),requests=[];
class Element{
 constructor(id){this.id=id;this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.style={};this.dataset={};this.classList={add(){},remove(){}};}
 set innerHTML(value){this.html=value;parse(value);}
 get innerHTML(){return this.html||'';}
 setAttribute(k,v){this[k]=v;}
 focus(){} scrollIntoView(){}
 click(){this.onclick?.();}
}
function parse(html){for(const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/value="([^"]*)"/)?.[1]||'';e.hidden=/\bhidden(?:\s|=|>)/.test(m[0]);nodes.set(m[1],e);}}
const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
parse(fs.readFileSync('src/neutral_atom_app/visualization/workbench.html','utf8'));
const q=i=>'Q'+String(i).padStart(3,'0');
function recording(n){return {scene:{bounds:{lower:{x_um:-10,y_um:-60},upper:{x_um:400,y_um:20}},zones:[],traps:[]},frames:[{atom_updates:Array.from({length:n},(_,i)=>({id:q(i),position:{x_um:i*10,y_um:0}}))}],operations:[],duration:1,summary:{metrics:{completed_gate_count:194}}};}
const example={compiler:'row_greedy',layout:'row',atom_count:36,aod_traps:36,ez_policy:'adaptive',seed:0,compile_timeout_s:3600,row_candidate_budget:4096,route_expansions:100000,gates:Array.from({length:194},(_,i)=>({id:'e'+i,gate_type:'H',qubit_ids:[q(i%36)],parameters:[],column:Math.floor(i/36)}))};
let blob,compiled,mounts=0;
const sandbox={console,AbortController,Blob,setTimeout,clearTimeout,
 URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
 document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id)},
 window:{addEventListener(){},NeutralAtomViewer:{mount(){mounts++;return {destroy(){},setTime(){},selectAtom(){}};}}},
 fetch:async(path,options)=>{
  let data;
  if(path==='/api/preview'){const input=JSON.parse(options.body);data={input,recording:recording(input.atom_count)};}
  else if(path==='/api/examples/surface-ghz')data=example;
  else if(path==='/api/compile'){compiled=JSON.parse(options.body);requests.push(compiled);data={id:'large'};}
  else if(path==='/api/jobs/large')data={status:'completed'};
  else if(path==='/api/jobs/large/result')data={status:'completed',input:compiled,recording:recording(compiled.atom_count),compile_seconds:2,decision_log:[{decision:0,selected:'row/example',start_us:0,duration_us:1,constructed:3,bound_pruned:5,candidate_count:8,local_optimum_certified:true,raman_count:4}]};
  else data={status:'cancelled'};
  return {ok:true,json:async()=>data};
 }};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/neutral_atom_app/visualization/workbench.js','utf8'),sandbox);
const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
async function main(){
 await new Promise(r=>setImmediate(r));assert(mounts>0);
 assert(!nodes.has('auto'));assert(el('initial-body').hidden);
 el('edit-initial').click();assert(!el('initial-body').hidden);
 el('edit-initial').click();assert(el('initial-body').hidden);
 el('tab-config').click();assert(!el('configuration-workspace').hidden&&el('circuit-workspace').hidden);
 el('return-circuit').click();assert(el('configuration-workspace').hidden&&!el('circuit-workspace').hidden);
 const initial=await exported();assert.equal(el('compiler').value,'recommended');
 el('compiler').value='baseline';el('compiler').onchange();
 const baseline=await exported();assert.equal(baseline.compiler,'basic');assert.deepEqual(baseline.gates,initial.gates);
 el('compiler').value='recommended';el('compiler').onchange();
 assert.deepEqual((await exported()).gates,initial.gates);
 const large={...example,atom_count:128,aod_traps:128,gates:Array.from({length:4096},(_,i)=>({id:'g'+i,gate_type:'H',qubit_ids:[q(i%128)],parameters:[],column:i}))};
 const text=JSON.stringify(large);assert(text.length>65536);
 el('import-file').files=[{size:text.length,text:async()=>text}];await el('import-file').onchange();
 assert.equal((await exported()).gates.length,4096);
 assert.equal((el('circuit').innerHTML.match(/data-column=/g)||[]).length,128*64);
 assert(el('circuit').innerHTML.includes('data-column="63"'));
 assert(!el('circuit').innerHTML.includes('data-column="64"'));
 el('next-page').onclick();assert(el('circuit').innerHTML.includes('data-column="64"'));
 el('column-jump').value='4096';el('column-jump').onchange();
 assert(el('circuit').innerHTML.includes('data-column="4095"'));
 assert.equal(el('next-page').disabled,true);
 el('circuit').onclick({target:{closest:()=>({dataset:{q:'127',column:'4095'}})}});
 el('edit-column').value='4095';el('apply-gate').onclick();
 assert.equal((await exported()).gates.find(g=>g.id==='g4095').column,4094);
 el('palette').onclick({target:{closest:()=>({dataset:{tool:'X'}})}});
 el('circuit').onclick({target:{closest:()=>({dataset:{q:'126',column:'4095'}})}});
 assert(el('toast').textContent.includes('4096'));
 el('delete-gate').onclick();assert.equal((await exported()).gates.length,4095);
 el('circuit').onclick({target:{closest:()=>({dataset:{q:'126',column:'4095'}})}});
 assert.equal((await exported()).gates.length,4096);
 el('undo').onclick();assert.equal((await exported()).gates.length,4095);
 el('redo').onclick();assert.equal((await exported()).gates.length,4096);
 el('import-file').files=[{size:2*1024*1024+1,text:async()=>text}];await el('import-file').onchange();
 assert(el('toast').textContent.includes('2 MiB'));
 el('compile-timeout').value='1111';el('compile-timeout').onchange();
 const previousCompilation=(await exported()).compilation;
 await el('surface-ghz').onclick();
 assert.deepEqual((await exported()).compilation,previousCompilation,'Template preserves explicit compilation settings');
 assert.equal((await exported()).gates.length,194);assert.equal(el('row-controls').hidden,false);
 assert.equal(el('ready-limit').disabled,true);
 el('compile-timeout').value='86400';el('compile-timeout').onchange();
 el('row-candidate-budget').value='65536';el('row-candidate-budget').onchange();
 el('route-expansions').value='1000000';el('route-expansions').onchange();
 await el('compile').onclick();assert.equal(requests.at(-1).compile_timeout_s,86400);
 assert.equal(requests.at(-1).row_candidate_budget,65536);
 assert.equal(requests.at(-1).route_expansions,1000000);
 assert(el('greedy-rows').innerHTML.includes('下界剪枝 5'));
 assert(el('greedy-summary').textContent.includes('8 个候选'));
 el('compile-timeout').value='';el('compile-timeout').onchange();
 assert(!('compile_timeout_s' in await exported()));
 el('layout').value='surface_patches';el('layout').onchange();
 el('compiler').value='recommended';el('compiler').onchange();
 let patch=await exported();assert.equal(patch.atom_count,36);
 assert.equal(patch.aod_rows,6);assert.equal(patch.aod_columns,6);
 assert.deepEqual(patch.aod_column_offsets_um,[0,10,20,40,50,60]);
 assert.equal(el('ez-neighbor-guard').checked,true);
 el('ez-neighbor-guard').checked=false;el('ez-neighbor-guard').onchange();
 el('aod-column-offsets').value='0, 20, 40, 80, 100, 120';el('aod-column-offsets').onchange();
 patch=await exported();assert.equal(patch.ez_neighbor_guard_enabled,false);
 assert.deepEqual(patch.aod_column_offsets_um,[0,20,40,80,100,120]);
 el('aod-row-offsets').value='0, 0, 20, 40, 50, 60';el('aod-row-offsets').onchange();
 assert(el('toast').textContent.includes('严格递增'));
 el('aod-rows').value='3';el('aod-rows').onchange();
 patch=await exported();assert.equal(patch.aod_rows,3);
 assert(!('aod_row_offsets_um' in patch));
 assert.deepEqual(patch.aod_column_offsets_um,[0,20,40,80,100,120]);
 el('aod-columns').value='3';el('aod-columns').onchange();
 patch=await exported();assert.equal(patch.aod_rows,3);assert.equal(patch.aod_columns,3);
 assert.equal(el('aod-capacity').textContent,'3 × 3 = 9 个交点');
 assert(!nodes.has('aod-traps'),'Capacity is derived and has no editable independent field');
 assert(!('aod_traps' in patch)&&!('aod_column_offsets_um' in patch));
 console.log('PASS: 4096-gate import, 64-column bounded render, absolute-column editing, limit/undo/redo, 36-atom example, row logs and explicit timeout budgets');
 console.log('PASS: 2D patch shape, nonuniform axes, explicit guard switch, invalid offsets and derived row-times-column capacity');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
