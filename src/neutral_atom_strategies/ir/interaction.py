"""Serializable, coordinate-free requests for an interaction service.

Move requests a relation between atoms, not two coincident trap positions and
not necessarily physical displacement of both operands. It has no gate effect.
Apply explicitly authorizes the referenced circuit gates. Independent pairs
may be split into physical batches; this IR makes no simultaneity guarantee.
"""
from dataclasses import dataclass


def _identifier(value):
    if not isinstance(value, str) or not value:
        raise ValueError('IR identifiers must be nonempty strings')
    return value


@dataclass(frozen=True)
class InteractionPair:
    gate_id: str
    atom_ids: tuple[str, str]

    def __post_init__(self):
        _identifier(self.gate_id)
        object.__setattr__(self, 'atom_ids', tuple(self.atom_ids))
        if len(self.atom_ids) != 2 or len(set(self.atom_ids)) != 2:
            raise ValueError('An interaction requires two distinct atoms')
        for atom in self.atom_ids:
            _identifier(atom)


@dataclass(frozen=True)
class MoveToInteraction:
    id: str
    pairs: tuple[InteractionPair, ...]
    zone: str = 'entanglement'

    def __post_init__(self):
        _identifier(self.id)
        _identifier(self.zone)
        object.__setattr__(self, 'pairs', tuple(self.pairs))
        if not self.pairs or not all(isinstance(p, InteractionPair) for p in self.pairs):
            raise ValueError('MoveToInteraction requires interaction pairs')
        if len(set(self.gate_ids)) != len(self.pairs):
            raise ValueError('Duplicate interaction gate')
        atoms = [q for p in self.pairs for q in p.atom_ids]
        if len(set(atoms)) != len(atoms):
            raise ValueError('One interaction block requires disjoint pairs')

    @property
    def gate_ids(self):
        return tuple(p.gate_id for p in self.pairs)

    @property
    def atom_ids(self):
        return frozenset(q for p in self.pairs for q in p.atom_ids)


@dataclass(frozen=True)
class ApplyInteraction:
    move_id: str
    gate_ids: tuple[str, ...]

    def __post_init__(self):
        _identifier(self.move_id)
        object.__setattr__(self, 'gate_ids', tuple(self.gate_ids))
        if not self.gate_ids or len(set(self.gate_ids)) != len(self.gate_ids):
            raise ValueError('ApplyInteraction requires unique gate IDs')
        for gate in self.gate_ids:
            _identifier(gate)


@dataclass(frozen=True)
class InteractionBlock:
    move: MoveToInteraction
    apply: ApplyInteraction

    def __post_init__(self):
        if self.apply.move_id != self.move.id or set(self.apply.gate_ids) != set(self.move.gate_ids):
            raise ValueError('ApplyInteraction must reference exactly its prepared pairs')

    @classmethod
    def for_gates(cls, gates, *, id, zone='entanglement'):
        gates = tuple(gates)
        if any(g.gate_type != 'CZ' for g in gates):
            raise ValueError('Current interaction lowering supports CZ only')
        move = MoveToInteraction(id, tuple(InteractionPair(g.id, g.qubit_ids) for g in gates), zone)
        return cls(move, ApplyInteraction(move.id, move.gate_ids))

    def to_dict(self):
        return {'schema': 'interaction-ir-v1', 'move': {
            'id': self.move.id, 'zone': self.move.zone,
            'pairs': [{'gate_id': p.gate_id, 'atom_ids': list(p.atom_ids)} for p in self.move.pairs]},
            'apply': {'move_id': self.apply.move_id, 'gate_ids': list(self.apply.gate_ids)}}

    @classmethod
    def from_dict(cls, value):
        # Reject concrete coordinates or unknown hints instead of silently
        # discarding an external compiler's placement decisions.
        if set(value) != {'schema', 'move', 'apply'} or value['schema'] != 'interaction-ir-v1':
            raise ValueError('Unsupported interaction IR schema')
        move, apply = value['move'], value['apply']
        if set(move) != {'id', 'zone', 'pairs'} or set(apply) != {'move_id', 'gate_ids'}:
            raise ValueError('Unexpected interaction IR fields')
        pairs = []
        for pair in move['pairs']:
            if set(pair) != {'gate_id', 'atom_ids'}:
                raise ValueError('Unexpected interaction pair fields')
            pairs.append(InteractionPair(pair['gate_id'], pair['atom_ids']))
        return cls(MoveToInteraction(move['id'], tuple(pairs), move['zone']),
                   ApplyInteraction(apply['move_id'], apply['gate_ids']))
