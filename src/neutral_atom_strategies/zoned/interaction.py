"""Explicit intent -> placement -> physical program boundary.

Only this adapter knows the current IDS placement / SLM-anchor implementation.
The intent IR does not depend on it. Native compilers that already resolved
sites should keep their resolved output, not discard it and re-run this search.
"""
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Position2D, ZoneType
from neutral_atom_env.domain.operations import CompiledPlan
from neutral_atom_env.program.binding import fingerprint
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.ir import InteractionBlock, MoveToInteraction, ApplyInteraction
from neutral_atom_strategies.motion.ordered_primitives import new_builder, finish
from neutral_atom_strategies.motion.single_trap import in_zone
from .models import LayerPlacement


class InteractionResolver(Protocol):
    """Replaceable placement decision layer; never operates the live env."""
    def search(self, state, gates, deadline) -> tuple[LayerPlacement, ...]: ...


class InteractionLowerer(Protocol):
    def layer(self, builder, placement: LayerPlacement): ...


@dataclass(frozen=True)
class ResolvedInteraction:
    request: MoveToInteraction
    state_fingerprint: str
    placement: LayerPlacement

    def to_dict(self):
        return {'request_id': self.request.id, 'state_fingerprint': self.state_fingerprint,
                'placement': primitive(self.placement)}


@dataclass(frozen=True)
class LoweredInteraction:
    plan: CompiledPlan
    resolved: ResolvedInteraction
    codegen_seconds: float
    audit_seconds: float


class InteractionCompiler:
    def __init__(self, resolver: InteractionResolver, lowerer: InteractionLowerer, deadline):
        self.resolver, self.lowerer, self.deadline = resolver, lowerer, deadline

    @staticmethod
    def _gates(state, move):
        if move.zone != ZoneType.ENTANGLEMENT.value:
            raise ValidationError('INTERACTION_ZONE_UNSUPPORTED',
                                  'Current resolver supports the entanglement zone type only')
        ready = {g.id: g for g in state.dag.ready_gates()}
        gates = []
        for pair in move.pairs:
            gate = ready.get(pair.gate_id)
            if gate is None or gate.gate_type != 'CZ' or set(gate.qubit_ids) != set(pair.atom_ids):
                raise ValidationError('INTERACTION_GATE_MISMATCH',
                                      'Intent must reference READY CZ gates and their actual operands')
            gates.append(gate)
        return tuple(gates)

    @staticmethod
    def _binding(state, move, placement):
        requested = {p.gate_id: set(p.atom_ids) for p in move.pairs}
        if (len(placement.choices) != len(requested) or
                {c.gate_id for c in placement.choices} != set(requested)):
            raise ValidationError('INTERACTION_BINDING_MISMATCH', 'Resolver changed the requested gates')
        if any(q not in move.atom_ids for q, _ in placement.staging):
            raise ValidationError('INTERACTION_BINDING_MISMATCH', 'Resolver staged an unrequested spectator')
        for choice in placement.choices:
            site = state.world.traps.get(choice.site)
            if {choice.anchor, choice.mobile} != requested[choice.gate_id]:
                raise ValidationError('INTERACTION_BINDING_MISMATCH', 'Resolver changed interaction operands')
            if (site is None or not in_zone(state, site.position, ZoneType.ENTANGLEMENT) or
                    not in_zone(state, Position2D(choice.x, choice.y), ZoneType.ENTANGLEMENT)):
                raise ValidationError('INTERACTION_BINDING_ZONE', 'Resolved interaction is outside the requested zone')
        # Pair distance, capture closure, all unintended interactions and swept
        # trajectories remain mandatory physical checks during lowering.

    def resolve(self, state, move: MoveToInteraction):
        gates = self._gates(state, move)
        placements = self.resolver.search(state, gates, self.deadline)
        stamp = fingerprint(state)
        result = []
        for placement in placements:
            self._binding(state, move, placement)
            result.append(ResolvedInteraction(move, stamp, placement))
        return tuple(result)

    def lower(self, state, resolved: ResolvedInteraction, apply: ApplyInteraction):
        # Constructing the block verifies that Move cannot authorize a different
        # pulse. Explicit Apply is mandatory even for already-positioned atoms.
        InteractionBlock(resolved.request, apply)
        if fingerprint(state) != resolved.state_fingerprint:
            raise ValidationError('INTERACTION_STALE_BINDING', 'Resolve again against the current physical state')
        self._gates(state, resolved.request)
        self._binding(state, resolved.request, resolved.placement)
        builder = new_builder(state, apply.gate_ids)
        started = perf_counter()
        self.lowerer.layer(builder, resolved.placement)
        codegen_seconds = perf_counter() - started
        started = perf_counter()
        plan = finish(builder, compiler='zoned-interaction-ir-v1')
        return LoweredInteraction(plan, resolved, codegen_seconds, perf_counter()-started)
