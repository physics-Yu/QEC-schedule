// DOM logic checks, not browser rendering or visual acceptance.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=process.argv[2],html=fs.readFileSync(path,'utf8');
const payload=html.match(/<script id="hierarchyPayload" type="application\/json">([\s\S]*?)<\/script>/)[1],script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element{constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.events={};this.style={};this.value='';this._text='';}set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;this._text='';}setAttribute(k,v){this.attrs[k]=String(v);}addEventListener(k,fn){this.events[k]=fn;}}
const es=new Map();for(const m of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g))es.set(m[3],new Element(m[1]));
const get=id=>{assert.ok(es.has(id),'Missing HTML #'+id);return es.get(id);};get('hierarchyPayload').textContent=payload;
const ctx={document:{getElementById:get,createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)},window:{}};
vm.createContext(ctx);vm.runInContext(script,ctx,{timeout:10000});
const api=ctx.window.naHierarchy,v=api.data.values,d=v.logical_dag,checks=[],before=JSON.stringify(api.data);
for(const e of d.edges)assert.ok(api.depth.get(e.source)<api.depth.get(e.target));checks.push('every_dependency_points_forward');
assert.equal(get('hMap').children.filter(e=>e.attrs['data-atom-id']).length,v.initial_state.atoms.length);checks.push('all_initial_atom_identities_rendered');
assert.equal(get('hMap').children.filter(e=>e.attrs['data-patch-id']).length,Object.keys(v.patch_placement.placements).length);checks.push('all_actual_patch_placements_rendered');
const last=d.nodes[d.nodes.length-1];api.selectNode(last.id);assert.ok(get('hSelection').textContent.includes(last.id));assert.equal(JSON.parse(get('hRaw').textContent).id,last.id);assert.ok(api.firstDepth<=api.depth.get(last.id)&&api.firstDepth+8>api.depth.get(last.id));checks.push('whole_graph_searchable_beyond_window');
get('hQuery').value='__not_a_node__';get('hQuery').events.input();assert.equal(get('hMatches').children.length,1);checks.push('node_search_filters');
const p=Object.keys(v.patch_placement.placements)[0];api.selectPatch(p);assert.equal(get('hPlacementStage').hidden,false);const detail=JSON.parse(get('hRaw').textContent);assert.equal(JSON.stringify(detail.placement),JSON.stringify(v.patch_placement.placements[p]));checks.push('patch_inspector_uses_actual_mapping');
assert.equal(JSON.stringify(api.data),before);checks.push('interaction_does_not_mutate_artifacts');
if(!v.atom){assert.ok(get('hPipeline').textContent.includes('原子动作 · 待接入'));assert.ok(get('hScope').textContent.includes('尚未接入'));checks.push('partial_stage_not_execution');}
if(v.physical_dag_bundle){
 const pb=v.physical_dag_bundle,staticNode=d.nodes.find(n=>pb.instances[n.id].implementation_kind==='static_physical_dag');
 api.selectNode(staticNode.id);get('hPhysical').onclick();assert.equal(get('hPhysicalStage').hidden,false);assert.ok(get('hPhysicalDag').children.some(e=>e.attrs['data-physical-id']));
 const rendered=JSON.parse(get('hRaw').textContent);assert.equal(rendered.instance.logical_node_id,staticNode.id);checks.push('physical_template_linked_to_exact_logical_instance');
 const adaptive=d.nodes.find(n=>pb.instances[n.id].implementation_kind==='adaptive_factory_protocol');
 if(adaptive){api.selectNode(adaptive.id);get('hPhysical').onclick();assert.ok(get('hPhysicalDag').textContent.includes('自适应工厂协议'));assert.equal(get('hPhysicalDag').children.filter(e=>e.attrs['data-physical-id']).length,0);checks.push('adaptive_factory_not_replaced_by_fake_gate');}
}
assert.equal(JSON.stringify(api.data),before);
console.log(JSON.stringify({path,passed:true,scope:'DOM logic only; no browser/visual acceptance',checks,logical_nodes:d.nodes.length,atoms:v.initial_state.atoms.length},null,2));
