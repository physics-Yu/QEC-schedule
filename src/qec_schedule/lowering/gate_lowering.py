"""Semantic gate lowering plus the explicitly named pre-refactor adapter."""
from dataclasses import dataclass, replace
from typing import Protocol

from ..compiler import PhysicalCircuit, PhysicalCircuitDAG, PhysicalGate
from ..compiler.semantic_requests import SemanticGateLowerer
from ..hardware import ActionTiming, AtomState, HardwareState, ZoneKind
from .experimental_ir import (ActionType, ExperimentalAction, ExperimentalPlan, Reservation,
                              ResourceRequirement, SiteRef)


@dataclass(frozen=True)
class PairDestination:
    zone: str
    slot: str
    sites: tuple[SiteRef, SiteRef]


class DestinationPolicy(Protocol):
    def pair(self, gate: PhysicalGate, candidates: tuple[PairDestination, ...], index: int) -> PairDestination: ...
    def measurement(self, gate: PhysicalGate, candidates: tuple[SiteRef, ...], index: int) -> SiteRef: ...


class RoundRobinDestinations:
    """Deterministic placement baseline. This is not a scheduler priority rule."""
    def pair(self, gate, candidates, index):
        return candidates[index % len(candidates)]

    def measurement(self, gate, candidates, index):
        return candidates[index % len(candidates)]


class LegacyGateLowerer:
    def __init__(self, timing: ActionTiming | None = None, *, destinations: DestinationPolicy | None = None):
        self.timing = timing if timing is not None else ActionTiming()
        self.destinations = destinations if destinations is not None else RoundRobinDestinations()

    def lower(self, circuit: PhysicalCircuit, state: HardwareState) -> ExperimentalPlan:
        return _PlanBuilder(circuit, state, self.timing, self.destinations).build()


class GateLowerer(SemanticGateLowerer):
    """Public lowering entry point for the runtime refactor.

    The optional timing argument is accepted for source compatibility with the
    old API but is intentionally ignored: semantic requests contain no timing
    or placement decisions. Use ``LegacyGateLowerer`` only for the migration
    compatibility tests and examples that still exercise the old IR.
    """

    def __init__(self, timing=None):
        self.timing = timing


class _PlanBuilder:
    def __init__(self, circuit, state, timing, destinations):
        PhysicalCircuitDAG(circuit)  # Includes same-qubit dependency validation.
        state.validate()
        if any(atom.state != AtomState.IDLE for atom in state.atoms):
            raise ValueError("Lowering requires an idle initial hardware snapshot")
        if not set(circuit.qubits) <= state.qubit_to_atom.keys():
            raise ValueError("Every physical circuit qubit needs an atom mapping")
        self.circuit, self.state, self.timing, self.destinations = circuit, state, timing, destinations
        self.zones = state.zones_by_id
        self.qubit_atoms = {q: state.atom_for_qubit(q).atom_id for q in circuit.qubits}
        self.homes = {}
        for q in circuit.qubits:
            atom = state.atom_for_qubit(q)
            if self.zones[atom.zone].kind != ZoneKind.STORAGE:
                raise ValueError("Initial circuit atoms must have home sites in Memory/Storage")
            self.homes[atom.atom_id] = SiteRef(atom.zone, atom.site_id, atom.position)
        self.locations = dict(self.homes)
        occupied = {a.site_id for a in state.atoms if a.site_id is not None}
        pairs, measurement = [], []
        for zone in state.zones:
            available = zone.capacity - len(state.atoms_in_zone(zone.id))
            sites = {s.id: SiteRef(zone.id, s.id, s.position) for s in zone.sites}
            if zone.kind == ZoneKind.ENTANGLING and zone.allows("ENTANGLE") and available >= 2:
                pairs.extend(PairDestination(zone.id, p.id, tuple(sites[s] for s in p.sites))
                             for p in zone.pair_slots if not set(p.sites) & occupied)
            if zone.kind == ZoneKind.MEASUREMENT and zone.allows("MEASURE") and available >= 1:
                measurement.extend(sites[s.id] for s in zone.sites if s.id not in occupied)
        self.pairs, self.measurement = tuple(pairs), tuple(measurement)
        self.pair_index = self.measure_index = 0
        self.actions, self.reservations = [], []
        self.completion = {}
        self.measurement_leases = {}  # atom -> reservation index, closes on departure.

    def emit(self, gate, kind, atoms, dependencies, duration, device, *, targets=None, metadata=None):
        sources = tuple(self.locations[a] for a in atoms)
        action = ExperimentalAction(
            id=f"{gate.id}/a{len(self.actions):06d}", gate_id=gate.id, action_type=kind,
            atoms=tuple(atoms), duration=duration, sources=sources, targets=sources if targets is None else targets,
            dependencies=tuple(sorted(set(dependencies))),
            required_resources=tuple(ResourceRequirement(f"atom_lock/{a}") for a in atoms) + (ResourceRequirement(f"device/{device}"),),
            metadata={**gate.metadata, "physical_gate": gate.gate_type.value, **(metadata or {})},
        )
        self.actions.append(action)
        return action.id

    def transit(self, gate, atom, destination, dependencies):
        source = self.locations[atom]
        if source == destination:
            return None, tuple(dependencies)
        transport_id = f"{gate.id}/transport{len(self.actions):06d}"
        metadata = {"transport_id": transport_id}
        pickup = self.emit(gate, "PICKUP", (atom,), dependencies, self.timing.pickup_duration, "aod", metadata=metadata)
        move = self.emit(gate, "MOVE", (atom,), (pickup,), source.position.distance_to(destination.position) / self.timing.move_speed,
                         "aod", targets=(destination,), metadata=metadata)
        self.locations[atom] = destination
        dropoff = self.emit(gate, "DROPOFF", (atom,), (move,), self.timing.dropoff_duration, "aod", metadata=metadata)
        # Controller/atom custody spans the complete transport, including gaps.
        # A future compatible movement epoch may merge multiple transport leases.
        self.reservations.append(Reservation(transport_id,
                                             (ResourceRequirement("device/aod"), ResourceRequirement(f"atom_lock/{atom}")),
                                             (pickup,), (dropoff,)))
        if atom in self.measurement_leases:
            index = self.measurement_leases.pop(atom)
            self.reservations[index] = replace(self.reservations[index], release_after=(dropoff,))
        return pickup, (dropoff,)

    def local(self, gate, kind, atom, dependencies, duration, device, operation, *, metadata=None):
        location = self.locations[atom]
        if not self.zones[location.zone].allows(operation):
            home = self.homes[atom]
            if not self.zones[home.zone].allows(operation):
                raise ValueError(f"No supported home zone for {operation} on {atom}")
            _, dependencies = self.transit(gate, atom, home, dependencies)
        return (self.emit(gate, kind, (atom,), dependencies, duration, device, metadata=metadata),)

    def entangle(self, gate, atoms, dependencies):
        if not self.pairs:
            raise ValueError("CZ/CNOT requires an available entangling pair slot with capacity for two atoms")
        destination = self.destinations.pair(gate, self.pairs, self.pair_index)
        if destination not in self.pairs:
            raise ValueError("Destination policy returned an invalid pair slot")
        self.pair_index += 1
        entries, arrivals = [], []
        for atom, target in zip(atoms, destination.sites):
            entry, terminals = self.transit(gate, atom, target, dependencies)
            entries.append(entry)
            arrivals.extend(terminals)
        pulse = self.emit(gate, "ENTANGLE", atoms, arrivals, self.timing.entangle_duration, "rydberg",
                          metadata={"gate": "CZ", "pair_slot": destination.slot})
        departures = []
        for atom in atoms:
            _, terminals = self.transit(gate, atom, self.homes[atom], (pulse,))
            departures.extend(terminals)
        self.reservations.append(Reservation(
            f"{gate.id}/pair", (ResourceRequirement(f"pair/{destination.zone}/{destination.slot}"),
                                ResourceRequirement(f"zone/{destination.zone}", 2),
                                *(ResourceRequirement(f"site/{s.site}") for s in destination.sites)),
            tuple(entries), tuple(departures),
        ))
        return tuple(departures)

    def measure(self, gate, atom, dependencies):
        source = self.locations[atom]
        if self.zones[source.zone].kind != ZoneKind.MEASUREMENT:
            if not self.measurement:
                raise ValueError("Measurement requires an available measurement site")
            destination = self.destinations.measurement(gate, self.measurement, self.measure_index)
            if destination not in self.measurement:
                raise ValueError("Destination policy returned an invalid measurement site")
            self.measure_index += 1
            entry, dependencies = self.transit(gate, atom, destination, dependencies)
            self.measurement_leases[atom] = len(self.reservations)
            self.reservations.append(Reservation(f"{gate.id}/measurement",
                                                (ResourceRequirement(f"site/{destination.site}"), ResourceRequirement(f"zone/{destination.zone}")),
                                                (entry,)))
        return (self.emit(gate, "MEASURE", (atom,), dependencies, self.timing.measurement_duration, "imaging", metadata={"basis": "Z"}),)

    def build(self):
        for gate in self.circuit.gates:
            dependencies = tuple(t for parent in gate.predecessors for t in self.completion[parent])
            atoms = tuple(self.qubit_atoms[q] for q in gate.qubits)
            atom = atoms[0]
            kind = gate.gate_type.value
            if kind in ("H", "X", "Y", "Z"):
                terminals = self.local(gate, "SINGLE_QUBIT", atom, dependencies, self.timing.single_qubit_duration,
                                       "local_1q", "LOCAL_1Q", metadata={"gate": kind})
            elif kind in ("PREPARE", "RESET"):
                if gate.metadata.get("state", "0") != "0":
                    raise ValueError("PREPARE/RESET currently supports state=0 only")
                duration = self.timing.prepare_duration if kind == "PREPARE" else self.timing.reset_duration
                terminals = self.local(gate, kind, atom, dependencies, duration, "state_preparation", kind, metadata={"state": "0"})
                if kind == "RESET":
                    _, terminals = self.transit(gate, atom, self.homes[atom], terminals)
            elif kind in ("CZ", "CNOT"):
                if kind == "CNOT":
                    dependencies = self.local(gate, "SINGLE_QUBIT", atoms[1], dependencies, self.timing.single_qubit_duration,
                                              "local_1q", "LOCAL_1Q", metadata={"gate": "H", "phase": "before_cz"})
                terminals = self.entangle(gate, atoms, dependencies)
                if kind == "CNOT":
                    terminals = self.local(gate, "SINGLE_QUBIT", atoms[1], terminals, self.timing.single_qubit_duration,
                                           "local_1q", "LOCAL_1Q", metadata={"gate": "H", "phase": "after_cz"})
            elif kind in ("MEASURE_X", "MEASURE_Z"):
                if kind == "MEASURE_X":
                    dependencies = self.local(gate, "SINGLE_QUBIT", atom, dependencies, self.timing.single_qubit_duration,
                                              "local_1q", "LOCAL_1Q", metadata={"gate": "H", "phase": "measure_x"})
                terminals = self.measure(gate, atom, dependencies)
            else:
                raise ValueError(f"Unsupported physical gate: {kind}")
            self.completion[gate.id] = terminals
        return ExperimentalPlan(tuple(self.actions), self.completion, tuple(self.reservations), self.homes, self.locations)
