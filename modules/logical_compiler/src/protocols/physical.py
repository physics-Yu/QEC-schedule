"""Transactional ownership of serial calls and admitted synchronous waves."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, replace
from math import isclose, isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from nadit_physical_compiler.atom_ir import Measure
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_layout
from nadit_physical_compiler.state import AtomLayout, validate_layout

from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentExpansion,
    InvocationContext,
)

from .assembly import (
    PhysicalBatch,
    PhysicalBundle,
    PhysicalEntry,
    PhysicalInvocation,
    PhysicalWait,
    assemble,
    validate_part,
)

_TIME_TOLERANCE_US = 1e-8

if TYPE_CHECKING:
    from ..scheduling import Admission
    from .parallel_physical import PhysicalBatchRequest


def _time(value: float) -> float:
    try:
        valid = type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("INVALID_PHYSICAL_TIME: expected a finite nonnegative time")
    return float(value)


def _bindings(
    value: Iterable[ComponentBinding] | Mapping[str, ComponentBinding],
    world: AtomLayout,
) -> dict[str, ComponentBinding]:
    bindings = tuple(value.values()) if isinstance(value, Mapping) else tuple(value)
    result: dict[str, ComponentBinding] = {}
    all_atoms = {atom.id for atom in world.atoms}
    bound_atoms: set[int] = set()
    for binding in bindings:
        if not isinstance(binding, ComponentBinding) or not binding.block_id:
            raise ValueError(
                "INVALID_PHYSICAL_BINDING: expected a named component binding"
            )
        if binding.block_id in result or len(set(binding.atom_ids)) != len(
            binding.atom_ids
        ):
            raise ValueError(
                "INVALID_PHYSICAL_BINDING: duplicate block or atom identity"
            )
        if not set(binding.atom_ids) <= all_atoms or bound_atoms & set(
            binding.atom_ids
        ):
            raise ValueError(
                "INVALID_PHYSICAL_BINDING: missing or multiply bound atoms"
            )
        result[binding.block_id] = binding
        bound_atoms.update(binding.atom_ids)
    if isinstance(value, Mapping) and any(
        key != binding.block_id for key, binding in value.items()
    ):
        raise ValueError("INVALID_PHYSICAL_BINDING: mapping keys must equal block IDs")
    return result


def _parts(value: Any) -> tuple[ComponentExpansion, ...]:
    if isinstance(value, ComponentExpansion):
        return (value,)
    expansion = getattr(value, "expansion", None)
    if isinstance(expansion, ComponentExpansion):
        return (expansion,)
    candidate = value if isinstance(value, tuple) else getattr(value, "parts", None)
    if (
        not isinstance(candidate, tuple)
        or not candidate
        or any(not isinstance(part, ComponentExpansion) for part in candidate)
    ):
        raise ValueError(
            "INVALID_PHYSICAL_EXPANSION: expected a component or nonempty parts tuple"
        )
    return candidate


def _exit_bindings(
    part: ComponentExpansion,
    bindings: dict[str, ComponentBinding],
) -> dict[str, ComponentBinding]:
    if part.exit_binding is not None and part.exit_participant_bindings:
        raise ValueError("INVALID_PHYSICAL_BINDING: ambiguous single and joint exits")
    exits = (
        (part.exit_binding,)
        if part.exit_binding is not None
        else part.exit_participant_bindings
    )
    if len({binding.block_id for binding in exits}) != len(exits):
        raise ValueError("INVALID_PHYSICAL_BINDING: repeated participant exit")
    result = dict(bindings)
    for binding in part.participant_bindings:
        if bindings.get(binding.block_id) != binding:
            raise ValueError("INVALID_PHYSICAL_BINDING: stale participant entry")
    for binding in exits:
        previous = bindings.get(binding.block_id)
        if previous is None or sorted(previous.atom_ids) != sorted(binding.atom_ids):
            raise ValueError(
                "INVALID_PHYSICAL_BINDING: exit changes registered block atoms"
            )
        result[binding.block_id] = binding
    return result


class PhysicalContext:
    """Compose selected code-owned actions under one caller-owned complete world.

    The context commits serial calls or admitted synchronous waves. It owns
    no quantum state, decoder or sampled measurement bits. Existing wire order is
    preserved and unbound world atoms are appended to form a fixed global wire
    map; both input and normalized mappings are recorded in the final snapshot.

    Args:
        device: Device whose resources are explicitly named by component bindings.
        entry_world: Complete occupied world, including spectator atoms.
        bindings: Distinct named blocks, as an iterable or block-ID mapping.

    Raises:
        ValueError: Entry geometry, identities or bindings are invalid.
    """

    def __init__(
        self,
        device: Device,
        entry_world: AtomLayout,
        bindings: Iterable[ComponentBinding] | Mapping[str, ComponentBinding],
    ) -> None:
        validate_layout(device, entry_world)
        wire_map = entry_world.qubit_to_atom + tuple(
            atom.id
            for atom in entry_world.atoms
            if atom.id not in entry_world.qubit_to_atom
        )
        self._input_entry_wire_map = entry_world.qubit_to_atom
        self._entry_world = replace(entry_world, qubit_to_atom=wire_map)
        self._world = self._entry_world
        self._device = device
        self._bindings = _bindings(bindings, self._world)
        self._clock_us = 0.0
        self._next_result_id = 0
        self._entries: tuple[PhysicalEntry, ...] = ()
        self._invocations: tuple[PhysicalInvocation, ...] = ()
        self._identities: frozenset[str] = frozenset()
        self._sources: dict[str, Any] = {}

    @property
    def clock_us(self) -> float:
        """Return the time at which the complete world reaches its current layout."""
        return self._clock_us

    @property
    def world(self) -> AtomLayout:
        """Return the complete current immutable world, including spectators."""
        return self._world

    @property
    def bindings(self) -> Mapping[str, ComponentBinding]:
        """Return a read-only view of the latest canonical role bindings."""
        return MappingProxyType(self._bindings)

    @property
    def next_result_id(self) -> int:
        """Return the first unreserved global physical measurement identity."""
        return self._next_result_id

    @property
    def snapshot_id(self) -> str:
        """Bind an admission to the current complete physical state and allocator."""
        return canonical_hash(
            {
                "device": encode_device(self._device),
                "world": encode_layout(self._world),
                "bindings": [
                    asdict(self._bindings[key]) for key in sorted(self._bindings)
                ],
                "clock_us": self._clock_us,
                "next_result_id": self._next_result_id,
                "invocation_ids": sorted(self._identities),
            }
        )

    @property
    def invocations(self) -> tuple[PhysicalInvocation, ...]:
        """Return committed calls in stable order, including simultaneous members."""
        return self._invocations

    def source(self, invocation_id: str) -> Any:
        """Return the committed original expansion for a code-owned continuation.

        This runtime-only object is never embedded in the JSON snapshot. Unknown
        or failed invocation IDs raise KeyError.
        """
        return self._sources[invocation_id]

    def batch_for(self, invocation_id: str) -> PhysicalBatch | None:
        """Find the committed batch for a member or part without changing state."""
        for entry in self._entries:
            if isinstance(entry, PhysicalBatch) and any(
                invocation_id == member_id
                or any(invocation_id == part.invocation_id for part in parts)
                for member_id, parts in entry.member_parts
            ):
                return entry
        return None

    def wait_until(self, time_us: float, *, reason: str) -> None:
        """Append a real Wait for a future deadline, without observing any results.

        Past/current deadlines are already satisfied. Invalid times or an empty
        reason raise ValueError without changing the context.
        """
        target = _time(time_us)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("INVALID_PHYSICAL_WAIT: a nonempty reason is required")
        if target > self._clock_us:
            self._entries += (PhysicalWait(self._clock_us, target, reason),)
            self._clock_us = target

    def invoke(
        self,
        bound: Any,
        invocation_id: str,
        result_count: int | None = None,
        *,
        not_before_us: float = 0,
    ) -> tuple[ComponentExpansion, ...]:
        """Expand, validate and atomically commit a bound component or adapter.

        ``bound`` is callable on InvocationContext, or implements ``expand``.
        It returns one ComponentExpansion, a tuple, or an object with ``parts``
        (tuple) or ``expansion`` (one component).
        ``result_count`` optionally declares the exact contiguous global result-ID
        range. Omission derives its size from a validated serial expansion.
        No mutations are committed if expansion or validation fails.

        Raises:
            ValueError: Identity, timing, world continuity, result range, bindings
                or physical checks fail; observed bits/physical Conditions occur.
            TypeError: The supplied object cannot expand a component.
        """
        if (
            not isinstance(invocation_id, str)
            or not invocation_id.strip()
            or invocation_id in self._identities
        ):
            raise ValueError(
                "INVALID_PHYSICAL_INVOCATION: empty or repeated invocation ID"
            )
        if result_count is not None and (
            type(result_count) is not int or result_count < 0
        ):
            raise ValueError(
                "INVALID_PHYSICAL_RESULT_COUNT: expected a nonnegative integer"
            )
        start = max(self._clock_us, _time(not_before_us))
        expand: Callable[[InvocationContext], Any] | None = getattr(
            bound, "expand", None
        )
        if expand is None and callable(bound):
            expand = bound
        if not callable(expand):
            raise TypeError(
                "INVALID_PHYSICAL_EXPANDER: expected a callable or expand method"
            )
        source = expand(
            InvocationContext(
                invocation_id, start, self._next_result_id, self._device, self._world
            )
        )
        parts = _parts(source)
        additions: list[PhysicalEntry] = []
        if start > self._clock_us:
            additions.append(
                PhysicalWait(self._clock_us, start, f"not_before:{invocation_id}")
            )
        world, bindings, clock = self._world, dict(self._bindings), start
        identities: set[str] = set()
        result_ids: list[int] = []
        for index, part in enumerate(parts):
            part_start = _time(part.start_us)
            if not isclose(part_start, clock, rel_tol=0, abs_tol=_TIME_TOLERANCE_US):
                if index == 0 or part_start < clock:
                    raise ValueError(
                        "PHYSICAL_TIME_DISCONTINUITY: "
                        "component starts at a different time"
                    )
                additions.append(
                    PhysicalWait(
                        clock, part_start, f"component_boundary:{part.invocation_id}"
                    )
                )
            if (
                not part.invocation_id
                or part.invocation_id in identities
                or part.invocation_id in self._identities
            ):
                raise ValueError(
                    "INVALID_PHYSICAL_INVOCATION: repeated part invocation ID"
                )
            identities.add(part.invocation_id)
            if (
                part.entry_state != world
                or part.exit_state.qubit_to_atom != self._entry_world.qubit_to_atom
            ):
                raise ValueError(
                    "PHYSICAL_WORLD_DISCONTINUITY: "
                    "stale entry or changed global wire map"
                )
            if {atom.id for atom in part.exit_state.atoms} != {
                atom.id for atom in self._entry_world.atoms
            }:
                raise ValueError("PHYSICAL_WORLD_DISCONTINUITY: missing world atoms")
            if any(node.condition is not None for node in part.dag.nodes):
                raise ValueError(
                    "UNSUPPORTED_PHYSICAL_CONDITION: "
                    "physical Condition remains unresolved"
                )
            for output in part.measurements:
                if (
                    output.invocation_id != part.invocation_id
                    or output.value is not None
                ):
                    raise ValueError(
                        "INVALID_PHYSICAL_RESULT: output identity or observed value"
                    )
                if (
                    type(output.result.measurement_id) is not int
                    or output.result.measurement_id < 0
                ):
                    raise ValueError(
                        "INVALID_PHYSICAL_RESULT: "
                        "expected a nonnegative result identity"
                    )
                _time(output.available_at_us)
                result_ids.append(output.result.measurement_id)
            if (
                tuple(output.port for output in part.measurements)
                != part.description.measurements
            ):
                raise ValueError(
                    "INVALID_PHYSICAL_RESULT: "
                    "measurement ports disagree with description"
                )
            measured = [
                (atom, reference.measurement_id)
                for step in part.program.steps
                for action in step.actions
                if isinstance(action, Measure)
                for atom, reference in action.results
            ]
            outputs = [
                (output.atom_id, output.result.measurement_id)
                for output in part.measurements
            ]
            if sorted(measured) != sorted(outputs):
                raise ValueError(
                    "INVALID_PHYSICAL_RESULT: "
                    "output atoms or IDs disagree with readout actions"
                )
            bindings = _exit_bindings(part, bindings)
            validate_part(part, self._device)
            additions.append(part)
            clock, world = _time(part.action_end_us), part.exit_state
        actual_count = len(result_ids) if result_count is None else result_count
        expected = list(
            range(self._next_result_id, self._next_result_id + actual_count)
        )
        if sorted(result_ids) != expected:
            raise ValueError(
                "INVALID_PHYSICAL_RESULT_RANGE: "
                "count, duplicate or unreserved result identity"
            )
        record = PhysicalInvocation(
            invocation_id,
            tuple(part.invocation_id for part in parts),
            start,
            clock,
            self._next_result_id,
            actual_count,
        )
        self._entries += tuple(additions)
        self._invocations += (record,)
        self._identities |= identities | {invocation_id}
        self._sources[invocation_id] = source
        self._clock_us, self._world, self._bindings = clock, world, bindings
        self._next_result_id += actual_count
        return parts

    def finalize(self) -> PhysicalBundle:
        """Validate the complete flattened program and return an immutable bundle.

        Raises ValueError for any global timing, replay or semantic inconsistency.
        Pending measurements stay pending, including beyond the last action.
        """
        return assemble(
            self._entries,
            device=self._device,
            entry_world=self._entry_world,
            world=self._world,
            bindings=tuple(self._bindings[key] for key in sorted(self._bindings)),
            invocations=self._invocations,
            input_entry_wire_map=self._input_entry_wire_map,
        )

    def invoke_batch(
        self,
        admission: Admission,
        requests: tuple[PhysicalBatchRequest, ...],
        *,
        not_before_us: float = 0,
    ) -> PhysicalBatch:
        """Commit one already-admitted lockstep wave, or preserve the whole context.

        Requests are PhysicalBatchRequest values with exact result counts. This
        verifies declarations after admission; it does not choose parallelism.
        Original member sources remain available through source(member_id).
        """
        from .parallel_physical import build_batch

        batch = build_batch(
            self, admission, requests, not_before_us=_time(not_before_us)
        )
        additions: tuple[PhysicalEntry, ...] = ()
        if batch.start_us > self._clock_us:
            additions = (
                PhysicalWait(
                    self._clock_us, batch.start_us, f"batch_not_before:{batch.batch_id}"
                ),
            )
        self._entries += additions + (batch,)
        self._invocations += batch.invocations
        self._identities |= {batch.batch_id} | {
            identity
            for member_id, parts in batch.member_parts
            for identity in (member_id, *(part.invocation_id for part in parts))
        }
        self._sources.update(
            {member_id: batch.source(member_id) for member_id, _ in batch.member_parts}
        )
        self._clock_us, self._world = batch.action_end_us, batch.world
        self._bindings = {binding.block_id: binding for binding in batch.bindings}
        self._next_result_id += sum(record.result_count for record in batch.invocations)
        return batch
