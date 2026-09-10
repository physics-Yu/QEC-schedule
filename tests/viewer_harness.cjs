// DOM/Canvas doubles for the component contract. Real browser checks are separate.
const vm=require('node:vm'),assert=require('node:assert/strict');
module.exports=function createHarness(html){
 const texts=[],arcs=[];
 const ctx=new Proxy({measureText:t=>({width:t.length*6}),fillText:t=>texts.push(t),arc:(...a)=>arcs.push(a)}, {get:(o,k)=>o[k]??(()=>{})});
 class Element{
  constructor(id,root){this.id=id;this.root=root;this.owned=[];this.listeners={};this.attrs={};this.style={};this.children={};this.classList={add(){},remove(){}};
   this.value=({mode:'keyframe',labels:'focus',speed:'1'})[id]||'';this.checked=['effects','aod','slm','grid','planned-path','zones'].includes(id);}
  set innerHTML(v){this.html=v;for(const id of this.owned)this.root.nodes.delete(id);this.owned=[];for(const m of v.matchAll(/id="([^"]+)"/g)){this.root.nodes.set(m[1],new Element(m[1],this.root));this.owned.push(m[1]);}}
  get innerHTML(){return this.html||'';}
  setAttribute(k,v){this.attrs[k]=v;}
  querySelector(s){return this.children[s]??=new Element(s,this.root);}
  addEventListener(k,f){this.listeners[k]=f;}
  getBoundingClientRect(){return {left:0,top:0,width:900,height:650};}
  getContext(){return ctx;}
  setPointerCapture(){} releasePointerCapture(){}
 }
 class Root extends Element{
  constructor(){super('root',null);this.root=this;this.nodes=new Map();}
  getElementById(id){assert(this.nodes.has(id),`Missing DOM id: ${id}`);return this.nodes.get(id);}
 }
 class Container{attachShadow(){return this.shadowRoot=new Root();}}
 const container=new Container();const sandbox={document:{hidden:false,listeners:new Set(),addEventListener(k,f){this[k]=f;this.listeners.add(f);},removeEventListener(k,f){this.listeners.delete(f);},getElementById(id){assert.equal(id,'atom-viewer');return container;}},window:{devicePixelRatio:2},ResizeObserver:class{observe(){} disconnect(){}},requestAnimationFrame(){return 1},cancelAnimationFrame(){},console,newContainer:()=>new Container()};
 vm.createContext(sandbox);vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1],sandbox);
 return {sandbox,texts,arcs,nodes:container.shadowRoot.nodes,get:code=>vm.runInContext(`with(viewer.debug){${code}}`,sandbox),el:id=>container.shadowRoot.getElementById(id)};
};
