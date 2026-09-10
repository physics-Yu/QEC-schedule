"""Derive visual activity from immutable snapshots; never modify simulation state."""
from dataclasses import dataclass
import json
from math import ceil, floor
from neutral_atom_env.domain.models import Position2D, StaticTrap, Zone, Rectangle, HolderRef


@dataclass(frozen=True)
class SceneAtom:
    id: str
    holder: HolderRef
    position: Position2D | None
    activity: str
    measured: bool


@dataclass(frozen=True)
class VisualScene:
    bounds: Rectangle
    spacing_um: float
    grid_x: tuple[float, ...]
    grid_y: tuple[float, ...]
    candidates: tuple[Position2D, ...]
    zones: tuple[Zone, ...]
    traps: tuple[StaticTrap, ...]
    atoms: tuple[SceneAtom, ...]


def build_scene(snapshot: str) -> VisualScene:
    from neutral_atom_env.simulation.state import SimulationState
    state = SimulationState.restore(snapshot)
    data = json.loads(snapshot)
    world = state.world
    def axis(lo,hi,origin):
        return tuple(origin+i*world.grid_spacing_um for i in range(
            ceil((lo-origin)/world.grid_spacing_um),floor((hi-origin)/world.grid_spacing_um)+1))
    xs = axis(world.bounds.lower.x_um,world.bounds.upper.x_um,world.grid_origin.x_um)
    ys = axis(world.bounds.lower.y_um,world.bounds.upper.y_um,world.grid_origin.y_um)
    return VisualScene(world.bounds,world.grid_spacing_um,xs,ys,
        tuple(Position2D(x,y) for x in xs for y in ys if world.is_candidate_site(Position2D(x,y))),
        world.zones,tuple(t for _,t in sorted(world.traps.items())),
        tuple(SceneAtom(a.id,state.placement.atom_to_holder[a.id],
            state.placement.position(a.id,world,state.aod),atom_activity(data,a.id),a.measured)
            for _,a in sorted(state.atoms.items())))


def atom_activity(data, atom_id):
    holder = data["placement"]["atom_to_holder"][atom_id]
    if holder["holder_type"] == "lost":
        return "lost"
    for node in data["dag"].values():
        if node["status"] == "running" and atom_id in node["gate"]["qubit_ids"]:
            return "measuring" if node["gate"]["gate_type"] == "MEASURE" else "gating"
    if holder["holder_type"] == "mobile" and data["aod"].get("is_moving", False):
        runtime=data.get('active_plan')
        if runtime:
            from neutral_atom_env.replay.trajectory import axes_from_dict, target_axes
            op=runtime['plan']['operations'][runtime['operation_index']]
            start=axes_from_dict(data['aod']);end=target_axes(data['aod'],op)
            cell=holder['holder_id'];col,row=cell['column'],cell['row']
            if abs(start.x_um[col]-end.x_um[col])<1e-12 and abs(start.y_um[row]-end.y_um[row])<1e-12:
                return 'idle'
        return "moving"
    return "idle"


def gate_label(node):
    gate = node["gate"]
    return f"{gate['gate_type']}({', '.join(gate['qubit_ids'])})"


def activity_color(activity, theme):
    return theme["active_color"] if activity in {"gating", "measuring"} else (
        theme["moving_color"] if activity == "moving" else theme["static_color"])
