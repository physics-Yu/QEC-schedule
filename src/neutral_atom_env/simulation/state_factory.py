from neutral_atom_env.domain.models import (Position2D, Rectangle, StaticTrap, GridCoord,
    Zone, ZoneType, Atom, HolderRef, HolderType, PhysicalGate)
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from .state import SimulationState
from neutral_atom_env.world.config import LayoutConfig
from dataclasses import replace


def make_demo_state(seed=0):
    world = LayoutConfig(columns=4, rows=1, zone_height_um=10, isolation_gap_um=10).build()
    world = replace(world, traps={f's{i}': replace(t,id=f's{i}') for i,t in enumerate(world.traps.values())})
    atoms = {f"Q{i:03d}": Atom(f"Q{i:03d}") for i in range(4)}
    placement = PlacementState({a: HolderRef(HolderType.STATIC, f"s{i}") for i, a in enumerate(atoms)})
    circuit = PhysicalCircuit((PhysicalGate("g1", "CZ", ("Q000", "Q001")),
                               PhysicalGate("g2", "H", ("Q002",)),
                               PhysicalGate("g3", "CZ", ("Q000", "Q002"))))
    return SimulationState(world, placement, atoms, AODRuntimeState(), DynamicGateDAG(circuit), seed)
