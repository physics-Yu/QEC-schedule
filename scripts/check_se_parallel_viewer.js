// Functional DOM-shim verification. This does not claim browser rendering QA.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
const out=path.resolve(process.argv[2]||'artifacts/demos/logical-components-20261007');
const standalone=true;
const upstream=process.argv.includes('--upstream');
const assets=process.argv.includes('--source-assets')?path.resolve('viewer'):out;
class Element{constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.dataset={};this.style={};this.value='';this._text='';this.hidden=false;}
 set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(e=>e.textContent).join('');}
 appendChild(e){this.children.push(e);return e;}replaceChildren(...a){this.children=a;this._text='';}setAttribute(k,v){this.attrs[k]=String(v);}
 getBoundingClientRect(){return{width:this.width||900,height:470};}}
const source=fs.readFileSync(path.join(out,standalone?'full-viewer.html':'index.html'),'utf8'),els=new Map();for(const m of source.matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"[^>]*>/g))els.set(m[2],new Element(m[1]));
if(standalone)for(const m of source.matchAll(/<script type="application\/octet-stream" id="([^"]+)">([^<]+)<\/script>/g))els.get(m[1]).textContent=m[2];
const descend=e=>e.children.flatMap(c=>[c,...descend(c)]);
const get=id=>{if(id.startsWith('packed-')&&!els.has(id))return null;assert(els.has(id),id);return els.get(id);};get('speed').value='1';get('mode').value='physical';get('path-style').value='original';get('timebase').value='100';get('atom-size').value='2.8';get('render-style').value='reference';for(const id of ['show-glow','show-traps','show-aod','show-transfers','show-gates','show-trails','show-grid','show-zones','show-scale'])get(id).checked=true;get('show-labels').checked=false;get('show-glow').checked=false;get('schedule-mode').value='follow';get('schedule-span').value='1000';get('clearance').value='1';let frame,context;
const document={getElementById:get,createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelectorAll:()=>get('catalog').children.filter(e=>e.className==='item'),head:{appendChild:e=>{vm.runInContext(fs.readFileSync(path.join(out,e.src),'utf8'),context);e.onload();}}};
context={document,window:{matchMedia:()=>({matches:false}),location:{hash:'#SE'},history:{replaceState:()=>{throw Error('Opaque preview history is unavailable');}}},requestAnimationFrame:f=>frame=f,ResizeObserver:class{observe(){}},Blob,Response,DecompressionStream,Uint8Array,atob};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(out,'manifest.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(out,'regions.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(out,'schedules.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(assets,'resource-schedule.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(assets,'motion-preview.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(assets,'lab-renderer.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(assets,'components.js'),'utf8'),context);
const api=context.window.componentViewer,checks=[];

assert.equal(api.manifest.components.length,9);
async function waitFor(id){const until=Date.now()+30000;while(api.data?.id!==id){if(Date.now()>until)throw Error('LOAD_TIMEOUT '+id);await new Promise(r=>setTimeout(r,5));}}
let positionChecks=0;
for(const row of api.manifest.components){api.showRow(row);await waitFor(row.id);assert.equal(api.data.actions.length,row.action_count);assert.equal(api.schedule.source.id,row.id);const expected=api.data.atoms.map(a=>a.slice(2,4));for(const a of api.data.actions)if(a[7]==='completed')for(const tr of a[4])expected[tr[0]]=tr.slice(3,5);api.setTime(api.data.end);for(const[i,a]of api.stateAt(api.data.end).entries()){assert.deepEqual([a.x,a.y],Array.from(expected[i]));positionChecks++;}}
checks.push('all_nine_examples_load_with_matching_schedule_and_final_positions');
api.showRow(api.manifest.components.find(r=>r.id==='SE'));await waitFor('SE');
const pulses=api.data.actions.filter(a=>a[6]==='CZ');assert.deepEqual(Array.from(pulses,a=>a[5].length),[6,3,6,3,6]);assert.equal(api.data.end,1889);
const transfers=api.data.actions.filter(a=>['pickup','drop'].includes(a[2]));assert.equal(transfers.length,14);assert(transfers.every(a=>a[1]-a[0]===100));
for(const a of pulses){api.setTime((a[0]+a[1])/2);assert(descend(get('scene')).some(e=>e.attrs['data-cz-illumination']==='active'));}
checks.push('SE_five_CZ_pulses_24_pairs_and_100us_transfers');
const resets=api.data.actions.filter(a=>a[2]==='reset'&&a[0]>0);assert.equal(resets.length,8);assert.equal(new Set(resets.map(a=>a[0])).size,1);api.setTime((resets[0][0]+resets[0][1])/2);const state=api.stateAt(api.current);for(const a of resets)for(const i of a[3]){assert.equal(state[i].carrier,'AOD');const g=descend(get('scene')).find(e=>e.attrs['data-atom']===String(i));assert.equal(g.attrs['data-atom-brightness'],'1');}assert(get('active').textContent.includes('复位'));
checks.push('eight_resets_simultaneous_in_AOD_bright_and_stationary');
const pickup=transfers.find(a=>a[2]==='pickup');api.setTime((pickup[0]+pickup[1])/2);assert(get('activity-detail').textContent.includes('本动作 100 μs'));assert(get('activity-detail').textContent.includes('0.5 秒'));get('finish-action').onclick();assert.equal(api.current,pickup[1]);
checks.push('transfer_countdown_and_end_navigation');
api.showRow(api.manifest.components.find(r=>r.id==='SE_PAIR'));await waitFor('SE_PAIR');assert.deepEqual(Array.from(api.data.actions.filter(a=>a[6]==='CZ'),a=>a[5].length),[12,6,12,6,12]);
checks.push('two_patches_share_five_broadcast_pulses');
get('back').onclick();assert(!get('landing').hidden);assert(get('viewer-page').hidden);assert(source.includes('8 组件<br>＋ 1 并行示例'));
checks.push('correct_nine_example_directory_and_return');
const result={passed:true,components:9,position_comparisons:positionChecks,checks,scope:'functional DOM shim; actual browser rendering and user visual review pending'};
fs.writeFileSync(path.join(out,'se-viewer-functional-checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
