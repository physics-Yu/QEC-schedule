"""Reproducible, physically executed comparison of three batching policies."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import Atom, GridCoord, HolderRef, HolderType as H, PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive, canonical_json
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.statistics import write_atom_statistics
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.patch_greedy import candidate_groups, preflight_group, batch_service
from neutral_atom_strategies.scheduling.smt_batch import SMTBatchPlanner, BatchDecision
from neutral_atom_strategies.scheduling.row_greedy import empty_graph_distance
from neutral_atom_env.domain.errors import ValidationError


STRATEGIES=('greedy','smt_single','smt_multi')


def demos():
    small=[[x,y] for y in (0,10) for x in (0,10,20,30)]
    sources=[[0,0],[10,0],[0,10],[10,10],[20,20],[0,20]]
    irregular=sources+[[x+40,y] for x,y in sources]+[[20,0],[60,0]]
    def spec(name,points,gates,rows=2,columns=4):
        return {'name':name,'positions':points,'aod_rows':rows,'aod_columns':columns,
                'gates':[{'type':kind,'qubits':qs} for kind,qs in gates],
                'timeout_s':60,'solver_timeout_ms':5000,'model_budget':24,'route_expansions':20000}
    return {
        'parallel':spec('四对竖直 CZ / 同型 H 并行',small,[('H',[i]) for i in range(8)]+[('CZ',[i,i+4]) for i in range(4)]),
        'closure':spec('矩形闭包：启发式遗漏的 2×2 子集',irregular,[('CZ',[i,i+6]) for i in range(6)],3,7),
        'dependency':spec('交叉配对与依赖',small,[('CZ',p) for p in ([0,4],[1,5],[2,7],[3,6],[0,1],[4,5],[2,3],[6,7])]),
        'mixed':spec('同型分批与异型依赖',small,[('H',[0]),('H',[4]),('X',[1]),('T',[5]),('CZ',[0,4]),('CZ',[1,5]),('H',[0]),('Z',[4])]),
    }


def validate_spec(spec):
    points=spec.get('positions',[]);gates=spec.get('gates',[])
    if not 2<=len(points)<=16 or not 1<=len(gates)<=16:
        raise ValueError('实验限 2–16 原子、1–16 个门')
    if any(len(p)!=2 or any(type(v) not in (int,float) or abs(v)>200 for v in p) for p in points):
        raise ValueError('坐标必须是 ±200 μm 内的有限二维数值')
    if len({tuple(p) for p in points})!=len(points):raise ValueError('原子坐标不能重复')
    for g in gates:
        k=g.get('type');qs=g.get('qubits',[])
        if k not in {'H','X','Y','Z','T','CZ'} or len(qs)!=(2 if k=='CZ' else 1):raise ValueError('仅支持 H/X/Y/Z/T/CZ')
        if len(set(qs))!=len(qs) or any(type(q)!=int or not 0<=q<len(points) for q in qs):raise ValueError('无效 qubit 编号')
    for key in ('aod_rows','aod_columns'):
        if type(spec.get(key))!=int or not 1<=spec[key]<=8:raise ValueError('AOD 行列范围 1–8')
    for key,default,limit in (('timeout_s',60,180),('solver_timeout_ms',5000,15000),('model_budget',24,64),('route_expansions',20000,100000)):
        v=spec.get(key,default)
        if type(v)!=int or not 1<=v<=limit:raise ValueError(f'{key} 必须为 1–{limit} 的整数')
    return spec


def make_state(spec):
    validate_spec(spec)
    points=[P(*p) for p in spec['positions']]
    low=P(min(p.x_um for p in points)-20,min(p.y_um for p in points)-20)
    high=P(max(p.x_um for p in points)+10*spec['aod_columns']+20,
           max(p.y_um for p in points)+10*spec['aod_rows']+20)
    bounds=Rectangle(low,high)
    traps={f'S{i}':StaticTrap(f'S{i}',GridCoord(round(p.x_um/5),round(p.y_um/5)),p) for i,p in enumerate(points)}
    world=WorldState(bounds,traps,(Zone('EZ',ZoneType.ENTANGLEMENT,bounds),))
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(len(points))}
    holders={q:HolderRef(H.STATIC,f'S{i}') for i,q in enumerate(atoms)}
    gates=tuple(PhysicalGate(f'g{i:03d}',g['type'],tuple(f'Q{q:03d}' for q in g['qubits'])) for i,g in enumerate(spec['gates']))
    aod=AODRuntimeState(pose=P(low.x_um+10,low.y_um+10),rows=spec['aod_rows'],columns=spec['aod_columns'],spacing_um=10,
                        enabled_rows=(False,)*spec['aod_rows'],enabled_columns=(False,)*spec['aod_columns'])
    state=SimulationState(world,PlacementState(holders),atoms,aod,DynamicGateDAG(PhysicalCircuit(gates)),hardware=HardwareConfig())
    SMTBatchPlanner.validate_family(state)
    return state


def realize(state, decisions, compiler, terminal=None):
    ids=frozenset(g for d in decisions for g in d.gate_ids)
    p=ProgramBuilder(state,TaskIntent(f'smt-experiment/{state.version}/{"-".join(sorted(ids))}',TaskTarget(),
        frozenset(state.atoms),phase='program' if ids else 'cleanup',gate_effects=ids))
    for decision in decisions:
        if decision.kind=='CZ':compiler.pulse_group(p,decision.members,decision.shift)
        else:p.add(K.RAMAN_ROTATION,f'{decision.kind} batch ×{len(decision.gate_ids)}',gate_ids=decision.gate_ids)
    if terminal is not None:compiler.restore(p,terminal)
    if not p.operations:return None
    p.intent=replace(p.intent,target=terminal or TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                       p.state.aod.configuration(),trap_state(p.state)))
    return p.finish('smt-experiment-restoring-v1')


def greedy_proposal(state,compiler,deadline,rejections,log):
    ready=state.dag.ready_gates()
    rotations=[g for g in ready if g.gate_type!='CZ']
    if rotations:
        k=rotations[0].gate_type
        decision=BatchDecision(k,tuple(g.id for g in rotations if g.gate_type==k))
        return (decision,),realize(state,(decision,),compiler)
    choices=candidate_groups(state,list(ready),'patch_greedy')
    best=None;constructed=0;pruned=0
    for shift,members in choices:
        if perf_counter()>deadline:raise TimeoutError('Greedy candidate search deadline')
        try:
            origin=preflight_group(state,compiler,shift,members)
            axes=state.aod.configuration()
            spanx=axes.x_um[-1]-axes.x_um[0];spany=axes.y_um[-1]-axes.y_um[0]
            lower=lambda a,b:empty_graph_distance(state.world.bounds,spanx,a,b,spany)
            target=P(origin.x_um+shift[0],origin.y_um+shift[1])
            bound=(state.hardware.load_duration_us+state.hardware.offload_duration_us+state.hardware.pulse_duration_us+
                   (lower(state.aod.pose,origin)+2*lower(origin,target))/state.hardware.speed_um_per_us)/len(members)
            if best is not None and bound>=best[0][0]-1e-9:
                pruned+=1;continue
            constructed+=1
            plan=batch_service(state,compiler,shift,members)
        except ValidationError as e:
            rejections.append({'stage':'greedy_realizer','members':members,'shift':shift,'code':e.violation.code,'message':e.violation.message})
            continue
        key=(plan.estimated_duration_us/len(members),-len(members),plan.estimated_distance_um,shift)
        if best is None or key<best[0]:best=(key,plan,BatchDecision('CZ',tuple(g for g,_,_ in members),members,shift))
    log.append({'heuristic_candidates':len(choices),'constructed':constructed,'bound_pruned':pruned,'objective':'actual restoring duration per completed gate',
                'implementation':'existing candidate_groups + preflight_group + batch_service; fixed EZ start'})
    if best is None:raise ValidationError('GREEDY_EXHAUSTED','Existing grouped candidates and single-atom fallbacks failed')
    return (best[2],),best[1]


def run_one(spec,strategy,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    state=make_state(spec);env=NeutralAtomEnv(state);initial=env.snapshot();terminal=initial_terminal(state)
    recorder=VisualRecorder(state);compiler=PatchArrayCompiler(spec.get('route_expansions',20000))
    planner=SMTBatchPlanner(mode='multi' if strategy=='smt_multi' else 'single',
        timeout_ms=spec.get('solver_timeout_ms',5000),model_budget=spec.get('model_budget',24))
    started=perf_counter();deadline=started+spec.get('timeout_s',60)
    rejections=[];decisions=[];plans=[];log=[];error=None;realize_s=0.;execute_s=0.
    def execute(plan):
        nonlocal execute_s
        if plan is None:return
        tick=perf_counter();env.submit(plan);plans.append(plan)
        env.run(on_event=lambda s,e:recorder.observe(s));execute_s+=perf_counter()-tick
    try:
        while not env.state.dag.completed:
            if perf_counter()>deadline:raise TimeoutError('Overall planning deadline')
            if strategy=='greedy':
                tick=perf_counter();batch,plan=greedy_proposal(env.state,compiler,deadline,rejections,log);realize_s+=perf_counter()-tick
            else:
                plan=None
                for batch in planner.proposals(env.state,deadline=deadline):
                    tick=perf_counter()
                    try:plan=realize(env.state,batch,compiler,terminal if strategy=='smt_multi' else None)
                    except ValidationError as e:
                        rejections.append({'stage':'physical_realizer','model':primitive(batch),'code':e.violation.code,
                            'message':e.violation.message,'classification':'search exclusion, not physical impossibility proof'})
                    finally:realize_s+=perf_counter()-tick
                    if plan is not None:break
                    if perf_counter()>deadline:raise TimeoutError('Realization exceeded planning deadline')
                if plan is None:raise ValidationError('SMT_NO_VALIDATED_PROGRAM','No physically validated program within the recorded symbolic/route budgets')
            decisions.extend(primitive(batch));execute(plan)
        tick=perf_counter();cleanup=realize(env.state,(),compiler,terminal);realize_s+=perf_counter()-tick
        execute(cleanup);validate_target(terminal,env.state)
    except (ValidationError,TimeoutError) as e:
        error={'code':e.violation.code if isinstance(e,ValidationError) else 'COMPILE_TIMEOUT',
               'message':e.violation.message if isinstance(e,ValidationError) else str(e)}
    compile_s=perf_counter()-started
    # Compiler-free replay from the exact same initial state and submitted plans.
    tick=perf_counter();replay=NeutralAtomEnv.restore(initial)
    for plan in plans:replay.submit(plan);replay.run()
    replay_equal=replay.snapshot()==env.snapshot();replay_s=perf_counter()-tick
    payload=recorder.payload();metrics=env.state.metrics()
    effects=[json.loads(r) for r in env.state.trace.records if json.loads(r).get('effect_completed')]
    counts=Counter(g for r in effects for g in r.get('effect_gate_ids',[]))
    complete=env.state.dag.completed
    effect_once=counts==Counter({g.id:1 for g in state.dag.circuit.gates}) if complete else all(v==1 for v in counts.values())
    cz=[d for d in decisions if d['kind']=='CZ']
    result={'strategy':strategy,'status':'completed' if error is None else 'failed','error':error,
        'initial_sha256':sha256(initial.encode()).hexdigest(),'input_sha256':sha256(canonical_json(spec).encode()).hexdigest(),
        'compile_seconds':compile_s,'realization_seconds':realize_s,'execution_recording_seconds':execute_s,
        'compile_timing_scope':'planning + validation + actual execution + recording; excludes imports, replay, export',
        'solver_build_seconds':sum(x.get('build_s',0) for x in planner.log),
        'solver_seconds':sum(x.get('solve_s',0) for x in planner.log),'replay_seconds':replay_s,
        'replay_equal':replay_equal,'effects_once':effect_once,'terminal_verified':error is None,
        'metrics':metrics,'cz_stages':len(cz),'cz_batch_sizes':[len(d['gate_ids']) for d in cz],
        'max_cz_batch':max((len(d['gate_ids']) for d in cz),default=0),
        'rejection_count':len(rejections),'solver_log':planner.log,'decisions':decisions,'baseline_log':log,
        'scope':'fixed EZ layout, 10um rigid axes, restoring batches, canonical pickup origin; no persistent or deformable routing',
        'physical_optimality_claim':False,'solver_version':__import__('z3').get_version_string()}
    for name,value in [('input.json',spec),('result.json',result),('recording.json',payload),('rejections.json',rejections),('plans.json',plans)]:
        (directory/name).write_text(canonical_json(value),encoding='utf-8')
    (directory/'initial.json').write_text(initial,encoding='utf-8');(directory/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
    env.state.trace.write(directory/'trace.jsonl');recorder.write(directory/'animation.html')
    write_atom_statistics(payload['atom_statistics'],directory)
    if not replay_equal or not effect_once:raise AssertionError('Execution/replay audit failed')
    return result


def run_comparison(spec,directory,progress=None):
    results=[]
    for strategy in STRATEGIES:
        if progress:progress({'strategy':strategy,'status':'compiling'})
        result=run_one(spec,strategy,Path(directory)/strategy);results.append(result)
        if progress:progress({'strategy':strategy,'status':result['status'],'compile_seconds':result['compile_seconds']})
    assert len({r['initial_sha256'] for r in results})==1
    report={'input':spec,'results':results,'same_initial_state':True,
            'status':'completed' if all(r['status']=='completed' for r in results) else 'failed'}
    Path(directory,'comparison.json').write_text(canonical_json(report),encoding='utf-8')
    return report
