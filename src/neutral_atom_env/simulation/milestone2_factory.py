"""Declared M2 family: storage sources Q000/Q003; static EZ partners Q001/Q002."""
from dataclasses import replace
from neutral_atom_env.domain.models import Position2D, GridCoord, PhysicalGate
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from .milestone1_factory import make_single_gate_state


def make_circuit_state(scenario='three_gate'):
    if scenario=='unsupported':
        return make_single_gate_state('both_storage')
    state=make_single_gate_state()
    positions=[Position2D(0,0),Position2D(5,-25),Position2D(15,-25),Position2D(20,0)]
    traps={key:replace(trap,position=positions[i],grid=GridCoord(round(positions[i].x_um/5),round(positions[i].y_um/5)))
           for i,(key,trap) in enumerate(state.world.traps.items())}
    pairs={
        'repeat':[(0,1),(0,1)],
        'switch_partner':[(0,1),(0,2)],
        'three_gate':[(0,1),(0,2),(1,3)],
        'join':[(0,1),(3,2),(0,2)],
    }[scenario]
    circuit=PhysicalCircuit(tuple(PhysicalGate(f'G{i:03d}','CZ',tuple(f'Q{q:03d}' for q in pair)) for i,pair in enumerate(pairs)))
    return replace(state,world=replace(state.world,traps=traps),dag=DynamicGateDAG(circuit))
