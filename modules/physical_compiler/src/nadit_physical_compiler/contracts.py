"""Small handoff records and structural interfaces for compiler algorithms."""

from dataclasses import dataclass
from typing import Protocol

from .atom_ir import AtomStep
from .device import Device
from .physical_ir import PhysicalDAG
from .state import AtomLayout, AtomState


@dataclass(frozen=True, slots=True)
class TransportGoal:
    """Bind a native relocation node to concrete SLM destinations.

    Args:
        operation_id: Node ID of an unconditional ``relocate`` operation.
        targets: Distinct (native quantum wire, Device SLM site ID) pairs.

    This mechanical contract does not define a gate or alter wire-to-atom identity.
    Current lowering supports SLM-held starts. Each displaced atom requires an
    attributed Load, nonzero Move, and target Store within this node's interval;
    an already satisfied target wire may remain stationary.
    """

    operation_id: int
    targets: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        if type(self.operation_id) is not int or self.operation_id < 0:
            raise ValueError("Transport goal operation_id must be nonnegative.")
        if (
            not isinstance(self.targets, tuple)
            or not self.targets
            or any(
                not isinstance(target, tuple)
                or len(target) != 2
                or type(target[0]) is not int
                or target[0] < 0
                or not isinstance(target[1], str)
                or not target[1]
                for target in self.targets
            )
        ):
            raise ValueError("Transport targets require native wires and SLM site IDs.")
        if len({wire for wire, _site in self.targets}) != len(self.targets) or len(
            {site for _wire, site in self.targets}
        ) != len(self.targets):
            raise ValueError("Transport goal wires and target sites must be distinct.")


def validate_transport_goals(
    dag: PhysicalDAG, device: Device, goals: tuple[TransportGoal, ...]
) -> None:
    """Check that concrete goals exactly cover the DAG's mechanical nodes.

    Raises ValueError for registry, native-node, wire, or Device-site mismatches.
    This checks the input contract only; replay establishes physical completion.
    """
    if not isinstance(goals, tuple) or any(
        not isinstance(goal, TransportGoal) for goal in goals
    ):
        raise ValueError("Transport goals must be a tuple of TransportGoal records.")
    by_id = {goal.operation_id: goal for goal in goals}
    nodes = {node.id: node for node in dag.nodes if node.name == "relocate"}
    if len(by_id) != len(goals) or by_id.keys() != nodes.keys():
        raise ValueError("Transport goals must exactly cover relocate nodes.")
    for identity, goal in by_id.items():
        node = nodes[identity]
        if (
            node.clbits
            or node.params
            or node.condition is not None
            or len(set(node.qubits)) != len(node.qubits)
            or set(node.qubits) != {wire for wire, _site in goal.targets}
        ):
            raise ValueError(
                f"Transport goal {identity} disagrees with its relocate node."
            )
        for _wire, site in goal.targets:
            try:
                device.site(site)
            except KeyError as error:
                raise ValueError(
                    f"Transport goal {identity} names unknown SLM site {site!r}."
                ) from error


@dataclass(frozen=True, slots=True)
class GateLayer:
    """Native DAG operations selected for one compilation layer.

    Args:
        operation_ids: Node IDs in the native PhysicalDAG. The caller resolves
            conditions and supplies ready operations before selection.
    """

    operation_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PlacementPlan:
    """Selected atom arrangements before and after a gate layer.

    Args:
        execution_layout: Atom positions and holders for executing the layer.
        exit_layout: Positions and holders to retain after the layer.
        preparation_layout: Optional intermediate layout before gate arrival,
            used to clear nonretained atoms from pulse coverage.
    """

    execution_layout: AtomLayout
    exit_layout: AtomLayout
    preparation_layout: AtomLayout | None = None


@dataclass(frozen=True, slots=True)
class AtomFragment:
    """Selected atom steps and their resulting layout.

    Args:
        steps: Existing Atom IR steps, retained without copying or validation.
        exit_layout: Layout after the selected steps.
        completed_operation_ids: Native DAG node IDs completed by the fragment.
            Transport alone completes only an explicit ``relocate`` goal.
        retained_atoms: Actual selected stays carried to the next layer by
            the compiler. These snapshots are compilation metadata.
    """

    steps: tuple[AtomStep, ...]
    exit_layout: AtomLayout
    completed_operation_ids: tuple[int, ...] = ()
    retained_atoms: tuple[AtomState, ...] = ()


class Scheduler(Protocol):
    """Select a layer deterministically without mutating scheduler state.

    Compilation and lookahead share this selector on different ready frontiers.
    """

    def select(self, dag: PhysicalDAG, ready: tuple[int, ...]) -> GateLayer:
        """Choose the next layer.

        Args:
            dag: Native physical operations and dependencies.
            ready: Node IDs whose dependencies and conditions are resolved.

        Returns:
            Selected operations from ready, using the same node IDs.
        """
        ...


class ReuseAnalyzer(Protocol):
    """Identify physical qubits that can remain for a following gate layer."""

    def analyze(
        self, dag: PhysicalDAG, current: GateLayer, following: GateLayer
    ) -> tuple[int, ...]:
        """Find reuse candidates between two selected layers.

        Args:
            dag: Native physical operations and dependencies.
            current: Layer being placed.
            following: Known following layer used for lookahead.

        Returns:
            Physical-qubit IDs considered for reuse, before atom binding.
        """
        ...


class Placer(Protocol):
    """Choose execution and exit arrangements using configured search options."""

    def place(
        self,
        dag: PhysicalDAG,
        layer: GateLayer,
        layout: AtomLayout,
        device: Device,
        *,
        reuse_qubits: tuple[int, ...] = (),
        following: GateLayer | None = None,
        retained_atoms: tuple[AtomState, ...] = (),
    ) -> PlacementPlan:
        """Choose layouts for a selected gate layer.

        Args:
            dag: Native physical operations and dependencies.
            layer: Layer to place.
            layout: Current atom arrangement and physical-qubit binding.
            device: Device geometry, timing, and capabilities.
            reuse_qubits: Current participants proposed to remain at their
                execution sites in the exit layout for the following CZ layer.
            following: Known next CZ layer for partner-distance estimates.
            retained_atoms: Incoming actual stays, including their positions
                and holders. Only matching current participants are anchors.

        Returns:
            Selected execution and exit layouts.
        """
        ...


class Transporter(Protocol):
    """Construct transport steps using one implementation's movement rules."""

    def construct(
        self, layout: AtomLayout, target_layout: AtomLayout, device: Device
    ) -> AtomFragment:
        """Construct a selected transport fragment.

        Args:
            layout: Current atom positions, holders, and active AOD lines.
            target_layout: Requested positions, holders, and active AOD lines.
            device: Device geometry, timing, and capabilities.

        Returns:
            Constructed Atom IR steps and their resulting layout.
        """
        ...
