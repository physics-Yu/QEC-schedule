/* Display-only endpoints, clocks and rectilinear interpolation. No compiler imports. */
(function(root){
'use strict';
const EPS=1e-8, clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
function upper(xs,x,key=v=>v){let lo=0,hi=xs.length;while(lo<hi){const m=(lo+hi)>>>1;if(key(xs[m])<=x)lo=m+1;else hi=m;}return lo;}
function mix(a,b,f){return[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];}
function distanceOnSegment(a,b,c,d){const x=a[0]-c[0],y=a[1]-c[1],vx=b[0]-a[0]-d[0]+c[0],vy=b[1]-a[1]-d[1]+c[1];const q=vx*vx+vy*vy,f=q?clamp(-(x*vx+y*vy)/q,0,1):0;return Math.hypot(x+vx*f,y+vy*f);}
function samplePath(path,t){if(t<=path[0][0])return path[0].slice(1);let i=upper(path,t,p=>p[0])-1;if(i>=path.length-1)return path.at(-1).slice(1);const a=path[i],b=path[i+1];return mix(a.slice(1),b.slice(1),(t-a[0])/(b[0]-a[0]));}
function create(d,{clearance=1}={}){
 const tracks=d.atoms.map(()=>[]),moves=[],byAction=new Map();
 for(const a of d.actions)if(a[7]==='completed'&&a[2]==='move'){
  moves.push(a);for(const m of a[4])tracks[m[0]].push({a,m});
 }
 function sourcePoint(i,t){const tr=tracks[i],j=upper(tr,t,v=>v.a[0])-1;if(j<0)return d.atoms[i].slice(2,4);const {a,m}=tr[j];return mix(m.slice(1,3),m.slice(3,5),a[1]===a[0]?1:clamp((t-a[0])/(a[1]-a[0]),0,1));}
 // Overlapping batches must be considered together, including another AOD.
 const clusters=[];
 for(const a of moves){let c=clusters.at(-1);if(!c||a[0]>=c.end-EPS){c={start:a[0],end:a[1],actions:[],cache:null};clusters.push(c);}c.end=Math.max(c.end,a[1]);c.actions.push(a);byAction.set(a,c);}
 function candidate(a,type,n=1,offset=0){
  const positions=a[4].map(m=>[m.slice(1,3)]),stages=[];
  const add=ps=>{let length=0;ps.forEach((p,i)=>{const old=positions[i].at(-1);length=Math.max(length,Math.abs(old[0]-p[0])+Math.abs(old[1]-p[1]));positions[i].push(p);});stages.push(length);};
  if(type==='corridor-x'){add(a[4].map(m=>[m[1]+offset,m[2]]));add(a[4].map(m=>[m[1]+offset,m[4]]));add(a[4].map(m=>m.slice(3,5)));}
  else if(type==='corridor-y'){add(a[4].map(m=>[m[1],m[2]+offset]));add(a[4].map(m=>[m[3],m[2]+offset]));add(a[4].map(m=>m.slice(3,5)));}
  else for(let k=1;k<=n;k++){
   const before=(k-1)/n,after=k/n;
   if(type==='xy'){add(a[4].map(m=>[m[1]+(m[3]-m[1])*after,m[2]+(m[4]-m[2])*before]));add(a[4].map(m=>[m[1]+(m[3]-m[1])*after,m[2]+(m[4]-m[2])*after]));}
   else {add(a[4].map(m=>[m[1]+(m[3]-m[1])*before,m[2]+(m[4]-m[2])*after]));add(a[4].map(m=>[m[1]+(m[3]-m[1])*after,m[2]+(m[4]-m[2])*after]));}
  }
  const total=stages.reduce((a,b)=>a+b,0),paths=new Map();
  positions.forEach((ps,i)=>{let length=0;const path=[[a[0],...ps[0]]];stages.forEach((s,j)=>{length+=s;if(s>EPS)path.push([a[0]+(a[1]-a[0])*length/total,...ps[j+1]]);});if(path.length===1)path.push([a[1],...ps.at(-1)]);path.at(-1)[0]=a[1];paths.set(a[4][i][0],path);});
  return{paths,type,subdivisions:n,length:total,offset};
 }
 function inspect(c,plans){
  const paths=new Map(),cuts=new Set([c.start,c.end]);
  for(const p of plans)for(const[i,path]of p.paths){if(!paths.has(i))paths.set(i,[]);paths.get(i).push(path);for(const k of path)cuts.add(k[0]);}
  const times=[...cuts].sort((a,b)=>a-b),ids=[...paths.keys()];let min=Infinity;
  function point(i,t){for(const path of paths.get(i)||[])if(t>=path[0][0]-EPS&&t<=path.at(-1)[0]+EPS)return samplePath(path,t);return sourcePoint(i,t);}
  for(let k=1;k<times.length;k++){
   const start=times[k-1],end=times[k],p0=d.atoms.map((_,i)=>point(i,start)),p1=d.atoms.map((_,i)=>point(i,end));
   for(const i of ids)for(let j=0;j<d.atoms.length;j++){
    if(i===j||(paths.has(j)&&j<i))continue;
    const gap=distanceOnSegment(p0[i],p1[i],p0[j],p1[j]);min=Math.min(min,gap);
    if(gap<clearance-EPS)return{passed:false,minGap:gap};
   }
  }
  return{passed:true,minGap:min};
 }
 function planCluster(c){
  if(c.cache)return c.cache;
  const choices=[['xy',1,0],['yx',1,0]];
  for(const offset of [2.5,-2.5,5,-5,10,-10,20,-20,40,-40])for(const axis of ['corridor-x','corridor-y'])choices.push([axis,1,offset]);
  // A corridor may sit just before the destination row/column, not only near A.
  // These are shared batch offsets; all atoms still move synchronously.
  const first=c.actions[0][4][0],dx=first[3]-first[1],dy=first[4]-first[2];
  for(const gap of [2.5,-2.5,5,-5,10,-10]){
   choices.push(['corridor-x',1,dx+gap],['corridor-y',1,dy+gap]);
   choices.push(['corridor-x',1,dx/2+gap],['corridor-y',1,dy/2+gap]);
  }
  for(const n of [2,4,8,16,32,64,128])for(const axis of ['xy','yx'])choices.push([axis,n,0]);
  let attempts=0;
  for(const [type,n,offset] of choices){
   const plans=c.actions.map(a=>candidate(a,type,n,offset)),check=inspect(c,plans);attempts++;
   if(check.passed){c.cache={plans,check,attempts,fallback:false};return c.cache;}
  }
  // Never draw an unchecked alternative as a safe path. Retain original recording.
  const plans=c.actions.map(a=>({type:'original',subdivisions:0,paths:new Map(a[4].map(m=>[m[0],[[a[0],m[1],m[2]],[a[1],m[3],m[4]]]]))}));
  c.cache={plans,check:inspect(c,plans),attempts,fallback:true};return c.cache;
 }
 function routeFor(a){const c=byAction.get(a);if(!c)return null;const result=planCluster(c);return{...result.plans[c.actions.indexOf(a)],...result.check,fallback:result.fallback,attempts:result.attempts,clearance};}
 function point(i,t,style='xy'){
  if(style==='original')return sourcePoint(i,t);
  const j=upper(tracks[i],t,v=>v.a[0])-1;if(j<0)return d.atoms[i].slice(2,4);
  const a=tracks[i][j].a;if(t>=a[1])return tracks[i][j].m.slice(3,5);
  return samplePath(routeFor(a).paths.get(i),t);
 }
 return{point,sourcePoint,routeFor,clusters,clearance,moves};
}
function timeline(d){
 const cuts=[...new Set([0,d.end,...d.actions.flatMap(a=>[a[0],a[1]])])].sort((a,b)=>a-b),segments=[];let displayEnd=0;
 for(let i=1;i<cuts.length;i++){const start=cuts[i-1],end=cuts[i];if(end-start<EPS)continue;const ms=clamp((end-start)*4,650,1600);segments.push({start,end,displayStart:displayEnd,displayEnd:displayEnd+ms});displayEnd+=ms;}
 function transform(t,from,to){if(!segments.length)return 0;const i=clamp(upper(segments,t,s=>s[from])-1,0,segments.length-1),s=segments[i];const ends={start:'end',displayStart:'displayEnd'};return s[to]+clamp((t-s[from])/(s[ends[from]]-s[from]),0,1)*(s[ends[to]]-s[to]);}
 return{cuts,segments,displayEnd,displayAt:t=>transform(t,'start','displayStart'),modelAt:t=>transform(t,'displayStart','start')};
}
function advance(t,elapsedMs,{mode='keyframe',speed=1,usPerSecond=10000,stop,clock}){return Math.min(stop,mode==='physical'?t+Math.max(0,elapsedMs)*speed*usPerSecond/1000:clock.modelAt(clock.displayAt(t)+Math.max(0,elapsedMs)*speed));}
const api={create,timeline,advance,samplePath,distanceOnSegment};root.MotionPreview=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
