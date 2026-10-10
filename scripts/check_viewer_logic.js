// DOM-shim unit test, NOT browser rendering or visual acceptance.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const path=process.argv[2];
if(!path)throw Error('Usage: node scripts/check_viewer_logic.js path/viewer.html');
const html=fs.readFileSync(path,'utf8'), payload=html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1], script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element{constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.events={};this.style={};this._text='';this.value='';this.checked=false;}set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;this._text='';}setAttribute(k,v){this.attrs[k]=String(v);}addEventListener(k,fn){this.events[k]=fn;}}
const elements=new Map();
for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const e=new Element(match[1]);e.checked=/\bchecked\b/.test(match[2]);elements.set(match[3],e);}
const get=id=>{assert.ok(elements.has(id),'HTML must define #'+id);return elements.get(id);};
get('payload').textContent=payload;get('speed').value='1';get('playMode').value='keyframe';get('labels').value='focus';
const context={document:{getElementById:get,createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelector:s=>get(s)},window:{},requestAnimationFrame:()=>{}};
vm.createContext(context);vm.runInContext(script,context,{timeout:10000});
const api=context.window.naViewer,data=api.data,trace=data.display_trace||data.trace,checks=[];
assert.equal(get('fixtureBadge').textContent,data.fixture?'FIXTURE · 查看器自测':'真实生产模块工件');checks.push('evidence_badge');
assert.equal(api.stateAt(0).size,data.atom_program.initial_state.atoms.length);checks.push('atom_identity_count');
const completed=new Set((trace?.events||[]).filter(e=>e.status==='completed').map(e=>e.action_id));
const move=data.atom_program.actions.find(a=>a.kind==='move'&&(!data.trace||completed.has(a.id)));
if(move){const mid=(move.t_start_us+move.t_end_us)/2,state=api.stateAt(mid);for(const tr of move.payload.trajectories){const p=state.get(tr.atom_id).position_um;for(let i=0;i<2;i++)assert.ok(Math.abs(p[i]-(tr.from_um[i]+tr.to_um[i])/2)<1e-8);}checks.push('declared_linear_midpoint');}
const results=Object.entries(trace?.results||{}), earliest=results.sort((a,b)=>a[1].ready_us-b[1].ready_us)[0];
if(earliest){api.setTime(earliest[1].ready_us-0.001);assert.ok(!get('results').textContent.includes(earliest[0]+' = '));api.setTime(earliest[1].ready_us);assert.ok(get('results').textContent.includes(earliest[0]+' = '));checks.push('ready_time_gating');}
const maxTime=Math.max(...data.atom_program.actions.map(a=>a.t_end_us),...results.map(([_,r])=>r.ready_us));api.setTime(maxTime);
const finalAtoms=trace?.final_state?.atoms;
if(finalAtoms){const list=Array.isArray(finalAtoms)?finalAtoms:Object.values(finalAtoms),state=api.stateAt(maxTime);for(const atom of list){const actual=state.get(atom.atom_id);if(atom.position_um)for(let i=0;i<2;i++)assert.ok(Math.abs(actual.position_um[i]-atom.position_um[i])<1e-8);assert.equal(actual.carrier,atom.carrier);assert.equal(actual.trap_id,atom.trap_id);}checks.push('final_positions_and_bindings_match_trace');}
get('search').value='__no_matching_source__';get('search').events.input();assert.equal(get('actions').children.length,0);checks.push('source_filter');
get('search').value='';get('search').events.input();assert.ok(get('actions').children.length<=60);checks.push('bounded_table_page');
const originalData=JSON.stringify(data),initialIds=[...api.stateAt(0).keys()];
api.selectAtom(initialIds[0]);assert.ok(get('atomDetail').textContent.includes(initialIds[0]));
get('atomSearch').value='__missing_atom__';get('atomSearch').events.input();assert.ok(get('atomList').textContent.includes('没有匹配'));
get('atomSearch').value='';get('atomSearch').events.input();assert.ok(get('atomList').children.length<=6);checks.push('atom_inspector_and_filter');
const firstCZ=data.atom_program.actions.filter(a=>a.kind==='gate'&&a.payload.name==='CZ'&&a.t_start_us>0&&(!data.trace||completed.has(a.id))).sort((a,b)=>a.t_start_us-b.t_start_us)[0];
if(firstCZ){api.setTime(0);get('nextGate').onclick();assert.equal(api.currentTime,firstCZ.t_start_us);const expected=data.atom_program.actions.filter(a=>a.kind==='gate'&&a.payload.name==='CZ'&&a.t_start_us<=api.currentTime&&api.currentTime<a.t_end_us&&(!data.trace||completed.has(a.id))).reduce((n,a)=>n+a.payload.pairs.length,0);assert.equal(get('scene').children.filter(e=>e.attrs['data-layer']==='cz').length,expected);checks.push('cz_jump_and_exact_pairs');}
const timeBefore=api.currentTime,stateBefore=JSON.stringify([...api.stateAt(timeBefore)]);
get('fitAtoms').onclick();get('zoomIn').onclick();get('fitActive').onclick();get('fitAll').onclick();assert.equal(api.viewport.zoom,1);
get('showTraps').checked=false;get('showTraps').events.change();assert.equal(get('scene').children.filter(e=>e.attrs['data-layer']==='trap').length,0);
get('showTraps').checked=true;get('showTraps').events.change();assert.equal(api.currentTime,timeBefore);assert.equal(JSON.stringify([...api.stateAt(timeBefore)]),stateBefore);checks.push('view_controls_preserve_model_state');
const bs=[...new Set([0,maxTime,...data.atom_program.actions.flatMap(a=>[a.t_start_us,a.t_end_us]),...results.map(([_,r])=>r.ready_us)])].sort((a,b)=>a-b);
if(bs.length>1){assert.ok(Math.abs(api.advance(bs[0],.3,'keyframe',1)-(bs[0]+bs[1])/2)<1e-7);assert.equal(api.advance(bs[0],.6,'keyframe',1),bs[1]);assert.ok(Math.abs(api.advance(0,15,'uniform',1)-maxTime/2)<1e-7);checks.push('presentation_clock_maps_to_original_time');}
assert.equal(JSON.stringify(data),originalData);checks.push('payload_not_mutated_by_interaction');
console.log(JSON.stringify({path,passed:true,scope:'DOM shim logic only; browser and user visual acceptance unverified',checks,atom_count:api.stateAt(maxTime).size,action_count:data.atom_program.actions.length},null,2));
