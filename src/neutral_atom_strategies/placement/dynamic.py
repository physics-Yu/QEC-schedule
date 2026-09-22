"""Dynamic placement boundary; initial-placement delivery does not enable reuse.

Policies propose holder assignments. A transport realizer must validate and
execute them. The fixed-target policy is an explicit baseline, not optimization.
"""
from dataclasses import dataclass
from typing import Protocol
from .models import LandingProposal


class DynamicPlacementPolicy(Protocol):
    def propose(self, snapshot, atom_ids: tuple[str, ...]) -> LandingProposal: ...


@dataclass(frozen=True)
class FixedReturnPolicy:
    destinations: tuple[tuple[str, str], ...]

    def __post_init__(self):
        proposal = LandingProposal(self.destinations, 'fixed baseline')
        object.__setattr__(self,'destinations',proposal.destinations)

    def propose(self, snapshot, atom_ids):
        mapping = dict(self.destinations)
        if len(set(atom_ids)) != len(atom_ids):
            raise ValueError('Duplicate requested atom')
        pairs = []
        for q in atom_ids:
            if q not in snapshot.atoms or q not in mapping or mapping[q] not in snapshot.world.traps:
                raise ValueError('Unknown atom or destination')
            pairs.append((q, mapping[q]))
        return LandingProposal(tuple(pairs), 'explicit fixed return baseline; routing still required')
