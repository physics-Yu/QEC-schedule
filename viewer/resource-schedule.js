/* Device usage from immutable action intervals; no rescheduling. */
(function(root){
'use strict';
const LABELS={'aod:data':'AOD · data','aod:magic':'AOD · magic','slm:ports':'SLM 端口','rydberg:global':'Rydberg · CZ','readout:array':'读出阵列','activity:1q':'单比特门 · 活动','activity:reset':'复位 · 活动','activity:classical':'经典控制 · 活动','occupancy:aod:data':'AOD · data 承载','occupancy:aod:magic':'AOD · magic 承载'};
const ORDER=Object.keys(LABELS);
function union(intervals){const spans=[];for(const [a,b]of [...intervals].sort((a,b)=>a[0]-b[0])){if(b<=a)continue;const last=spans.at(-1);if(last&&a<=last[1])last[1]=Math.max(last[1],b);else spans.push([a,b]);}return spans;}
function create(value){
 const present=new Map(value.lanes.map(l=>[l.id,l]));
 const entries=[...ORDER,...value.lanes.map(l=>l.id).filter(id=>!ORDER.includes(id))].map(id=>present.get(id)||{id,kind:id.startsWith('activity:')?'activity':'declared_resources',intervals:[]});
 const lanes=entries.map(l=>({...l,label:LABELS[l.id]||l.id,spans:union(l.intervals)}));
 for(const l of lanes){l.duration=l.spans.reduce((sum,s)=>sum+s[1]-s[0],0);l.utilization=value.end?l.duration/value.end:0;l.maxSpan=l.intervals.reduce((v,x)=>Math.max(v,x[1]-x[0]),0);}
 function after(xs,t){let lo=0,hi=xs.length;while(lo<hi){const m=(lo+hi)>>>1;if(xs[m][0]<=t)lo=m+1;else hi=m;}return lo;}
 function active(t){return lanes.map(l=>({id:l.id,label:l.label,kind:l.kind,intervals:l.intervals.slice(after(l.intervals,t-l.maxSpan-1e-8),after(l.intervals,t)).filter(x=>t<x[1])}));}
 function range(t,mode,span,phase){if(mode==='all')return[0,value.end||1];if(mode==='phase'&&phase)return[phase.start_us,Math.max(phase.end_us,phase.start_us+1)];const size=Math.min(Number(span),value.end||1),start=Math.max(0,Math.min(value.end-size,t-size*.25));return[start,start+size];}
 return{lanes,active,range,source:value};
}
const api={create,union,LABELS};root.ResourceSchedule=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
