"""Observe the existing nonzoned scheduler without inventing contention causes."""

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from math import hypot, isclose
from typing import Any

from nadit_physical_compiler.atom_ir import (
    AtomAction,
    AtomStep,
    CZPulse,
    GlobalRY,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.compiler import CompilationResult
from nadit_physical_compiler.contracts import AtomFragment, GateLayer
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy


def _category(action: AtomAction, layer_kind: str) -> str:
    if isinstance(action, Load | Move | Store):
        purpose = (
            "readout"
            if layer_kind == "measure"
            else "cz"
            if layer_kind == "cz"
            else "other"
        )
        return f"{purpose}_{type(action).__name__.lower()}"
    if isinstance(action, CZPulse):
        return "cz_pulse"
    if isinstance(action, Measure):
        return "readout_exposure"
    if isinstance(action, Reset):
        return "reset"
    if isinstance(action, Rotation | LocalU | GlobalRY):
        return "rotation"
    if isinstance(action, Wait):
        return "wait"
    raise TypeError(f"Unsupported action for accounting: {type(action).__name__}.")


def partition_step(step: AtomStep, layer_kind: str) -> dict[str, float]:
    """Partition elapsed time, counting parallel actions once and retaining tails.

    Mixed categories receive a joined label rather than being double counted.
    This is accounting only; it does not validate concurrent hardware actions.
    """
    result: dict[str, float] = defaultdict(float)
    boundaries = sorted({0.0, *(action.duration_us for action in step.actions)})
    for start, end in pairwise(boundaries):
        categories = sorted(
            {
                _category(action, layer_kind)
                for action in step.actions
                if action.duration_us > start
            }
        )
        result["+".join(categories)] += end - start
    return dict(result)


@dataclass
class RecordedStrategy:
    """Record actual layer choices and fragments from an unchanged base strategy.

    Args:
        base: Existing fixed-home nonzoned strategy, with lookahead disabled.
        node_owners: Factory ID for each native DAG node; metadata may use -1.
        atom_owners: Active workload atoms only; missing IDs remain spectators.

    Use a fresh recorder per compilation. Report rejects compiler-inserted waits:
    the layer clock is intended for unconditional SE with zero feedback latency.
    """

    base: NonZonedStrategy
    node_owners: tuple[int, ...]
    atom_owners: dict[int, int]
    records: list[dict[str, Any]] = field(default_factory=list, init=False)
    clock_us: float = field(default=0.0, init=False)
    _steps: list[AtomStep] = field(default_factory=list, init=False, repr=False)
    _pending: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _dag: PhysicalDAG | None = field(default=None, init=False, repr=False)

    @property
    def lookahead_enabled(self) -> bool:
        """Disable speculation exactly as the wrapped nonzoned strategy does."""
        return self.base.lookahead_enabled

    def select(self, dag: PhysicalDAG, ready: tuple[int, ...]) -> GateLayer:
        """Delegate selection and remember the observed ready frontier."""
        if len(self.node_owners) != len(dag.nodes):
            raise ValueError("Node ownership must cover the native DAG exactly.")
        if self._pending is not None:
            raise ValueError("Recorder received another selection before lowering.")
        if self._dag is not None and self._dag != dag:
            raise ValueError("Use a fresh recorder for each DAG.")
        self._dag = dag
        layer = self.base.select(dag, ready)
        self._pending = {
            "ready_operation_ids": list(ready),
            "selected_operation_ids": list(layer.operation_ids),
        }
        return layer

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
        """Return the original fragment and record its real interval and phases."""
        if self._pending is None or self._pending["selected_operation_ids"] != list(
            layer.operation_ids
        ):
            raise ValueError("Lowering must match the recorder's selected layer.")
        fragment = self.base.lower(
            dag,
            layer,
            layout,
            device,
            following=following,
            retained_atoms=retained_atoms,
        )
        kind = dag.nodes[layer.operation_ids[0]].name
        phases: dict[str, float] = defaultdict(float)
        batches = []
        for step in fragment.steps:
            for category, duration in partition_step(step, kind).items():
                phases[category] += duration
            for action in step.actions:
                if isinstance(action, Load):
                    atoms = tuple(binding[0] for binding in action.bindings)
                    batches.append(
                        {
                            "atom_count": len(atoms),
                            "factory_ids": self._owners(atoms),
                            "aod_id": action.grid.aod_id,
                            "row_count": len(action.grid.rows),
                            "column_count": len(action.grid.columns),
                        }
                    )
        duration = sum(step.duration_us for step in fragment.steps)
        record = self._pending | {
            "layer_index": len(self.records),
            "kind": kind,
            "factory_ids": sorted(
                {
                    self.node_owners[i]
                    for i in layer.operation_ids
                    if self.node_owners[i] >= 0
                }
            ),
            "start_us": self.clock_us,
            "end_us": self.clock_us + duration,
            "first_step": len(self._steps),
            "stop_step": len(self._steps) + len(fragment.steps),
            "time_partition_us": dict(phases),
            "load_batches": batches,
        }
        self.records.append(record)
        self._pending = None
        self.clock_us += duration
        self._steps.extend(fragment.steps)
        return fragment

    def _owners(self, atoms: tuple[int, ...]) -> list[int]:
        return sorted(
            {self.atom_owners[a] for a in atoms if self.atom_owners.get(a, -1) >= 0}
        )

    def report(
        self, result: CompilationResult, entry: AtomLayout, device: Device
    ) -> dict[str, Any]:
        """Replay once to attribute actual actions, readout destinations and exits.

        Call after independent physical validation. No timing residual or idle
        interval is classified as a resource-blocking cause. Spectator exposure
        is separate from factory participation and cannot inflate concurrency.
        """
        if self._pending is not None or tuple(self._steps) != result.program.steps:
            raise ValueError(
                "Result contains unobserved actions or compiler-inserted waits."
            )
        if self._dag is None:
            raise ValueError("No observed DAG is available.")
        if not isclose(
            self.clock_us, result.program.duration_us, abs_tol=1e-8, rel_tol=1e-12
        ):
            raise ValueError("Observed fragment clock disagrees with program duration.")
        return _Report(self, result, entry, device).build()


class _Report:
    def __init__(
        self,
        observer: RecordedStrategy,
        result: CompilationResult,
        entry: AtomLayout,
        device: Device,
    ):
        self.observer, self.result, self.entry, self.device = (
            observer,
            result,
            entry,
            device,
        )
        self.batches: list[dict[str, Any]] = []
        self.active_batches: dict[str, dict[str, Any]] = {}
        self.destinations: list[dict[str, Any]] = []
        self.pulses: list[dict[str, Any]] = []
        self.factories: dict[int, dict[str, Any]] = {
            owner: {
                "factory_id": owner,
                "measurement_ready_us": None,
                "action_completion_us": 0.0,
                "final_home_us": 0.0,
            }
            for owner in sorted(set(observer.atom_owners.values()))
            if owner >= 0
        }
        self.ready = {m.result: m.available_at_us for m in result.measurements}
        self.phases: dict[str, float] = defaultdict(float)
        self.overlap_us = 0.0
        self.peak = 0

    def _action_atoms(self, action: AtomAction, layout: AtomLayout) -> tuple[int, ...]:
        if isinstance(action, Load | Store):
            return tuple(b[0] for b in action.bindings)
        if isinstance(action, Move):
            return tuple(a for a, _ in action.targets)
        if isinstance(action, Measure):
            return tuple(a for a, _ in action.results)
        if isinstance(action, Rotation | LocalU | Reset):
            return action.atoms
        if isinstance(action, CZPulse | GlobalRY):
            assert self.observer._dag is not None
            return tuple(
                sorted(
                    {
                        layout.qubit_to_atom[q]
                        for i in action.source_ids
                        for q in self.observer._dag.nodes[i].qubits
                    }
                )
            )
        return ()

    def _transport(
        self,
        action: Load | Move | Store,
        atoms: tuple[int, ...],
        layout: AtomLayout,
        record: dict[str, Any],
        start: float,
    ) -> None:
        aod_id = action.grid.aod_id
        if isinstance(action, Load):
            if aod_id in self.active_batches:
                raise ValueError(
                    "Recorder expects closed nonzoned LOAD/STORE episodes."
                )
            batch = {
                "batch_id": len(self.batches),
                "layer_index": record["layer_index"],
                "purpose": "readout" if record["kind"] == "measure" else "cz",
                "aod_id": aod_id,
                "start_us": start,
                "end_us": None,
                "atom_count": len(atoms),
                "factory_ids": self.observer._owners(atoms),
                "unowned_atom_count": sum(
                    self.observer.atom_owners.get(a, -1) < 0 for a in atoms
                ),
                "source_rows_um": [r.coordinate for r in action.grid.rows],
                "source_columns_um": [c.coordinate for c in action.grid.columns],
                "moves": [],
            }
            self.batches.append(batch)
            self.active_batches[aod_id] = batch
        elif isinstance(action, Move):
            batch = self.active_batches[aod_id]
            distances = {
                a: hypot(
                    target.x - layout.atom(a).position.x,
                    target.y - layout.atom(a).position.y,
                )
                for a, target in action.targets
            }
            by_owner = {
                str(owner): max(
                    (
                        d
                        for a, d in distances.items()
                        if self.observer.atom_owners.get(a, -1) == owner
                    ),
                    default=0.0,
                )
                for owner in self.observer._owners(atoms)
            }
            batch["moves"].append(
                {
                    "start_us": start,
                    "end_us": start + action.duration_us,
                    "duration_us": action.duration_us,
                    "maximum_atom_distance_um": max(distances.values(), default=0.0),
                    "total_atom_distance_um": sum(distances.values()),
                    "factory_maximum_distance_um": by_owner,
                    "target_rows_um": [r.coordinate for r in action.grid.rows],
                    "target_columns_um": [c.coordinate for c in action.grid.columns],
                }
            )
        else:
            batch = self.active_batches.pop(aod_id)
            batch["end_us"] = start + action.duration_us
            for atom, site in action.bindings:
                owner = self.observer.atom_owners.get(atom, -1)
                if owner >= 0 and self.entry.atom(atom).holder == SLMHolder(site):
                    self.factories[owner]["final_home_us"] = max(
                        self.factories[owner]["final_home_us"],
                        start + action.duration_us,
                    )

    def build(self) -> dict[str, Any]:
        layout = self.entry
        records = iter(self.observer.records)
        record = next(records, None)
        for index, (start, step) in enumerate(self.result.program.timeline()):
            while record is not None and index >= record["stop_step"]:
                record = next(records, None)
            if record is None:
                raise ValueError("Action step has no observed layer.")
            for phase, duration in partition_step(step, record["kind"]).items():
                self.phases[phase] += duration
            owners_by_action = []
            for action in step.actions:
                atoms = self._action_atoms(action, layout)
                owners = self.observer._owners(atoms)
                owners_by_action.append((action.duration_us, owners))
                for owner in owners:
                    self.factories[owner]["action_completion_us"] = max(
                        self.factories[owner]["action_completion_us"],
                        start + action.duration_us,
                    )
                if isinstance(action, Load | Move | Store):
                    self._transport(action, atoms, layout, record, start)
                elif isinstance(action, Measure):
                    for atom, reference in action.results:
                        position = layout.atom(atom).position
                        owner = self.observer.atom_owners.get(atom, -1)
                        ready = self.ready[reference]
                        self.destinations.append(
                            {
                                "atom_id": atom,
                                "factory_id": owner,
                                "measurement_id": reference.measurement_id,
                                "start_us": start,
                                "available_at_us": ready,
                                "x_um": position.x,
                                "y_um": position.y,
                            }
                        )
                        if owner >= 0:
                            previous = self.factories[owner]["measurement_ready_us"]
                            self.factories[owner]["measurement_ready_us"] = max(
                                previous or 0.0, ready
                            )
                elif isinstance(action, CZPulse):
                    illuminated = (
                        action.coverage
                        if isinstance(action.coverage, tuple)
                        else tuple(
                            a.id
                            for a in layout.atoms
                            if action.coverage.contains(a.position)
                        )
                    )
                    spectators = set(illuminated) - set(atoms)
                    self.pulses.append(
                        {
                            "start_us": start,
                            "end_us": start + action.duration_us,
                            "participant_factory_ids": owners,
                            "participant_atom_count": len(atoms),
                            "illuminated_atom_count": len(illuminated),
                            "spectator_atom_count": len(spectators),
                            "unowned_spectator_atom_count": sum(
                                self.observer.atom_owners.get(a, -1) < 0
                                for a in spectators
                            ),
                        }
                    )
            boundaries = sorted({0.0, *(duration for duration, _ in owners_by_action)})
            for left, right in pairwise(boundaries):
                active_owners = {
                    owner
                    for duration, values in owners_by_action
                    if duration > left
                    for owner in values
                }
                self.peak = max(self.peak, len(active_owners))
                if len(active_owners) > 1:
                    self.overlap_us += right - left
            layout = apply_step(layout, step, self.device)
        if self.active_batches:
            raise ValueError("Transport episode did not release its AOD.")
        if layout != self.result.exit_state:
            raise ValueError("Observed replay disagrees with result exit state.")
        for atom, owner in self.observer.atom_owners.items():
            if owner >= 0 and layout.atom(atom) != self.entry.atom(atom):
                raise ValueError(
                    "Parallel SE reporting requires every active atom back at home."
                )
        if not isclose(
            sum(self.phases.values()),
            self.result.program.duration_us,
            abs_tol=1e-8,
            rel_tol=1e-12,
        ):
            raise ValueError("Exclusive phase durations do not conserve elapsed time.")
        return {
            "scope": "observed_actions_not_contention_causes",
            "program_duration_us": self.result.program.duration_us,
            "result_completion_us": self.result.duration_us,
            "time_partition_us": dict(self.phases),
            "layers": self.observer.records,
            "transport_batches": self.batches,
            "measured_destinations": self.destinations,
            "cz_pulses": self.pulses,
            "per_factory": list(self.factories.values()),
            "concurrency": {
                "peak_active_factory_count": self.peak,
                "multi_factory_active_time_us": self.overlap_us,
                "multi_factory_layer_count": sum(
                    len(r["factory_ids"]) > 1 for r in self.observer.records
                ),
                "shared_transport_batch_count": sum(
                    len(b["factory_ids"]) > 1 for b in self.batches
                ),
                "maximum_factories_in_transport_batch": max(
                    (len(b["factory_ids"]) for b in self.batches), default=0
                ),
            },
        }
