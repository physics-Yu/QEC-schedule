"""Stage-A fixtures; no production demo, application, or greedy imports."""
import random
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import Atom, GridCoord, HolderRef, HolderType, PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState


def make_snapshot(gates,atom_count=4,seed=0):
    if type(atom_count) is not int or atom_count not in (4,6,8):
        raise ValueError('Stage-A fixture supports 4, 6, or 8 atoms')
    width=atom_count//2
    points=[P(i*10,j*20) for j in range(2) for i in range(width)]
    bounds=Rectangle(P(-40,-40),P(width*10+40,70))
    traps={f'S{i}':StaticTrap(f'S{i}',GridCoord(round(p.x_um/5),round(p.y_um/5)),p) for i,p in enumerate(points)}
    world=WorldState(bounds,traps,(Zone('EZ',ZoneType.ENTANGLEMENT,bounds),))
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(atom_count)}
    holders={q:HolderRef(HolderType.STATIC,f'S{i}') for i,q in enumerate(atoms)}
    circuit=PhysicalCircuit(tuple(PhysicalGate(f'g{i:04d}',kind,tuple(f'Q{q:03d}' for q in qs)) for i,(kind,qs) in enumerate(gates)))
    state=SimulationState(world,PlacementState(holders),atoms,
        AODRuntimeState(pose=P(-20,-20),rows=1,columns=width,spacing_um=10,
                        enabled_rows=(False,),enabled_columns=(False,)*width),
        DynamicGateDAG(circuit),seed=seed,hardware=HardwareConfig(backend='row_column_orthogonal'))
    return NeutralAtomEnv(state).snapshot()


def suite(seed=0):
    rng=random.Random(seed)
    random_gates=[]
    for _ in range(6):
        if rng.random()<0.35:
            random_gates.append(('CZ',rng.sample(range(4),2)))
        else:random_gates.append((rng.choice(['H','X','Y','Z','T']),[rng.randrange(4)]))
    return {
        'parallel_h': (4,[('H',[q]) for q in range(4)]),
        'parallel_cz': (4,[('H',[q]) for q in range(4)]+[('CZ',[0,2]),('CZ',[1,3])]),
        'dependency': (4,[('H',[0]),('X',[1]),('CZ',[0,2]),('H',[2]),('CZ',[1,3]),('Z',[3])]),
        'random_mixed': (4,random_gates),
        'six_atoms': (6,[('H',[q]) for q in range(6)]+[('CZ',[i,i+3]) for i in range(3)]),
        'eight_atoms': (8,[('H',[q]) for q in range(8)]+[('CZ',[i,i+4]) for i in range(4)]),
    }
