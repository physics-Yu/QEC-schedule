"""Native author compiler and local physics are separate, measured stages."""
from collections import Counter
from dataclasses import replace
from math import ceil
from pathlib import Path
from time import perf_counter
import json

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.models import (Atom, GridCoord, HolderRef, HolderType,
    PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_strategies.qmap_native import compile_native
from neutral_atom_strategies.qmap_native.adapter import NativeProgramAdapter


def compatible_architecture(n, *, rows=8, columns=16):
    """Explicit experimental platform; never reported as the paper's 4um grid.

    The author paired-SLM architecture is retained. SZ pitch is 10um to meet
    the existing local 5um addressed-light clearance; EZ partner spacing is 2um.
    """
    cols = max(4,min(16,ceil(n/2)))
    sz_rows = max(3,ceil(n/cols)+1)
    width, ez_y = max(120,20*cols+30), sz_rows*10+30
    return dict(name='QMAP paired SLM / local 10um storage',
        operation_duration=dict(rydberg_gate=.3,single_qubit_gate=1,atom_transfer=100),
        operation_fidelity=dict(rydberg_gate=.995,single_qubit_gate=.9997,atom_transfer=.999),
        qubit_spec=dict(T=1.5e6),storage_zones=[dict(zone_id=0,slms=[dict(id=0,
            site_separation=[10,10],r=sz_rows,c=cols,location=[0,0])],
            offset=[0,0],dimension=[(cols-1)*10,(sz_rows-1)*10])],
        entanglement_zones=[dict(zone_id=0,slms=[dict(id=i+1,site_separation=[20,20],
            r=2,c=cols,location=[1+2*i,ez_y]) for i in range(2)],
            offset=[1,ez_y],dimension=[(cols-1)*20+2,20])],
        aods=[dict(id=0,site_separation=2,r=rows,c=columns)],
        arch_range=[[-20,-20],[width,ez_y+50]],rydberg_range=[[[-20,ez_y-10],[width,ez_y+50]]])


def make_state(request, native, adapter):
    arch = native['architecture']
    lower,upper = arch['arch_range']
    ezlower,ezupper = arch['rydberg_range'][0]
    zones = (Zone('SZ',ZoneType.STORAGE,Rectangle(P(*lower),P(upper[0],ezlower[1]-1))),
             Zone('EZ',ZoneType.ENTANGLEMENT,Rectangle(P(*ezlower),P(*ezupper))))
    positions = {point for point in adapter.initial.values()}
    traps = {}
    for zone in arch['storage_zones']+arch['entanglement_zones']:
        for slm in zone['slms']:
            for r in range(slm['r']):
                for c in range(slm['c']):
                    x = slm['location'][0]+c*slm['site_separation'][0]
                    y = slm['location'][1]+r*slm['site_separation'][1]
                    key = f'SLM{slm["id"]}_{r}_{c}'
                    traps[key] = StaticTrap(key,GridCoord(x,y),P(x,y),enabled=(x,y) in positions)
    sites = {(t.position.x_um,t.position.y_um):t.id for t in traps.values()}
    atoms = {q:Atom(q) for q in adapter.names.values()}
    placement = PlacementState({adapter.names[name]:HolderRef(HolderType.STATIC,sites[point])
                               for name,point in adapter.initial.items()})
    gates = tuple(PhysicalGate(g.get('id',f'g{i:05d}'),g['type'].upper(),
                              tuple(f'Q{q:03d}' for q in g['qubits'])) for i,g in enumerate(request['gates']))
    spec = arch['aods'][0]
    aod = AODRuntimeState(pose=P(*lower),rows=spec['r'],columns=spec['c'],spacing_um=2)
    # This experimental paired array explicitly uses no square-lattice neighbor
    # reservation, as in the author hardware. Continuous checks remain enabled.
    hardware = HardwareConfig(backend='row_column_orthogonal',selective_transfer_enabled=True,
                              ez_neighbor_guard_enabled=False)
    return SimulationState(WorldState(Rectangle(P(*lower),P(*upper)),traps,zones,grid_spacing_um=1),
        placement,atoms,aod,DynamicGateDAG(PhysicalCircuit(gates)),hardware=hardware)


def run(request, directory, *, local=True, timeout_s=300, native_result=None):
    directory = Path(directory)
    native = native_result if native_result is not None else compile_native(request,directory/'upstream',timeout_s=timeout_s)
    if not local:
        return native
    adapter = NativeProgramAdapter(native['code'])
    env = NeutralAtomEnv(make_state(request,native,adapter))
    initial = env.snapshot()
    recorder = VisualRecorder(env.state)
    recorder.scene.update(display_grid_step_um=10,show_candidate_sites=False)
    start = perf_counter()
    error = None
    try:
        adapter.run(env,on_event=lambda s,e:recorder.observe(s,e))
    except Exception as exc:
        error = adapter.failure or dict(type=type(exc).__name__,message=str(exc))
    seconds = perf_counter()-start
    replay = NeutralAtomEnv.restore(initial)
    replay_start = perf_counter()
    replay_error = None
    try:
        for plan in adapter.plans:
            replay.submit(plan)
            replay.run()
    except Exception as exc:
        replay_error = str(exc)
    effects = Counter(g for raw in env.state.trace.records for r in [json.loads(raw)]
                      if r.get('effect_completed') for g in r.get('effect_gate_ids',[]))
    result = dict(status='failed' if error else 'completed',failure=error,
        native_program_reused=native_result is not None,
        native_stats=native['stats'],native_call_seconds=native['native_call_seconds'],
        process_wall_seconds=native['process_wall_seconds'],author_metrics=native['author_metrics'],
        adapter_execute_record_seconds=seconds,independent_replay_seconds=perf_counter()-replay_start,
        replay_equal=replay_error is None and replay.snapshot()==env.snapshot(),
        effects_once=effects==Counter({g.id:1 for g in env.state.dag.circuit.gates}),
        terminal_verified=error is None,
        metrics=env.state.metrics(),decisions=adapter.decisions,capacity_adaptations=adapter.capacity_adaptations,
        local_physical_profile='paired SLM, SZ10um, EZ2um, orthogonal, neighbor reservation disabled',
        benchmark_equivalence='Different geometry/timing; compare native paper-profile results separately')
    if not error and (not result['replay_equal'] or not result['effects_once']):
        result['status'] = 'failed'
    directory.mkdir(parents=True,exist_ok=True)
    for name,data in [('result.json',result),('recording.json',recorder.payload()),('plans.json',primitive(adapter.plans))]:
        (directory/name).write_text(canonical_json(data),encoding='utf-8')
    (directory/'initial.json').write_text(initial,encoding='utf-8')
    (directory/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
    recorder.write(directory/'physical.html')
    return result
