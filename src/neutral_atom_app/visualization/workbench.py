"""Editable input -> deterministic platform -> existing physical compiler/executor."""
from neutral_atom_experiments.input_geometry import aod_shape, aod_offsets
from neutral_atom_env.environment import NeutralAtomEnv
from neutral_atom_app.control import ControlProgram, configured_strategy
from math import ceil, sqrt, isfinite
import random
from time import perf_counter
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, Position2D, Rectangle, StaticTrap, GridCoord, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, AODRuntimeState
from neutral_atom_env.platform import Platform, initialize
from neutral_atom_strategies.scheduling.scheduler import EagerScheduler, ScheduleResult
from neutral_atom_strategies.planning.eager_baseline import EagerBaseline
from neutral_atom_strategies.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import primitive

from neutral_atom_env.hardware.gate_contract import EXECUTABLE_GATES
GATES = EXECUTABLE_GATES
LAYOUTS = ('row', 'grid', 'shuffled', 'qmap_paired', 'surface_patches', 'surface_qec_ghz2', 'surface_qec_ghz4')
QEC_LAYOUTS = frozenset({'surface_qec_ghz2','surface_qec_ghz4'})
QEC_GATES = frozenset({'H','X','Y','Z','CZ','MEASURE','RESET'})
QEC_STRATEGIES = frozenset({'qec_ghz2','qec_persistent','qec_joint','qec_temporal','qec_temporal_four'})
TEMPORAL_STRATEGIES = frozenset({'qec_temporal','qec_temporal_four'})
MAX_ATOMS = 128
MAX_GATES = 4096
MAX_COLUMNS = 4096
MAX_AOD_TRAPS = 128
MAX_COMPILE_TIMEOUT_S = 86400
SEARCH_LIMITS = {'ready_limit':128, 'site_limit':128, 'lookahead_depth':8,
                 'beam_width':32, 'rollout_budget':4096,
                 'row_candidate_budget':65536, 'route_expansions':1000000}
ORDERED_SEARCH_LIMITS = dict(SEARCH_LIMITS, beam_width=512, plan_budget=128, route_budget=256,
                             solver_timeout_ms=60000, model_budget=256, readout_candidate_budget=64, readout_top_k=64)
ORDERED_STRATEGIES = frozenset({'ordered_greedy','smt_ordered','zoned_ids','qmap_native'})
COMPILATION_OPTIONS = frozenset({'motion_router','readout_mode','qmap_routing'})
M4_STRATEGIES = frozenset({'basic', 'greedy', 'critical_path', 'lookahead'})
ROW_STRATEGIES = frozenset({'row_symmetric', 'row_greedy'})
PATCH_STRATEGIES = frozenset({'patch_symmetric', 'patch_greedy'})
CIRCUIT_PROFILES = ('physical','qec_ghz2','qec_temporal','qec_temporal_four')
COMPILATION_BUDGETS = frozenset(ORDERED_SEARCH_LIMITS) | {'max_decisions','compile_timeout_s'}
ALL_COMPILERS = {'legacy','resident','returning'} | M4_STRATEGIES | ROW_STRATEGIES | PATCH_STRATEGIES | QEC_STRATEGIES | ORDERED_STRATEGIES


def resolve_compilation(value):
    """Separate protocol semantics from scheduling, preserving legacy dispatch.

    Nested compilation is authoritative; flat compiler/budgets are compatibility
    mirrors. This function never changes gates, geometry or protocol metadata.
    """
    value=dict(value)
    old=value.get('compiler','legacy')
    profile=value.get('circuit_profile')
    if 'circuit_profile' not in value:
        profile=({'qec_temporal':'qec_temporal','qec_temporal_four':'qec_temporal_four'}.get(old)
                 if isinstance(old,str) else None) or ('qec_ghz2' if isinstance(old,str) and old in QEC_STRATEGIES else 'physical')
    if not isinstance(profile,str) or profile not in CIRCUIT_PROFILES:
        raise ValueError('Unknown circuit_profile')
    surface=value.get('layout')=='surface_patches'
    choices=({'recommended':'patch_greedy' if surface else 'greedy',
              'baseline':'patch_symmetric' if surface else 'basic'} if profile=='physical' else
             {'recommended':'qec_joint','baseline':'qec_ghz2'} if profile=='qec_ghz2' else
             {'recommended':profile})
    if 'compilation' in value:
        config=value['compilation']
        if not isinstance(config,dict):raise ValueError('compilation must be an object')
        if set(config)-({'strategy','implementation'} | COMPILATION_BUDGETS | COMPILATION_OPTIONS):
            raise ValueError('Unknown compilation configuration field')
        config=dict(config)
        strategy=config.get('strategy','recommended')
    elif 'circuit_profile' in value and 'compiler' not in value:
        config={};strategy='recommended'
    else:
        if not isinstance(old,str) or old not in ALL_COMPILERS:raise ValueError('Unknown compiler strategy')
        strategy=next((name for name,compiler in choices.items() if compiler==old),'legacy')
        config={'implementation':old} if strategy=='legacy' else {}
    if not isinstance(strategy,str) or strategy not in {'recommended','baseline','legacy'}:
        raise ValueError('compilation.strategy must be recommended, baseline or legacy')
    if strategy=='legacy':
        compiler=config.get('implementation')
        if not isinstance(compiler,str) or compiler not in ALL_COMPILERS:
            raise ValueError('Legacy compilation requires an existing implementation')
    else:
        if 'implementation' in config:raise ValueError('implementation is only valid for legacy compilation')
        if strategy not in choices:
            raise ValueError(f'compilation.strategy={strategy} is not supported for circuit_profile={profile}; only the existing guarded joint strategy is available')
        compiler=choices[strategy]
    compatible=(ALL_COMPILERS-QEC_STRATEGIES if profile=='physical' else
                ({'qec_ghz2','qec_persistent','qec_joint'} | ORDERED_STRATEGIES) if profile=='qec_ghz2' else {profile})
    if compiler not in compatible:
        raise ValueError('Compiler implementation does not support the declared circuit_profile; protocol guards cannot be bypassed')
    config['strategy']=strategy
    for key in COMPILATION_BUDGETS | COMPILATION_OPTIONS:
        if key in config:value[key]=config[key]
        elif 'compilation' in value:value.pop(key,None)
        elif key in value:config[key]=value[key]
    qec=profile!='physical'
    if 'qec_enabled' in value and (type(value['qec_enabled']) is not bool or value['qec_enabled']!=qec):
        raise ValueError('qec_enabled must agree with circuit_profile')
    if qec:value['qec_enabled']=True
    value.update(compiler=compiler,circuit_profile=profile,compilation=config,
        compilation_backend={'compiler':compiler,'available_strategies':list(choices),
            'legacy':strategy=='legacy','scope':('Existing guarded temporal QEC joint scheduling; baseline is not supported'
                if profile in {'qec_temporal','qec_temporal_four'} else
                'Existing two-patch Clifford QEC transport family' if qec else
                'Existing physical circuit and declared layout family; finite search may fail')})
    if compiler in ORDERED_STRATEGIES:
        value['compilation_backend']['kernel']='ordered-axis-readout-v1'
        value['compilation_backend']['scope']='Generic ordered-axis controller; finite routes, per-batch return, no fixed demo circuit'
    if compiler=='zoned_ids':
        value['compilation_backend']['kernel']='zoned-ids-v1'
        value['compilation_backend']['scope']='Layer scheduling, EZ residency, bounded routing-aware placement, compatible batches, validated physical codegen'
    if compiler=='qmap_native':
        if profile!='physical':
            raise ValueError('Native QMAP unitary frontend does not implement measurement/reset/feedback')
        value['compilation_backend']['kernel']='mqt.qmap-3.5.0-native-cpp'
        value['compilation_backend']['scope']='Author scheduler/reuse/IDS/router/codegen; checked local physical adapter'
    return value


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def validate_input(value,*,max_atoms=MAX_ATOMS):
    if not isinstance(value, dict):
        raise ValueError('Input must be a JSON object')
    value=resolve_compilation(value)
    n = integer(value.get('atom_count'), 1, max_atoms, 'atom_count')
    layout = value.get('layout')
    if layout not in LAYOUTS:
        raise ValueError('Unknown layout strategy')
    if layout == 'surface_patches' and n != 36:
        raise ValueError('surface_patches layout requires 36 atoms (four 3x3 patches)')
    qec = value.get('qec_enabled', False)
    if type(qec) is not bool:
        raise ValueError('qec_enabled must be boolean')
    if (value.get('compiler') not in ORDERED_STRATEGIES and qec != (value.get('compiler') in QEC_STRATEGIES)) or qec != (layout in QEC_LAYOUTS):
        raise ValueError('QEC requires qec_enabled=true, a QEC compiler and its QEC layout together')
    four = value['circuit_profile'] == 'qec_temporal_four'
    if qec and layout != ('surface_qec_ghz4' if four else 'surface_qec_ghz2'):
        raise ValueError('qec_temporal_four requires surface_qec_ghz4; other QEC compilers require surface_qec_ghz2')
    if qec and n != (68 if four else 34):
        raise ValueError('surface_qec_ghz4 requires 68 atoms: 36 data and 32 ancillas' if four else
                         'surface_qec_ghz2 requires 34 atoms: 18 data and 16 ancillas')
    if 'qec_patch_origins' in value and not qec:
        raise ValueError('qec_patch_origins requires the QEC profile')
    allowed_gates = QEC_GATES if qec else frozenset(GATES) - {'MEASURE','RESET','MZ'}
    seed = integer(value.get('seed', 0), 0, 2**31-1, 'seed')
    order = value.get('anchor_order', 'forward')
    if order not in ('forward', 'reverse'):
        raise ValueError('Unknown anchor order')
    # Legacy editor exports may carry a duration. Drop it: physical 1Q is fixed at 1 us.
    gates = value.get('gates')
    if not isinstance(gates, list) or len(gates) > MAX_GATES:
        raise ValueError(f'Use at most {MAX_GATES} gates')
    result = []; occupied = set(); ids = set()
    qubits = {f'Q{i:03d}' for i in range(n)}
    for raw in gates:
        if not isinstance(raw, dict):
            raise ValueError('Gate must be an object')
        if raw.get('gate_type') not in allowed_gates:
            raise ValueError('QEC Clifford 模式仅支持 H、X、Y、Z、CZ、MEASURE、RESET；T 不受 tableau 支持。' if qec else '可运行门仅限 H、X、Y、Z、T、CZ；MEASURE/RESET 需要启用专用 QEC 模式。')
        condition = {'condition':raw['condition']} if raw.get('condition') else {}
        if raw.get('depends_on'):
            condition['depends_on']=raw['depends_on']
        if condition and not qec:
            raise ValueError('Measurement-conditioned gates require the QEC profile')
        if 'readout_flip' in raw:
            if type(raw['readout_flip']) is not bool:
                raise ValueError('readout_flip must be boolean')
            if raw['readout_flip'] and value['circuit_profile'] not in {'qec_temporal','qec_temporal_four'}:
                raise ValueError('Readout report flips require an explicit qec_temporal or qec_temporal_four profile')
            condition['readout_flip'] = raw['readout_flip']
        gate = PhysicalGate(raw.get('id'), raw.get('gate_type'), raw.get('qubit_ids', ()), raw.get('parameters', ()), **condition)
        if not isinstance(gate.id, str) or len(gate.id) > 40 or not gate.id.isascii() or not all(c.isalnum() or c in '_-' for c in gate.id):
            raise ValueError('Gate ID must contain 1–40 ASCII letters, numbers, underscores or hyphens')
        if gate.id in ids or gate.gate_type not in allowed_gates:
            raise ValueError('Duplicate gate ID or unsupported physical gate')
        ids.add(gate.id)
        column = integer(raw.get('column'), 0, MAX_COLUMNS-1, 'gate column')
        for q in gate.qubit_ids:
            if q not in qubits:
                raise ValueError('Gate references a qubit outside atom_count; remove or retarget it first')
            if (column, q) in occupied:
                raise ValueError('Two gates cannot occupy the same wire and column')
            occupied.add((column, q))
        result.append(primitive(gate) | {'column': column})
    # Columns are logical order, not timing or a claim of parallel scheduling.
    result.sort(key=lambda g: (g['column'], g['id']))
    result={'atom_count': n, 'layout': layout, 'seed': seed, 'anchor_order': order, 'gates': result,
            'circuit_profile':value['circuit_profile'],'compilation':value['compilation'],
            'compilation_backend':value['compilation_backend']}
    if 'compiler' in value:
        if value['compiler'] not in {'legacy','resident','returning'} | M4_STRATEGIES | ROW_STRATEGIES | PATCH_STRATEGIES | QEC_STRATEGIES | ORDERED_STRATEGIES:raise ValueError('Unknown compiler strategy')
        result['compiler']=value['compiler']
    if qec:
        result['qec_enabled']=True
        if 'qec_patch_origins' in value:
            if four:
                from neutral_atom_experiments.qec_four_layout import normalize_patch_origins
            else:
                from neutral_atom_experiments.qec_layout import normalize_patch_origins
            result['qec_patch_origins']=primitive(normalize_patch_origins(value['qec_patch_origins']))
        fault=value.get('qec_fault')
        if fault is not None and (not isinstance(fault,dict) or set(fault)!={'pauli','qubit_id'}
                or fault['pauli'] not in {'X','Y','Z'} or fault['qubit_id'] not in {f'Q{i:03d}' for i in range(18)}):
            raise ValueError('qec_fault must be null or {pauli: X/Y/Z, qubit_id: data atom Q000..Q017}')
        # Display metadata follows the editable physical gate, never injects an
        # additional effect or reconstructs the protocol behind the editor.
        actual_fault=next((g for g in result['gates'] if g['id']=='QEC_FAULT'),None)
        result['qec_fault']=({'pauli':actual_fault['gate_type'],'qubit_id':actual_fault['qubit_ids'][0]}
            if actual_fault and actual_fault['gate_type'] in {'X','Y','Z'} else None)
        if 'qec_protocol' in value:
            metadata=value['qec_protocol']
            if not isinstance(metadata,dict):
                raise ValueError('qec_protocol must be an object containing editor stage metadata')
            result['qec_protocol']=primitive(metadata)
    if 'ez_policy' in value:
        if value['ez_policy'] not in {'adaptive','pair'}: raise ValueError('Unknown EZ policy')
        result['ez_policy']=value['ez_policy']
    if 'max_decisions' in value:
        result['max_decisions']=integer(value['max_decisions'],1,10000,'max_decisions')
    if 'compile_timeout_s' in value:
        result['compile_timeout_s']=integer(value['compile_timeout_s'],1,MAX_COMPILE_TIMEOUT_S,'compile_timeout_s')
    for key, maximum in ORDERED_SEARCH_LIMITS.items():
        if key in value:
            limit=32 if key=='beam_width' and value['compiler'] not in ORDERED_STRATEGIES else maximum
            result[key]=integer(value[key],1,limit,key)
    backend=value.get('aod_backend','rigid')
    if backend not in {'rigid','row_column','row_column_orthogonal'}:raise ValueError('Unknown AOD backend')
    if 'aod_backend' in value:result['aod_backend']=backend
    for key,allowed in {'motion_router':{'axis_hold','legacy_corridor'},'readout_mode':{'adaptive','aod_only','slm_only'},'qmap_routing':{'strict','relaxed'}}.items():
        if key in value:
            if value[key] not in allowed:raise ValueError('Invalid '+key)
            result[key]=value[key]
    if 'ez_neighbor_guard_enabled' in value:
        if type(value['ez_neighbor_guard_enabled']) is not bool:
            raise ValueError('ez_neighbor_guard_enabled must be boolean')
        result['ez_neighbor_guard_enabled']=value['ez_neighbor_guard_enabled']
    if ('aod_rows' in value) != ('aod_columns' in value):
        raise ValueError('Specify both aod_rows and aod_columns')
    if 'aod_rows' in value:
        result['aod_rows']=integer(value['aod_rows'],1,MAX_AOD_TRAPS,'aod_rows')
        result['aod_columns']=integer(value['aod_columns'],1,MAX_AOD_TRAPS,'aod_columns')
        if result['aod_rows']*result['aod_columns']>MAX_AOD_TRAPS:
            raise ValueError('AOD rows times columns must not exceed 128')
    if 'aod_traps' in value:
        count=integer(value['aod_traps'],1,MAX_AOD_TRAPS,'aod_traps')
        if 'aod_rows' in result and count!=result['aod_rows']*result['aod_columns']:
            raise ValueError('aod_traps must match aod_rows times aod_columns')
        result['aod_traps']=count
    aod_rows,aod_columns=aod_shape(result)
    for key,count in (('aod_row_offsets_um',aod_rows),('aod_column_offsets_um',aod_columns)):
        if key not in value:
            continue
        offsets=value[key]
        if (not isinstance(offsets,(list,tuple)) or len(offsets)!=count
                or any(type(x) not in (int,float) or not isfinite(x) for x in offsets)
                or offsets[0]!=0 or any(b<=a for a,b in zip(offsets,offsets[1:]))):
            raise ValueError(f'{key} must contain {count} finite, strictly increasing numbers starting at zero')
        result[key]=list(offsets)
    if aod_rows*aod_columns>1 and (result.get('compiler') not in M4_STRATEGIES | ROW_STRATEGIES | PATCH_STRATEGIES | QEC_STRATEGIES | ORDERED_STRATEGIES or result.get('ez_policy')!='adaptive'):
        raise ValueError('Multiple AOD traps require an M4 strategy or patch/row strategy + adaptive EZ')
    if 'placement_search' in value:
        from neutral_atom_app.studio_placement import search_options
        result['placement_search']=search_options(value['placement_search'])
    from neutral_atom_app.visualization.studio_config import validate_studio
    return validate_studio(value, result)


def build_inputs(value,*,max_atoms=MAX_ATOMS):
    value = validate_input(value,max_atoms=max_atoms)
    if value['compiler']=='qmap_native':
        from neutral_atom_app.qmap_native import preview_state
        state=preview_state(value)
        return value,state.dag.circuit,Platform(state.world,state.hardware,state.aod),{
            q:h.holder_id for q,h in state.placement.atom_to_holder.items()}
    if value.get('qec_enabled'):
        if value['layout']=='surface_qec_ghz4':
            from neutral_atom_experiments.qec_four_layout import build_qec_four_inputs as build_qec_inputs
        else:
            from neutral_atom_experiments.qec_layout import build_qec_inputs
        value,circuit,platform,placement=build_qec_inputs(value)
        if value.get('aod_backend','rigid')!='rigid':
            from dataclasses import replace
            platform=replace(platform,hardware=replace(platform.hardware,backend=value.get('aod_backend','rigid')))
        return value,circuit,platform,placement
    n = value['atom_count']
    columns = n if value['layout'] == 'row' else ceil(sqrt(n))
    surface=value['layout']=='surface_patches'
    positions=[((i//9%2)*40+(i%3)*10, (i//18)*40+(i%9//3)*10) if surface
               else ((i%columns)*10,(i//columns)*10) for i in range(n)]
    width = max(25, max(x for x,y in positions)+15)
    top = max(20, max(y for x,y in positions)+10)
    aod_rows,aod_columns=aod_shape(value)
    row_offsets,column_offsets=aod_offsets(value,aod_rows,aod_columns)
    def rect(x1, y1, x2, y2):
        return Rectangle(Position2D(x1,y1), Position2D(x2,y2))
    traps = {}
    for i,(x,y) in enumerate(positions):
        traps[f'S{i:03d}'] = StaticTrap(f'S{i:03d}', GridCoord(x//5,y//5), Position2D(x,y))
    ez_bottom=-105 if surface else min(-45,-30-max(y for x,y in positions)) if aod_rows>1 else -45
    if value.get('ez_policy') == 'adaptive':
        for y in range(ez_bottom+5,-20,5):
            for x in range(0,width-4,5):
                key=f'EZ_{x}_{-y}'
                traps[key]=StaticTrap(key,GridCoord(x//5,y//5),Position2D(x,y),enabled=False)
    else:
        for i,x in enumerate((5,width-10)):
            traps[f'EZ{i}'] = StaticTrap(f'EZ{i}',GridCoord(x//5,-7),Position2D(x,-35))
    if value.get('aod_backend','rigid')!='rigid':
        # Whole-layout staging is a policy; provide matching EZ sites for the
        # user's layout, rather than replacing it with a fixed demo factory.
        ez_bottom=min(ez_bottom,-35-max(y for x,y in positions))
        if value.get('ez_policy')=='adaptive':
            for y in range(ez_bottom+5,-20,5):
                for x in range(0,width-4,5):
                    key=f'EZ_{x}_{-y}'
                    traps.setdefault(key,StaticTrap(key,GridCoord(x//5,y//5),Position2D(x,y),enabled=False))
    # Inactive capacity axes also stay within world bounds. Add explicit space,
    # without enlarging the storage/entanglement addressing zones.
    left=-20 if surface else -10
    bottom=min(-140,ez_bottom-20) if surface else ez_bottom-20
    right=max(160,width+column_offsets[-1]) if surface else width+column_offsets[-1]
    upper=max(140,top+row_offsets[-1]) if surface else top+row_offsets[-1]
    if value.get('aod_backend','rigid')!='rigid':
        right=max(right,width+10*(aod_columns-1)+10)
        upper=max(upper,top+10*(aod_rows-1)+10)
    world = WorldState(rect(left,bottom,right,upper), traps,
        (Zone('SZ',ZoneType.STORAGE,rect(left,-5,width,top)),
         Zone('EZ',ZoneType.ENTANGLEMENT,rect(left,ez_bottom,width,-20)),
         Zone('MZ',ZoneType.MEASUREMENT,rect(left,bottom,width,ez_bottom-5))), grid_spacing_um=5)
    platform = Platform(world,HardwareConfig(backend=value.get('aod_backend','rigid'),ez_neighbor_guard_enabled=value.get('ez_neighbor_guard_enabled',True)),
                        AODRuntimeState(rows=aod_rows,columns=aod_columns,
                            spacing_um=5 if aod_rows*aod_columns==1 else 10,pose=Position2D(0,0),
                            row_offsets_um=row_offsets if row_offsets!=tuple(i*(5 if aod_rows*aod_columns==1 else 10) for i in range(aod_rows)) else None,
                            column_offsets_um=column_offsets if column_offsets!=tuple(i*(5 if aod_rows*aod_columns==1 else 10) for i in range(aod_columns)) else None))
    sites = list(range(n))
    if value['layout'] == 'shuffled':
        random.Random(value['seed']).shuffle(sites)
    placement = {f'Q{i:03d}':f'S{site:03d}' for i,site in enumerate(sites)}
    circuit = PhysicalCircuit(tuple(PhysicalGate(**{k:v for k,v in g.items() if k != 'column'}) for g in value['gates']))
    return value, circuit, platform, placement


def initialize_input(value,circuit,platform,placement):
    state=initialize(circuit,platform,placement,seed=value['seed'])
    if value.get('qec_enabled'):
        from dataclasses import replace
        from neutral_atom_env.quantum.stabilizer import StabilizerState
        state=replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    return state


def recording_payload(recorder,value):
    payload=recorder.payload()
    if value.get('qec_enabled'):
        if value['layout']=='surface_qec_ghz4':
            from neutral_atom_experiments.surface_qec_temporal_four import atom_roles
        else:
            from neutral_atom_experiments.surface_qec import atom_roles
        payload['scene']['atom_roles']=atom_roles()
    return payload


def preview(value):
    value,circuit,platform,placement = build_inputs(value)
    state = initialize_input(value,circuit,platform,placement)
    return {'input': value, 'recording': recording_payload(VisualRecorder(state),value)}


def failure_report(result, state, value):
    """Compact, reproducible explanation; rejections are not execution effects."""
    if result.status=='completed': return None
    diagnostics=primitive(result.diagnostics)
    first=diagnostics[0] if diagnostics else {}
    groups={}
    for rejection in getattr(result,'candidate_rejections',()):
        violation=rejection.get('violation',{})
        code=violation.get('code',rejection.get('code','UNKNOWN'))
        group=groups.setdefault(code,{'code':code,'count':0,'example':rejection})
        group['count']+=1
    return {'status':result.status,'phase':first.get('phase','candidate_search'),
            'code':first.get('code','COMPILATION_STALLED'),'message':first.get('message','No complete plan'),
            'completed_gates':state.metrics()['completed_gate_count'],'total_gates':len(value['gates']),
            'unfinished_gates':first.get('unfinished_gates',[]),
            'budgets':{k:first.get(k,value.get(k)) for k in ('max_decisions','ready_limit','site_limit',
                       'lookahead_depth','beam_width','rollout_budget','row_candidate_budget','route_expansions')},
            'search':first.get('search_log',[]), 'placement_search':first.get('placement_search'), 'codegen':first.get('codegen'), 'route_rejections':first.get('route_rejections',[]),'causes':list(groups.values()),
            'note':'有限候选搜索未完成，不代表该线路在物理上不可能。已执行片段保留；可修改线路、布局或预算后重新编译。'}


def compile_input(value, progress=None):
    started=perf_counter()
    value=validate_input(value)
    if value['compiler']=='qmap_native':
        from neutral_atom_app.qmap_native import compile_workbench
        return compile_workbench(value,progress)
    value,circuit,platform,placement = build_inputs(value)
    from neutral_atom_app.visualization.studio_config import configuration_issue
    if issue := configuration_issue(value):
        raise ValueError(issue)
    state = initialize_input(value,circuit,platform,placement)
    env = NeutralAtomEnv(state)
    recorder = VisualRecorder(state)
    if value.get('compiler','legacy')!='legacy':
        def observe(s,event):
            recorder.observe(s,event)
            if progress and (s.version%12==0 or event.event_type.value=='plan_completed'):
                progress({'completed_gates':s.metrics()['completed_gate_count'],'total_gates':len(circuit.gates),
                          'simulation_time_us':s.time_us,'commits':s.version})
        strategy = configured_strategy(value)
        run_options = dict(strategy.options)
        result = ControlProgram(strategy).run(env, on_event=observe)
        extra={}
        if value.get('qec_enabled'):
            if value['circuit_profile']=='qec_temporal_four':
                from neutral_atom_experiments.surface_qec_temporal_four import summarize
            elif value['circuit_profile']=='qec_temporal':
                from neutral_atom_experiments.surface_qec_temporal import summarize
            else:
                from neutral_atom_experiments.surface_qec import summarize
            extra['qec_result']=summarize(state)
        return {'input':value,'status':result.status,'diagnostics':primitive(result.diagnostics),
                'run_options':run_options,
                'compile_seconds':perf_counter()-started,
                'candidate_rejections':primitive(result.candidate_rejections),
                'decision_log':primitive(getattr(result,'decision_log',())),
                'failure_report':failure_report(result,state,value), 'recording':recording_payload(recorder,value),**extra},state
    scheduler = EagerScheduler(env,policy=EagerBaseline(SingleTrapCompiler(anchor_order=value['anchor_order'])))
    while True:
        event = scheduler.step()
        if isinstance(event, ScheduleResult):
            result = event
            break
        recorder.observe(state,event)
        if progress and (state.version % 12 == 0 or event.event_type.value == 'plan_completed'):
            progress({'completed_gates':state.metrics()['completed_gate_count'], 'total_gates':len(circuit.gates),
                      'simulation_time_us':state.time_us,'commits':state.version})
    return {'input':value,'status':result.status,'diagnostics':primitive(result.diagnostics),
            'recording':recorder.payload()}, state
