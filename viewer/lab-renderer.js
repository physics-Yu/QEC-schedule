/* Optical-platform schematic. All scene geometry shares one world transform. */
(function(root){
'use strict';
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
function transfer(kind,start,end,t){const p=end===start?1:clamp((t-start)/(end-start)),f=p*p*(3-2*p);return{progress:p,slm:kind==='pickup'?1-f:f,aod:kind==='pickup'?f:1-f,direction:kind==='pickup'?'SLM → AOD':'AOD → SLM'};}
function prepare(d,motion,regions){
 // Trap light is drawn on the current atom below. Past drop locations are
 // not persistent light sources once their atoms leave.
 return{traps:[],regions};
}
function draw({scene,node,d,model,state,active,motion,current,view,options,size,width,height,selected,onSelect}){
 scene.replaceChildren();scene.setAttribute('viewBox',`0 0 ${width} ${height}`);scene.setAttribute('data-render-style',options.style);
 const b=d.bounds.map((v,i)=>v+(i%2?45:-45)),margin=48,scale=view.zoom*Math.min((width-2*margin)/Math.max(30,b[1]-b[0]),(height-2*margin)/Math.max(30,b[3]-b[2]));
 const ox=width/2-((b[0]+b[1])/2+view.x)*scale,oy=height/2+((b[2]+b[3])/2+view.y)*scale;
 const defs=node('defs');scene.appendChild(defs);
 const atomLight=node('radialGradient',{id:'atom-light'});for(const[offset,color,opacity]of [['0%','#f8ffe7',1],['24%','#e2f4bc',.9],['55%','#83b579',.5],['100%','#83b579',0]])atomLight.appendChild(node('stop',{offset,'stop-color':color,'stop-opacity':opacity}));defs.appendChild(atomLight);
 const warmLight=node('radialGradient',{id:'aod-light'});for(const[offset,opacity]of [['0%',.6],['45%',.2],['100%',0]])warmLight.appendChild(node('stop',{offset,'stop-color':'#79a878','stop-opacity':opacity}));defs.appendChild(warmLight);
 const coldLight=node('radialGradient',{id:'slm-light'});for(const[offset,opacity]of [['0%',.5],['50%',.18],['100%',0]])coldLight.appendChild(node('stop',{offset,'stop-color':'#9acea1','stop-opacity':opacity}));defs.appendChild(coldLight);
 const clip=node('clipPath',{id:'plot-clip'});clip.appendChild(node('rect',{x:margin,y:margin,width:width-2*margin,height:height-2*margin}));defs.appendChild(clip);
 const plot=node('g',{'clip-path':'url(#plot-clip)'});scene.appendChild(plot);
 scene.appendChild(node('rect',{x:margin,y:margin,width:width-2*margin,height:height-2*margin,fill:'none',stroke:'#dce3e9','stroke-width':.7}));
 const world=node('g',{transform:`matrix(${scale} 0 0 ${-scale} ${ox} ${oy})`,'data-world-scale':scale});plot.appendChild(world);
 const add=(tag,attrs,label)=>{const e=node(tag,attrs,label);world.appendChild(e);return e;};
 const text=(x,y,label,color='var(--scene-text)',font=2.6)=>add('text',{transform:`translate(${x} ${y}) scale(1 -1)`,x:0,y:0,fill:color,style:`font-size:${font}px`,'data-world-label':'true'},label);
 const glow=options.glow&&options.style!=='technical',radius=size;
 const v=[(margin-ox)/scale,(width-margin-ox)/scale,(oy-height+margin)/scale,(oy-margin)/scale];
 const niceStep=span=>{const raw=span/6,p=Math.pow(10,Math.floor(Math.log10(raw))),n=raw/p;return (n<=1?1:n<=2?2:n<=5?5:10)*p;};
 const stepX=niceStep(v[1]-v[0]),stepY=niceStep(v[3]-v[2]),zoneLabels=[];
 add('rect',{x:v[0],y:v[2],width:v[1]-v[0],height:v[3]-v[2],fill:'var(--plot-empty)','data-plot-background':'true'});
 if(options.zones&&model.regions){for(const[id,label,color]of [['compute','Compute zone','var(--compute-zone)'],['measurement','Measurement zone','var(--measurement-zone)']]){const z=model.regions[id],left=Math.max(v[0],z[0]??v[0]),right=Math.min(v[1],z[1]??v[1]),bottom=Math.max(v[2],z[2]??v[2]),top=Math.min(v[3],z[3]??v[3]);if(right<=left||top<=bottom)continue;add('rect',{x:left,y:bottom,width:right-left,height:top-bottom,fill:id==='compute'&&options.gates&&active.some(a=>a[6]==='CZ')?'#edb6ad':color,'data-zone':id,'data-cz-illumination':id==='compute'&&options.gates&&active.some(a=>a[6]==='CZ')?'active':'idle'});zoneLabels.push([left+4,top-7,id==='measurement'?`${label} · ${d.readout_capacity===null?'并行读出无上限':d.readout_capacity+' 路读出'}`:(id==='compute'&&options.gates&&active.some(a=>a[6]==='CZ')?'Compute zone · CZ pulse':label)]);}}
 if(options.grid){
  for(let x=Math.ceil(v[0]/stepX)*stepX;x<=v[1];x+=stepX){add('line',{x1:x,x2:x,y1:v[2],y2:v[3],stroke:'var(--scene-grid)','stroke-width':.45,'data-grid':'x'});scene.appendChild(node('text',{x:ox+x*scale,y:height-margin+18,'text-anchor':'middle',style:'font-size:11px','data-axis-tick':'x'},Number(x.toFixed(4)).toString()));}
  for(let y=Math.ceil(v[2]/stepY)*stepY;y<=v[3];y+=stepY){add('line',{x1:v[0],x2:v[1],y1:y,y2:y,stroke:'var(--scene-grid)','stroke-width':.45,'data-grid':'y'});scene.appendChild(node('text',{x:margin-9,y:oy-y*scale+4,'text-anchor':'end',style:'font-size:11px','data-axis-tick':'y'},Number(y.toFixed(4)).toString()));}
  scene.appendChild(node('text',{x:width-margin,y:height-9,'text-anchor':'end',style:'font-size:10px'},'x / μm'));scene.appendChild(node('text',{x:margin,y:margin-15,style:'font-size:10px'},'y / μm'));
 }
 for(const [x,y,label]of zoneLabels)text(x,y,label,'var(--scene-muted)',5);
 const busy=new Map();for(const a of active)for(const i of (a[6]==='CZ'?a[5].flat():a[3])){const old=busy.get(i);if(!old||['pickup','drop','move','measure'].includes(a[2]))busy.set(i,a);}
 if(options.aod){const groups=new Map();state.forEach((a,i)=>{const kind=busy.get(i)?.[2];if(a.carrier==='AOD'||['pickup','drop'].includes(kind)){const key=d.atoms[i][5];if(!groups.has(key))groups.set(key,[]);const act=busy.get(i),gain=['pickup','drop'].includes(kind)&&options.transfers?transfer(kind,act[0],act[1],current).aod:1;groups.get(key).push({...a,gain});}});for(const[group,ps]of groups){const xs=[...new Set(ps.map(a=>a.x))],ys=[...new Set(ps.map(a=>a.y))],x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);for(const x of xs)add('line',{x1:x,x2:x,y1:v[2],y2:v[3],stroke:'var(--aod-light)','stroke-width':.32,'stroke-dasharray':'2 2',opacity:.04+.2*Math.max(...ps.filter(p=>p.x===x).map(p=>p.gain)),'data-aod-axis':'column'});for(const y of ys)add('line',{x1:v[0],x2:v[1],y1:y,y2:y,stroke:'var(--aod-light)','stroke-width':.36,'stroke-dasharray':'2 2',opacity:.08+.5*Math.max(...ps.filter(p=>p.y===y).map(p=>p.gain)),'data-aod-axis':'row'});if(options.labels)text(x0,y1+6,`AOD ${group}`,'var(--aod-light)');}}
 for(const a of active){
  if(a[2]==='move'&&options.trails)for(const tr of a[4]){const route=options.path==='original'?null:motion.routeFor(a),path=route?route.paths.get(tr[0]):[[a[0],tr[1],tr[2]],[a[1],tr[3],tr[4]]];add('polyline',{points:path.map(p=>`${p[1]},${p[2]}`).join(' '),fill:'none',stroke:route?.fallback?'var(--gate)':'var(--aod-light)','stroke-width':.28,opacity:.55,'stroke-dasharray':'1.4 1.1','data-route':route?.type||'original'});if(options.labels&&tr[0]===(selected??a[4][0][0])){for(const[label,x,y]of[['A',tr[1],tr[2]],['B',tr[3],tr[4]]]){add('circle',{cx:x,cy:y,r:1.1,fill:'none',stroke:'var(--aod-light)','stroke-width':.22});text(x+2,y+2,label,'var(--aod-light)');}}}
  if(options.gates)for(const pair of a[5]){const p=state[pair[0]],q=state[pair[1]],f=clamp((current-a[0])/Math.max(1e-9,a[1]-a[0])),strength=.35+.65*Math.sin(Math.PI*f);if(glow)add('line',{x1:p.x,y1:p.y,x2:q.x,y2:q.y,stroke:'var(--gate)','stroke-width':radius*2.8,opacity:.08+.15*strength,'stroke-linecap':'round'});add('line',{x1:p.x,y1:p.y,x2:q.x,y2:q.y,stroke:'var(--gate)','stroke-width':.55,opacity:.8,'stroke-linecap':'round','data-cz':'true'});if(options.labels)text((p.x+q.x)/2+2,(p.y+q.y)/2+2,'CZ','var(--gate)');}
 }
 state.forEach((a,i)=>{
  const act=busy.get(i),kind=act?.[2],role=/\/x\d+$/.test(a.site)?'x':/\/z\d+$/.test(a.site)?'z':/\/d\d+$/.test(a.site)?'data':'probe',color=role==='x'?'var(--xanc)':role==='z'?'var(--zanc)':role==='data'?'var(--data)':'var(--anc)';
  const g=add('g',{'data-atom':i,'data-role':role,'aria-label':a.qubit}),hasTransfer=['pickup','drop'].includes(kind),f=hasTransfer?transfer(kind,act[0],act[1],current):null,slm=Number(a.carrier==='SLM'),aod=Number(a.carrier==='AOD'),emission=options.transfers?(f?f.aod:aod):0;
  g.setAttribute('data-atom-brightness',emission);g.setAttribute('data-carrier',a.carrier);
  if(options.traps){
   if(glow){g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*3.6,fill:'url(#slm-light)',opacity:slm,'data-trap-field':'SLM'}));g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*(f?3.8-f.aod:2.8),fill:'url(#aod-light)',opacity:aod,'data-trap-field':'AOD'}));}
   g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*1.06,fill:'var(--slm-light)',stroke:'none','stroke-width':.18,opacity:slm,'data-trap-ring':'SLM'}));
   g.appendChild(node('rect',{x:a.x-radius*1.12,y:a.y-radius*1.12,width:radius*2.24,height:radius*2.24,rx:radius*1.12,fill:'none',stroke:'var(--aod-light)','stroke-width':.26,opacity:aod,'data-trap-ring':'AOD'}));
  }
  if(hasTransfer&&options.transfers){g.setAttribute('data-transfer',kind);g.setAttribute('data-progress',f.progress);g.setAttribute('data-slm-weight',f.slm);g.setAttribute('data-aod-weight',f.aod);}
  if(act&&options.gates&&['gate','measure','reset'].includes(kind)){g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*1.8,fill:'none',stroke:kind==='measure'?'var(--measure)':'var(--gate)','stroke-width':.38,opacity:.8,'data-operation-ring':kind}));}
  // Emission represents AOD occupancy, including a stationary hold during CZ.
  // Every glow element is centred on the atom and inherits the world transform.
  if(emission>0)g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*2,fill:'url(#atom-light)',opacity:emission*.85,'data-atom-emission-halo':'true'}));
  const core=radius*.65;
  g.appendChild(node('circle',{cx:a.x,cy:a.y,r:core,fill:color,stroke:'none','data-atom-glyph':'true'}));
  if(emission>0){g.appendChild(node('circle',{cx:a.x,cy:a.y,r:core*.8,fill:'#e7f6c6',opacity:emission*.96,'data-atom-emission-core':'true'}));g.appendChild(node('circle',{cx:a.x,cy:a.y,r:core*.32,fill:'#fbfff3',opacity:emission*.92,'data-atom-emission-center':'true'}));}
  if(selected===i)g.appendChild(node('circle',{cx:a.x,cy:a.y,r:radius*2,fill:'none',stroke:'var(--scene-text)','stroke-width':.3,'stroke-dasharray':'1 .65'}));
  const hit=node('circle',{cx:a.x,cy:a.y,r:Math.max(radius,6/scale),fill:'transparent'});hit.onclick=()=>onSelect(i);g.appendChild(hit);
  if(options.labels)text(a.x+radius*1.8,a.y+radius,a.qubit.split('/').at(-1)+(a.site!==a.qubit?'→'+a.site.split('/').at(-1):''),'var(--scene-text)',2.4);
 });
 if(options.labels)for(const p of d.patches||[])text(p[1],p[2]-3,p[0],'var(--scene-muted)',3);
 // Fixed screen text is UI chrome; the physical scale bar has a world-space length.
 if(options.scale){const length=10,x=margin+10,y=height-margin-12;scene.appendChild(node('line',{x1:x,x2:x+length*scale,y1:y,y2:y,stroke:'var(--scene-muted)','stroke-width':1}));scene.appendChild(node('text',{x,y:y-7,fill:'var(--scene-muted)',style:'font-size:10px'},'10 μm'));}
 return{scale,world};
}
const api={prepare,draw,transfer};root.LabRenderer=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
