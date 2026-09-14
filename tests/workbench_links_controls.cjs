// Real HTTP jobs/results and actual editor handlers; DOM/viewer host doubles.
const vm=require('node:vm'),assert=require('node:assert/strict');
const [base,jobId]=process.argv.slice(2);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function boot(search){
 const nodes=new Map(),requests=[],mounted=[];let blob;
 class Element{
  constructor(id){this.id=id;this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.dataset={};this.style={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k)};}
  set innerHTML(s){this.html=s;parse(s);} get innerHTML(){return this.html||'';}
  setAttribute(k,v){this[k]=v;} focus(){} scrollIntoView(){} click(){this.onclick?.();}
 }
 function parse(s){for(const m of s.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/value="([^"]*)"/)?.[1]||'';nodes.set(m[1],e);}}
 parse(await (await fetch(base)).text());
 const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
 assert(!nodes.has('auto'),'Automatic compilation toggle was removed; compilation requires a click');
 const sandbox={console,AbortController,URLSearchParams,Blob,setTimeout,clearTimeout,
  URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
  document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id)},
  window:{location:{search},addEventListener(){},NeutralAtomViewer:{mount(host,data){mounted.push(data);return {destroy(){},setTime(){},selectAtom(){}};}}},
  fetch:async(path,options)=>{requests.push({path,options});return fetch(base+path,options);}};
 vm.createContext(sandbox);vm.runInContext(await (await fetch(base+'/workbench.js')).text(),sandbox);
 for(let i=0;i<200;i++){if(!el('compile').disabled&&el('compile-message').textContent!=='正在载入链接')break;await pause(30);}
 assert.equal(el('compile').disabled,false,'link must finish');
 const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
 return {el,requests,mounted,exported};
}
async function main(){
 const example=await boot('?example=surface-ghz');
 assert.equal((await example.exported()).gates.length,194);
 assert.equal((await example.exported()).compile_timeout_s,3600);

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
 await saved.el('compile').onclick();
 assert.equal(saved.mounted.at(-1).summary.metrics.completed_gate_count,3);
 assert.equal(saved.el('compile-state').dataset.state,'completed');
 const missing=await boot('?job='+'f'.repeat(32));
 assert(missing.el('toast').textContent.includes('链接载入失败'));
 assert.equal((await missing.exported()).gates.length,8);
 assert(!missing.requests.some(r=>r.path==='/api/compile'));
 const malformed=await boot('?job=../../not-a-job');
 assert(malformed.el('toast').textContent.includes('无效'));
 assert(!malformed.requests.some(r=>r.path.startsWith('/api/jobs/')));
 console.log('PASS: real-API example/job deep links, no automatic compile, saved playback and editable recompile, missing/malformed link preserves draft');
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
