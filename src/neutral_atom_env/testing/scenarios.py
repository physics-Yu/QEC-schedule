"""Executable acceptance scenarios shared by pytest and the report generator."""
from dataclasses import dataclass, replace, FrozenInstanceError
import json
from pathlib import Path
from neutral_atom_env.domain.models import (Atom, HolderRef, HolderType, MobileCellIndex, Position2D,
    PhysicalGate, GateStatus, SimulationEvent, EventType)
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import PlacementState, AODRuntimeState
from neutral_atom_env.world.config import LayoutConfig
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import make_demo_state
from neutral_atom_env.testing.logical_executor import LogicalTestExecutor as Executor
from .scene import build_scene


@dataclass(frozen=True)
class Frame:
    name: str
    description: str
    snapshot: str
    view: str = 'layout'


@dataclass(frozen=True)
class Evidence:
    checks: dict
    frames: tuple[Frame, ...] = ()
    violations: tuple = ()
    diagnostic_base: str | None = None
    trace: tuple = ()


def make_world(dense=False, config=None):
    path = Path(__file__).resolve().parents[3]/'configs/world/acceptance.json'
    config = config or (LayoutConfig.load(path) if path.exists() else LayoutConfig())
    world = config.build()
    enabled = [t for t in world.traps.values() if t.enabled]
    chosen = enabled if dense else enabled[::3]
    atoms = {f'Q{i:03d}': Atom(f'Q{i:03d}') for i in range(len(chosen))}
    placement = PlacementState({a:HolderRef(HolderType.STATIC,t.id) for a,t in zip(atoms,chosen)})
    return SimulationState(world,placement,atoms,AODRuntimeState(pose=Position2D(15,-30)),DynamicGateDAG(PhysicalCircuit(())))


def layout_scenario():
    configs = [('sparse',False,None),('dense',True,None),
               ('spacing_7_5',True,LayoutConfig(columns=12,rows=4,spacing_um=7.5,zone_height_um=30,isolation_gap_um=15)),
               ('disabled_boundary',True,LayoutConfig(columns=10,rows=5,zone_height_um=20,disabled_traps=(0,14,49)))]
    frames=[];counts={}
    for name,dense,config in configs:
        state=make_world(dense,config)
        scene=build_scene(state.snapshot())
        assert scene.spacing_um==state.world.grid_spacing_um
        assert all(state.world.is_candidate_site(p) for p in scene.candidates)
        if config is None:
            assert not state.world.is_candidate_site(Position2D(0,-30))
        for atom in state.atoms:
            holder=state.placement.atom_to_holder[atom]
            trap=state.world.traps[holder.holder_id]
            assert trap.enabled and state.world.is_candidate_site(trap.position)
            assert state.placement.static_occupancy[trap.id]==atom
            assert state.placement.position(atom,state.world,state.aod)==trap.position
        assert state.snapshot()==make_world(dense,config).snapshot()
        frames.append(Frame(name,f'{len(state.atoms)} atoms / {len(state.world.traps)} traps / {scene.spacing_um:g} μm',state.snapshot()))
        counts[name]={'atoms':len(state.atoms),'traps':len(state.world.traps),'disabled':sum(not t.enabled for t in state.world.traps.values())}
    boundary=make_world(True,configs[-1][2])
    assert boundary.world.is_candidate_site(Position2D(5,0))
    assert boundary.world.is_candidate_site(Position2D(5,-20))
    assert not boundary.world.is_candidate_site(Position2D(5,-25))
    assert not boundary.world.is_candidate_site(Position2D(5.1,-20))
    return Evidence({'layouts':counts,'all_positions_and_reverse_occupancy':True,'boundary_and_isolation_band':True,'deterministic':True},tuple(frames))


def holder_scenario():
    state=make_world()
    holders=dict(state.placement.atom_to_holder)
    for i in range(4):holders[f'Q{i:03d}']=HolderRef(HolderType.MOBILE,MobileCellIndex(i//2,i%2))
    mixed=replace(state,placement=PlacementState(holders))
    positions={}
    for key,holder in mixed.placement.atom_to_holder.items():
        p=mixed.placement.position(key,mixed.world,mixed.aod)
        if holder.holder_type==HolderType.MOBILE:
            cell=holder.holder_id
            expected=Position2D(15+cell.column*5,-30+cell.row*5)
            assert mixed.placement.mobile_occupancy[cell]==key
            old=state.placement.atom_to_holder[key].holder_id
            assert old not in mixed.placement.static_occupancy
        else:
            expected=mixed.world.traps[holder.holder_id].position
            assert mixed.placement.static_occupancy[holder.holder_id]==key
        assert p==expected
        positions[key]={'holder':str(holder.holder_id),'x_um':p.x_um,'y_um':p.y_um}
    assert len(mixed.placement.mobile_occupancy)+len(mixed.placement.static_occupancy)==len(mixed.atoms)
    return Evidence({'checked_atoms':len(positions),'mobile_count':4,'all_holder_positions':positions},
        (Frame('mixed_holders','Independent initialization; AOD idle, no load/move simulated',mixed.snapshot()),))


def complex_circuit():
    gates=[PhysicalGate(f'G{i:03d}','H',(f'Q{i:03d}',)) for i in range(8)]
    pairs=[(0,1),(2,3),(4,5),(6,7),(1,2),(3,4),(5,6),(0,7)]
    gates += [PhysicalGate(f'G{i+8:03d}','CZ',(f'Q{a:03d}',f'Q{b:03d}')) for i,(a,b) in enumerate(pairs)]
    return PhysicalCircuit(tuple(gates))


def dag_scenario():
    state=make_world();circuit=complex_circuit();dag=DynamicGateDAG(circuit)
    # Independent O(n²) oracle: preceding operation on each operand.
    expected={g.id:set() for g in circuit.gates}
    parents={g.id:set() for g in circuit.gates}
    for i,g in enumerate(circuit.gates):
        for q in g.qubit_ids:
            previous=next((p for p in reversed(circuit.gates[:i]) if q in p.qubit_ids),None)
            if previous:
                expected[previous.id].add(g.id);parents[g.id].add(previous.id)
    assert all(dag.nodes[key].successors==value for key,value in expected.items())
    frames=[Frame('dag_initial','Logical dependencies only; READY is not physical executability',replace(state,dag=dag).snapshot(),'dag')]
    completed=set();trace=[]
    for i,g in enumerate(circuit.gates):
        expected_ready={key for key,deps in parents.items() if key not in completed and deps<=completed}
        assert {g.id for g in dag.ready_gates()}==expected_ready
        before=dag
        for target in (GateStatus.RESERVED,GateStatus.RUNNING,GateStatus.COMPLETED):
            dag=dag.transitioned(g.id,target)
        assert before.nodes[g.id].status==GateStatus.READY
        completed.add(g.id)
        actual={g.id for g in dag.ready_gates()}
        assert actual=={key for key,deps in parents.items() if key not in completed and deps<=completed}
        assert all(n.remaining_predecessors==len(parents[key]-completed) for key,n in dag.nodes.items())
        trace.append({'completed':g.id,'ready':sorted(actual)})
        if i in {7,11,15}:frames.append(Frame(f'dag_after_{i+1}',f'After {i+1} logical completions; no physical pulse',replace(state,dag=dag).snapshot(),'dag'))
    assert dag.completed
    return Evidence({'gates':16,'edges_checked':sum(map(len,expected.values())),'frontiers_checked':17,
                     'remaining_counts_checked_each_step':True},tuple(frames),trace=tuple(trace))


def diagnostic_scenario():
    base=make_world();holders=dict(base.placement.atom_to_holder);violations=[]
    for kind in ['duplicate','missing','outside','disabled','off_grid']:
        try:
            if kind=='duplicate':
                bad=holders|{'Q001':holders['Q000']};replace(base,placement=PlacementState(bad))
            elif kind=='missing':
                bad=dict(holders);del bad['Q000'];replace(base,placement=PlacementState(bad))
            elif kind=='outside':
                bad=holders|{'Q000':HolderRef(HolderType.MOBILE,MobileCellIndex(0,0))}
                replace(base,placement=PlacementState(bad),aod=replace(base.aod,pose=Position2D(200,200)))
            elif kind=='disabled':
                traps=dict(base.world.traps);traps['S000']=replace(traps['S000'],enabled=False)
                replace(base,world=replace(base.world,traps=traps))
            else:
                traps=dict(base.world.traps);traps['S000']=replace(traps['S000'],position=Position2D(.2,0))
                replace(base,world=replace(base.world,traps=traps))
        except ValidationError as error:violations.append(error.violation)
        else:raise AssertionError(f'{kind} was incorrectly accepted')
    assert [v.code for v in violations]==['DUPLICATE_HOLDER','HOLDER_SET_MISMATCH','ATOM_OUTSIDE_WORLD','UNAVAILABLE_STATIC_TRAP','INVALID_STATIC_SITE']
    assert violations[0].atom_ids==('Q000','Q001') and violations[0].position==Position2D(0,0)
    assert violations[1].atom_ids==('Q000',)
    assert violations[2].position==Position2D(200,200)
    assert violations[3].holder_id=='S000'
    return Evidence({'rejected':5,'structured_error_fields_checked':True},violations=tuple(violations),diagnostic_base=base.snapshot())


def checkpoint_scenario():
    state=make_demo_state(seed=713);executor=Executor(state)
    for t,kind,gate in [(0,EventType.RNG_DRAW,None),(1,EventType.GATE_RESERVED,'g2'),(1,EventType.GATE_STARTED,'g2'),
                        (2,EventType.RNG_DRAW,None),(2,EventType.GATE_COMPLETED,'g2'),(2,EventType.WAIT_COMPLETED,None)]:
        executor.schedule(SimulationEvent(t,kind,gate))
    for _ in range(3):executor.step()
    saved=state.snapshot();restored=SimulationState.restore(saved)
    assert saved==restored.snapshot()
    assert state.rng_state!=make_demo_state(seed=713).rng_state
    executor.run();Executor(restored).run()
    assert state.snapshot()==restored.snapshot() and state.trace.records==restored.trace.records
    assert len(state.trace.records)==6
    draws=[json.loads(record)['random_value'] for record in state.trace.records if 'random_value' in json.loads(record)]
    assert len(draws)==2 and draws[0]!=draws[1]
    return Evidence({'checkpoint_version':3,'final_version':6,'pending_events_restored':3,
        'same_time_event_order_preserved':True,'final_snapshot_equal':True,'trace_equal':True,'rng_draws':draws},
        (Frame('checkpoint','Saved checkpoint (H gate running)',saved,'data'),Frame('continued','After both executions finish',state.snapshot(),'data')),
        trace=tuple(json.loads(r) for r in state.trace.records))


def ownership_scenario():
    state=make_demo_state();before=state.snapshot()
    derived_queue=state.event_queue.push(SimulationEvent(1,EventType.WAIT_COMPLETED))
    derived_dag=state.dag.transitioned('g1',GateStatus.RESERVED)
    derived_trace=state.trace.appended({'example':'external derived value'})
    assert state.snapshot()==before and derived_queue and derived_dag.nodes['g1'].status==GateStatus.RESERVED and derived_trace.records
    rejected=0
    for target,name,value in [(state,'time_us',99),(state.dag,'_nodes',{}),(state.event_queue,'next_sequence',99),(state.trace,'records',())]:
        try:setattr(target,name,value)
        except FrozenInstanceError:rejected+=1
        else:raise AssertionError('Public runtime object mutable')
    assert rejected==4
    executor=Executor(state);executor.schedule(SimulationEvent(1,EventType.GATE_STARTED,'g2'))
    before=state.snapshot()
    try:executor.step()
    except ValueError:pass
    else:raise AssertionError('Invalid transition accepted')
    assert state.snapshot()==before
    return Evidence({'frozen_objects_checked':4,'derived_values_cannot_mutate_state':True,'failed_commit_atomic':True})


SCENARIOS = (
    ('layout','01 / 布局、间距与边界','不同密度、7.5 μm 网格、禁用 trap 和隔离带是否一致？',layout_scenario),
    ('holders','02 / 持有关系','每一个原子的正反向映射与位置是否都正确？',holder_scenario),
    ('dag','03 / 逻辑依赖演进','所有依赖边与每一步 frontier 释放是否正确？',dag_scenario),
    ('diagnostics','04 / 结构化诊断','错误是否直接携带冲突原子、holder 与坐标？',diagnostic_scenario),
    ('checkpoint','05 / 快照恢复与续跑','恢复队列、RNG 和 trace 后能否得到完全相同的结果？',checkpoint_scenario),
    ('ownership','06 / 状态写入边界','外部派生对象和失败事件能否改变运行时状态？',ownership_scenario),
)
