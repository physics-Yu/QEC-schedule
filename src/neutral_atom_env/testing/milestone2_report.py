"""M2 acceptance artifacts built from actual multi-plan execution."""
from pathlib import Path
import html
import json
from math import isclose
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.replay.serializer import canonical_json, primitive
from .milestone1_report import animation, timeline
from .renderer import render_layout, render_dag
from .theme import VisualTheme
from .artifacts import page


EXPECTED={
    'repeat':(624.6,468.6,112,112,2),
    'switch_partner':(664.6,488.6,132,132,2),
    'three_gate':(1116.9,890.9,258,218,3),
    'join':(1076.9,900.9,238,198,3),
}


def build_report(root='artifacts/milestone2'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    index=root/'index.html'
    index.write_text(page('Milestone 2','<h1>本轮验收生成中</h1>'),encoding='utf-8')
    theme=VisualTheme.load();results=[];sections=[]
    try:
        for name in (*EXPECTED,'unsupported'):
            directory=root/name;directory.mkdir(exist_ok=True)
            state=make_circuit_state(name);snapshots=[state.snapshot()]
            result=EagerScheduler(state).run(lambda s,e:snapshots.append(s.snapshot()))
            metrics=state.metrics()
            if name in EXPECTED:
                wall,logical,aod_distance,atom_distance,count=EXPECTED[name]
                assert result.status=='completed'
                for key,value in [('episode_wall_time_us',wall),('logical_completion_elapsed_us',logical),
                                  ('total_aod_distance_um',aod_distance),('total_atom_distance_um',atom_distance),
                                  ('completed_plan_count',count),('completed_gate_count',count)]:
                    assert isclose(metrics[key],value),(name,key,metrics[key],value)
                assert state.placement.atom_to_holder==make_circuit_state(name).placement.atom_to_holder
                assert not state.active_plan and not state.reservations and not state.placement.mobile_occupancy
            else:
                assert result.status=='stalled' and snapshots==[state.snapshot()]
                assert result.diagnostics['candidate_failures'][0]['violation']['code']=='STATIC_PARTNER_REQUIRED'
            trace=[json.loads(r) for r in state.trace.records]
            plans=[r['event']['plan'] for r in trace if r['event']['event_type']=='plan_started']
            for filename,value in [('plans.json',plans),('metrics.json',metrics),('snapshots.json',[json.loads(s) for s in snapshots]),
                                   ('diagnostics.json',result.diagnostics),('result.json',primitive(result))]:
                (directory/filename).write_text(canonical_json(value),encoding='utf-8')
            (directory/'initial.json').write_text(snapshots[0],encoding='utf-8')
            (directory/'final.json').write_text(snapshots[-1],encoding='utf-8')
            state.trace.write(directory/'trace.jsonl')
            cards='';links=''
            if plans:
                animation(snapshots,None,directory/'animation.html',theme)
                timeline(trace,directory/'timeline.png',theme)
                links=f'<a href="{name}/animation.html">交互回放</a><a href="{name}/plans.json">全部计划</a>'
                keys=[(0,'Initial')]+[(i,r['event']['plan_id']+' · '+r['label']) for i,r in enumerate(trace,1)
                     if r['event']['event_type']=='operation_started' and r.get('operation_type')=='entangling_pulse']
                keys.append((len(snapshots)-1,'Final offload'))
                for i,label in keys:
                    render_layout(snapshots[i],directory/f'frame_{i}.png',theme,show_aod=True,show_labels=True)
                    render_dag(snapshots[i],directory/f'dag_{i}.svg',theme)
                    cards+=f'<div class="card"><header>{html.escape(label)} · {json.loads(snapshots[i])["time_us"]:g} μs</header><img src="{name}/frame_{i}.png"><img src="{name}/dag_{i}.svg"></div>'
                cards=f'<details><summary>时间占用图</summary><img src="{name}/timeline.png"></details><details><summary>实际事件关键帧 / DAG</summary><div class="grid">{cards}</div></details>'
            from neutral_atom_env.visualization.summary import summarize_trace,summary_html
            summary=summarize_trace(trace,metrics)
            (directory/'summary.json').write_text(canonical_json(summary),encoding='utf-8')
            overview=summary_html(summary)
            viewer=f'<iframe title="{name} 原子运动" src="{name}/animation.html" loading="lazy" style="width:100%;height:900px;border:1px solid #e5e9f0;border-radius:12px"></iframe>' if plans else ''
            sections.append(f'<section class="card"><header><h2>{name}</h2><span class="badge">PASS · {result.status}</span></header><div style="padding:24px"><nav>{links}<a href="{name}/metrics.json">指标</a><a href="{name}/trace.jsonl">Trace</a><a href="{name}/diagnostics.json">诊断</a></nav>{overview}{viewer}{cards}</div></section>')
            results.append({'scenario':name,'passed':True,'status':result.status,'metrics':metrics})
        body='<h1>Milestone 2 · 连续 eager 电路</h1><p>单 AOD · 单 CZ · 每个计划返回卸载 · 实际源与伙伴变化</p><p>公开初始条件：Q000/Q003 在 storage；Q001/Q002 已在 EZ。伙伴预置不计入本电路时间，不展示为已运输。支持该二分布局中的可行固定折线路由；全 storage、任意路由、参数化门、KEEP 和 RL 尚未实现。</p><p>总 wall time 从首个计划开始，包含每个返回、卸载和空载归还；逻辑完成时间截止最后 pulse。运动学参数未标定，不预测量子态或保真度。</p>'+''.join(sections)
        index.write_text(page('Milestone 2',body).replace('MILESTONE 0','MILESTONE 2'),encoding='utf-8')
    except Exception as error:
        index.write_text(page('Milestone 2',f'<h1>本轮验收失败</h1><pre>{html.escape(str(error))}</pre>'),encoding='utf-8')
        (root/'results.json').write_text(canonical_json(results+[{'passed':False,'error':str(error)}]),encoding='utf-8')
        raise
    (root/'results.json').write_text(canonical_json(results),encoding='utf-8')
    return results
