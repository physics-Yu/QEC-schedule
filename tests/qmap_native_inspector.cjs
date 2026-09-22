// Unit verification of sparse seeking; this is not browser or physical QA.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const path=require('path'),base=process.argv[2];
const data=JSON.parse(fs.readFileSync(path.join(base,'native-view-data.json'),'utf8'));
const context=new Proxy({}, {get:(o,k)=>o[k]||(o[k]=()=>{})});
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{id,checked:['show-slm','show-grid','interpolate'].includes(id),value:id==='speed'?'32':'0',textContent:id==='native-data'?JSON.stringify(data):'',innerHTML:'',setAttribute(){},getContext:()=>context,getBoundingClientRect:()=>({width:900,height:540}),focus(){},setPointerCapture(){}});return elements.get(id)}
const sandbox={document:{getElementById:element},window:{},devicePixelRatio:1,ResizeObserver:class{observe(){}},requestAnimationFrame:()=>{},console};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/neutral_atom_app/visualization/qmap_native_inspector.js','utf8'),sandbox);
const api=sandbox.window.NativeInspector,selected=[0,1,5000,512,511,513,Math.floor(data.ops.length/2),data.ops.length,...api.czIndices.filter((_,i)=>i%251===0)],expected=new Map();
let xy=data.initial.flat(),held=new Array(data.initial.length).fill(0),gates=0,cz=0;
const wanted=new Set(selected);
for(let i=0;i<=data.ops.length;i++){if(wanted.has(i))expected.set(i,{positions:xy.slice(),held:held.slice(),completedGates:gates,completedCZ:cz});if(i===data.ops.length)break;const [kind,line,values,ids]=data.ops[i];if(kind===1)for(const[q,x,y]of values){xy[q*2]=x;xy[q*2+1]=y}else if(kind===0||kind===2)for(const q of values)held[q]=kind===0?1:0;gates+=ids.length;cz+=kind===3?1:0}
for(const i of selected.reverse()){api.seek(i);const state=api.getState(),truth=expected.get(i);for(const key of Object.keys(truth))assert.deepStrictEqual(JSON.parse(JSON.stringify(state[key])),truth[key],`${key} mismatch at ${i}`)}
api.seek(data.ops.length);assert.equal(api.getState().completedGates,14998);assert.equal(api.getState().completedCZ,4999);assert(api.getState().held.every(v=>v===0));
element('cz-index').value='2500';element('cz-go').onclick();assert.equal(api.getState().completed,api.czIndices[2499]);assert.equal(api.getState().selected,2499);
element('gate-index').value='14998';element('gate-go').onclick();assert.equal(api.getState().completed,data.gates[14997][2]);
console.log(JSON.stringify({status:'passed',seek_checks:selected.length,atoms:data.initial.length,instructions:data.ops.length,final_gates:14998,cz_layers:4999,cz_jump:2500,last_gate_jump:true}));
