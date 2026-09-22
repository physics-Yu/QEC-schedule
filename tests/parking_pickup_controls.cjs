// Actual editor handlers and HTTP compiler; DOM/viewer doubles, not GUI acceptance.
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.argv[2],pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const nodes=new Map(),requests=[],mounted=[],seek=[];let blob,link='';
 class Element{
  constructor(id){this.id=id;this.value='';this.dataset={};this.style={};this.disabled=false;this.hidden=false;}
  set innerHTML(v){this.html=v;}get innerHTML(){return this.html||'';}
  setAttribute(k,v){this[k]=v;} querySelectorAll(){return [];}
  focus(){}scrollIntoView(){}click(){this.onclick?.();}
 }
 const html=await (await fetch(base)).text();
 for(const m of html.matchAll(/\bid="([^"]+)"/g))nodes.set(m[1],new Element(m[1]));
 assert.match(html,/<option value="pattern_optimal">/);
 const el=id=>{assert(nodes.has(id),id);return nodes.get(id);};
 const sandbox={console,Blob,setTimeout,clearTimeout,URLSearchParams,location:{search:''},history:{replaceState(a,b,c){link=c;}},
  URL:{createObjectURL(b){blob=b;return 'blob:test';},revokeObjectURL(){}},
  document:{getElementById:el,addEventListener(){},createElement:id=>new Element(id),querySelectorAll:()=>Array.from(nodes.values()).filter(e=>!['export-input','pickup-end','transport-start','export-replay'].includes(e.id))},
  window:{NeutralAtomViewer:{mount(host,data){mounted.push(data);return {destroy(){},setTime(t){seek.push(t);}};}}},
  fetch:async(path,options)=>{requests.push(path);return fetch(base+path,options);}};
 vm.createContext(sandbox);vm.runInContext(await (await fetch(base+'/parking.js')).text(),sandbox);
 for(let i=0;i<200&&!mounted.length;i++)await pause(30);
 assert(mounted.length);assert(!requests.includes('/api/compile'));
 const exported=async()=>{el('export-input').onclick();return JSON.parse(await blob.text());};
 assert.equal((await exported()).rows,10);assert.equal((await exported()).columns,10);
 assert.equal((el('board').innerHTML.match(/class="site"/g)||[]).length,100);
 assert(!el('board').innerHTML.includes('<button'),'Sites must be point markers, not tile buttons');
 assert.match(html,/stroke-dasharray:3 3/);assert.match(html,/#db4b50/);assert.match(html,/#3879c7/);
 el('show-ids').checked=true;el('show-ids').onchange();assert.match(el('board').innerHTML,/class="site-label"/);
 el('board-zoom').value='2';el('board-zoom').onchange();assert.equal(el('board').style.width,'200%');
 el('fit-capacity').onclick();assert.equal((await exported()).aod_rows,10);
 el('fit-transport').onclick();assert.equal((await exported()).shift_x_um,140);
 const click=(id,data)=>el(id).onclick({detail:0,target:{closest:()=>({dataset:data})}});
 click('paint-tools',{paint:'0'});click('board',{r:'0',c:'0'});
 assert.equal((await exported()).cells[0][0],0);
 click('paint-tools',{paint:'1'});click('board',{r:'0',c:'0'});
 assert.equal((await exported()).cells[0][0],1);
 click('paint-tools',{paint:'toggle'});click('board',{r:'0',c:'0'});
 assert.equal((await exported()).cells[0][0],2);
 assert(!requests.includes('/api/compile'),'Editing must never compile automatically');
 if(process.argv.includes('--editor-only')){
  console.log('PASS 10x10 SVG markers, red/blue/dashed styles, editing, IDs, zoom, capacity and transport helpers; no automatic compile');return;
 }
 await el('small-example').onclick();await el('compile').onclick();
 assert.match(el('status').textContent,/已完成/);assert.equal(el('failure').hidden,true);
 const rowLink=link;el('pickup-end').onclick();el('transport-start').onclick();
 assert(seek[1]>seek[0]);assert.match(el('steps').innerHTML,/Q001/);
 await el('export-replay').onclick();assert.match(await blob.text(),/NeutralAtomViewer.mount/);
 el('strategy').value='naive_columnwise';el('strategy').onchange();await el('compile').onclick();
 assert.match(el('status').textContent,/已完成/);const columnLink=link;
 assert(mounted.at(-1).operations.some(o=>o.kind==='aod_recapture'));
 el('aod_rows').value='1';el('aod_rows').onchange();await el('compile').onclick();
 assert.equal(el('failure').hidden,false);assert.match(el('failure-message').textContent,/AXIS_CAPACITY/);
 assert.equal((await exported()).aod_rows,1);assert.equal(link,columnLink,'Failure must not publish a successful replay');
 el('aod_rows').value='2';el('aod_rows').onchange();el('clear').onclick();await el('compile').onclick();
 assert.match(el('status').textContent,/已完成/);assert.equal(mounted.at(-1).operations.length,0);
 const report={status:'passed',row_url:base+'/'+rowLink,column_url:base+'/'+columnLink,checks:['manual compile','editable SLM and targets','both strategies','capture and recapture','pickup/transport seeking','offline export','capacity failure','empty no-op'],scope:'HTTP + actual JS with DOM/viewer doubles; not real GUI'};
 fs.writeFileSync('artifacts/parking-delivery/controls.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
