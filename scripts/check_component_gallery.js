// Functional DOM-shim verification. This does not claim browser rendering QA.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
const out=path.resolve(process.argv[2]||'artifacts/demos/logical-components-20261007');
const standalone=process.argv.includes('--standalone');
const upstream=process.argv.includes('--upstream');const frameAware=process.argv.includes('--frame-aware');
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
assert.equal(api.manifest.components.length,process.argv.includes('--joint-frontier')?82:frameAware?78:upstream?66:71);
async function waitFor(id){const until=Date.now()+30000;while(api.data?.id!==id){if(Date.now()>until)throw Error('Data load timed out: '+id);await new Promise(r=>setTimeout(r,5));}}
assert.equal(document.querySelectorAll().length,api.manifest.components.length);checks.push('all_component_buttons_present');
let comparisons=0;
for(const row of api.manifest.components){api.showRow(row);await waitFor(row.id);assert.equal(api.data.id,row.id);assert.equal(api.data.actions.length,row.action_count);assert.equal(api.schedule.source.id,row.id);assert(!get('viewer-page').hidden);assert(get('landing').hidden);
 if(row.implementation_version==='neutral-modular/1'){
  assert(get('qualification').textContent.includes('当前模块配方'));assert(get('qualification').textContent.includes('视觉待验'));
  assert(api.data.modules?.length>0,'missing module references '+row.id);
  get('module-select').value='0';get('module-select').onchange();assert.equal(api.current,api.data.modules[0].start_us);
  assert(get('module-detail').textContent.includes(api.data.modules[0].module_hash));
  if(['T','TDG','REJECT_RETRY'].includes(row.id))for(const k of ['leaf_compile_count','placement_search_count','routing_search_count'])assert.equal(row.module_stats[k],0,k);
 }
 const d=api.data,coords=d.atoms.map(a=>a.slice(2,4));
 for(const a of d.actions){if(a[7]!=='completed')continue;for(const tr of a[4])coords[tr[0]]=tr.slice(3,5);}
 for(const [i,a]of api.stateAt(d.end).entries()){assert(Math.abs(a.x-coords[i][0])<1e-8);assert(Math.abs(a.y-coords[i][1])<1e-8);comparisons++;}
 const site=d.atoms.map(a=>a[6]||a[1]);
 for(const a of d.actions){if(a[7]!=='completed')continue;for(const b of a[9]||[]){assert.equal(site[b[0]],b[1]);site[b[0]]=b[2];assert.equal(api.stateAt(a[1]-1e-6)[b[0]].site,b[1]);assert.equal(api.stateAt(a[1])[b[0]].site,b[2]);}}
 for(const [i,a]of api.stateAt(d.end).entries())assert.equal(a.site,site[i]);
 const moves=d.actions.filter(a=>a[2]==='move'&&a[7]==='completed');for(const a of [moves[0],moves[Math.floor(moves.length/2)],moves.at(-1)].filter(Boolean)){
   const state=api.stateAt((a[0]+a[1])/2);for(const tr of a[4]){assert(Math.abs(state[tr[0]].x-(tr[1]+tr[3])/2)<1e-8);assert(Math.abs(state[tr[0]].y-(tr[2]+tr[4])/2)<1e-8);comparisons++;}}
 for(const width of [320,736,1024]){get('scene').width=width;api.setTime(0);assert.equal(descend(get('scene')).filter(e=>'data-atom' in e.attrs).length,d.atoms.length);assert(!JSON.stringify(get('scene').attrs).includes('NaN'));}
}
const zm=api.manifest.components.find(r=>r.id==='MEASURE_Z');
if(zm){api.showRow(zm);await waitFor(zm.id);if(api.data.readout_capacity===null){
 const reads=api.data.actions.filter(a=>a[2]==='measure');assert.equal(reads.length,9);assert.equal(new Set(reads.map(a=>a[0])).size,1);
 assert.deepEqual(Array.from(api.data.actions.filter(a=>a[2]==='pickup'),a=>a[3].length),[9,9]);
 api.setTime(reads[0][0]);assert(get('active').textContent.includes('测量 × 9'));assert(get('scene').textContent.includes('并行读出无上限'));
 checks.push('unlimited_Z_readout_nine_simultaneous_single_trip_and_label');}}
checks.push('every_component_loads_and_preserves_action_count','all_final_positions_match_projection','site_binding_changes_only_after_committed_arrival','representative_move_midpoints_interpolate_exactly','all_atoms_render_at_320_736_1024');
if(api.manifest.components.every(r=>r.implementation_version==='neutral-modular/1'))checks.push('all_rows_current_module_version','module_reference_source_and_time_navigation');
if(['T','TDG','REJECT_RETRY'].every(id=>api.manifest.components.some(r=>r.id===id&&r.implementation_version==='neutral-modular/1')))checks.push('top_level_protocols_zero_compile_and_search');
api.showRow(api.manifest.components.find(r=>r.id==='SE'));
await waitFor('SE');
get('start').onclick();get('move').onclick();assert.equal(api.current,api.data.actions.find(a=>a[2]==='move'&&a[0]>0)[0]);
get('start').onclick();get('cz').onclick();assert(descend(get('scene')).some(e=>e.attrs['data-cz']==='true'));
get('measure').onclick();assert(get('active').textContent.includes('测量'));checks.push('move_CZ_measure_controls');
get('start').onclick();get('play').onclick();frame(0);frame(100);assert(api.current>0);get('play').onclick();const paused=api.current;frame(200);assert.equal(api.current,paused);checks.push('play_pause_animation_clock');
get('scrub').value=String(api.data.end/3);get('scrub').oninput();assert.equal(api.current,api.data.end/3);checks.push('slider_seeks_model_time');
const phase=api.data.phases[0];get('phase').value=phase.id;get('phase').onchange();assert.equal(api.current,phase.start_us);checks.push('phase_navigation');
get('atom-select').value='4';get('atom-select').onchange();assert(get('atom-detail').textContent.includes(api.data.atoms[4][1]));checks.push('keyboard_accessible_atom_selector');
const post=api.manifest.components.find(r=>r.id==='CLASSICAL_POSTPROCESS');if(post){api.showRow(post);await waitFor(post.id);api.setTime(api.data.end);assert(get('result-status').textContent.includes('3 × 5'));checks.push('actual_classical_output_displayed_after_ready');}
if(standalone)checks.push('embedded_gzip_streams_decode_without_external_assets');
// Same physical rate for different components and for phase-local playback.
for(const id of [frameAware?'H_PHYSICAL':'H',upstream?'CX':'T']){api.showRow(api.manifest.components.find(r=>r.id===id));await waitFor(id);get('start').onclick();get('mode').value='physical';get('mode').onchange();get('play').onclick();frame(1000);frame(1100);assert(Math.abs(api.current-10)<1e-8);get('play').onclick();}
checks.push('fixed_physical_rate_independent_of_component_duration');
get('mode').value='keyframe';get('mode').onchange();const target=api.data.end/3;get('scrub').value=String(api.clock.displayAt(target));get('scrub').oninput();assert(Math.abs(api.current-target)<1e-6);assert(get('timebase-label').hidden);get('start').onclick();get('play').onclick();frame(2000);frame(7000);assert(Math.abs(api.current-api.clock.modelAt(5000))<1e-6);get('play').onclick();checks.push('keyframe_mapping_slider_and_multi_boundary_time_advance');
get('seek-time').value='123';get('seek').onclick();assert.equal(api.current,123);const beforeZoom=api.view.zoom;get('zoom-in').onclick();assert(api.view.zoom>beforeZoom);get('fit').onclick();assert.equal(api.view.zoom,1);checks.push('precise_seek_zoom_and_fit');
let checkedPaths=0,fallbacks=0;
get('path-style').value='xy';
for(const row of api.manifest.components){api.showRow(row);await waitFor(row.id);const moves=api.motion.moves;for(const a of [moves[0],moves[Math.floor(moves.length/2)],moves.at(-1)].filter(Boolean)){
 const route=api.motion.routeFor(a);if(route.fallback){fallbacks++;continue;}assert(route.passed&&route.minGap>=1-1e-8);
 for(const tr of a[4]){const path=route.paths.get(tr[0]);assert.deepEqual(Array.from(path[0]),[a[0],tr[1],tr[2]]);assert.deepEqual(Array.from(path.at(-1)),[a[1],tr[3],tr[4]]);for(let k=1;k<path.length;k++)assert(Math.abs(path[k][1]-path[k-1][1])<1e-8||Math.abs(path[k][2]-path[k-1][2])<1e-8);checkedPaths++;}
 api.setTime((a[0]+a[1])/2);assert(get('route-status').textContent.includes('检查通过'));assert(get('motion-detail').textContent.includes('→ B'));assert(descend(get('scene')).some(e=>e.tag==='polyline'));
 }}
checks.push('all_components_sampled_xy_routes_keep_endpoints_times_and_axis_segments','continuous_clearance_results_and_AB_speed_visible');

api.showRow(api.manifest.components.find(r=>r.id==='SE'));await waitFor('SE');
get('atom-size').value='4';get('atom-size').oninput();const glyphs=descend(get('scene')).filter(e=>'data-atom' in e.attrs);const xGlyph=glyphs.find(e=>e.attrs['data-role']==='x'),zGlyph=glyphs.find(e=>e.attrs['data-role']==='z'),dataGlyph=glyphs.find(e=>e.attrs['data-role']==='data');
assert(xGlyph.children.some(e=>e.attrs.fill==='var(--xanc)'));assert(zGlyph.children.some(e=>e.attrs.fill==='var(--zanc)'));assert(dataGlyph.children.some(e=>Math.abs(Number(e.attrs.r)-4*.65)<1e-8));assert(source.includes('value="100" selected'));checks.push('world_size_markers_distinct_X_Z_and_100us_per_second_default');
get('schedule-mode').value='all';get('schedule-mode').onchange();const lane=api.schedule.lanes[0],iv=lane.intervals[0],mid=(iv[0]+iv[1])/2;get('schedule').onclick({clientX:118+mid/api.data.end*(900-118-16),clientY:30});assert.equal(api.current,iv[0]);assert(get('schedule-detail').textContent.includes(lane.label));assert(get('device-live').textContent.includes('使用'));checks.push('resource_schedule_click_seeks_source_interval_and_live_dashboard');
get('back').onclick();assert(get('viewer-page').hidden);assert(!get('landing').hidden);document.querySelectorAll()[0].onclick();await waitFor(api.manifest.components[0].id);assert(!get('viewer-page').hidden);assert(get('landing').hidden);checks.push('component_directory_enter_return_and_reenter');
get('category-filter').value=api.manifest.components[0].category;get('category-filter').onchange();assert(document.querySelectorAll().filter(x=>!x.hidden).every(x=>x.dataset.category===get('category-filter').value));checks.push('landing_category_filter');
// All visible glyph dimensions and strokes inherit the same world transform.
api.showRow(api.manifest.components.find(r=>r.id==='SE'));await waitFor('SE');
const pickup=api.data.actions.find(a=>a[2]==='pickup'&&a[7]==='completed'),drop=api.data.actions.find(a=>a[2]==='drop'&&a[7]==='completed');
api.setTime((pickup[0]+pickup[1])/2);const visible=()=>descend(get('scene')),world=()=>visible().find(e=>'data-world-scale' in e.attrs);
const before=Number(world().attrs['data-world-scale']),radiusBefore=visible().find(e=>e.attrs['data-atom-glyph']==='true'&&e.tag==='circle').attrs.r;
get('zoom-out').onclick();const after=Number(world().attrs['data-world-scale']);assert(Math.abs(after/before-1/1.4)<1e-8);assert.equal(visible().find(e=>e.attrs['data-atom-glyph']==='true'&&e.tag==='circle').attrs.r,radiusBefore);assert(visible().some(e=>e.attrs['data-slm-trap']==='true'));assert(visible().some(e=>'data-aod-axis' in e.attrs));
get('scene').width=450;api.setTime(api.current);const narrowScale=api.screenScale;get('scene').width=900;api.setTime(api.current);assert(api.screenScale>=narrowScale);checks.push('single_world_transform_scales_atoms_traps_fields_gates_and_strokes');
for(const a of [pickup,drop]){for(const f of [.1,.5,.9]){const t=a[0]+(a[1]-a[0])*f;api.setTime(t);const ring=visible().find(e=>e.attrs['data-transfer']===a[2]);assert(ring);const slm=Number(ring.attrs['data-slm-weight']),aod=Number(ring.attrs['data-aod-weight']);assert(Math.abs(slm+aod-1)<1e-8);if(f===.5)assert(Math.abs(slm-.5)<1e-8);const state=api.stateAt(t),start=api.stateAt(a[0]);for(const i of a[3]){assert.equal(state[i].x,start[i].x);assert.equal(state[i].y,start[i].y);assert.equal(state[i].carrier,a[2]==='pickup'?'SLM':'AOD');}}api.setTime(a[1]);for(const i of a[3])assert.equal(api.stateAt(a[1])[i].carrier,a[2]==='pickup'?'AOD':'SLM');}
checks.push('pickup_drop_crossfade_stationary_positions_and_end_time_carrier_commit');
api.setTime((pickup[0]+pickup[1])/2);get('show-transfers').checked=false;get('show-transfers').onchange();assert(!visible().some(e=>'data-transfer' in e.attrs));get('show-traps').checked=false;get('show-traps').onchange();assert(!visible().some(e=>e.attrs['data-slm-trap']==='true'||'data-trap-ring' in e.attrs));get('show-aod').checked=false;get('show-aod').onchange();assert(!visible().some(e=>'data-aod-axis' in e.attrs));
get('preset-debug').onclick();assert.equal(get('scene').attrs['data-render-style'],'technical');assert(visible().some(e=>e.attrs['data-world-label']==='true'));get('preset-lab').onclick();assert.equal(get('scene').attrs['data-render-style'],'reference');assert(!get('show-glow').checked);assert(!get('show-trails').checked);assert(get('show-transfers').checked);assert(!get('show-labels').checked);checks.push('render_options_and_reference_debug_presets');
get('start').onclick();get('next-transfer').onclick();assert.equal(api.current,pickup[0]);checks.push('next_transfer_navigation');
api.showRow(api.manifest.components.find(r=>r.id==='SE'));await waitFor('SE');
assert(descend(get('scene')).some(e=>e.attrs['data-zone']==='compute'));assert(descend(get('scene')).some(e=>e.attrs['data-zone']==='measurement'));assert(get('scene').textContent.includes('Compute zone'));assert(descend(get('scene')).some(e=>e.attrs['data-axis-tick']==='x'));assert(descend(get('scene')).some(e=>e.attrs['data-axis-tick']==='y'));
const zones=context.window.COMPONENT_ZONES.SE;assert.equal(zones.compute_source_zone,'storage_entanglement');assert.deepEqual(Array.from(zones.compute),[null,null,0,1000]);
assert.equal(descend(get('scene')).filter(e=>e.attrs['data-atom-glyph']==='true'&&e.tag==='circle').length,api.data.atoms.length);
assert(!source.match(/id="show-glow"[^>]*checked/));assert(!source.match(/id="show-trails"[^>]*checked/));assert(source.includes('--compute-zone:#e3ecf3'));checks.push('reference_light_plot_compute_zone_from_device_white_grid_and_round_atoms');
api.showRow(api.manifest.components.find(r=>r.id==='CX'));await waitFor('CX');get('start').onclick();get('cz').onclick();
assert(descend(get('scene')).some(e=>e.attrs['data-zone']==='compute'&&e.attrs['data-cz-illumination']==='active'));assert(get('activity-detail').textContent.includes('原子静止'));assert(get('carrier-counts').textContent.includes('AOD'));
const heldPulse=api.data.actions.find(a=>a[0]===api.current&&a[6]==='CZ'),heldState=api.stateAt(api.current);assert.equal(heldPulse[5].length,9);for(const pair of heldPulse[5])assert.deepEqual(Array.from(pair,i=>heldState[i].carrier).sort(),['AOD','SLM']);
get('show-gates').checked=false;get('show-gates').onchange();assert(!descend(get('scene')).some(e=>e.attrs['data-cz-illumination']==='active'));get('show-gates').checked=true;get('show-gates').onchange();api.setTime(heldPulse[1]);assert(!descend(get('scene')).some(e=>e.attrs['data-cz-illumination']==='active'));checks.push('CZ_exact_interval_and_AOD_SLM_pairs');
get('start').onclick();get('next-transfer').onclick();const activePickup=api.data.actions.find(a=>a[0]===api.current&&a[2]==='pickup');assert(get('activity-detail').textContent.includes('当前速度下'));get('finish-action').onclick();assert.equal(api.current,activePickup[1]);checks.push('CZ_compute_zone_illumination_transfer_countdown_and_explicit_skip');
api.setTime((activePickup[0]+activePickup[1])/2);get('mode').value='physical';get('mode').onchange();get('speed').value='2';get('speed').onchange();assert(get('activity-detail').textContent.includes(String((pickup[1]-pickup[0])/2/100/2)+' 秒'));assert.equal(get('slm-transfer').textContent,'SLM 50%');assert.equal(get('aod-transfer').textContent,'AOD 50%');get('speed').value='1';get('speed').onchange();checks.push('transfer_weights_and_speed_change_countdown');
api.showRow(api.manifest.components.find(r=>r.id==='MEASURE_Z'));await waitFor('MEASURE_Z');assert.deepEqual(Array.from(context.window.COMPONENT_ZONES.MEASURE_Z.measurement),[null,null,1020,1220]);get('measure').onclick();for(const factor of [1.4,1/1.4]){factor>1?get('zoom-in').onclick():get('zoom-out').onclick();const all=descend(get('scene')),mz=all.find(e=>e.attrs['data-zone']==='measurement'),bg=all.find(e=>e.attrs['data-plot-background']==='true');assert.equal(mz.attrs.x,bg.attrs.x);assert.equal(mz.attrs.width,bg.attrs.width);}checks.push('measurement_zone_spans_viewport_x_at_multiple_zooms');
const result={passed:true,standalone,components:api.manifest.components.length,position_comparisons:comparisons,xy_paths_checked:checkedPaths,explicit_original_fallbacks:fallbacks,checks,scope:'projection and functional DOM shim; browser and user visual review pending'};
api.showRow(api.manifest.components.find(r=>r.id==='CX'));await waitFor('CX');
const atomGroup=i=>descend(get('scene')).find(e=>e.attrs['data-atom']===String(i)),brightness=i=>Number(atomGroup(i).attrs['data-atom-brightness']);
const capture=api.data.actions.find(a=>a[2]==='pickup'&&a[7]==='completed'),release=api.data.actions.find(a=>a[2]==='drop'&&a[7]==='completed'),atomIndex=capture[3][0];
get('show-transfers').checked=true;get('show-glow').checked=false;get('show-traps').checked=false;get('show-aod').checked=false;
for(const action of [capture,release]){let prior=null;for(const f of [0,.1,.5,.9,1]){api.setTime(action[0]+(action[1]-action[0])*f);const value=brightness(atomIndex);if(prior!==null)assert(action[2]==='pickup'?value>prior:value<prior);prior=value;const atom=atomGroup(atomIndex),core=atom.children.find(e=>'data-atom-glyph' in e.attrs),light=atom.children.find(e=>'data-atom-emission-core' in e.attrs);if(value>0){assert(light);assert.equal(light.attrs.cx,core.attrs.cx);assert.equal(light.attrs.cy,core.attrs.cy);assert(Math.abs(Number(light.attrs.opacity)-value*.96)<1e-8);}else assert(!light);}}
checks.push('atom_body_brightens_on_pickup_and_dims_on_drop_without_trap_effects');
const transport=api.data.actions.find(a=>a[2]==='move'&&a[3].includes(atomIndex));api.setTime((transport[0]+transport[1])/2);assert.equal(brightness(atomIndex),1);const flying=api.stateAt(api.current)[atomIndex],halo=atomGroup(atomIndex).children.find(e=>'data-atom-emission-halo' in e.attrs);assert.equal(Number(halo.attrs.cx),flying.x);assert.equal(Number(halo.attrs.cy),flying.y);
const held=api.data.actions.find(a=>a[6]==='CZ');api.setTime((held[0]+held[1])/2);for(const pair of held[5])for(const i of pair)assert.equal(brightness(i),api.stateAt(api.current)[i].carrier==='AOD'?1:0);checks.push('emission_follows_moving_atom_and_persists_during_stationary_AOD_CZ');
get('show-transfers').checked=false;get('show-transfers').onchange();assert(!descend(get('scene')).some(e=>'data-atom-emission-halo' in e.attrs));get('show-transfers').checked=true;get('show-transfers').onchange();assert.equal(brightness(atomIndex),1);checks.push('atom_brightness_toggle_and_role_colored_core_preserved');
fs.writeFileSync(path.join(out,upstream?'held-cz-upstream-viewer-checks.json':standalone?'atom-brightness-functional-checks.json':'atom-brightness-functional-checks-external.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
