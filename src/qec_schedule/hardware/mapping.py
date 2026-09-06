"""Deterministic initial placement consuming only the public QECCode interface."""
from collections.abc import Mapping

from ..qec.code import QECCode
from .atom import Atom, AtomType
from .config import HardwareConfig
from .hardware_state import HardwareState
from .zones import ZoneKind


def build_initial_state(code: QECCode, config: HardwareConfig, *, placements: Mapping[str, str] | None = None) -> HardwareState:
    code.validate()
    qubits = code.data_qubits() + code.ancilla_qubits()
    storage = [(z, s) for z in config.zones if z.kind == ZoneKind.STORAGE for s in z.sites[:z.capacity]]
    if placements is None:
        if len(qubits) > len(storage):
            raise ValueError("Insufficient storage capacity for code qubits")
        locations = dict(zip(qubits, storage))
    else:
        if set(placements) != set(qubits):
            raise ValueError("Explicit placement must cover every code qubit exactly")
        all_sites = {s.id: (z, s) for z in config.zones if z.kind == ZoneKind.STORAGE for s in z.sites}
        if not set(placements.values()) <= all_sites.keys():
            raise ValueError("Initial placement must use known storage sites")
        locations = {q: all_sites[site] for q, site in placements.items()}
    ancilla_bases = {s.ancilla: s.basis for s in code.stabilizers()}
    data = set(code.data_qubits())
    atoms = []
    for q in qubits:
        zone, site = locations[q]
        atoms.append(Atom(f"atom:{q}", q, AtomType.DATA if q in data else AtomType.ANCILLA,
                          site.position, zone.id, site.id, syndrome_basis=ancilla_bases.get(q)))
    reservoir = [(z, s) for z in config.zones if z.kind == ZoneKind.RESERVOIR for s in z.sites[:z.capacity]]
    for i, (zone, site) in enumerate(reservoir[:config.reservoir_atoms]):
        atoms.append(Atom(f"R{i}", None, AtomType.RESERVOIR, site.position, zone.id, site.id))
    return HardwareState(tuple(atoms), config.zones, min_atom_separation=config.min_atom_separation)
