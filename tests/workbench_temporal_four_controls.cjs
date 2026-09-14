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
// Deliberately small UI fixture; not a quantum/physical acceptance result.
const example={compiler:'qec_temporal_four',qec_enabled:true,layout:'surface_qec_ghz4',atom_count:68,
 seed:7,aod_rows:7,aod_columns:14,aod_row_offsets_um:[0,5,10,15,20,25,30],aod_column_offsets_um:[0,5,10,15,20,25,30,40,45,50,55,60,65,70],
 qec_patch_origins:[[0,0],[40,0],[0,40],[40,40]],ez_policy:'adaptive',gates:[
 {id:'m',gate_type:'MEASURE',qubit_ids:['Q036'],parameters:[],column:0,readout_flip:true},
 {id:'h',gate_type:'H',qubit_ids:['Q000'],parameters:[],column:1},
 {id:'x',gate_type:'X',qubit_ids:['Q001'],parameters:[],column:1,condition:[['m',1]],depends_on:['m']}],
 qec_protocol:{noisy_rounds:['round1','round2','round3'],closing_round:'closing',readouts:[{gate_id:'m',round:'round1'}]}};
let blob,compiled,mounts=0;
const sandbox={console,AbortController,Blob,setTimeout,clearTimeout,
 URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
 document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id)},
 window:{addEventListener(){},NeutralAtomViewer:{mount(){mounts++;return {destroy(){},setTime(){},selectAtom(){}};}}},
 fetch:async(path,options)=>{
  let data;
  if(path==='/api/preview'){const input=JSON.parse(options.body);data={input,recording:recording(input.atom_count)};}
  else if(path==='/api/examples/surface-qec-temporal-four'||path==='/api/examples/surface-qec-temporal'||path==='/api/examples/surface-qec-ghz2')data=JSON.parse(JSON.stringify(example));
  else if(path==='/api/compile'){compiled=JSON.parse(options.body);requests.push(compiled);data={id:'large'};}
  else if(path==='/api/jobs/large')data={status:'completed'};
  else if(path==='/api/jobs/large/result')data={status:'completed',input:compiled,recording:recording(compiled.atom_count),compile_seconds:0,decision_log:[],qec_result:{verified_logical_ghz4:false,measurement_protocol_complete:false,history_complete:false,history_supported:false,logical_xxxx:0,logical_zz_pairs:{AB:1,BC:-1,CD:1},true_measurement_results:{m:0},reported_measurement_results:{m:1},corrections:[],decoded_corrections:[{gate_type:'X',qubit_ids:['Q001']}]}};
  else data={status:'cancelled'};
  return {ok:true,json:async()=>data};
 }};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/neutral_atom_app/visualization/workbench.js','utf8'),sandbox);
const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
async function main(){
 await new Promise(r=>setImmediate(r));
 await el('surface-qec-temporal-four').onclick();
 const original=await exported();assert.equal(original.compiler,'qec_temporal_four');
 assert.equal(original.atom_count,68);assert.equal(el('qec-patch-origin-2').value,'0, 40');assert.equal(el('qec-patch-origin-3').value,'40, 40');
 assert.equal(el('qec-patch-control-2').hidden,false);assert.equal(el('qec-patch-control-3').hidden,false);
 assert(el('qec-roles').textContent.includes('Q000–Q035: data'));assert(el('qec-roles').textContent.includes('Q036–Q067: ancilla'));
 el('qec-patch-origin-3').value='45, 40';el('qec-patch-origin-3').onchange();
 const moved=await exported();assert.deepEqual(moved.qec_patch_origins,[[0,0],[40,0],[0,40],[45,40]]);
 assert.deepEqual(moved.gates,original.gates);assert.deepEqual(moved.aod_column_offsets_um,original.aod_column_offsets_um);
 el('undo').click();assert.deepEqual(await exported(),original);
 assert(el('qec-fault').disabled);assert(el('qec-fault-target').disabled);
 const select=id=>{const g=original.gates.find(g=>g.id===id);el('circuit').onclick({target:{closest:()=>({dataset:{q:Number(g.qubit_ids[0].slice(1)),column:g.column}})}});};
 select('m');assert(!el('readout-flip-control').hidden);assert(el('edit-readout-flip').checked);
 assert(el('readout-flip-note').textContent.includes('round1'));
 el('edit-readout-flip').checked=false;el('apply-gate').click();
 let changed=await exported();assert.equal(changed.gates[0].readout_flip,false);
 assert.deepEqual(changed.gates.slice(1),original.gates.slice(1));
 assert.deepEqual(changed.qec_patch_origins,original.qec_patch_origins);
 assert.deepEqual(changed.aod_column_offsets_um,original.aod_column_offsets_um);
 el('undo').click();assert.deepEqual(await exported(),original);
 select('h');assert(el('readout-flip-control').hidden);
 el('qec-fault').value='Y';el('qec-fault-target').value='Q004';el('qec-fault').onchange();
 assert.deepEqual(await exported(),original,'Legacy fault handler must not rewrite temporal gates');
 const body=JSON.stringify(changed);el('import-file').files=[{size:body.length,text:async()=>body}];await el('import-file').onchange();
 assert.deepEqual(await exported(),changed);
 await el('compile').onclick();
 assert.deepEqual(compiled.gates,changed.gates,'Actual edited readout flag must enter compile request');
 assert(el('qec-result-status').textContent.includes('不受支持'));
 assert(el('qec-result-status').textContent.includes('GHZ₄'));assert(el('qec-result-status').textContent.includes('128 位'));
 assert(el('qec-syndromes').innerHTML.includes('协议预期 160 位'));
 assert(el('qec-logical').textContent.includes('XXXX = 0'));assert(el('qec-logical').textContent.includes('BC = -1'));
 assert(el('qec-syndromes').innerHTML.includes('真实投影位'));
 assert(el('qec-syndromes').innerHTML.includes('报告翻转'));
 assert(el('qec-corrections').textContent.includes('实际触发的条件纠错 0 项'));
 assert(!el('qec-corrections').textContent.includes('X(Q001)'),'Decoder suggestions are not applied corrections');
 console.log('PASS four-patch origins/68 roles/160 bits/128 history/XXXX and pair ZZ plus editor flags, undo, JSON, original gates/axes, legacy guard and true/reported/unsupported display (UI doubles only)');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
