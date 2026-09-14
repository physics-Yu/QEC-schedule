// Actual editor event handlers + actual HTTP compiler. DOM/viewer host doubles:
// this verifies the edit/recompile contract, not browser rendering or FPS.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=process.argv[2]||'http://127.0.0.1:8766',nodes=new Map(),responses=[],requests=[],downloads=[];
class Element{
 constructor(id){this.id=id;this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.dataset={};this.style={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k)};}
 set innerHTML(s){this.html=s;parse(s);}
 get innerHTML(){return this.html||'';}
 setAttribute(k,v){this[k]=v;}
 scrollIntoView(){}
 showModal(){this.open=true;}
 close(){this.open=false;}
 click(){if(this.href)downloads.push(this.href);else this.onclick?.();}
}
function parse(s){for(const m of s.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/value="([^"]*)"/)?.[1]||'';nodes.set(m[1],e);}}
const el=id=>{assert(nodes.has(id),'Missing editor element '+id);return nodes.get(id);};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const until=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await pause(50);}throw Error('Editor preview timeout');};
async function main(){
 const html=await (await fetch(base)).text();parse(html);
 assert(html.indexOf('id="initial-body"')<html.indexOf('id="circuit"'));
 assert(html.includes('id="edit-initial"'));assert(!html.includes('id="auto"'));
 let mounted=null,blob;
 const sandbox={console,AbortController,Blob,setTimeout,clearTimeout,
  URL:{createObjectURL(b){blob=b;return 'blob:download';},revokeObjectURL(){}},
  fetch:async(path,options)=>{if(path==='/api/compile')requests.push(JSON.parse(options.body));const r=await fetch(base+path,options);if(path.endsWith('/result'))responses.push(await r.clone().json());return r;},
  document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id)},
  window:{addEventListener(){},NeutralAtomViewer:{mount(host,data){mounted=data;return {destroy(){},setTime(){},selectAtom(){}};}}}};
 vm.createContext(sandbox);vm.runInContext(await (await fetch(base+'/workbench.js')).text(),sandbox);
 await until(()=>mounted!==null);
 assert.equal(el('compiler').value,'recommended');assert.equal(el('anchor-order').disabled,true);
 assert.equal(mounted.scene.atoms?.length||mounted.frames[0].atom_updates.length,4);
 await el('compile').onclick();
 assert.equal(responses.at(-1).status,'completed');assert.equal(requests.at(-1).gates.length,8);
 assert.equal(responses.at(-1).recording.summary.overlap_time_us,4);
 assert.equal(el('greedy-decisions').hidden,false);assert(el('greedy-rows').innerHTML.includes('G000'));
 // Place an X through the actual palette + circuit handlers.
 el('palette').onclick({target:{closest:()=>({dataset:{tool:'X'}})}});
 el('circuit').onclick({target:{closest:()=>({dataset:{q:'3',column:'5'}})}});
 assert.equal(el('greedy-decisions').hidden,true);assert(el('viewer').classes.has('stale'));
 await el('compile').onclick();
 assert.equal(requests.at(-1).gates.length,9);assert.equal(responses.at(-1).recording.summary.metrics.completed_gate_count,9);
 // Retarget a T gate through the actual editor, retaining its fixed unitary.
 el('circuit').onclick({target:{closest:()=>({dataset:{q:'2',column:'2'}})}});
 el('edit-q0').value='Q003';el('edit-column').value='3';
 el('apply-gate').onclick();await el('compile').onclick();
 assert.deepEqual(responses.at(-1).recording.operations.find(o=>o.gate_id==='G003').u_parameters_rad,[0,0,Math.PI/4]);
 assert.deepEqual(requests.at(-1).gates.find(g=>g.id==='G003').qubit_ids,['Q003']);
 // Initial conditions are actual compilation inputs, not cosmetic layout.
 el('atom-count').value='6';el('atom-count').onchange();el('layout').value='shuffled';el('layout').onchange();
 await el('compile').onclick();assert.equal(requests.at(-1).atom_count,6);assert.equal(requests.at(-1).layout,'shuffled');
 assert.equal(responses.at(-1).recording.frames[0].atom_updates.length,6);
 el('export-input').onclick();const before=JSON.parse(await blob.text());
 el('random-circuit').onclick();el('export-input').onclick();const random=JSON.parse(await blob.text());
 assert.equal(random.gates.length,12);assert.equal(random.compiler,'greedy');
 assert.equal(random.compilation.strategy,'recommended');
 assert(random.gates.every(g=>['H','X','Y','Z','T','CZ'].includes(g.gate_type)&&g.parameters.length===0));
 el('undo').onclick();el('export-input').onclick();assert.deepEqual(JSON.parse(await blob.text()),before);
 el('redo').onclick();el('export-input').onclick();assert.deepEqual(JSON.parse(await blob.text()),random);
 // Import an exact saved input using the same validation path.
 el('import-file').files=[{size:JSON.stringify(before).length,text:async()=>JSON.stringify(before)}];
 await el('import-file').onchange();await el('compile').onclick();
 const ordered=gs=>[...gs].sort((a,b)=>a.id.localeCompare(b.id));
 assert.deepEqual(ordered(requests.at(-1).gates),ordered(before.gates));assert.equal(responses.at(-1).status,'completed');
 // Failure is visible and leaves the last valid result labelled stale.
 const valid=JSON.parse(JSON.stringify(before));valid.gates[0].qubit_ids=['Q999','Q001'];
 el('import-file').files=[{size:100,text:async()=>JSON.stringify(valid)}];await el('import-file').onchange();
 assert(el('toast').textContent.includes('导入失败'));
 const unsupported=JSON.parse(JSON.stringify(before));unsupported.gates[0]={id:'old-u',gate_type:'U3',parameters:[0,0,0],qubit_ids:['Q000'],column:0};
 el('import-file').files=[{size:100,text:async()=>JSON.stringify(unsupported)}];await el('import-file').onchange();
 assert(el('toast').textContent.includes('仅限'));
 // A genuine finite-budget failure opens a modal, exports evidence, then recovers.
 el('max-decisions').value='1';el('max-decisions').onchange();await el('compile').onclick();
 assert.equal(responses.at(-1).status,'stalled');assert.equal(el('failure-dialog').hidden,false);
 assert(el('failure-causes').textContent.includes('DECISION_BUDGET_EXHAUSTED'));
 el('failure-download').onclick();const failed=JSON.parse(await blob.text());
 assert.equal(failed.input.max_decisions,1);assert(failed.recording.operations.length>0);
 el('failure-close').onclick();assert.equal(el('failure-dialog').hidden,true);
 el('max-decisions').value='10000';el('max-decisions').onchange();await el('compile').onclick();
 assert.equal(responses.at(-1).status,'completed');assert.equal(requests.at(-1).ez_policy,'adaptive');
 fs.writeFileSync('artifacts/m4-editor-http.json',JSON.stringify({status:'passed',kind:'editor DOM double with actual HTTP compiler',
  checks:['default greedy','initial conditions first','place X','retarget T','recompile','change atom count/layout','random/undo/redo','export/import','invalid and unsupported import','decision table','stale result'],
  runs:responses.map(r=>({gates:r.input.gates.length,atoms:r.input.atom_count,layout:r.input.layout,status:r.status,wall_us:r.recording.duration,overlap_us:r.recording.summary.overlap_time_us}))},null,2));
 console.log('PASS M4 editor handlers + real HTTP: restricted gates, retarget T, atom/layout changes, recompile, random/undo/redo, import/export, stale state, decisions');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
