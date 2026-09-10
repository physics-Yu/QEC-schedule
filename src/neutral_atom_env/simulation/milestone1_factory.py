from dataclasses import replace
from pathlib import Path
import json
from neutral_atom_env.domain.models import (Position2D, Rectangle, StaticTrap, GridCoord, Zone, ZoneType,
    Atom, HolderRef, HolderType, PhysicalGate)
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from .state import SimulationState


def make_single_gate_state(scenario='baseline'):
    path=Path(__file__).resolve().parents[3]/'configs/hardware/milestone1.json'
    values=json.loads(path.read_text(encoding='utf-8'))
    geometry={key:values.pop(key) for key in ('rows','columns','spacing_um')}
    values['interaction_offset']=Position2D(**values['interaction_offset'])
    hardware=HardwareConfig(**values)
    positions=[Position2D(0,0),Position2D(5,-25),Position2D(15,5),Position2D(20,5)]
    if scenario=='incidental':positions[2]=Position2D(10,5)
    elif scenario=='unintended':positions[2:]=[Position2D(5,0),Position2D(10,-25)]
    elif scenario=='blocked':positions[3]=Position2D(3,-10)
    elif scenario=='both_storage':positions[1]=Position2D(5,0)
    elif scenario!='baseline':raise ValueError('Unknown M1 scenario')
    zones=(Zone('storage',ZoneType.STORAGE,Rectangle(Position2D(-5,-12 if scenario=='blocked' else -5),Position2D(25,10))),
           Zone('entanglement',ZoneType.ENTANGLEMENT,Rectangle(Position2D(-5,-30),Position2D(25,-15))),
           Zone('measurement',ZoneType.MEASUREMENT,Rectangle(Position2D(-5,-45),Position2D(25,-35))))
    traps={f'S{i:03d}':StaticTrap(f'S{i:03d}',GridCoord(round(p.x_um/(1 if scenario=='blocked' else 5)),round(p.y_um/(1 if scenario=='blocked' else 5))),p) for i,p in enumerate(positions)}
    world=WorldState(Rectangle(Position2D(-5,-45),Position2D(30,10)),traps,zones,1 if scenario=='blocked' else 5)
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(4)}
    holders=PlacementState({a:HolderRef(HolderType.STATIC,f'S{i:03d}') for i,a in enumerate(atoms)})
    circuit=PhysicalCircuit((PhysicalGate('G000','CZ',('Q000','Q001')),))
    return SimulationState(world,holders,atoms,AODRuntimeState(**geometry),DynamicGateDAG(circuit),hardware=hardware)
