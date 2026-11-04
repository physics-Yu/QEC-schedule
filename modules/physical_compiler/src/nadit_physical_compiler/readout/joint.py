"""Joint retained readout and permanent SLM motion under existing AOD rules."""

from dataclasses import dataclass
from math import hypot

from ..atom_ir import AtomAction, AtomStep, Load, Measure, Move, Store
from ..contracts import AtomFragment, GateLayer
from ..device import Device
from ..physical_ir import PhysicalDAG
from ..replay import apply_step
from ..state import AODGrid, AtomLayout, SLMHolder
from ..transport.occupancy import Occupancy
from ..transport.rules import MoveRequest, build_conflict_map, rules_for
from ..transport.strict import _BatchSelector
from .planning import plan_readout


@dataclass
class _JointSelector(_BatchSelector):
    measured: frozenset[int]

    def _close(self, selected: set[int], pending: set[int]) -> set[int] | None:
        closed = super()._close(selected, pending)
        if closed is None:
            return None
        moves = tuple(m for atom, m in self.requests.items() if atom in closed)
        _, _, bindings = self.rules.frames(moves)
        rows = {row for atom, row, _ in bindings if atom in self.measured}
        columns = {column for atom, _, column in bindings if atom in self.measured}
        if any(
            row in rows and column in columns
            for atom, row, column in bindings
            if atom not in self.measured
        ):
            # Both active axes would retain this permanent atom in the AOD.
            return None
        return closed


def lower_joint_readout(
    dag: PhysicalDAG,
    layer: GateLayer,
    layout: AtomLayout,
    transport_target: AtomLayout,
    device: Device,
    aod_id: str,
) -> AtomFragment:
    """Plan ready readout and disjoint permanent motion in shared strict batches.

    Readout positions come from the existing selector with permanent destinations
    treated as final spectators. Actual source/target closure uses the complete
    current world. Batches may mix readout and permanent movers when active-line
    deactivation can store the latter without releasing measured atoms. Otherwise
    the same conflict selector chooses legal smaller batches, or raises when no
    batch can proceed. No singleton fallback or additional quantum operation is
    inserted. All durations come from Device.
    """
    if layout.qubit_to_atom != transport_target.qubit_to_atom or tuple(
        a.id for a in layout.atoms
    ) != tuple(a.id for a in transport_target.atoms):
        raise ValueError("Joint readout must preserve atom and wire identities.")
    operations = {
        layout.qubit_to_atom[dag.nodes[i].qubits[0]]: i for i in layer.operation_ids
    }
    target_atoms = {atom.id: atom for atom in transport_target.atoms}
    permanent = {
        atom.id: MoveRequest(atom.id, atom.position, target_atoms[atom.id].position)
        for atom in layout.atoms
        if atom != target_atoms[atom.id]
    }
    if permanent.keys() & operations.keys():
        raise ValueError("Joint readout and permanent movers must be disjoint.")
    batches = plan_readout(dag, layer, transport_target, device, aod_id)
    rules = rules_for(device.aod(aod_id), device.timing)
    current = layout
    steps: list[AtomStep] = []
    for batch in batches:
        requests = {move.atom_id: move for move in (*batch.moves, *permanent.values())}
        selector = _JointSelector(
            rules,
            requests,
            build_conflict_map(tuple(requests.values()), rules),
            Occupancy({a.id: a.position for a in current.atoms}),
            frozenset(operations),
        )
        pending = set(requests)
        while pending:
            selected = selector.select(pending)
            emitted = _emit_trip(
                selected, operations, dag, current, transport_target, device, aod_id
            )
            steps.extend(emitted)
            for step in emitted:
                current = apply_step(current, step, device)
            current_positions = {atom.id: atom.position for atom in current.atoms}
            for move in selected:
                pending.remove(move.atom_id)
                permanent.pop(move.atom_id, None)
                selector.occupied.remove(move.atom_id)
                selector.occupied.add(move.atom_id, current_positions[move.atom_id])
    if current != transport_target:
        raise ValueError("JOINT_READOUT_EXIT_MISMATCH")
    return AtomFragment(tuple(steps), current, layer.operation_ids)


def _emit_trip(
    moves: tuple[MoveRequest, ...],
    operations: dict[int, int],
    dag: PhysicalDAG,
    layout: AtomLayout,
    destination: AtomLayout,
    device: Device,
    aod_id: str,
) -> tuple[AtomStep, ...]:
    rules = rules_for(device.aod(aod_id), device.timing)
    source, target, bindings = rules.frames(moves)
    actions: list[AtomAction] = [
        Load(source, bindings, duration_us=device.timing.load_us)
    ]
    if any(move.source != move.target for move in moves):
        actions.append(
            Move(
                target,
                tuple((move.atom_id, move.target) for move in moves),
                duration_us=device.timing.move_duration(
                    max(
                        hypot(m.target.x - m.source.x, m.target.y - m.source.y)
                        for m in moves
                    )
                ),
            )
        )
    measured = tuple(move for move in moves if move.atom_id in operations)
    permanent = tuple(move for move in moves if move.atom_id not in operations)
    rows = {row for atom, row, _ in bindings if atom in operations}
    columns = {column for atom, _, column in bindings if atom in operations}
    kept_target = AODGrid(
        aod_id,
        tuple(line for line in target.rows if line.id in rows),
        tuple(line for line in target.columns if line.id in columns),
    )
    if permanent:
        actions.append(
            Store(
                kept_target,
                _stores(permanent, destination),
                duration_us=device.timing.store_us,
            )
        )
    if measured:
        assert device.readout is not None
        results = []
        for move in measured:
            result = dag.nodes[operations[move.atom_id]].result
            assert result is not None
            results.append((move.atom_id, result))
        actions.append(
            Measure(
                device.readout.channel,
                tuple(results),
                True,
                duration_us=device.readout.duration_us,
                source_ids=tuple(operations[move.atom_id] for move in measured),
            )
        )
        kept_source = AODGrid(
            aod_id,
            tuple(line for line in source.rows if line.id in rows),
            tuple(line for line in source.columns if line.id in columns),
        )
        if any(move.source != move.target for move in measured):
            actions.append(
                Move(
                    kept_source,
                    tuple((move.atom_id, move.source) for move in measured),
                    duration_us=device.timing.move_duration(
                        max(
                            hypot(m.target.x - m.source.x, m.target.y - m.source.y)
                            for m in measured
                        )
                    ),
                )
            )
        actions.append(
            Store(
                AODGrid(aod_id),
                _stores(measured, layout),
                duration_us=device.timing.store_us,
            )
        )
    return tuple(AtomStep((action,)) for action in actions)


def _stores(
    moves: tuple[MoveRequest, ...], layout: AtomLayout
) -> tuple[tuple[int, str], ...]:
    holders = {atom.id: atom.holder for atom in layout.atoms}
    stores = []
    for move in moves:
        holder = holders[move.atom_id]
        if not isinstance(holder, SLMHolder):
            raise ValueError(
                "Joint readout permanent/return destinations must be SLM sites."
            )
        stores.append((move.atom_id, holder.site_id))
    return tuple(stores)
