"""Rank explicit post-CZ SLM landing intents before asking a router for paths."""
from math import hypot
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.models import HolderRef, HolderType, ZoneType
from neutral_atom_env.domain.operations import CaptureBinding
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
from neutral_atom_strategies.motion.single_trap import in_zone
from .reuse import future_partners


def landing_candidates(state, bindings, limit=8):
    """Rigid projections of the loaded batch plus its original support fallback.

    This changes no logical mapping. Full axis sweeps and OFFLOAD are checked by
    codegen. General row/column reshaping at the landing is a later extension.
    """
    current=state.aod.configuration()
    positions={b.atom_id:current.position(b.cell) for b in bindings}
    first=positions[bindings[0].atom_id]
    lookup={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
            if in_zone(state,t.position,ZoneType.ENTANGLEMENT) and t.id not in state.placement.static_occupancy}
    partners=future_partners(state)
    candidates=[]
    for (x,y),tid in lookup.items():
        dx,dy=x-first.x_um,y-first.y_um
        targets={b.atom_id:lookup.get((positions[b.atom_id].x_um+dx,positions[b.atom_id].y_um+dy)) for b in bindings}
        if any(t is None for t in targets.values()):continue
        holders=dict(state.placement.atom_to_holder)
        for q,t in targets.items():holders[q]=HolderRef(HolderType.STATIC,t)
        try:validate_ez_neighbors(state,holders=holders)
        except ValidationError:continue
        target=AODConfiguration(tuple(v+dx for v in current.x_um),tuple(v+dy for v in current.y_um))
        if (target.x_um[0]<state.world.bounds.lower.x_um or target.x_um[-1]>state.world.bounds.upper.x_um
                or target.y_um[0]<state.world.bounds.lower.y_um or target.y_um[-1]>state.world.bounds.upper.y_um):continue
        cost=hypot(dx,dy)
        for q,tid in targets.items():
            partner=partners.get(q)
            if partner and partner not in targets:
                p=state.placement.position(partner,state.world,state.aod);t=state.world.traps[tid].position
                cost+=.1*hypot(t.x_um-p.x_um,t.y_um-p.y_um)
        unload=tuple(CaptureBinding(b.atom_id,b.cell,targets[b.atom_id]) for b in bindings)
        candidates.append((cost,target,unload))
    candidates.sort(key=lambda v:(v[0],v[1].x_um,v[1].y_um))
    return tuple(candidates[:limit])
