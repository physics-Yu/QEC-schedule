"""Physical atom records. No quantum state or Hamiltonian is stored."""
from dataclasses import dataclass
from enum import Enum

from .geometry import Position


class AtomType(str, Enum):
    DATA = "DATA"
    ANCILLA = "ANCILLA"
    RESERVOIR = "RESERVOIR"


class AtomState(str, Enum):
    IDLE = "IDLE"
    HELD_STATIC = "HELD_STATIC"
    AOD_CAPTURED = "AOD_CAPTURED"
    MOVING = "MOVING"
    GATING = "GATING"
    MEASURING = "MEASURING"
    IN_ENTANGLING_REGION = "IN_ENTANGLING_REGION"
    IN_MEASUREMENT_REGION = "IN_MEASUREMENT_REGION"
    MEASURED = "MEASURED"
    LOST = "LOST"


@dataclass(frozen=True)
class Atom:
    atom_id: str
    assigned_qubit: str | None
    atom_type: AtomType
    position: Position
    zone: str | None
    site_id: str | None
    state: AtomState = AtomState.IDLE
    syndrome_basis: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "atom_type", AtomType(self.atom_type))
        object.__setattr__(self, "state", AtomState(self.state))
        if not isinstance(self.atom_id, str) or not self.atom_id.strip():
            raise ValueError("atom_id must be nonempty")
        if self.atom_type == AtomType.RESERVOIR:
            if self.assigned_qubit is not None:
                raise ValueError("Reservoir atoms are unassigned")
        elif not isinstance(self.assigned_qubit, str) or not self.assigned_qubit.strip():
            raise ValueError("Data/ancilla atoms require an assigned qubit")
        if self.atom_type == AtomType.ANCILLA:
            if self.syndrome_basis not in ("X", "Y", "Z", "MIXED"):
                raise ValueError("Ancilla needs its stabilizer basis")
        elif self.syndrome_basis is not None:
            raise ValueError("Only ancillas have a syndrome basis")
        if self.state in (AtomState.MOVING, AtomState.LOST):
            if self.zone is not None or self.site_id is not None:
                raise ValueError("Moving/lost atoms must release their static zone and site")
        elif self.state in (AtomState.AOD_CAPTURED, AtomState.IN_ENTANGLING_REGION,
                            AtomState.IN_MEASUREMENT_REGION, AtomState.MEASURED):
            if not self.zone or self.site_id is not None:
                raise ValueError("Dynamic-region atoms need a zone and no fixed trap site")
        elif not self.zone or not self.site_id:
            raise ValueError("A stationary atom must occupy a zone and trap site")

    def to_dict(self):
        return {"atom_id": self.atom_id, "assigned_qubit": self.assigned_qubit,
                "atom_type": self.atom_type.value, "position": self.position.to_list(),
                "zone": self.zone, "site_id": self.site_id, "state": self.state.value,
                "syndrome_basis": self.syndrome_basis}
