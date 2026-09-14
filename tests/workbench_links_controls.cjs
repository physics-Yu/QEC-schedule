// Real HTTP jobs/results and actual editor handlers; DOM/viewer host doubles.
const vm=require('node:vm'),assert=require('node:assert/strict');
const [base,jobId]=process.argv.slice(2);
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
 const sandbox={console,AbortController,URLSearchParams,Blob,setTimeout,clearTimeout,
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
 const example=await boot('?example=surface-ghz');
 const configuredExample=await (await fetch(base+'/api/studio/demos/surface-ghz')).json();
 assert.equal((await example.exported()).gates.length,194);
 assert.equal((await example.exported()).compile_timeout_s,configuredExample.compilation.compile_timeout_s);

 assert(!example.requests.some(r=>r.path==='/api/compile'));
 const saved=await boot('?job='+jobId);
 assert.equal((await saved.exported()).gates.length,2);
 assert.equal(saved.el('compile-state').dataset.state,'completed');
 assert.equal(saved.mounted.at(-1).summary.metrics.completed_gate_count,2);
 assert(!saved.requests.some(r=>r.path==='/api/compile'));
 // Continue editing the exact loaded input and compile through the real server.
 saved.el('palette').onclick({target:{closest:()=>({dataset:{tool:'X'}})}});
 saved.el('circuit').onclick({target:{closest:()=>({dataset:{q:'0',column:'1'}})}});
 assert(saved.el('viewer').classes.has('stale'));
 assert.equal((await saved.exported()).gates.length,3);
 // The edited draft must pass the real preview validation before compilation.
 for(let i=0;i<200&&saved.el('compile').disabled;i++)await pause(30);
 assert.equal(saved.el('compile').disabled,false,'edited input must validate before compiling');
 await saved.el('compile').onclick();
 assert.equal(saved.mounted.at(-1).summary.metrics.completed_gate_count,3);
 assert.equal(saved.el('compile-state').dataset.state,'completed');
 const missing=await boot('?job='+'f'.repeat(32));
 assert(missing.el('toast').textContent.includes('链接载入失败'));
 assert.deepEqual((await missing.exported()).gates,missing.defaultGates);
 assert(!missing.requests.some(r=>r.path==='/api/compile'));
 const malformed=await boot('?job=../../not-a-job');
 assert(malformed.el('toast').textContent.includes('无效'));
 assert(!malformed.requests.some(r=>r.path.startsWith('/api/jobs/')));
 console.log('PASS: real-API example/job deep links, no automatic compile, saved playback and editable recompile, missing/malformed link preserves draft');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
