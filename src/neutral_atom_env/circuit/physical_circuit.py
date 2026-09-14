from dataclasses import dataclass
from neutral_atom_env.domain.models import PhysicalGate


@dataclass(frozen=True)
class PhysicalCircuit:
    gates: tuple[PhysicalGate, ...]

    def __post_init__(self):
        object.__setattr__(self, "gates", tuple(self.gates))
        if len({g.id for g in self.gates}) != len(self.gates):
            raise ValueError("Duplicate gate ID")
        earlier={}
        for gate in self.gates:
            if any(g not in earlier for g in gate.depends_on):
                raise ValueError('Explicit gate dependencies must reference earlier gates')
            if any(g not in earlier or earlier[g].gate_type not in {'MEASURE','MZ'} for g,_ in gate.condition):
                raise ValueError('Conditions must reference earlier measurement gates')
            earlier[gate.id]=gate
