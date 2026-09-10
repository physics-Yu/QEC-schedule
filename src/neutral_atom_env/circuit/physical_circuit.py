from dataclasses import dataclass
from neutral_atom_env.domain.models import PhysicalGate


@dataclass(frozen=True)
class PhysicalCircuit:
    gates: tuple[PhysicalGate, ...]

    def __post_init__(self):
        object.__setattr__(self, "gates", tuple(self.gates))
        if len({g.id for g in self.gates}) != len(self.gates):
            raise ValueError("Duplicate gate ID")
