"""Native QMAP composition for the existing editable workbench and viewer."""
from dataclasses import replace
from pathlib import Path
from time import perf_counter
import uuid

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.qmap_native import compile_native
from neutral_atom_strategies.qmap_native.adapter import NativeProgramAdapter
from neutral_atom_experiments.qmap_native import compatible_architecture, make_state

ROOT = Path(__file__).resolve().parents[2]


def request_from_input(value):
    from neutral_atom_app.visualization.studio_config import configuration_issue
    if issue := configuration_issue(value):
        raise ValueError(issue)
    if value['layout']!='qmap_paired':
        raise ValueError('原生 QMAP 需要显式选择 QMAP 成对 SLM 平台；不能直接替换原布局。')
    if value.get('placement_search',{}).get('enabled'):
        raise ValueError('原生 QMAP 已负责初态与动态落点，不叠加旧版初态反复编译搜索。')
    return dict(atom_count=value['atom_count'],gates=[dict(id=g['id'],type=g['gate_type'],
        qubits=[int(q[1:]) for q in g['qubit_ids']]) for g in value['gates']],
        routing=value.get('qmap_routing','strict'),architecture=compatible_architecture(value['atom_count'],
            rows=value.get('aod_rows',8),columns=value.get('aod_columns',16)))


def preview_state(value):
    request = request_from_input(value)
    arch = request['architecture']
    slm = arch['storage_zones'][0]['slms'][0]
    # The pinned author initial placer fills storage rows nearest EZ first.
    code = '\n'.join(f'atom ({(q%slm["c"])*10}, {(slm["r"]-1-q//slm["c"])*10}) atom{q}'
                     for q in range(value['atom_count']))
    return make_state(request,dict(architecture=arch),NativeProgramAdapter(code))


def compile_workbench(value, progress=None):
    started = perf_counter()
    request = request_from_input(value)
    directory = ROOT/'artifacts/qmap-native/workbench'/uuid.uuid4().hex
    native = compile_native(request,directory,timeout_s=value.get('compile_timeout_s',300))
    adapter = NativeProgramAdapter(native['code'])
    env = NeutralAtomEnv(make_state(request,native,adapter))
    initial = env.snapshot()
    recorder = VisualRecorder(env.state)
    recorder.scene.update(display_grid_step_um=10,show_candidate_sites=False)
    def observe(state,event):
        recorder.observe(state,event)
        if progress and event.event_type.value=='plan_completed':
            progress(dict(completed_gates=state.metrics()['completed_gate_count'],total_gates=len(value['gates']),
                simulation_time_us=state.time_us,commits=state.version,
                native_compile_seconds=native['stats']['totalTime']/1e6))
    physical_start = perf_counter()
    error = None
    try:
        from neutral_atom_app.control import ControlProgram
        ControlProgram(adapter).run(env,on_event=observe)
    except Exception as exc:
        error = adapter.failure or dict(code=type(exc).__name__,error=str(exc))
    physical_seconds = perf_counter()-physical_start
    report = None if error is None else dict(status='failed',phase='QMAP local physical adapter',
        code=error['code'],message=error.get('error',''),source_line=error.get('line'),
        completed_gates=env.state.metrics()['completed_gate_count'],total_gates=len(value['gates']),
        note='作者原生程序已保存；本地物理兼容失败，没有更换作者调度或放宽物理条件。')
    timing = dict(strategy='qmap_native',native_compile_seconds=native['stats']['totalTime']/1e6,
        native_call_seconds=native['native_call_seconds'],frontend_process_seconds=native['process_wall_seconds'],
        physical_adapter_execute_record_seconds=physical_seconds,author_metrics=native['author_metrics'],
        stats=native['stats'],versions=native['versions'],source_directory=str(directory))
    timing['capacity_adaptations']=adapter.capacity_adaptations
    from neutral_atom_env.replay.serializer import canonical_json, primitive
    (directory/'initial.json').write_text(initial,encoding='utf-8')
    (directory/'plans.json').write_text(canonical_json(primitive(adapter.plans)),encoding='utf-8')
    (directory/'compatibility.json').write_text(canonical_json(dict(timing=timing,failure=error,
        adaptations=[x for x in adapter.decisions if x['kind']!='CZ'])),encoding='utf-8')
    return dict(input=value,status='stalled' if error else 'completed',compile_seconds=perf_counter()-started,
        diagnostics=[timing],run_options=dict(engine='mqt.qmap==3.5.0',routing=request['routing'],
            geometry='paired SLM; SZ10um; EZ2um; orthogonal; square neighbor guard disabled'),
        candidate_rejections=[],decision_log=[dict(decision=i,strategy='qmap_native',selected=d['kind'],**d)
            for i,d in enumerate(adapter.decisions)],failure_report=report,
        recording=recorder.payload()),env.state
