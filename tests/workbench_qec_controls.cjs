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
function parse(html){for(const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/value="([^"]*)"/)?.[1]||'';nodes.set(m[1],e);}}
const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
parse(fs.readFileSync('src/neutral_atom_app/visualization/workbench.html','utf8'));
const q=i=>'Q'+String(i).padStart(3,'0');
function recording(n){return {scene:{bounds:{lower:{x_um:-10,y_um:-60},upper:{x_um:400,y_um:20}},zones:[],traps:[]},frames:[{atom_updates:Array.from({length:n},(_,i)=>({id:q(i),position:{x_um:i*10,y_um:0}}))}],operations:[],duration:1,summary:{metrics:{completed_gate_count:194}}};}
const oldExample={compiler:'row_greedy',layout:'row',atom_count:36,aod_traps:36,ez_policy:'adaptive',seed:0,compile_timeout_s:3600,row_candidate_budget:4096,route_expansions:100000,gates:Array.from({length:194},(_,i)=>({id:'e'+i,gate_type:'H',qubit_ids:[q(i%36)],parameters:[],column:Math.floor(i/36)}))};
const example=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let blob,compiled,mounts=0;
const sandbox={console,AbortController,Blob,setTimeout,clearTimeout,
 URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
 document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id)},
 window:{addEventListener(){},NeutralAtomViewer:{mount(){mounts++;return {destroy(){},setTime(){},selectAtom(){}};}}},
 fetch:async(path,options)=>{
  let data;
  if(path==='/api/preview'){const input=JSON.parse(options.body);data={input,recording:recording(input.atom_count)};}
  else if(path==='/api/examples/surface-qec-ghz2')data=example;
  else if(path==='/api/compile'){compiled=JSON.parse(options.body);requests.push(compiled);data={id:'large'};}
  else if(path==='/api/jobs/large')data={status:'completed'};
  else if(path==='/api/jobs/large/result')data={status:'completed',input:compiled,recording:recording(compiled.atom_count),compile_seconds:2,decision_log:[{decision:0,selected:'row/example',start_us:0,duration_us:1,constructed:3,bound_pruned:5,candidate_count:8,local_optimum_certified:true,raman_count:4}]};
  else data={status:'cancelled'};
  return {ok:true,json:async()=>data};
 }};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/neutral_atom_app/visualization/workbench.js','utf8'),sandbox);
const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
async function main(){
 await new Promise(r=>setImmediate(r));
 await el('surface-qec-ghz2').onclick();
 const original=await exported();assert(original.qec_enabled);
 assert(!Object.hasOwn(original,'qec_patch_origins'),'Default display must not inject an absent field');
 assert.equal(el('qec-patch-origin-0').value,'0, 0');assert.equal(el('qec-patch-origin-1').value,'40, 0');
 el('qec-patch-origin-1').value='45, 5';el('qec-patch-origin-1').onchange();
 const shifted=await exported();assert.deepEqual(shifted.qec_patch_origins,[[0,0],[45,5]]);
 assert.deepEqual(shifted.gates,original.gates);assert.deepEqual(shifted.aod_column_offsets_um,original.aod_column_offsets_um);
 assert.equal(shifted.aod_rows,original.aod_rows);assert.equal(shifted.aod_columns,original.aod_columns);
 el('undo').click();assert(!Object.hasOwn(await exported(),'qec_patch_origins'));
 el('qec-patch-origin-1').value='42, 0';el('qec-patch-origin-1').onchange();
 assert(!Object.hasOwn(await exported(),'qec_patch_origins'),'Expected invalid edit must not change draft');
 assert(el('palette').innerHTML.includes('MEASURE'));assert(el('palette').innerHTML.includes('RESET'));
 assert(!el('palette').innerHTML.includes('data-tool="T"'));
 assert(el('circuit').innerHTML.includes('ancilla'));
 const n=original.gates.length,conditional=original.gates.find(g=>g.condition?.length);
 assert(conditional);
 el('circuit').onclick({target:{closest:()=>({dataset:{q:Number(conditional.qubit_ids[0].slice(1)),column:conditional.column}})}});
 assert(el('gate-condition').textContent.includes('AND'));
 const before=JSON.stringify(conditional);
 el('edit-q0').value=conditional.qubit_ids[0];el('apply-gate').onclick();assert.equal(JSON.stringify((await exported()).gates.find(g=>g.id===conditional.id)),before);
 // Preserve an independent manual edit while changing the actual fault gate.
 el('palette').onclick({target:{closest:()=>({dataset:{tool:'H'}})}});
 el('circuit').onclick({target:{closest:()=>({dataset:{q:0,column:200}})}});
 el('qec-fault').value='Y';el('qec-fault-target').value='Q004';el('qec-fault').onchange();
 let value=await exported(),fault=value.gates.find(g=>g.id==='QEC_FAULT');
 assert.equal(value.gates.length,n+2);assert.equal(fault.gate_type,'Y');assert.equal(fault.qubit_ids[0],'Q004');
 assert(value.gates.some(g=>g.column===200&&g.gate_type==='H'));
 const dependent=value.gates.filter(g=>g.depends_on?.includes('QEC_FAULT'));assert(dependent.length);
 el('qec-fault').value='none';el('qec-fault').onchange();value=await exported();
 assert.equal(value.gates.length,n+1);assert(!value.gates.some(g=>g.depends_on?.includes('QEC_FAULT')));
 assert(value.gates.some(g=>g.column===200));
 const body=JSON.stringify(value);el('import-file').files=[{size:body.length,text:async()=>body}];await el('import-file').onchange();
 assert.deepEqual((await exported()).gates,value.gates);
 console.log('PASS: actual QEC editor handlers keep conditions/dependencies, preserve edits through fault add/remove, roundtrip JSON and restrict palette (DOM/HTTP doubles only)');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
