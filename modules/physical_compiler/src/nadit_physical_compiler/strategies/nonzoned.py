"""Shared-array native layers with optional same-atom relocation goals."""

from dataclasses import dataclass, replace

from ..atom_ir import AtomStep, Load, Move, Store
from ..contracts import AtomFragment, GateLayer, TransportGoal
from ..device import Device
from ..emission import WholeLayerEmitter, emit_layer
from ..motion import check_load, check_move, check_store
from ..nonzoned.emission import emit_batch
from ..nonzoned.planning import plan_layer
from ..nonzoned.support import require_capabilities
from ..physical_ir import PhysicalDAG
from ..placement import GatePairCatalog
from ..readout import BatchReadout
from ..replay import apply_step
from ..scheduling import ReadyScheduler
from ..semantic_actions import check_action_semantics
from ..state import AtomLayout, AtomState, SLMHolder, validate_layout
from ..transport import StrictTransport
from ..transport.occupancy import Occupancy
from ..validation_durations import check_duration


@dataclass(frozen=True, slots=True)
class NonZonedStrategy:
    """Compile with fixed homes, ENOLA-inspired batching, and one CZ per layer.

    Args:
        aod_id: Flexible AOD used for strict shared-array transfers.
        catalog: Isolated two-trap cells distributed across the shared array.
        max_cz_gates: Optional layer limit; None uses the cell count.
        max_measurements: Readout layer limit, normally taken from Device.
        transport_goals: Native same-atom relocations with explicit vacant SLM
            destinations. Ready disjoint goals share physical planning with gates.

    The caller supplies the reference through compile_physical.entry_state.
    Calls without transport goals restore their entry layout. A selected goal
    changes only its named atom endpoints; gate actors return to their entry.
    No mutable placement or measurement state is retained on the strategy.
    """

    aod_id: str
    catalog: GatePairCatalog
    max_cz_gates: int | None = None
    max_measurements: int | None = None
    transport_goals: tuple[TransportGoal, ...] = ()

    @property
    def lookahead_enabled(self) -> bool:
        """Fixed-home layers do not request or consume speculative lookahead."""
        return False

    def select(self, dag: PhysicalDAG, ready: tuple[int, ...]) -> GateLayer:
        """Select only operations admitted by the existing DAG controller."""
        scheduler = ReadyScheduler(
            self.catalog.capacity if self.max_cz_gates is None else self.max_cz_gates,
            max_measurements=self.max_measurements,
        )
        if not self.transport_goals:
            return scheduler.select(dag, ready)
        quantum = scheduler.select(
            dag, tuple(index for index in ready if dag.nodes[index].name != "relocate")
        )
        selected = list(quantum.operation_ids)
        occupied = {q for index in selected for q in dag.nodes[index].qubits}
        for index in sorted(ready):
            node = dag.nodes[index]
            if node.name == "relocate" and occupied.isdisjoint(node.qubits):
                selected.append(index)
                occupied.update(node.qubits)
        return GateLayer(tuple(sorted(selected)))

    def lower(
        self,
        dag: PhysicalDAG,
        layer: GateLayer,
        layout: AtomLayout,
        device: Device,
        *,
        following: GateLayer | None = None,
        retained_atoms: tuple[AtomState, ...] = (),
    ) -> AtomFragment:
        """Prepare all pairs, pulse once, and undo selected transport batches."""
        if not layer.operation_ids:
            return AtomFragment((), layout)
        goals = tuple(
            goal
            for goal in self.transport_goals
            if goal.operation_id in layer.operation_ids
        )
        if goals:
            return self._lower_joint(dag, layer, layout, device, goals)
        name = dag.nodes[layer.operation_ids[0]].name
        require_capabilities(device, self.aod_id, readout=name == "measure")
        if name == "measure":
            return BatchReadout(self.aod_id).lower(dag, layer, layout, device)
        if name != "cz":
            return emit_layer(dag, layer, layout, device)
        plan = plan_layer(dag, layer, layout, device, self.catalog, self.aod_id)
        arrival = tuple(
            step
            for batch in plan.batches
            for step in emit_batch(batch, layout, device, self.aod_id)
        )
        pulse = WholeLayerEmitter(self.catalog.coverage)(
            dag, layer, plan.execution_layout, device
        )
        departure = tuple(
            step
            for batch in reversed(plan.batches)
            for step in emit_batch(batch, layout, device, self.aod_id, returning=True)
        )
        return AtomFragment(
            arrival + pulse.steps + departure, layout, layer.operation_ids
        )

    def _lower_joint(
        self,
        dag: PhysicalDAG,
        layer: GateLayer,
        layout: AtomLayout,
        device: Device,
        goals: tuple[TransportGoal, ...],
    ) -> AtomFragment:
        target, owners = _relocation_target(layout, device, goals)
        goal_ids = {goal.operation_id for goal in goals}
        quantum = GateLayer(tuple(i for i in layer.operation_ids if i not in goal_ids))
        if any(
            layout.qubit_to_atom[q] in owners
            for index in quantum.operation_ids
            for q in dag.nodes[index].qubits
        ):
            raise ValueError("Joint relocation and gate wires must be disjoint.")
        name = (
            dag.nodes[quantum.operation_ids[0]].name if quantum.operation_ids else None
        )
        require_capabilities(device, self.aod_id, readout=name == "measure")
        transport = StrictTransport(self.aod_id)
        if name == "cz":
            plan = plan_layer(dag, quantum, target, device, self.catalog, self.aod_id)
            arrival = transport.construct(layout, plan.execution_layout, device)
            pulse = WholeLayerEmitter(self.catalog.coverage)(
                dag, quantum, arrival.exit_layout, device
            )
            departure = transport.construct(arrival.exit_layout, target, device)
            steps = arrival.steps + pulse.steps + departure.steps
        elif name == "measure":
            fragment = BatchReadout(self.aod_id).lower(
                dag, quantum, layout, device, transport_target=target
            )
            steps = fragment.steps
        elif name in (None, "rx", "ry", "rz", "u", "reset"):
            arrival = transport.construct(layout, target, device)
            steps = arrival.steps
            if quantum.operation_ids:
                pulse = emit_layer(dag, quantum, layout, device)
                steps = (AtomStep(steps[0].actions + pulse.steps[0].actions),) + steps[
                    1:
                ]
        else:
            raise ValueError(f"UNSUPPORTED_MIXED_TRANSPORT_OPERATION: {name!r}")
        tagged = _tag_transport(steps, owners)
        actual = _checked_replay(dag, device, layout, tagged)
        if actual != target:
            raise ValueError("JOINT_TRANSPORT_EXIT_MISMATCH")
        return AtomFragment(tagged, actual, layer.operation_ids)


def _relocation_target(
    layout: AtomLayout, device: Device, goals: tuple[TransportGoal, ...]
) -> tuple[AtomLayout, dict[int, int]]:
    if layout.aod_grids or any(
        not isinstance(a.holder, SLMHolder) for a in layout.atoms
    ):
        raise ValueError("Joint relocation requires an idle SLM entry world.")
    atoms = {atom.id: atom for atom in layout.atoms}
    occupied = Occupancy({atom.id: atom.position for atom in layout.atoms})
    owners: dict[int, int] = {}
    destinations: set[str] = set()
    for goal in goals:
        displaced = False
        for wire, site_id in goal.targets:
            atom_id = layout.qubit_to_atom[wire]
            if atom_id in owners or site_id in destinations:
                raise ValueError("Overlapping ready relocation goals.")
            site = device.site(site_id)
            if occupied.at(site.position) - {atom_id}:
                raise ValueError("Relocation destination is occupied.")
            destination = AtomState(atom_id, site.position, SLMHolder(site_id))
            displaced |= destination != atoms[atom_id]
            atoms[atom_id] = destination
            owners[atom_id] = goal.operation_id
            destinations.add(site_id)
        if not displaced:
            raise ValueError("A relocation goal must displace at least one atom.")
    target = replace(layout, atoms=tuple(atoms[atom.id] for atom in layout.atoms))
    validate_layout(device, target)
    return target, owners


def _tag_transport(
    steps: tuple[AtomStep, ...], owners: dict[int, int]
) -> tuple[AtomStep, ...]:
    result = []
    for step in steps:
        actions = []
        for action in step.actions:
            if isinstance(action, Load | Move | Store):
                members = (
                    action.targets if isinstance(action, Move) else action.bindings
                )
                sources = set(action.source_ids) | {
                    owners[a[0]] for a in members if a[0] in owners
                }
                action = replace(action, source_ids=tuple(sorted(sources)))
            actions.append(action)
        result.append(AtomStep(tuple(actions)))
    return tuple(result)


def _checked_replay(
    dag: PhysicalDAG, device: Device, layout: AtomLayout, steps: tuple[AtomStep, ...]
) -> AtomLayout:
    for step in steps:
        for action in step.actions:
            checks = [check_duration(device, layout, action)]
            if isinstance(action, Load):
                checks.append(
                    check_load(
                        device,
                        layout,
                        action.grid,
                        {a: (r, c) for a, r, c in action.bindings},
                    )
                )
            elif isinstance(action, Move):
                checks.append(
                    check_move(device, layout, action.grid, dict(action.targets))
                )
            elif isinstance(action, Store):
                checks.append(
                    check_store(device, layout, action.grid, dict(action.bindings))
                )
            checks.extend(check_action_semantics(dag, device, layout, action, step))
            for check in checks:
                if not check.ok:
                    raise ValueError(
                        f"JOINT_TRANSPORT_INVALID: {check.rule}: {check.message}"
                    )
        layout = apply_step(layout, step, device)
        validate_layout(device, layout)
    return layout
