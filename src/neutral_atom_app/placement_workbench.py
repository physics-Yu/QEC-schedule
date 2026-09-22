"""Free initial-placement experiment assembly and shared-viewer evidence.

Sequential placement is an explicit row-major baseline on the same full SLM
domain. Search and physical scheduling remain in the strategy package.
"""
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate,Position2D,Rectangle,StaticTrap,GridCoord,Zone,ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.platform import Platform
from neutral_atom_env.world import WorldState,AODRuntimeState
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.placement import CompilerSearchConfig
from .placement_execution import optimize_free_layout


def default_input():
    gates=[dict(id=f'h{q}',gate_type='H',qubit_ids=[f'Q{q:03d}']) for q in range(4)]
    for r in range(3):
        for i in range(4):
            gates.append(dict(id=f'cz{r}_{i}',gate_type='CZ',qubit_ids=[f'Q{i:03d}',f'Q{7-i:03d}']))
        if r<2:
            for i in range(4):gates.append(dict(id=f'between{r}_{i}',gate_type='H',qubit_ids=[f'Q{i:03d}']))
    gates.append(dict(id='phase',gate_type='T',qubit_ids=['Q007']))
    return dict(atom_count=8,source_rows=4,source_columns=8,spacing_um=10,
        aod_rows=4,aod_columns=8,evaluations=16,seed=7,compile_timeout_s=180,gates=gates,
        proposal_pool=256,workers=4,terminal_mode='stable')


def build_problem(raw):
    value=dict(raw)
    # Old saved jobs retain their original serial/fixed-terminal contract.
    for key,default in [('proposal_pool',64),('workers',1),('terminal_mode','fixed')]:
        value.setdefault(key,default)
    allowed=set(default_input())
    if set(value)-allowed:raise ValueError('Unknown input fields: '+str(sorted(set(value)-allowed)))
    limits={'atom_count':(1,64),'source_rows':(1,12),'source_columns':(1,12),
            'aod_rows':(1,16),'aod_columns':(1,16),'evaluations':(1,64),
            'seed':(0,2**31-1),'compile_timeout_s':(1,600),'proposal_pool':(1,1024),'workers':(1,8)}
    for key,(lo,hi) in limits.items():
        if type(value.get(key)) is not int or not lo<=value[key]<=hi:
            raise ValueError(f'{key} must be integer in {lo}..{hi}')
    if value['terminal_mode'] not in {'fixed','stable'}:raise ValueError('Unknown terminal mode')
    pitch=value['spacing_um']
    if type(pitch) not in (float,int) or pitch not in (5,10,15,20):
        raise ValueError('SLM pitch must be 5, 10, 15 or 20 um on the physical grid')
    n=value['atom_count'];rows=value['source_rows'];columns=value['source_columns']
    ar=value['aod_rows'];ac=value['aod_columns']
    if n>rows*columns:raise ValueError('Insufficient SLM sites for sequential baseline')
    if ar*ac>128:raise ValueError('Single-AOD capacity must be at most 128')
    gates=value.get('gates')
    if not isinstance(gates,list) or len(gates)>1200:raise ValueError('Use a complete list of at most 1200 gates')
    circuit=PhysicalCircuit(tuple(PhysicalGate(**g) for g in gates))
    qubits=tuple(f'Q{i:03d}' for i in range(n))
    if any(q not in qubits for g in circuit.gates for q in g.qubit_ids):raise ValueError('Gate references an unknown qubit')
    if any(g.gate_type not in {'H','X','Y','Z','T','CZ','MEASURE','RESET'} for g in circuit.gates):raise ValueError('Unsupported gate')
    quantum=None
    if any(g.gate_type in {'MEASURE','RESET'} or g.condition for g in circuit.gates):
        if any(g.gate_type=='T' for g in circuit.gates):raise ValueError('Readout requires Clifford tracking; T is not supported in that mode')
        from neutral_atom_env.quantum.stabilizer import StabilizerState
        quantum=StabilizerState.zero(qubits)
    rect=lambda a,b,c,d:Rectangle(Position2D(a,b),Position2D(c,d))
    width=(columns-1)*pitch+15;top=(rows-1)*pitch+15;ez_bottom=-(rows-1)*pitch-50
    traps={}
    for r in range(rows):
        for c in range(columns):
            i=r*columns+c;key=f'S{i:03d}'
            traps[key]=StaticTrap(key,GridCoord(c*pitch//5,r*pitch//5),Position2D(c*pitch,r*pitch),enabled=i<n)
    for y in range(int(ez_bottom+5),-20,5):
        for x in range(0,int(width),5):
            key=f'EZ_{x}_{-y}'
            traps[key]=StaticTrap(key,GridCoord(x//5,y//5),Position2D(x,y),enabled=False)
    world=WorldState(rect(-10,ez_bottom-60,width+10*(ac-1)+10,top+10*(ar-1)+10),traps,
        (Zone('SZ',ZoneType.STORAGE,rect(-10,-5,width,top)),
         Zone('EZ',ZoneType.ENTANGLEMENT,rect(-10,ez_bottom,width,-20)),
         Zone('MZ',ZoneType.MEASUREMENT,rect(-10,ez_bottom-50,width,ez_bottom-10))),5)
    platform=Platform(world,HardwareConfig(backend='row_column_orthogonal'),
                      AODRuntimeState(rows=ar,columns=ac,spacing_um=10,pose=Position2D(0,0)))
    sequential={q:f'S{i:03d}' for i,q in enumerate(qubits)}
    return value,circuit,platform,sequential,quantum


def record_trial(folder,output):
    folder=Path(folder);env=NeutralAtomEnv.restore((folder/'initial.json').read_text(encoding='utf-8'))
    recorder=VisualRecorder(env.state)
    for raw in json.loads((folder/'plans.json').read_text(encoding='utf-8')):
        env.submit(plan_from_dict(raw));env.run(on_event=recorder.observe)
    if env.snapshot()!=(folder/'final.json').read_text(encoding='utf-8'):
        raise AssertionError('Recording replay differs from verified final checkpoint')
    recorder.write_json(output)
    recorder.write(Path(output).with_suffix('.html'))
    return recorder.payload()


def compare(raw,directory,progress=None):
    value,circuit,platform,sequential,quantum=build_problem(raw)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'input.json').write_text(canonical_json(value),encoding='utf-8')
    started=perf_counter()
    def on_trial(trial):
        if progress:progress(dict(phase='search',trial=trial.index+1,budget=value['evaluations'],
            valid=trial.evaluation.valid,time_us=trial.evaluation.total_time_us,
            failure=trial.evaluation.failure,wall_seconds=perf_counter()-started))
    result=optimize_free_layout(circuit,platform,sequential,quantum_state=quantum,seed=value['seed'],
        config=CompilerSearchConfig(max_evaluations=value['evaluations'],allow_vacancies=True,seed=value['seed'],
                                   proposal_pool=value['proposal_pool']),
        workers=value['workers'],terminal_mode=value['terminal_mode'],
        compiler_options=dict(strategy='ordered_greedy',compile_timeout_s=value['compile_timeout_s']),
        output=directory/'search',on_trial=on_trial)
    report=dict(status='completed' if result.selected and result.baseline.evaluation.valid else 'failed',
        input=value,search_status=result.status,improvement_percent=result.improvement_percent,
        diagnostics=result.diagnostics,baseline=asdict(result.baseline),
        selected=asdict(result.selected) if result.selected else None,
        source_sites=[dict(id=t.id,x_um=t.position.x_um,y_um=t.position.y_um) for t in platform.world.traps.values() if t.id.startswith('S')],
        trials=[dict(index=t.index,valid=t.evaluation.valid,time_us=t.evaluation.total_time_us,
                     failure=t.evaluation.failure,origin=t.origin) for t in result.trials],
        quantum_scope='Clifford tracked with measurement' if quantum else 'physical execution; no quantum-state fidelity claim',
        terminal_mode=value['terminal_mode'],
        contract='same circuit, site domain, hardware, compiler and completion rule; prepared initial support; assembly excluded')
    if report['status']=='completed':
        if progress:progress(dict(phase='recording',message='重新重放两组验证计划，生成共用回放'))
        for name,trial in [('baseline',result.baseline),('optimized',result.selected)]:
            folder=directory/'search'/f'trial-{trial.index:04d}'
            payload=record_trial(folder,directory/f'{name}.json')
            report[name+'_metrics']=json.loads((folder/'result.json').read_text(encoding='utf-8'))['metrics']
        baseline=NeutralAtomEnv.restore((directory/'search'/'trial-0000'/'final.json').read_text(encoding='utf-8')).state
        final=NeutralAtomEnv.restore((directory/'search'/f'trial-{result.selected.index:04d}'/'final.json').read_text(encoding='utf-8')).state
        equal=baseline.placement==final.placement and baseline.aod==final.aod and baseline.slm_enabled==final.slm_enabled
        if value['terminal_mode']=='fixed' and not equal:
            raise AssertionError('Comparison terminal changed')
        from neutral_atom_env.domain.operations import TaskTarget
        from neutral_atom_env.program.task_validation import validate_target
        validate_target(TaskTarget(),baseline);validate_target(TaskTarget(),final)
        report['terminal_equal']=equal
        report['stable_completion_verified']=True
    report['wall_seconds']=perf_counter()-started
    (directory/'comparison.json').write_text(canonical_json(report),encoding='utf-8')
    return report
