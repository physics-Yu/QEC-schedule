"""PhysicalCircuit -> all-SZ rigid transport -> real events -> reusable animation."""
from pathlib import Path
import argparse
import html
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate,EventType
from neutral_atom_env.simulation.rigid_parking_factory import make_rigid_parking_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.visualization import VisualRecorder,write_bundle,render_summary
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.testing.renderer import render_layout,render_dag
from neutral_atom_env.testing.theme import VisualTheme
from neutral_atom_env.testing.artifacts import page


def build(output,scenario='circuit',circuit_path=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    def write(name,value):
        (output/name).write_text(canonical_json(value),encoding='utf-8')
    (output/'index.html').write_text(page('运行中','<h1>正在生成真实执行记录</h1>'),encoding='utf-8')
    write('result.json',{'status':'building'})
    try:
        if circuit_path is None and scenario=='circuit':
            circuit_path=Path(__file__).resolve().parents[1]/'configs/circuits/rigid_parking.json'
        circuit=None
        if circuit_path:
            data=json.loads(Path(circuit_path).read_text(encoding='utf-8'))
            circuit=PhysicalCircuit(tuple(PhysicalGate(**g) for g in data['gates']))
        state=make_rigid_parking_state(scenario,circuit=circuit)
        initial=state.snapshot();origin=state.placement;axes=state.aod.configuration()
        (output/'initial.json').write_text(initial,encoding='utf-8')
        write('circuit.json',state.dag.circuit)
        recorder=VisualRecorder(state);keyframes={'initial':initial};plans={}
        def observe(s,event):
            recorder.observe(s,event)
            if not s.active_plan:return
            plan=s.active_plan.plan;plans[plan.id]=plan
            if plan.intent.gate_ids!=frozenset({state.dag.circuit.gates[0].id}):return
            if event.operation_id is None:return
            op=next(o for o in plan.operations if o.id==event.operation_id)
            label=None
            if event.event_type==EventType.OPERATION_STARTED and op.operation_type.value=='entangling_pulse':label='pulse'
            if event.event_type==EventType.OPERATION_COMPLETED:
                label={'Joint load in SZ':'joint_loaded','Park operand in EZ SLM':'parked',
                       'Restore joint transport configuration':'restored_configuration','Recapture parked operand':'recaptured'}.get(op.label)
                if op.label=='Joint transport to EZ' and op.transfer_phase=='approach':label='arrived_ez'
            if label:keyframes[label]=s.snapshot()
        result=EagerScheduler(state).run(on_event=observe)
        if result.status=='completed':
            assert state.dag.completed and state.placement==origin and state.aod.configuration()==axes
            assert not state.placement.mobile_occupancy and not state.reservations
        keyframes['final']=state.snapshot()
        write('result.json',result);write('plans.json',list(plans.values()));write('metrics.json',state.metrics())
        (output/'final.json').write_text(state.snapshot(),encoding='utf-8')
        (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        recorder.write(output/'index.html');recorder.write_json(output/'recording.json');write_bundle(output)
        summary=recorder.payload()['summary'];write('summary.json',summary)
        theme=VisualTheme.load();render_summary(summary,output/'timeline.png',theme)
        render_dag(initial,output/'circuit.svg',theme)
        for name,saved in keyframes.items():render_layout(saved,output/f'{name}.png',theme,show_aod=True)
        cards=''.join(f'<figure><img src="{name}.png" alt="{name}"><figcaption>{name}</figcaption></figure>' for name in keyframes)
        gate_lines=' → '.join(f'{g.id}: {g.gate_type}({", ".join(g.qubit_ids)})' for g in state.dag.circuit.gates)
        body=f'''<h1>全 SZ 起步 · rigid 联合运输与 EZ 交接</h1><p>{html.escape(result.status)} · {state.metrics()['completed_gate_count']} 个门完成</p>
        <p>输入 PhysicalCircuit：{html.escape(gate_lines)}</p><p>全部原子初始在 SZ；EZ 只有空 SLM trap。完整捕获集一起运输，临时交出一个目标，其他 AOD 原子一起局部移动，执行 CZ 后恢复构型、接回并共同返回。rigid 间距不变，选择性交接使用显式开启的理想硬件能力。</p>
        <nav><a href="index.html">打开完整运动动画</a><a href="circuit.json">输入电路</a><a href="plans.json">编译计划</a><a href="trace.jsonl">实际事件</a><a href="metrics.json">指标</a><a href="result.json">运行状态</a></nav>
        <img src="circuit.svg" alt="输入电路 DAG"><img src="timeline.png" alt="实际操作时序"><details><summary>第一门交接关键帧与整条电路终态</summary>{cards}</details>'''
        (output/'report.html').write_text(page('Rigid pair parking',body).replace('NEUTRAL ATOM LAB / MILESTONE 0','NEUTRAL ATOM LAB / RIGID PAIR PARKING'),encoding='utf-8')
        return result
    except Exception as error:
        write('result.json',{'status':'failed','error':str(error)})
        (output/'index.html').write_text(page('生成失败',f'<h1>生成失败</h1><pre>{html.escape(str(error))}</pre>'),encoding='utf-8')
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',choices=['pair','incidental','circuit'],default='circuit')
    parser.add_argument('--circuit',type=Path,help='JSON PhysicalCircuit: {gates:[{id,gate_type,qubit_ids}]}')
    parser.add_argument('--output',type=Path,default=Path('artifacts/rigid-parking'))
    args=parser.parse_args();result=build(args.output,args.scenario,args.circuit)
    print(result.status,(args.output/'index.html').resolve())
    return 0 if result.status=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
