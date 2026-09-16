// Real HTTP jobs/results and actual editor handlers; DOM/viewer host doubles.
const vm=require('node:vm'),assert=require('node:assert/strict');
const [base]=process.argv.slice(2);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function boot(search){
 const nodes=new Map(),requests=[],mounted=[];let blob;
 class Element{
  constructor(id){this.id=id;this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.dataset={};this.style={};this.parentElement={hidden:false};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),toggle:(k,on)=>on?this.classes.add(k):this.classes.delete(k)};}
  set innerHTML(s){this.html=s;parse(s);} get innerHTML(){return this.html||'';}
  setAttribute(k,v){this[k]=v;} focus(){} scrollIntoView(){} click(){this.onclick?.();}
  querySelectorAll(){return [];}
 }
 function parse(s){for(const m of s.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/value="([^"]*)"/)?.[1]||'';nodes.set(m[1],e);}}
 parse(await (await fetch(base)).text());
 const sessionCard=new Element('session-card');
 const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
 assert(!nodes.has('auto'),'Automatic compilation toggle was removed; compilation requires a click');
 const sandbox={console,AbortController,URLSearchParams,Blob,setTimeout,clearTimeout,location:{protocol:'http:',search},
  URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
  document:{body:new Element('body'),getElementById:el,addEventListener(){},createElement:id=>new Element(id),querySelectorAll(){return [];},querySelector(selector){assert.equal(selector,'.session-card');return sessionCard;}},
  window:{location:{search},addEventListener(){},NeutralAtomViewer:{mount(host,data){mounted.push(data);return {destroy(){},setTime(){},selectAtom(){}};}}},
  fetch:async(path,options)=>{requests.push({path,options});return fetch(base+path,options);}};
 vm.createContext(sandbox);
 // Match the real page's bootstrap order, including the external configuration.
 for(const script of ['/studio-catalog.js','/studio-model.js','/workbench.js']){
  vm.runInContext(await (await fetch(base+script)).text(),sandbox);
 }
 for(let i=0;i<200;i++){if(!el('compile').disabled&&el('compile-message').textContent!=='正在载入链接')break;await pause(30);}
 assert.equal(el('compile').disabled,false,'link must finish');
 const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
 const defaultGates=JSON.parse(JSON.stringify(sandbox.window.AtomStudioModel.newCustom(sandbox.window.AtomStudioCatalog).gates));
 return {el,requests,mounted,exported,defaultGates};
}
async function main(){
 const page=await boot('');const {el,exported,requests,mounted}=page;
 const waitPreview=async()=>{await pause(700);for(let i=0;i<200&&el('compile').disabled;i++)await pause(30);assert.equal(el('compile').disabled,false,el('compilation-compatibility').textContent);};
 let draft=await exported();assert.equal(draft.compilation.implementation,'ordered_greedy');assert.equal(draft.aod_backend,'row_column_orthogonal');
 assert(!requests.some(r=>r.path==='/api/compile'));
 el('atom-count').value='6';el('atom-count').onchange();await waitPreview();
 el('layout').value='shuffled';el('layout').onchange();await waitPreview();
 el('aod-rows').value='1';el('aod-rows').onchange();await waitPreview();
 el('aod-columns').value='3';el('aod-columns').onchange();await waitPreview();
 el('aod-column-offsets').value='0, 15, 35';el('aod-column-offsets').onchange();await waitPreview();
 el('motion-router').value='axis_hold';el('motion-router').onchange();await waitPreview();
 el('palette').onclick({target:{closest:()=>({dataset:{tool:'CZ'}})}});
 for(const q of ['0','1'])el('circuit').onclick({target:{closest:()=>({dataset:{q,column:'2'}})}});
 await waitPreview();draft=await exported();assert.equal(draft.atom_count,6);assert.equal(draft.layout,'shuffled');assert.deepEqual(draft.aod_column_offsets_um,[0,15,35]);
 assert(draft.gates.some(g=>g.gate_type==='CZ'));assert(!requests.some(r=>r.path==='/api/compile'));
 await el('compile').onclick();assert.equal(el('compile-state').dataset.state,'completed');
 assert.equal(mounted.at(-1).backend,'row_column_orthogonal');
 const first=await exported();el('compiler').value='preset:smt_ordered';el('compiler').onchange();await waitPreview();
 const second=await exported();assert.deepEqual(second.gates,first.gates);assert.equal(second.layout,first.layout);assert.deepEqual(second.aod_column_offsets_um,first.aod_column_offsets_um);
 await el('compile').onclick();assert.equal(el('compile-state').dataset.state,'completed');
 assert.equal(mounted.at(-1).summary.metrics.completed_gate_count,second.gates.length);
 assert.equal((await exported()).compiler,'smt_ordered');
 el('layout').value='row';el('layout').onchange();await waitPreview();
 el('preset').value='nonuniform_pairs';el('preset').onchange();await waitPreview();
 const dynamic=await exported();assert.equal(dynamic.atom_count,6);assert.equal(dynamic.gates.length,3);
 assert.deepEqual(dynamic.aod_column_offsets_um,[0,15,35]);
 await el('compile').onclick();assert.equal(el('compile-state').dataset.state,'completed');
 assert.match(el('greedy-rows').innerHTML,/抓取/);assert.match(el('greedy-rows').innerHTML,/作用/);
 assert(mounted.at(-1).operations.some(o=>o.kind==='aod_move'&&o.moving_count===3&&['x_um','y_um'].some(k=>o.source_axes[k].some((x,i)=>Math.abs(x-o.source_axes[k][0]-o.target_axes[k][i]+o.target_axes[k][0])>1e-7))));
 el('platform-export').onclick(); // exercises configuration serialization handlers
 el('compiler').value='preset:greedy';el('compiler').onchange();await pause(800);
 assert.equal(el('compile').disabled,true,'old strategy cannot silently consume ordered hardware');
 assert.equal((await exported()).aod_backend,'row_column_orthogonal');
 el('aod-backend').value='rigid';el('aod-backend').onchange();await pause(800);
 assert.equal(el('compile').disabled,true,'old M4 still rejects nonuniform array');
 el('compiler').value='preset:ordered_greedy';el('compiler').onchange();el('aod-backend').value='row_column_orthogonal';el('aod-backend').onchange();await waitPreview();
 const before=JSON.stringify((await exported()).gates);
 el('experiment-demo').value='ordered-qec-ghz2';await el('experiment-demo').onchange();await waitPreview();
 assert.equal((await exported()).compiler,'ordered_greedy');assert.equal((await exported()).atom_count,34);assert.equal(el('aod-backend').disabled,true);
 el('experiment-demo').value='custom';await el('experiment-demo').onchange();await waitPreview();
 assert.equal(JSON.stringify((await exported()).gates),before);assert.equal((await exported()).atom_count,6);
 console.log('PASS actual editor handlers + HTTP: arbitrary atom/layout/nonuniform axes, no auto compile, greedy and SMT real CZ compilation, independent configurations, incompatible old backend rejected, QEC demo and custom draft restored. DOM/viewer host doubles, not a browser.');
}
main().catch(e=>{console.error(e);process.exit(1)});
