"""Real event-driven M1 acceptance, metrics, timeline and continuous observer playback."""
from pathlib import Path
import json
import html
from dataclasses import asdict
from math import isclose
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.replay.serializer import canonical_json, primitive
from .renderer import render_layout
from .theme import VisualTheme
from .scene import build_scene
from .artifacts import page
from neutral_atom_env.planning.eager_baseline import EagerBaseline


def execute_case(name):
    state=make_single_gate_state(name);snapshots=[state.snapshot()]
    plan=MotionCompiler().compile(EagerBaseline().choose(state),state)
    assert state.snapshot()==snapshots[0]
    executor=Executor(state);executor.submit(plan)
    while state.event_queue:
        executor.step();snapshots.append(state.snapshot())
    metrics=state.metrics();count=2 if name=='incidental' else 1
    assert metrics['completed_gate_count']==1 and metrics['aod_load_count']==metrics['aod_offload_count']==1
    assert isclose(metrics['cycle_makespan_us'],312.3) and isclose(metrics['circuit_makespan_us'],156.3)
    assert metrics['total_aod_distance_um']==56 and metrics['total_atom_distance_um']==56*count
    assert metrics['captured_atom_count_total']==count
    initial=SimulationState.restore(snapshots[0])
    assert state.placement.atom_to_holder==initial.placement.atom_to_holder
    assert not state.reservations and state.active_plan is None and state.dag.completed
    for saved in snapshots:
        s=SimulationState.restore(saved)
        assert s.placement.position('Q001',s.world,s.aod)==Position2D(5,-25)
    return state,plan,snapshots


def timeline(trace,path,theme):
    """Compatibility entry: bounded device-time summary, never one row per operation."""
    from neutral_atom_env.visualization.summary import summarize_trace,render_summary
    render_summary(summarize_trace(trace),path,theme)


def animation(snapshots,plan,path,theme):
    """Compatibility adapter; all browser drawing lives in the reusable viewer."""
    from neutral_atom_env.visualization import VisualRecorder
    VisualRecorder.from_snapshots(snapshots,theme).write(path)


def build_report(root='artifacts/milestone1'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);theme=VisualTheme.load()
    (root/'index.html').write_text(page('Milestone 1','<h1>本轮验收生成中</h1>'),encoding='utf-8')
    sections=[];results=[]
    for name in ('baseline','incidental'):
        directory=root/name;directory.mkdir(exist_ok=True)
        state,plan,snapshots=execute_case(name);trace=[json.loads(r) for r in state.trace.records]
        for filename,value in [('plan.json',primitive(plan)),('metrics.json',state.metrics()),('snapshots.json',[json.loads(s) for s in snapshots])]:
            (directory/filename).write_text(canonical_json(value),encoding='utf-8')
        (directory/'initial.json').write_text(snapshots[0],encoding='utf-8');(directory/'final.json').write_text(snapshots[-1],encoding='utf-8')
        state.trace.write(directory/'trace.jsonl')
        animation(snapshots,plan,directory/'animation.html',theme);timeline(trace,directory/'timeline.png',theme)
        keyframes=[(0,'Initial AOD traps')]
        for i,record in enumerate(trace,1):
            if (record['event']['event_type']=='operation_completed' and record.get('label') in {'Load','Depart source'}) or (record['event']['event_type']=='operation_started' and record.get('label')=='CZ pulse'):
                keyframes.append((i,record['label']))
        keyframes.append((len(snapshots)-1,'Final offload'))
        cards=''
        for i,label in keyframes:
            render_layout(snapshots[i],directory/f'frame_{i}.png',theme,show_aod=True)
            cards+=f'<a class="card" href="{name}/frame_{i}.png"><header>{html.escape(label)} · {json.loads(snapshots[i])["time_us"]:g} μs</header><img src="{name}/frame_{i}.png"></a>'
        metrics=state.metrics();results.append({'scenario':name,'passed':True,'metrics':metrics})
        from neutral_atom_env.visualization.summary import summarize_trace,summary_html
        summary=summarize_trace(trace,metrics)
        (directory/'summary.json').write_text(canonical_json(summary),encoding='utf-8')
        overview=summary_html(summary)
        sections.append(f'<section class="card"><header><h2>{name}</h2><span class="badge">PASS</span></header><div style="padding:24px"><p>静态伙伴预置于 EZ；无隐式伙伴运输。捕获 {len(plan.captured_atom_ids)} 个原子，附带 {len(plan.incidental_atom_ids)} 个。</p><nav><a href="{name}/animation.html">播放 / 检查 pulse</a><a href="{name}/metrics.json">指标</a><a href="{name}/plan.json">编译计划</a><a href="{name}/trace.jsonl">事件 trace</a></nav>{overview}<iframe title="{name} 原子运动" src="{name}/animation.html" loading="lazy" style="width:100%;height:900px;border:1px solid #e5e9f0;border-radius:12px"></iframe><details><summary>时间占用图</summary><img src="{name}/timeline.png"></details><details><summary>展开关键帧（全部来自实际事件）</summary><div class="grid">{cards}</div></details></div></section>')
    diagnostics=[]
    for name,expected in [('unintended','UNINTENDED_PAIR'),('blocked','INVALID_TRANSFER_PATH'),('both_storage','STATIC_PARTNER_REQUIRED')]:
        state=make_single_gate_state(name);before=state.snapshot()
        try:MotionCompiler().compile(ExecuteGateBatchIntent(frozenset({'G000'})),state)
        except ValidationError as error:
            assert error.violation.code==expected and state.snapshot()==before
            diagnostics.append(primitive(error.violation));results.append({'scenario':name,'passed':True,'expected_rejection':expected})
        else:raise AssertionError('Invalid case was accepted')
    (root/'diagnostics.json').write_text(canonical_json(diagnostics),encoding='utf-8')
    (root/'results.json').write_text(canonical_json(results),encoding='utf-8')
    body='<h1>Milestone 1 · 单 CZ 往返验收</h1><p>连续 AOD pose · 静态 EZ 伙伴 · 2 μm 作用距离 · 真实事件轨迹</p><p class="muted">这是恒速分段的运动学与几何安全模型，不包含加速度、陷阱深度、温度、原子损失或 RF 波形。网格只约束 SLM；移动原子在非 SLM 坐标发生作用。</p>'+''.join(sections)
    body+='<section class="card"><header>执行前拒绝的负例</header><pre style="padding:24px;white-space:pre-wrap">'+html.escape(json.dumps(diagnostics,ensure_ascii=False,indent=2))+'</pre></section>'
    body=body.replace('NEUTRAL ATOM LAB / MILESTONE 0','NEUTRAL ATOM LAB / MILESTONE 1')
    document=page('Milestone 1',body).replace('NEUTRAL ATOM LAB / MILESTONE 0','NEUTRAL ATOM LAB / MILESTONE 1')
    (root/'index.html').write_text(document,encoding='utf-8')
    return results
