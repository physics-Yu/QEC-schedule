"""Full two-logical QEC GHZ on a common ordered-axis platform and controller."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json,primitive
from neutral_atom_env.statistics import write_atom_statistics
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.platform import initialize
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_experiments.qec_layout import build_qec_inputs
from neutral_atom_experiments.surface_qec import experiment_input,summarize,atom_roles
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment
from neutral_atom_strategies.scheduling.qec import readout_groups,readout_service
from neutral_atom_strategies.scheduling.ordered_greedy import OrderedAxisGreedy,new_builder,finish,restore
from neutral_atom_strategies.scheduling.smt_ordered import SMTOrderedAxisPlanner
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy

STRATEGIES=('ordered_greedy','smt_ordered')


def demos():
    value=experiment_input(fault={'pauli':'Y','qubit_id':'Q013'})
    value['readout_policy']=json.loads((Path(__file__).resolve().parents[2]/'configs/strategies/readout_placement.json').read_text(encoding='utf-8'))
    # Protocol fault shape is validated by its generator; keep the full input
    # as the editor model so IDs, classical conditions and explicit DAG survive.
    value.update(motion_router='axis_hold',aod_backend='row_column_orthogonal',name='两逻辑 QEC GHZ · 单数据 Y 故障恢复',timeout_s=1800,
                 solver_timeout_ms=5000,model_budget=24,beam_width=64,plan_budget=4,route_budget=128)
    return {'qec_ghz2':value}


def validate_spec(spec):
    ReadoutPlacementPolicy(**spec.get('readout_policy',{}))
    if not isinstance(spec.get('gates'),list) or not 1<=len(spec['gates'])<=1200:raise ValueError('Need 1–1200 physical gates/control slots')
    for k,default,limit in [('timeout_s',1800,7200),('solver_timeout_ms',5000,60000),('model_budget',24,256),
                            ('beam_width',64,512),('plan_budget',4,128),('route_budget',128,256)]:
        v=spec.get(k,default)
        if type(v)!=int or not 1<=v<=limit:raise ValueError(f'{k} must be 1–{limit}')
    if any(g.get('gate_type') not in ('H','X','Y','Z','CZ','MEASURE','RESET') for g in spec['gates']):
        raise ValueError('Clifford QEC tracking supports H/X/Y/Z/CZ/MEASURE/RESET')
    if spec.get('aod_rows',7)!=7 or spec.get('aod_columns',14)!=14:raise ValueError('Matched QEC platform uses 7×14 AOD')
    if spec.get('aod_backend','row_column') not in ('row_column','row_column_orthogonal'):raise ValueError('Unsupported ordered AOD backend')
    if spec.get('motion_router','axis_hold') not in ('axis_hold','legacy_corridor'):raise ValueError('Unsupported motion router')
    return spec


def make_state(spec):
    validate_spec(spec)
    value,circuit,platform,placement=build_qec_inputs(spec)
    platform=replace(platform,hardware=replace(platform.hardware,backend=spec.get('aod_backend','row_column')))
    state=initialize(circuit,platform,placement,seed=value.get('seed',0))
    return replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))


def run_one(spec,strategy,directory,*,initial_state=None,terminal_target=None,render=True):
    if strategy not in STRATEGIES:raise ValueError('Unknown strategy')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    env=NeutralAtomEnv(initial_state if initial_state is not None else make_state(spec))
    initial=env.snapshot();terminal=terminal_target or initial_terminal(env.state)
    recorder=VisualRecorder(env.state);recorder.scene['atom_roles']=atom_roles()
    started=perf_counter();deadline=started+spec.get('timeout_s',1800)
    planner=(OrderedAxisGreedy(beam_width=spec.get('beam_width',64),plan_budget=spec.get('plan_budget',4),route_budget=spec.get('route_budget',128),motion_router=spec.get('motion_router','axis_hold'))
             if strategy=='ordered_greedy' else SMTOrderedAxisPlanner(spec.get('solver_timeout_ms',5000),spec.get('model_budget',24),spec.get('route_budget',128),spec.get('motion_router','axis_hold')))
    transport=OrderedTransfer(deadline,spec.get('route_budget',128),spec.get('motion_router','axis_hold'))
    readout_policy=ReadoutPlacementPolicy(**spec.get('readout_policy',{}))
    plans=[];decisions=[];error=None;execution_s=0.;planning_s=0.;phase='stage_to_EZ'
    def execute(plan):
        nonlocal execution_s
        if plan is None:return
        tick=perf_counter();env.submit(plan);plans.append(plan)
        env.run(on_event=lambda s,e:recorder.observe(s));execution_s+=perf_counter()-tick
        progress=dict(phase=phase,plans=len(plans),completed_gates=sum(n.status.value=='completed' for n in env.state.dag.nodes.values()),
                      elapsed_seconds=perf_counter()-started,simulation_time_us=env.state.metrics()['simulation_time_us'])
        (directory/'progress.json').write_text(json.dumps(progress),encoding='utf-8')
        print(json.dumps(progress),flush=True)
    try:
        p=new_builder(env.state);transport.transfer_group(p,patch_assignment(env.state),'Stage all data and ancillas to EZ');execute(finish(p))
        while not env.state.dag.completed:
            if perf_counter()>deadline:raise TimeoutError('QEC ordered comparison deadline')
            tick=perf_counter();ready=sorted(env.state.dag.ready_gates(),key=lambda g:g.id)
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                kind=rotations[0].gate_type;ids=tuple(g.id for g in rotations if g.gate_type==kind)
                phase='single_qubit';p=new_builder(env.state,ids);p.add(K.RAMAN_ROTATION,kind+' batch',gate_ids=ids)
                decision={'kind':kind,'gate_ids':ids};plan=finish(p)
            elif any(g.gate_type=='CZ' for g in ready):
                phase='CZ';decision,plan=planner.propose(env.state,deadline)
            else:
                phase='readout';gates=[g for g in ready if g.gate_type in ('MEASURE','RESET')]
                if not gates:raise ValidationError('QEC_FRONTIER_EMPTY','No executable supported frontier')
                gates=[g for g in gates if g.gate_type==gates[0].gate_type];plan=None;last=None
                for group in readout_groups(env.state,gates):
                    try:
                        plan,_=readout_service(env.state,transport,group,placement_policy=readout_policy)
                        decision={'kind':group[0].gate_type,'gate_ids':tuple(g.id for g in group),
                                  'readout_target':readout_policy.log[-1]['selected']};break
                    except ValidationError as e:last=e
                if plan is None:raise last
            planning_s+=perf_counter()-tick;decisions.append(primitive(decision));execute(plan)
        phase='restore_SZ';p=new_builder(env.state)
        transport.transfer_group(p,{q:h.holder_id for q,h in terminal.holders},'Return all data and ancillas to SZ')
        execute(finish(p));execute(restore(env.state,terminal));validate_target(terminal,env.state)
    except (ValidationError,TimeoutError) as e:
        error={'code':e.violation.code if isinstance(e,ValidationError) else 'COMPILE_TIMEOUT','message':str(e),'phase':phase}
    elapsed=perf_counter()-started
    quantum=summarize(env.state)
    tick=perf_counter();replay=NeutralAtomEnv.restore(initial)
    for i,plan in enumerate(plans,1):
        replay.submit(plan);replay.run()
        (directory/'verification-progress.json').write_text(json.dumps({'phase':'independent_replay','plans':i,'total_plans':len(plans)}),encoding='utf-8')
    equal=replay.snapshot()==env.snapshot();replay_s=perf_counter()-tick
    effects=[json.loads(r) for r in env.state.trace.records if json.loads(r).get('effect_completed')]
    counts=Counter(g for r in effects for g in r.get('effect_gate_ids',[]))
    once=counts==Counter({g.id:1 for g in env.state.dag.circuit.gates})
    payload=recorder.payload();cz=[d for d in decisions if d['kind']=='CZ']
    result=dict(strategy=strategy,status='completed' if error is None else 'failed',error=error,
                initial_sha256=sha256(initial.encode()).hexdigest(),input_sha256=sha256(canonical_json(spec).encode()).hexdigest(),
                compile_seconds=elapsed,realization_seconds=planning_s,execution_recording_seconds=execution_s,replay_seconds=replay_s,
                replay_equal=equal,effects_once=once,terminal_verified=error is None,quantum=quantum,metrics=env.state.metrics(),
                cz_batch_sizes=[len(d['gate_ids']) for d in cz],max_cz_batch=max((len(d['gate_ids']) for d in cz),default=0),cz_stages=len(cz),
                decisions=decisions,readout_log=readout_policy.log,solver_log=planner.log if strategy=='smt_ordered' else [],baseline_log=planner.log if strategy=='ordered_greedy' else [],
                rejection_count=len(planner.rejections)+len(transport.rejections),
                scope='Same complete caller DAG, quantum state, ordered-axis backend, finite 2.5um routes and terminal. Shared Raman/MZ services. CZ only: greedy beam vs symbolic maximum frontier batch. Restoring batches.',
                physical_optimality_claim=False)
    for name,value in [('input.json',spec),('result.json',result),('recording.json',payload),('plans.json',plans),('rejections.json',planner.rejections+transport.rejections)]:
        (directory/name).write_text(canonical_json(value),encoding='utf-8')
    (directory/'initial.json').write_text(initial,encoding='utf-8');(directory/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
    env.state.trace.write(directory/'trace.jsonl')
    if render:recorder.write(directory/'animation.html')
    write_atom_statistics(payload['atom_statistics'],directory)
    if not equal or (error is None and not once):raise AssertionError('QEC replay/effect audit failed')
    return result
