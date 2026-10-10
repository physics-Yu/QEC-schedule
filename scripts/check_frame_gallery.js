// Functional DOM-shim verification. This does not claim browser rendering QA.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
const out=path.resolve(process.argv[2]||'artifacts/demos/logical-components-20261007');
const standalone=process.argv.includes('--standalone');
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

async function waitFor(id){const until=Date.now()+30000;while(api.data?.id!==id){if(Date.now()>until)throw Error('Data load timed out: '+id);await new Promise(r=>setTimeout(r,5));}}
let comparisons=0;
for(const row of api.manifest.components.filter(r=>r.kind==='frame_session')){api.showRow(row);await waitFor(row.id);assert.equal(api.data.actions.length,row.action_count);assert.equal(api.schedule.source.id,row.id);assert(!get('clifford-panel').hidden);const d=api.data;
 const coords=d.atoms.map(a=>a.slice(2,4));for(const a of d.actions){if(a[7]==='completed')for(const tr of a[4])coords[tr[0]]=tr.slice(3,5);}
 for(const [i,a]of api.stateAt(d.end).entries()){assert(Math.abs(a.x-coords[i][0])<1e-8);assert(Math.abs(a.y-coords[i][1])<1e-8);comparisons++;}
 api.setTime(d.end);assert(!get('clifford-state').textContent.includes('undefined'));assert(!JSON.stringify(get('scene').attrs).includes('NaN'));
 get('back').onclick();assert(get('viewer-page').hidden);
}
for(const id of ['H','H_THEN_H']){api.showRow(api.manifest.components.find(r=>r.id===id));await waitFor(id);assert.equal(api.data.end,0);assert.equal(api.data.actions.length,0);const before=JSON.stringify(api.stateAt(0));
 get('play').onclick();assert(get('clifford-state').textContent.includes('算法 Z → 物理 X'));assert(get('clifford-state').textContent.includes('物理 −Y'));assert.equal(JSON.stringify(api.stateAt(0)),before);
 if(id==='H_THEN_H'){get('clifford-next').onclick();assert(get('clifford-state').textContent.includes('F = I'));assert.equal(JSON.stringify(api.stateAt(0)),before);}
 assert(api.schedule.lanes.every(l=>l.intervals.length===0));
}
api.showRow(api.manifest.components.find(r=>r.id==='H_THEN_SE'));await waitFor('H_THEN_SE');get('start').onclick();get('play').onclick();frame(0);frame(100);assert.equal(api.current,10);get('play').onclick();
const result={passed:true,components:api.manifest.components.length,position_comparisons:comparisons,checks:['all_frame_sessions_load','zero_hardware_time_and_resources_for_virtual_H','signed_Y_pullback','HH_cancels_without_motion','fixed_100us_per_second','continuous_final_positions','directory_return'],scope:'DOM function checks; browser rendering and visual acceptance pending'};
fs.writeFileSync(path.join(out,'frame-functional-checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
