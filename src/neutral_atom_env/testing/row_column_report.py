"""Evidence for the selectable row/column backend, using the shared replay template."""
import json
import html
from pathlib import Path
from math import isclose
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.row_column_factory import make_row_column_state
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.replay.serializer import canonical_json
from .milestone1_report import animation, timeline
from .renderer import render_layout
from .theme import VisualTheme
from .artifacts import page


def build_report(root='artifacts/row_column',backend='row_column'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);theme=VisualTheme.load()
    (root/'index.html').write_text(page('AOD backend','<h1>本轮报告生成中</h1>'),encoding='utf-8')
    results=[];cards=[]
    for scenario in ('pair_compression','incidental','mobile_static'):
        state=make_row_column_state(scenario,backend);initial=state.snapshot()
        try:plan=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
        except ValidationError as error:
            if backend!='rigid' or scenario=='mobile_static' or error.violation.code!='STATIC_PARTNER_REQUIRED':raise
            assert state.snapshot()==initial
            results.append({'scenario':scenario,'backend':backend,'status':'expected_rejection','code':error.violation.code})
            cards.append(f'<section class="card"><header>{scenario}</header><p>rigid 无法靠整体平移缩短同阵列目标间距，编译器拒绝该场景：{error.violation.code}。</p></section>')
            continue
        snapshots=[initial];ex=Executor(state);ex.submit(plan)
        while state.event_queue:ex.step();snapshots.append(state.snapshot())
        metrics=state.metrics()
        assert metrics['completed_gate_count']==1 and not state.active_plan and not state.reservations
        assert metrics['total_aod_distance_um']==(56 if scenario=='mobile_static' else 64)
        assert metrics['total_atom_distance_um']=={'pair_compression':116,'incidental':174,'mobile_static':56}[scenario]
        assert json.loads(initial)['placement']==json.loads(snapshots[-1])['placement']
        directory=root/scenario;directory.mkdir(exist_ok=True)
        trace=[json.loads(r) for r in state.trace.records]
        for name,value in [('plan.json',plan),('snapshots.json',[json.loads(s) for s in snapshots]),('metrics.json',metrics)]:
            (directory/name).write_text(canonical_json(value),encoding='utf-8')
        state.trace.write(directory/'trace.jsonl')
        animation(snapshots,plan,directory/'animation.html',theme)
        timeline(trace,directory/'timeline.png',theme)
        # Three causally distinct static views, only for the incidental deformation case.
        if scenario=='incidental':
            for label,condition in [('before_compression',lambda d:d['active_plan'] and d['aod']['is_moving'] and d['active_plan']['plan']['operations'][d['active_plan']['operation_index']]['label']=='Reconfigure axes'),
                                    ('pulse',lambda d:d['dag']['G000']['status']=='running')]:
                saved=next(s for s in snapshots if condition(json.loads(s)))
                render_layout(saved,directory/f'{label}.png',theme,show_aod=True)
            render_layout(snapshots[-1],directory/'final.png',theme,show_aod=True)
        rows=''.join(f'<tr><td>{key}</td><td>{metrics[key]:.6g}</td></tr>' for key in ['cycle_makespan_us','circuit_makespan_us','total_aod_distance_um','total_atom_distance_um','captured_atom_count_total'])
        description='两颗移动原子位于相邻 AOD 列，从 5 μm 压缩到 2 μm 执行 CZ；原路展开并卸载。' if scenario!='mobile_static' else '移动原子与预置静态伙伴配对，验证原有路径在新后端下的兼容性。'
        if scenario=='incidental':description+=' Q002 随同行移动；格间运输阶段位于 x=7.5 μm，最终随行列配置调整到 x=6 μm。'
        cards.append(f'<section class="card"><header><h2>{scenario}</h2><span class="badge">PASS · {backend}</span></header><div style="padding:24px"><p>{description}</p><nav><a href="{scenario}/animation.html">播放真实轨迹 / 关键帧演示</a><a href="{scenario}/plan.json">计划与行列坐标</a><a href="{scenario}/metrics.json">指标</a></nav><table>{rows}</table></div></section>')
        results.append({'scenario':scenario,'backend':backend,'status':'passed','metrics':metrics})
    if backend=='row_column':
        state=make_row_column_state('outer_pair_blocked');before=state.snapshot()
        try:MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
        except ValidationError as error:
            assert error.violation.code=='AOD_PAIR_SPACING_INFEASIBLE' and state.snapshot()==before
            results.append({'scenario':'outer_pair_blocked','backend':backend,'status':'expected_rejection','code':error.violation.code})
            cards.insert(0,'<section class="card"><header><h2>旧版外侧两列压缩：已拒绝</h2></header><p style="padding:18px">原先 x=(4,5,6) μm 的三列配置只有 1 μm 相邻间距，现由硬约束拒绝。中间空 trap 依然存在；外侧两列隔着两个间隙，中心距必须大于 2.02 μm，无法满足当前 2 μm 门作用半径。下方合法例明确改为相邻两列操作数，作用半径保持 2 μm。</p></section>')
        else:raise AssertionError('Unsafe outer pair was accepted')
    (root/'results.json').write_text(canonical_json(results),encoding='utf-8')
    body=f'<h1>AOD backend · {html.escape(backend)}</h1><p>行列联动、不可交叉、全路径 clearance；2 μm 门距离保持不变。后端在执行前通过配置或命令行选择，回放模式只改变呈现时间。</p><p>row_column 是依据公开实验约束构建的运动学后端；三次轨迹与速度/加速度/段内 jerk 上限采用未标定配置，不模拟光场、损失或保真度。</p>'+''.join(cards)
    (root/'index.html').write_text(page('AOD backend',body),encoding='utf-8')
    return results
