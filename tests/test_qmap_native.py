"""Physics and input-parity regressions; no native dependency required here."""
from dataclasses import replace
import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.world import PlacementState
from neutral_atom_strategies.qmap_native.naviz import parse, transport_blocks, capacity_projection
from neutral_atom_strategies.qmap_native.adapter import NativeProgramAdapter, fill_axis
from neutral_atom_experiments.qmap_native import compatible_architecture, make_state


def state_and_adapter():
    code = '''atom (0.000, 20.000) atom0
atom (10.000, 20.000) atom1
@+ load [
atom0
atom1
]
@+ move [
(1.000, 20.000) atom0
(3.000, 20.000) atom1
]
@+ move [
(1.000, 60.000) atom0
(3.000, 60.000) atom1
]
@+ store [
atom0
atom1
]
@+ cz zone0
'''
    adapter = NativeProgramAdapter(code)
    req = dict(atom_count=2,gates=[dict(type='CZ',qubits=[0,1])])
    arch = compatible_architecture(2,rows=2,columns=2)
    return make_state(req,dict(architecture=arch),adapter), adapter


def test_native_program_executes_actual_cz_and_replays():
    state, adapter = state_and_adapter()
    env = NeutralAtomEnv(state)
    initial = env.snapshot()
    adapter.run(env)
    assert env.state.dag.completed
    assert next(d for d in adapter.decisions if d['kind']=='CZ')['gate_ids'] == ('g00000',)
    replay = NeutralAtomEnv.restore(initial)
    for plan in adapter.plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()


def test_unknown_native_instruction_is_never_dropped():
    with pytest.raises(ValueError,match='Unsupported'):
        parse('atom (0, 0) atom0\n@+ measure atom0')


def test_qubit_identity_uses_author_id_not_declaration_order():
    adapter = NativeProgramAdapter('atom (0, 0) atom8\natom (0, 10) atom0')
    assert adapter.names == {'atom8':'Q008','atom0':'Q000'}


def test_axis_crossing_is_rejected():
    code = '''atom (0, 0) a
atom (10, 0) b
@+ load [
a
b
]
@+ move [
(10, 0) a
(0, 0) b
]
@+ store [
a
b
]
'''
    with pytest.raises(ValueError,match='crosses'):
        transport_blocks(*parse(code))


def test_capacity_is_checked_not_truncated():
    with pytest.raises(ValidationError,match='exceeds'):
        fill_axis({2:20},2,-20,50,1.01)


def test_unused_axes_stay_put_when_order_allows():
    assert fill_axis({0:2},4,-20,80,1.01,(0,10,20,30))==(2,10,20,30)
    assert fill_axis({},4,-20,80,1.01,(0,10,20,30))==(0,10,20,30)


def test_collinear_waypoints_do_not_force_extra_stops():
    from neutral_atom_strategies.qmap_native.naviz import Instruction
    state,adapter=state_and_adapter()
    original=list(adapter.instructions)
    original.insert(2,Instruction('move',moves=(('atom0',(0.5,20)),('atom1',(6.5,20)))))
    adapter.instructions=tuple(original)
    env=NeutralAtomEnv(state);adapter.run(env)
    shortcuts=[d for d in adapter.decisions if d['kind']=='local_path_shortcut']
    assert shortcuts and shortcuts[0]['removed_author_waypoints']==2
    adapter.validate_final(env.state)


def test_blocked_shortcut_keeps_a_legal_waypoint_route():
    from neutral_atom_env.domain.models import Atom,StaticTrap,GridCoord,Position2D
    from neutral_atom_strategies.qmap_native.naviz import Instruction
    state,a=state_and_adapter()
    initial=dict(a.initial)
    extra={'atom2':(0,40),'atom3':(3,45)}
    initial.update(extra);a.initial=initial;a.names.update(atom2='Q002',atom3='Q003')
    traps=dict(state.world.traps);atoms=dict(state.atoms);holders=dict(state.placement.atom_to_holder)
    for name,(x,y) in extra.items():
        q=a.names[name];traps[name]=StaticTrap(name,GridCoord(x,y),Position2D(x,y),enabled=True)
        atoms[q]=Atom(q);holders[q]=HolderRef(HolderType.STATIC,name)
    state=replace(state,world=replace(state.world,traps=traps),atoms=atoms,
                  placement=PlacementState(holders),slm_enabled=None)
    a.instructions=(a.instructions[0],
        Instruction('move',moves=(('atom0',(5,25)),('atom1',(15,25)))),
        Instruction('move',moves=(('atom0',(-4,50)),('atom1',(8,50)))),
        Instruction('move',moves=(('atom0',(1,60)),('atom1',(3,60)))),
        *a.instructions[-2:])
    env=NeutralAtomEnv(state);a.run(env)
    transport=next(p for p in a.plans if any(o.operation_type==K.AOD_LOAD for o in p.operations))
    lo=next(i for i,o in enumerate(transport.operations) if o.operation_type==K.AOD_LOAD)
    hi=next(i for i,o in enumerate(transport.operations) if o.operation_type==K.AOD_OFFLOAD)
    assert sum(o.operation_type==K.AOD_MOVE for o in transport.operations[lo:hi])>=3
    a.validate_final(env.state)


def test_capacity_projection_preserves_each_trajectory_and_cz_boundary():
    _,adapter = state_and_adapter()
    source=adapter.instructions
    projected,changes=capacity_projection(adapter.initial,source,1,1)
    assert changes and [o for o in projected if o.kind=='cz']==[o for o in source if o.kind=='cz']
    for atom in adapter.initial:
        def per_atom(ops):
            return [(o.kind,dict(o.moves).get(atom)) for o in ops if atom in o.atoms or atom in dict(o.moves)]
        assert per_atom(projected)==per_atom(source)
    assert all(len(set(x.values()))<=1 and len(set(y.values()))<=1
               for x,y in transport_blocks(adapter.initial,projected).values())


def test_retained_pair_single_qubit_gate_separates_then_restores():
    state,a=state_and_adapter()
    from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
    from neutral_atom_env.domain.models import PhysicalGate
    from neutral_atom_strategies.qmap_native.naviz import Instruction
    a.instructions += (Instruction('u',('atom0',),parameters=(1.5707963267948966,0,3.141592653589793)),Instruction('cz'))
    gates=state.dag.circuit.gates+(PhysicalGate('h','H',('Q000',)),PhysicalGate('cz2','CZ',('Q000','Q001')))
    env=NeutralAtomEnv(replace(state,dag=DynamicGateDAG(PhysicalCircuit(gates))))
    a.run(env)
    a.validate_final(env.state)
    assert env.state.placement.position('Q001',env.state.world,env.state.aod).x_um==3
    assert env.state.metrics()['completed_gate_count']==3
    assert len([d for d in a.decisions if d['kind']=='CZ'])==2
    assert any(d['kind']!='CZ' for d in a.decisions)


def test_partial_ordered_store_releases_only_unneeded_column():
    state,_ = state_and_adapter()
    backend = get_backend(state.hardware)
    aod = replace(state.aod,pose=state.world.traps['SLM0_2_0'].position,spacing_um=10,
                  enabled_rows=(True,False),enabled_columns=(True,True))
    cells = (MobileCellIndex(0,0),MobileCellIndex(0,1))
    holders = {f'Q{i:03d}':HolderRef(HolderType.MOBILE,c) for i,c in enumerate(cells)}
    work = replace(state,aod=aod,placement=PlacementState(holders),
                   slm_enabled={t:False for t in state.world.traps})
    binding = CaptureBinding('Q000',cells[0],'SLM0_2_0')
    out = backend.park(work,(binding,))
    assert out.aod.enabled_rows==(True,False)
    assert out.aod.enabled_columns==(False,True)
    assert out.placement.atom_to_holder['Q001']==holders['Q001']
    assert out.placement.atom_to_holder['Q000'].holder_type==HolderType.STATIC
    with pytest.raises(ValidationError,match='explicitly enabled'):
        backend.park(replace(work,hardware=replace(work.hardware,selective_transfer_enabled=False)),(binding,))
