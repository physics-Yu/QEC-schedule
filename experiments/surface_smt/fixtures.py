"""One fixed d3 circuit, common geometry, and constructive feasible witnesses.

The witness deliberately returns after each CX slot. This supplies an upper
bound only: neither these groups nor their four-slot barriers enter the solver.
"""

from dataclasses import dataclass
from hashlib import sha256
from math import hypot
from typing import Literal

import qiskit.qasm3
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    CZPulse,
    Load,
    Measure,
    Move,
    Store,
)
from nadit_physical_compiler.capabilities import (
    CZCapability,
    LocalControl,
    ReadoutCapability,
)
from nadit_physical_compiler.contracts import GateLayer
from nadit_physical_compiler.device import (
    AOD,
    Device,
    PairArray,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.emission.actions import emit_layer
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.smt.contracts import Plan, Snapshot
from nadit_physical_compiler.state import (
    AODGrid,
    AODHolder,
    AODLine,
    AtomLayout,
    AtomState,
    SLMHolder,
)

from modules.codes.rotated_surface_d3.components.circuits import se_layers, source_qasm
from modules.codes.rotated_surface_d3.definition import REFERENCE_COORDINATES

ARCHITECTURES = ("nonzoned", "zoned")
MOTIONS = ("flexible", "rigid")
HOME_BOUNDS = Region(-2, -2, 65, 65)
GATE_BOUNDS = Region(78, -2, 135, 65)
READOUT_BOUNDS = Region(-2, 78, 65, 145)
WORKSPACE = Region(-5, -5, 140, 150)
ANCILLA_GROUPS = (
    ((10, 11, 12, 14, 15, 16),),
    ((14, 16), (15,), (10,), (11,), (12,)),
    ((14,), (13, 15), (9,), (10,), (11,)),
    ((9, 10, 11, 13, 14, 15),),
)


@dataclass(frozen=True)
class Fixture:
    """Frozen circuit and device inputs, with named witness destinations."""

    architecture: str
    motion: str
    device: Device
    entry_state: AtomLayout
    dag: PhysicalDAG
    source_qasm: str
    scheduling_qasm: str
    cx_source_layers: tuple[tuple[int, ...], ...]
    home_sites: tuple[str, ...]
    data_guest_sites: tuple[str, ...]
    gate_left_sites: tuple[str, ...]
    gate_right_sites: tuple[str, ...]
    readout_sites: tuple[str, ...]

    @property
    def physical_dag(self) -> PhysicalDAG:
        return self.dag

    @property
    def profile(self) -> dict:
        """Describe input adaptation and the scope of the theoretical profile."""
        return {
            "source": "rotated_surface_d3/se_round",
            "source_sha256": sha256(self.source_qasm.encode()).hexdigest(),
            "scheduling_source_sha256": sha256(
                self.scheduling_qasm.encode()
            ).hexdigest(),
            "adaptation": "Remove only global barrier q statements; preserve per-wire native order.",
            "atoms": 17,
            "cx": 24,
            "ancilla_resets": 8,
            "measurements": 8,
            "round_home": True,
            "geometry": "Common trap bank; 10 um coordinate scale; 2 um guest offset; gate translation (80,0); readout translation (0,80).",
            "timing_profile": "theoretical-linear/v1",
            "timing_us": {
                "load": 15,
                "store": 15,
                "move_per_um": 1,
                "rotation": 1,
                "reset": 10,
                "cz": 0.36,
                "measure": 100,
                "feedback": 1,
            },
            "quantum_scope": "Ideal stabilizer extraction and N/Z hook orientation; not a circuit-level distance proof.",
        }


def make_fixture(
    architecture: Literal["nonzoned", "zoned"], motion: Literal["flexible", "rigid"]
) -> Fixture:
    """Build one of four cases with identical sites, timings, and capacity."""
    if architecture not in ARCHITECTURES or motion not in MOTIONS:
        raise ValueError("Expected nonzoned/zoned and flexible/rigid.")
    homes = tuple(f"home_{q}" for q in range(17))
    guests = tuple(f"guest_{q}" for q in range(9))
    left = tuple(f"gate_left_{q}" for q in range(9))
    right = tuple(f"gate_right_{q}" for q in range(9))
    readout = tuple(f"readout_{q}" for q in range(9, 17))
    positions = tuple(Position(10 * x, 10 * y) for x, y in REFERENCE_COORDINATES)
    sites = tuple(SLMSite(name, p) for name, p in zip(homes, positions, strict=True))
    for names, points, dx, dy in (
        (guests, positions[:9], 2, 0),
        (left, positions[:9], 80, 0),
        (right, positions[:9], 82, 0),
        (readout, positions[9:], 0, 80),
    ):
        sites += tuple(
            SLMSite(name, Position(p.x + dx, p.y + dy))
            for name, p in zip(names, points, strict=True)
        )
    local_ops = ("rotate", "reset")
    home_ops = local_ops + (("cz",) if architecture == "nonzoned" else ())
    gate_ops = local_ops + (("cz",) if architecture == "zoned" else ())
    zone_id = "home" if architecture == "nonzoned" else "gate"
    pair_left, pair_right = (
        (homes[:9], guests) if architecture == "nonzoned" else (left, right)
    )
    device = Device(
        name=f"surface-d3-{architecture}-{motion}",
        zones=(
            Zone("home", HOME_BOUNDS, home_ops, "storage"),
            Zone("gate", GATE_BOUNDS, gate_ops, "entanglement"),
            Zone("readout", READOUT_BOUNDS, local_ops + ("measure",), "measurement"),
        ),
        slm_sites=sites,
        aods=(AOD("transport", WORKSPACE, 1, motion=motion),),
        timing=Timing(15, 15, 1),
        cz=CZCapability("rydberg", 4.6, 0.36, allow_spectators=True),
        readout=ReadoutCapability("camera", 100, 1, 5, True, ("slm", "aod"), None),
        local=LocalControl("local", 1, 10),
        pair_arrays=(
            PairArray(
                "pairs",
                zone_id,
                tuple(tuple(pair_left[r : r + 3]) for r in (0, 3, 6)),
                tuple(tuple(pair_right[r : r + 3]) for r in (0, 3, 6)),
            ),
        ),
    )
    entry = AtomLayout(
        tuple(AtomState(q, p, SLMHolder(homes[q])) for q, p in enumerate(positions)),
        qubit_to_atom=tuple(range(17)),
    )
    original = source_qasm("se_round")
    scheduling = (
        "\n".join(
            line for line in original.splitlines() if line.strip() != "barrier q;"
        )
        + "\n"
    )
    source = qiskit.qasm3.loads(scheduling)
    cx_ids = tuple(
        i for i, inst in enumerate(source.data) if inst.operation.name == "cx"
    )
    layers = tuple(tuple(cx_ids[i : i + 6]) for i in range(0, 24, 6))
    return Fixture(
        architecture,
        motion,
        device,
        entry,
        loads_qasm(scheduling),
        original,
        scheduling,
        layers,
        homes,
        guests,
        left,
        right,
        readout,
    )


def constructive_program(fixture: Fixture) -> AtomProgram:
    """Construct a symmetric, lawful round-home upper bound for either AOD."""
    device, dag = fixture.device, fixture.dag
    layout = fixture.entry_state
    steps: list[AtomStep] = []
    parents = {node.id: set() for node in dag.nodes}
    for a, b in dag.edges:
        parents[b].add(a)

    def append(step: AtomStep) -> None:
        nonlocal layout
        steps.append(step)
        layout = apply_step(layout, step, device)

    def local(nodes: tuple[int, ...]) -> None:
        pending = set(nodes)
        while pending:
            ready = tuple(i for i in sorted(pending) if not parents[i] & pending)
            for step in emit_layer(dag, GateLayer(ready), layout, device).steps:
                append(step)
            pending.difference_update(ready)

    def load(atoms: tuple[int, ...]) -> None:
        xs = sorted({layout.atom(a).position.x for a in atoms})
        ys = sorted({layout.atom(a).position.y for a in atoms})
        grid = AODGrid(
            "transport",
            tuple(AODLine(i, y) for i, y in enumerate(ys)),
            tuple(AODLine(i, x) for i, x in enumerate(xs)),
        )
        bindings = tuple(
            (
                a,
                ys.index(layout.atom(a).position.y),
                xs.index(layout.atom(a).position.x),
            )
            for a in atoms
        )
        append(AtomStep((Load(grid, bindings, duration_us=device.timing.load_us),)))

    def move(targets: dict[int, Position]) -> None:
        vectors = {
            (p.x - layout.atom(a).position.x, p.y - layout.atom(a).position.y)
            for a, p in targets.items()
        }
        if len(vectors) != 1:
            raise ValueError("The constructive group must be a rigid translation.")
        dx, dy = vectors.pop()
        old = layout.grid("transport")
        grid = AODGrid(
            old.aod_id,
            tuple(AODLine(line.id, line.coordinate + dy) for line in old.rows),
            tuple(AODLine(line.id, line.coordinate + dx) for line in old.columns),
        )
        append(
            AtomStep(
                (
                    Move(
                        grid,
                        tuple(targets.items()),
                        duration_us=device.timing.move_duration(hypot(dx, dy)),
                    ),
                )
            )
        )

    def store(destinations: dict[int, str]) -> None:
        append(
            AtomStep(
                (
                    Store(
                        AODGrid("transport"),
                        tuple(destinations.items()),
                        duration_us=device.timing.store_us,
                    ),
                )
            )
        )

    def transfer(destinations: dict[int, str]) -> None:
        load(tuple(destinations))
        move({a: device.site(site).position for a, site in destinations.items()})
        store(destinations)

    cx_sources = {s for layer in fixture.cx_source_layers for s in layer}
    local(tuple(n.id for n in dag.nodes if n.source_id < min(cx_sources)))
    for pairs, sources, groups in zip(
        se_layers(), fixture.cx_source_layers, ANCILLA_GROUPS, strict=True
    ):
        data_to_ancilla = {min(a, b): max(a, b) for a, b in pairs}
        ancilla_to_data = {a: d for d, a in data_to_ancilla.items()}
        data_groups: list[tuple[int, ...]] = []
        if fixture.architecture == "zoned":
            for y in sorted({layout.atom(d).position.y for d in data_to_ancilla}):
                group = tuple(
                    d for d in sorted(data_to_ancilla) if layout.atom(d).position.y == y
                )
                data_groups.append(group)
                transfer({d: fixture.gate_left_sites[d] for d in group})
        guests = (
            fixture.data_guest_sites
            if fixture.architecture == "nonzoned"
            else fixture.gate_right_sites
        )
        for group in groups:
            transfer({a: guests[ancilla_to_data[a]] for a in group})
        cz = tuple(n.id for n in dag.nodes if n.source_id in sources and n.name == "cz")
        by_source = {dag.nodes[i].source_id: i for i in cz}
        local(
            tuple(
                n.id
                for n in dag.nodes
                if n.source_id in sources and n.id < by_source[n.source_id]
            )
        )
        append(
            AtomStep(
                (
                    CZPulse(
                        device.cz.channel,
                        HOME_BOUNDS
                        if fixture.architecture == "nonzoned"
                        else GATE_BOUNDS,
                        duration_us=device.cz.duration_us,
                        source_ids=cz,
                    ),
                )
            )
        )
        local(
            tuple(
                n.id
                for n in dag.nodes
                if n.source_id in sources and n.id > by_source[n.source_id]
            )
        )
        for group in reversed(groups):
            transfer({a: fixture.home_sites[a] for a in group})
        for group in reversed(data_groups):
            transfer({d: fixture.home_sites[d] for d in group})
    local(
        tuple(
            n.id
            for n in dag.nodes
            if n.source_id > max(cx_sources) and n.name != "measure"
        )
    )
    ancillas = tuple(range(9, 17))
    load(ancillas)
    move({a: device.site(fixture.readout_sites[a - 9]).position for a in ancillas})
    measurements = tuple(n for n in dag.nodes if n.name == "measure")
    append(
        AtomStep(
            (
                Measure(
                    device.readout.channel,
                    tuple((n.qubits[0], n.result) for n in measurements),
                    True,
                    duration_us=device.readout.duration_us,
                    source_ids=tuple(n.id for n in measurements),
                ),
            )
        )
    )
    move({a: device.site(fixture.home_sites[a]).position for a in ancillas})
    store({a: fixture.home_sites[a] for a in ancillas})
    return AtomProgram(tuple(steps), dag.global_phase)


def program_to_plan(fixture: Fixture, program: AtomProgram) -> Plan:
    """Convert an actual witness by replay, including active empty lines."""
    layout = fixture.entry_state

    def snapshot() -> Snapshot:
        grid = layout.grid("transport")
        return Snapshot(
            tuple(a.position for a in layout.atoms),
            tuple(isinstance(a.holder, AODHolder) for a in layout.atoms),
            tuple(sorted(line.coordinate for line in grid.columns)),
            tuple(sorted(line.coordinate for line in grid.rows)),
        )

    states = [snapshot()]
    transitions, operations = [], []
    for step in program.steps:
        kinds = {
            type(a).__name__.lower()
            for a in step.actions
            if isinstance(a, Load | Move | Store)
        }
        if len(kinds) > 1:
            raise ValueError("A witness step must have one transport transition.")
        transitions.append(next(iter(kinds)) if kinds else "none")
        operations.append(tuple(i for a in step.actions for i in a.source_ids))
        layout = apply_step(layout, step, fixture.device)
        states.append(snapshot())
    return Plan(tuple(states), tuple(transitions), tuple(operations))
