"""All-SZ initial layouts; EZ has an empty, explicitly configured parking trap."""
from neutral_atom_env.domain.models import Position2D,Rectangle,StaticTrap,GridCoord,Zone,ZoneType,Atom,HolderRef,HolderType,PhysicalGate
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState,PlacementState,AODRuntimeState
from neutral_atom_env.circuit import PhysicalCircuit,DynamicGateDAG
from .state import SimulationState


def make_rigid_parking_state(scenario='circuit',*,circuit=None):
    if scenario not in {'pair','circuit','incidental'}:raise ValueError('Unknown rigid parking scenario')
    count=2 if scenario=='pair' else 4
    positions=[Position2D(0,0),Position2D(10,0),Position2D(0,10),Position2D(10,10)][:count]
    traps={f'S{i:03d}':StaticTrap(f'S{i:03d}',GridCoord(round(p.x_um/5),round(p.y_um/5)),p) for i,p in enumerate(positions)}
    traps['EZ_PARK']=StaticTrap('EZ_PARK',GridCoord(1,-7),Position2D(5,-35))
    zones=tuple(Zone(name,kind,Rectangle(Position2D(-25,lo),Position2D(45,hi))) for name,kind,lo,hi in
        [('storage',ZoneType.STORAGE,-10,25),('entanglement',ZoneType.ENTANGLEMENT,-50,-20),('measurement',ZoneType.MEASUREMENT,-70,-55)])
    world=WorldState(Rectangle(Position2D(-25,-70),Position2D(45,25)),traps,zones,5)
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(count)}
    placement=PlacementState({q:HolderRef(HolderType.STATIC,f'S{i:03d}') for i,q in enumerate(atoms)})
    if circuit is None:
        pairs=[(0,1)] if scenario!='circuit' else [(0,1),(2,3),(0,2),(1,3),(0,3),(1,2)]
        circuit=PhysicalCircuit(tuple(PhysicalGate(f'G{i:03d}','CZ',tuple(f'Q{q:03d}' for q in pair)) for i,pair in enumerate(pairs)))
    return SimulationState(world,placement,atoms,AODRuntimeState(rows=2,columns=2,spacing_um=10),DynamicGateDAG(circuit),hardware=HardwareConfig(selective_transfer_enabled=True))
