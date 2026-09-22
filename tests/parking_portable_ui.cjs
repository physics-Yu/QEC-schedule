// Actual standalone HTML scripts, minimal DOM doubles. Not a real-browser visual test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function harness(html){
 const nodes=new Map();let raf,blob,filename='';
 class Element{
  constructor(id){this.id=id;this.value='';this.dataset={};this.style={};this.disabled=false;this.checked=false;this.clientWidth=900;this.clientHeight=520;this.textContent='';this.innerHTML='';this.listeners={};}
  focus(){} scrollIntoView(){} setAttribute(k,v){this[k]=v;} querySelectorAll(){return [];} addEventListener(k,v){this.listeners[k]=v;}
  getBoundingClientRect(){return {left:0,top:0,width:900,height:520};} click(){if(this.download)filename=this.download;this.onclick?.();}
 }
 for(const m of html.matchAll(/\bid="([^"]+)"/g))nodes.set(m[1],new Element(m[1]));
 const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
 el('demo-input').textContent=html.match(/<script id="demo-input"[^>]*>([\s\S]*?)<\/script>/)[1];
 el('demo-plan').textContent=html.match(/<script id="demo-plan"[^>]*>([\s\S]*?)<\/script>/)[1];
 el('board-zoom').value='1';
 const sandbox={console,Blob,performance,setTimeout:fn=>fn(),requestAnimationFrame:fn=>{raf=fn;},URL:{createObjectURL(v){blob=v;return 'blob:test';},revokeObjectURL(){}},
  document:{getElementById:el,createElement:id=>new Element(id),addEventListener(){},documentElement:{cloneNode(){const seeds={};return {querySelector(id){return seeds[id]||(seeds[id]={});},get outerHTML(){let s=html;for(const [id,node] of Object.entries(seeds))s=s.replace(new RegExp('(<script id="'+id.slice(1)+'"[^>]*>)[\\s\\S]*?(</script>)'),(_,a,b)=>a+node.textContent+b);return s;}};}}},addEventListener(){}};
 sandbox.NeutralAtomViewer={mount(host,data,options){host.innerHTML='shared-viewer-mounted';let time=0;return {data,options,setTime(t){time=t;},getStatus(){return {time_us:time};},pause(){},destroy(){host.innerHTML='';}};}};
 sandbox.window=sandbox;vm.createContext(sandbox);
 for(const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g))if(!match[1].includes('application/json')&&!match[2].includes('const SHELL='))vm.runInContext(match[2],sandbox);
 return {el,api:sandbox.ParkingLab,tick:t=>raf(t),blob:()=>blob,filename:()=>filename,click:(id,dataset)=>el(id).onclick({target:{closest:()=>({dataset})}})};
}
(async()=>{
 const html=fs.readFileSync(process.argv[2]||'demo/parking/index.html','utf8');
 assert(!/<(?:script|link)[^>]*(?:src|href)=/i.test(html),'No external assets');assert(!/\bfetch\s*\(|XMLHttpRequest|WebSocket/.test(html),'No network APIs');
 const h=harness(html),e=h.el;assert.equal(h.api.getDraft().rows,10);assert.equal(h.api.getPlan().metrics.targets,43);
 assert.equal((e('board').innerHTML.match(/class="site"/g)||[]).length,100);assert.match(html,/3 · 原子执行回放/);assert.match(html,/QEC SCHEDULE/);
 assert.equal(h.api.getViewer().options.atomColors.Q000,'#db4b50');assert.equal(h.api.getViewer().options.atomColors.Q002,'#3879c7');
 const old=JSON.stringify(h.api.getPlan());h.click('paint-tools',{paint:'0'});
 e('board').onkeydown({key:'Enter',preventDefault(){},target:{closest:()=>({dataset:{r:'0',c:'0'}})}});
 assert.equal(h.api.getDraft().cells[0][0],0);assert(h.api.isDirty());assert.equal(JSON.stringify(h.api.getPlan()),old,'No automatic generation');
 e('undo').onclick();assert.equal(h.api.getDraft().cells[0][0],2);e('compile').onclick();assert(!h.api.isDirty());assert.match(e('status').textContent,/ms/);
 e('pickup-end').onclick();assert.equal(h.api.getTime(),h.api.getPlan().pickupEnd);
 await e('small-example').onclick();e('strategy').value='naive_columnwise';e('strategy').onchange();e('compile').onclick();assert.equal(h.api.getPlan().groups.length,3);
 e('epsilon_x_um').value='1';e('epsilon_x_um').onchange();e('compile').onclick();assert(h.api.isDirty());assert.match(e('failure-message').textContent,/GAP/);
 e('epsilon_x_um').value='2.5';e('epsilon_x_um').onchange();e('compile').onclick();
 e('export-replay').onclick();assert.match(h.filename(),/2x3.html/);const exported=await h.blob().text(),shared=harness(exported);
 assert.equal(JSON.stringify(shared.api.getDraft()),JSON.stringify(h.api.getDraft()));assert.equal(shared.api.getPlan().duration,h.api.getPlan().duration);assert(!shared.api.isDirty());
 shared.el('clear').onclick();shared.el('compile').onclick();assert.equal(shared.api.getPlan().operations.length,0);
 e('export-input').onclick();const json=await h.blob().text();assert.equal(JSON.parse(json).input.strategy,'naive_columnwise');
 await e('example').onclick();e('input-file').files=[{size:json.length,text:async()=>json}];await e('input-file').onchange();assert.equal(h.api.getDraft().rows,2);assert(h.api.isDirty());
 e('input-file').files=[{size:7,text:async()=>'invalid'}];await e('input-file').onchange();assert.match(e('status').textContent,/导入失败/);
 await e('example').onclick();h.click('paint-tools',{paint:'1'});e('board').onpointerdown({preventDefault(){},target:{closest:()=>({dataset:{r:'0',c:'0'}})}});assert.equal(h.api.getDraft().cells[0][0],1);
 await e('compatible-example').onclick();assert.equal(h.api.getDraft().strategy,'pattern_optimal');e('compile').onclick();assert.equal(h.api.getPlan().groups.length,2);assert.equal(h.api.getPlan().metrics.targets,9);assert.match(e('compatibility-report').textContent,/按行 2 批/);assert.match(e('compatibility-report').textContent,/无目标行 9/);
 e('export-replay').onclick();const groupedShare=harness(await h.blob().text());assert.equal(groupedShare.api.getPlan().groups.length,2);assert.equal(groupedShare.api.getDraft().strategy,'pattern_optimal');
 console.log('PASS original workbench controller: 100 sites, role colors, explicit generation, editing, undo, errors, row/column, import/export and share roundtrip; DOM doubles. Shared viewer tested separately.');
})().catch(e=>{console.error(e);process.exitCode=1;});
