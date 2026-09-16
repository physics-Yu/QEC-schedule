/* Pure circuit presets and workspace classification; no transport or API effects. */
(()=>{'use strict';
const q=i=>'Q'+String(i).padStart(3,'0');
function circuitPreset(kind,n){
 if(!Number.isInteger(n)||n<1||n>128)throw Error('原子数应为 1–128。');
 const gates=[];
 const add=(type,ids,column)=>gates.push({id:'G'+String(gates.length).padStart(3,'0'),gate_type:type,qubit_ids:ids.map(q),parameters:[],column});
 if(kind==='empty')return gates;
 if(kind==='parallel1q'||kind==='rotations')for(let i=0;i<n;i++)add(kind==='parallel1q'?'H':'T',[i],0);
 else if(kind==='ghz'){
  add('H',[0],0);
  // CX(control,target) = H(target) CZ(control,target) H(target).
  for(let i=1;i<n;i++){add('H',[i],3*i-2);add('CZ',[0,i],3*i-1);add('H',[i],3*i);}
 }else if(kind==='chain'){
  for(let i=1;i<n;i++)add('CZ',[i-1,i],i-1);
 }else if(kind==='mixed'){
  add('H',[0],0);if(n>1)add('CZ',[0,1],1);add('T',[0],2);
 }else if(kind==='nonuniform_pairs'){
  if(n<6)throw Error('非均匀配对示例需要至少 6 个原子；请先调整原子数。');
  for(const pair of [[0,1],[2,4],[3,5]])add('CZ',pair,0);
 }else throw Error('未知电路示例。');
 return gates;
}
function newCustom(config){
 if(!config||config.schema!=='atom-studio-catalog/v1')throw Error('需要有效的工作台配置文件。');
 const preset=config.algorithms.find(a=>a.id===config.default_algorithm);
 if(!preset)throw Error('默认算法不在通用目录中。');
 const value=JSON.parse(JSON.stringify(config.workspace_defaults));
 value.compilation={strategy:'legacy',implementation:preset.id,...config.compilation_defaults,...preset.defaults};
 value.gates=circuitPreset(config.default_circuit,value.atom_count);
 return value;
}
const model={circuitPreset,newCustom};
if(typeof module!=='undefined')module.exports=model;
else window.AtomStudioModel=model;
})();
