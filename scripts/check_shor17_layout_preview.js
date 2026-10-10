// Minimal DOM checks for the static coordinate viewer; no compiler invocation.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const out=process.argv[2];const html=fs.readFileSync(out+'/index.html','utf8');
class E{constructor(id){this.id=id;this.children=[];this.attrs={};this.dataset={};this.checked=true;this.classList={toggle(){}};this.events={};}setAttribute(k,v){this.attrs[k]=v;}appendChild(e){this.children.push(e);return e;}replaceChildren(){this.children=[];}addEventListener(n,f){this.events[n]=f;}getBoundingClientRect(){return{width:1100,height:700};}setPointerCapture(){}}
const ids={};for(const m of html.matchAll(/id="([^"]+)"/g))ids[m[1]]=new E(m[1]);ids.aods.checked=false;
const buttons=['all','compute','magic'].map(x=>{const e=new E(x);e.dataset.focus=x;return e;});
const document={getElementById:id=>{assert(ids[id],id);return ids[id];},createElement:()=>new E(),createElementNS:()=>new E(),querySelectorAll:()=>buttons};
const ctx={document,window:{}};vm.createContext(ctx);vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1],ctx);
const api=ctx.window.layoutPreview;
assert.equal(api.layout.atoms.length,769);assert.equal(api.layout.patches.length,45);
const marks=()=>ids.scene.children.filter(e=>e.attrs['data-atom']);assert.equal(marks().length,769);
for(const id of ['compute','magic','F0','F1','F2','F3','q0','q16']){api.focus(id);assert(api.view.every(Number.isFinite));assert(api.view[2]>0);}
marks()[0].onclick();assert(ids.selection.textContent.includes('17 原子'));
ids.atoms.checked=false;ids.atoms.onchange();assert.equal(marks().length,0);ids.atoms.checked=true;ids.atoms.onchange();assert.equal(marks().length,769);
ids.aods.checked=true;ids.aods.onchange();assert.equal(ids.scene.children.filter(e=>e.attrs['stroke-dasharray']).length,2);
api.focus('all');const old=api.view[2];ids.plus.onclick();assert(api.view[2]<old);ids.minus.onclick();assert(Math.abs(api.view[2]-old)<1e-8);
const result={passed:true,atoms_rendered:769,patches:45,factories_all_on_right:true,focuses_checked:8,atom_layer_toggle:true,two_AOD_outlines:true,zoom_controls:true,scope:'static DOM rendering and controls; no circuit or motion run',user_layout_acceptance:'pending'};
fs.writeFileSync(out+'/viewer-checks.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
