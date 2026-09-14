"""Circuit + platform + placement -> replaceable compiler -> actual execution.

This entry point contains no gate sequence, atom-count, coordinate, or route fixture.
"""
from dataclasses import dataclass
import json
from pathlib import Path
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import PhysicalGate, Position2D, Rectangle, StaticTrap, GridCoord, Zone, ZoneType, Atom, HolderRef, HolderType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.planning.eager_baseline import EagerBaseline
from neutral_atom_env.planning.compilers import make_compiler
from neutral_atom_env.visualization import VisualRecorder
from .state import SimulationState
from .scheduler import EagerScheduler


def load_circuit(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    return PhysicalCircuit(tuple(PhysicalGate(**g) for g in value['gates']))


@dataclass(frozen=True)
class Platform:
    world: WorldState
    hardware: HardwareConfig
    aod: AODRuntimeState

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        def rect(v):
            return Rectangle(Position2D(**v['lower']), Position2D(**v['upper']))
        w = data['world']
        traps = {}
        origin = Position2D(**w.get('grid_origin', {'x_um': 0, 'y_um': 0}))
        spacing = w['grid_spacing_um']
        for t in w['traps']:
            if t['id'] in traps:
                raise ValueError('Duplicate trap ID')
            pos = Position2D(**t['position'])
            traps[t['id']] = StaticTrap(t['id'], GridCoord(round((pos.x_um-origin.x_um)/spacing),
                                  round((pos.y_um-origin.y_um)/spacing)), pos, t.get('enabled', True))
        world = WorldState(rect(w['bounds']), traps,
                           tuple(Zone(z['id'], ZoneType(z['zone_type']), rect(z['bounds'])) for z in w['zones']), spacing, origin)
        hw = dict(data.get('hardware', {}))
        for name in ('interaction_offset', 'mobile_pair_center'):
            if name in hw:
                hw[name] = Position2D(**hw[name])
        aod = dict(data['aod'])
        if 'pose' in aod:
            aod['pose'] = Position2D(**aod['pose'])
        return cls(world, HardwareConfig(**hw), AODRuntimeState(**aod))


def initialize(circuit, platform, placement, *, seed=0):
    """placement maps physical qubit IDs to enabled SLM traps, independent of circuit."""
    atoms = {q: Atom(q) for q in placement}
    holders = PlacementState({q: HolderRef(HolderType.STATIC, trap) for q, trap in placement.items()})
    return SimulationState(platform.world, holders, atoms, platform.aod, DynamicGateDAG(circuit), seed=seed, hardware=platform.hardware)


def run_circuit(circuit, platform, placement, *, compiler=None, policy=None, seed=0, on_event=None):
    if compiler is not None and policy is not None:
        raise ValueError('Pass compiler or a policy that owns its compiler, not both')
    state = initialize(circuit, platform, placement, seed=seed)
    recorder = VisualRecorder(state)
    def observe(s, event):
        recorder.observe(s, event)
        if on_event is not None:
            on_event(s, event)
    result = EagerScheduler(state, policy=policy or EagerBaseline(compiler=compiler or make_compiler())).run(observe)
    return result, state, recorder
