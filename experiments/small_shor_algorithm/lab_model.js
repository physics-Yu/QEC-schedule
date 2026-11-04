/* Experimental presentation model: physical loss and separate T2 exposure budgets. */
(function(root){
  'use strict';
  const core=typeof module!=='undefined'&&module.exports?require('./loss_time_model.js'):root.ShorLossTime;
  const DEFAULTS={...core.DEFAULTS,t2Slm:1000,t2Aod:1000,t2Enabled:true};
  const QUANTUM=new Set(['LocalU','Rotation','GlobalRY','CZPulse','CPhasePulse']);
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function exposure(trace){
    const rows=new Map(trace.initial.atoms.map(a=>[a.id,{id:a.id,windows:[],busy:[],holders:[{time:0,kind:a.holder.kind}],open:null}]));
    function close(row,end){if(row.open!==null){row.windows.push([row.open.start,end]);row.open=null;}}
    for(const step of trace.steps)for(const action of step.actions){
      const start=step.start_us,end=start+action.duration_us;
      for(const id of action.atoms){
        const row=rows.get(id);
        if(QUANTUM.has(action.kind)){
          if(row.open===null)row.open={start,last:end};
          row.open.last=Math.max(row.open.last,end);
          row.busy.push([start,end]);
        }else if(action.kind==='Measure'||action.kind==='Reset'){
          close(row,start);row.busy.push([start,end]);
        }
      }
      for(const atom of action.patch.atoms){
        const row=rows.get(atom.id),kind=atom.holder.kind;
        if(row.holders[row.holders.length-1].kind!==kind)row.holders.push({time:end,kind});
      }
    }
    const result=new Map();
    for(const row of rows.values()){
      if(row.open!==null)close(row,row.open.last);
      const points=[...new Set([0,trace.duration_us,...row.windows.flat(),...row.busy.flat(),...row.holders.map(h=>h.time)])].sort((a,b)=>a-b);
      const intervals=[];let holderIndex=0;
      for(let i=1;i<points.length;i++){
        const start=points[i-1],end=points[i],mid=(start+end)/2;
        if(end<=start)continue;
        while(holderIndex+1<row.holders.length&&row.holders[holderIndex+1].time<=mid)holderIndex++;
        if(!row.windows.some(([a,b])=>a<=mid&&mid<b)||row.busy.some(([a,b])=>a<=mid&&mid<b))continue;
        const kind=row.holders[holderIndex].kind;
        const previous=intervals[intervals.length-1];
        if(previous&&previous.end===start&&previous.kind===kind)previous.end=end;
        else intervals.push({start,end,kind});
      }
      result.set(row.id,intervals);
    }
    return result;
  }
  function zeroStatus(p){
    if(p.speed===0)return {status:'stopped',message:'速度为 0：非零距离移动无法完成。总时长为 ∞，不外推整条电路的 loss。',duration:Infinity};
    const missing=[['mass','原子质量'],['frequency','陷阱频率'],['width','有效阱宽']].filter(([key])=>p[key]===0).map(([,label])=>label);
    if(missing.length)return {status:'invalid',message:missing.join('、')+'为 0：当前束缚／搬运模型没有物理定义，暂停计算。',duration:null};
    return null;
  }
  function build(base,settings){
    const p={...DEFAULTS,...settings};
    for(const [key,value] of Object.entries(p))if(typeof value==='number'&&(!Number.isFinite(value)||value<0))throw Error('参数必须为非负有限数：'+key);
    const status=zeroStatus(p);if(status)return {...status,params:p,trace:null};
    const trace=core.retime(base,p),intervals=exposure(trace);
    const events=new Map(trace.initial.atoms.map(a=>[a.id,[]])),countEvents=[];
    for(const event of trace.noise_report.noise.loss.events)events.get(event.atom).push({...event,end:event.start_us+event.duration_us});
    for(const list of events.values())list.sort((a,b)=>a.end-b.end);
    for(const step of trace.steps)for(const action of step.actions){
      const source={Load:'load',Store:'store',Move:'move',CZPulse:'cz',CPhasePulse:'cp',Measure:'imaging',LocalU:'single',Rotation:'single',GlobalRY:'single',Reset:'reset'}[action.kind];
      if(source)countEvents.push({source,count:['cz','cp'].includes(source)?new Set(action.pairs.flat()).size:action.atoms.length,end:step.start_us+action.duration_us});
    }
    return {status:'ok',params:p,trace,intervals,events,countEvents,duration:trace.duration_us};
  }
  function at(model,time){
    if(model.status!=='ok')return null;
    const p=model.params,t=clamp(time,0,model.duration),atoms=[];
    const physical={load:0,store:0,move:0,cz:0,cp:0,imaging:0,single:0,reset:0};
    const decoherence={slm:0,aod:0};let allSurvive=1;
    for(const atom of model.trace.initial.atoms){
      const list=model.events.get(atom.id),contributions=Object.fromEntries(Object.keys(physical).map(k=>[k,0]));
      let survival=1;
      for(let i=0;i<list.length&&list[i].end<=t+1e-9;){
        let j=i+1;while(j<list.length&&list[j].end===list[i].end)j++;
        const hazards={},certain={};let h=0,n=0;
        for(let k=i;k<j;k++){
          const e=list[k],v=-Math.log(e.survival_probability);
          if(v===Infinity){certain[e.cause]=(certain[e.cause]||0)+1;n++;}
          else{hazards[e.cause]=(hazards[e.cause]||0)+v;h+=v;}
        }
        const loss=survival*(n?1:-Math.expm1(-h));
        for(const key of Object.keys(physical))contributions[key]+=loss*(n?(certain[key]||0)/n:h?(hazards[key]||0)/h:0);
        survival*=n?0:Math.exp(-h);i=j;
      }
      let coherence=1;const exposureUs={slm:0,aod:0},coherenceBy={slm:0,aod:0};
      for(const interval of model.intervals.get(atom.id)){
        const duration=Math.max(0,Math.min(t,interval.end)-interval.start);if(!duration)continue;
        exposureUs[interval.kind]+=duration;
        if(!p.t2Enabled)continue;
        const t2=(interval.kind==='aod'?p.t2Aod:p.t2Slm)*1000;
        const attenuation=t2===0?0:Math.exp(-duration/t2);
        coherenceBy[interval.kind]+=coherence*(1-attenuation);coherence*=attenuation;
      }
      for(const key of Object.keys(physical))physical[key]+=contributions[key];
      for(const key of Object.keys(decoherence))decoherence[key]+=coherenceBy[key];
      allSurvive*=survival;
      atoms.push({id:atom.id,loss:1-survival,coherenceLoss:1-coherence,composite:1-survival*coherence,
        exposureUs,physical:contributions,decoherence:coherenceBy});
    }
    const n=atoms.length,mean=key=>n?atoms.reduce((s,a)=>s+a[key],0)/n:0;
    const counts=Object.fromEntries(Object.keys(physical).map(k=>[k,0]));
    for(const event of model.countEvents)if(event.end<=t+1e-9)counts[event.source]+=event.count;
    return {time:t,atoms,physical,decoherence,counts,expectedLost:atoms.reduce((s,a)=>s+a.loss,0),
      meanLoss:mean('loss'),meanCoherenceLoss:mean('coherenceLoss'),meanComposite:mean('composite'),allSurvive};
  }
  const api={DEFAULTS,build,at,exposure,zeroStatus};root.ShorLabModel=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
