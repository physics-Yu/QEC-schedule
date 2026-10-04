"""Persistent scheduling executor, deliberately independent of the legacy Env.

This kernel checks identity, carrier state and causal effects. Continuous
geometry, laser footprints and device constraints belong to the offline audit.
Reports come from an explicitly declared classical source, not a quantum model.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from .model import Block, GateSpec, Observation, Operation, TrajectoryEvaluation, freeze, gate_kind, thaw


class KernelError(ValueError):
    def __init__(self, code: str, message: str, *, operation_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(thaw(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class DeclaredReportSource:
    """Versioned trajectory, report lookup, or seeded Bernoulli declaration.

    A source is copied into its executor. ``cursor`` advances only after a
    successful MEASURE completion; previewing a failed batch consumes no bits.
    Seeded samples use a counter hash so checkpointing needs no hidden RNG state.
    """

    def __init__(
        self, *, source_id: str = "declared-trajectory", version: str = "1",
        bits: Sequence[int] | None = None, reports: Mapping[str, int] | None = None,
        seed: int | None = None, probability_one: float | None = None,
    ):
        if not isinstance(source_id, str) or not source_id or not isinstance(version, str) or not version:
            raise ValueError("report sources require an id and version")
        if sum((bits is not None, reports is not None, probability_one is not None)) != 1:
            raise ValueError("declare exactly one of bits, reports, or probability_one")
        self.source_id, self.version = source_id, version
        self._bits = tuple(bits) if bits is not None else None
        self._reports = dict(reports) if reports is not None else None
        for bit in self._bits or ():
            self._check_bit(bit)
        for report, bit in (self._reports or {}).items():
            if not isinstance(report, str) or not report:
                raise ValueError("report ids must be nonempty strings")
            self._check_bit(bit)
        if probability_one is not None:
            probability_one = float(probability_one)
            if not isfinite(probability_one) or not 0 <= probability_one <= 1:
                raise ValueError("probability_one must be in [0, 1]")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("a statistical source requires an integer seed")
        self.seed, self.probability_one = seed, probability_one
        self._cursor = 0

    @staticmethod
    def _check_bit(bit: int) -> None:
        if isinstance(bit, bool) or not isinstance(bit, int) or bit not in (0, 1):
            raise ValueError("declared reports must be integer bits")

    @property
    def cursor(self) -> int:
        return self._cursor

    def _preview(self, report_ids: tuple[str, ...]) -> tuple[int, ...]:
        result = []
        for offset, report in enumerate(report_ids):
            cursor = self._cursor + offset
            if self._bits is not None:
                if cursor >= len(self._bits):
                    raise KernelError("MISSING_REPORT", f"report trajectory exhausted at {report}")
                bit = self._bits[cursor]
            elif self._reports is not None:
                if report not in self._reports:
                    raise KernelError("MISSING_REPORT", f"source has no report {report}")
                bit = self._reports[report]
            else:
                sample = int(_digest([self.source_id, self.version, self.seed, cursor, report]), 16)
                bit = int(sample < self.probability_one * (1 << 256))
            result.append(bit)
        return tuple(result)

    def checkpoint(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id, "version": self.version,
            "bits": list(self._bits) if self._bits is not None else None,
            "reports": dict(self._reports) if self._reports is not None else None,
            "seed": self.seed, "probability_one": self.probability_one,
            "cursor": self._cursor,
        }

    @classmethod
    def restore(cls, payload: Mapping[str, Any]) -> DeclaredReportSource:
        result = cls(**{key: payload[key] for key in ("source_id", "version", "bits", "reports", "seed", "probability_one")})
        cursor = payload["cursor"]
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("invalid report source cursor")
        if result._bits is not None and cursor > len(result._bits):
            raise ValueError("report cursor exceeds trajectory")
        result._cursor = cursor
        return result


class KernelExecutor:
    CHECKPOINT_VERSION = 2
    _GATE_KINDS = frozenset(("H", "X", "Y", "Z", "T", "CZ", "MEASURE", "RESET"))
    _OP_KINDS = frozenset(("CONFIGURE", "LOAD", "MOVE", "STORE", "GATE", "CZ", "MEASURE", "RESET", "WAIT"))

    def __init__(
        self, initial_positions: Mapping[str, tuple[float, float]],
        gates: Iterable[GateSpec] = (), *, initial_holders: Mapping[str, str] | None = None,
        initial_aod_axes: Mapping[str, Mapping[str, Sequence[float]]] | None = None,
        report_source: DeclaredReportSource | None = None,
        recording: bool = True,
        journal_sink: Callable[[Mapping[str, Any]], Any] | None = None,
    ):
        self._atom_ids = tuple(initial_positions)
        if any(not isinstance(atom, str) or not atom for atom in self._atom_ids):
            raise ValueError("atom ids must be nonempty strings")
        self._atom_index = {atom: index for index, atom in enumerate(self._atom_ids)}
        holders = dict(initial_holders or {})
        if set(holders) - set(self._atom_ids):
            raise ValueError("initial holders contain unknown atoms")
        # Each atom has exactly one location truth: (holder, x, y).
        self._locations: list[tuple[str, float, float]] = []
        for atom, point in initial_positions.items():
            if len(point) != 2:
                raise ValueError("positions require two coordinates")
            x, y = float(point[0]), float(point[1])
            holder = holders.get(atom, "slm")
            if not isfinite(x) or not isfinite(y) or not isinstance(holder, str) or not holder:
                raise ValueError("invalid initial atom location")
            self._locations.append((holder, x, y))
        self._device_axes = {device: (*self._parse_axes(axes), (), ()) for device, axes in (initial_aod_axes or {}).items()}
        for device in {location[0] for location in self._locations if location[0] != "slm"}:
            self._update_axes(device)
        self._time_us, self._version = 0.0, 0
        self._gate_specs: dict[str, GateSpec] = {}
        self._remaining_dependencies: dict[str, int] = {}
        self._successors: dict[str, list[str]] = {}
        self._ready: set[str] = set()
        self._completed: set[str] = set()
        self._completed_order: list[str] = []
        self._gate_fragment: dict[str, str] = {}
        self._fragments: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        self._fragment_remaining: dict[str, int] = {}
        self._measurement_results: dict[str, int] = {}
        self._measurement_times: dict[str, float] = {}
        self._report_order: list[str] = []
        self._report_bindings: dict[str, dict[str, str]] = {}
        self._report_source = DeclaredReportSource.restore(report_source.checkpoint()) if report_source is not None else None
        self._active_block: Block | None = None
        self._operation_cursor = 0
        self._running: tuple[float, float] | None = None
        self._serial_context: dict[str, Any] | None = None
        self._block_start_us = 0.0
        self._block_completed: list[str] = []
        self._block_completed_set: set[str] = set()
        self._inflight: dict[str, dict[str, Any]] = {}
        self._scheduled_events: list[tuple[float, int, int, str, str]] = []
        self._scheduled_resources: dict[str, tuple[str, ...]] = {}
        self._operation_by_id: dict[str, Operation] = {}
        self._operation_ordinals: dict[str, int] = {}
        self._submitted_block_ids: set[str] = set()
        self._recording = bool(recording)
        self._journal_sink = journal_sink
        self._journal: list[Mapping[str, Any]] = []
        self._sink_errors: list[str] = []
        self._in_journal_sink = False
        self._observation_cache: Observation | None = None
        gates = tuple(gates)
        if gates:
            self._declare_fragment("__initial__", gates, ())
        self._state_digest = _digest({
            "atoms": list(zip(self._atom_ids, self._locations)),
            "aod_axes": self._device_axes,
            "gates": [self._gate_payload(gate) for gate in gates],
            "source": self._report_source.checkpoint() if self._report_source else None,
        })

    @property
    def time_us(self) -> float:
        return self._time_us

    @property
    def version(self) -> int:
        return self._version

    @property
    def journal(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._journal)

    @property
    def journal_sink_errors(self) -> tuple[str, ...]:
        return tuple(self._sink_errors)

    def state_hash(self) -> str:
        """An incremental digest of committed state, independent of recording."""
        return self._state_digest

    def observe(self) -> Observation:
        if self._observation_cache is None:
            evaluated = self.evaluate()
            inflight = tuple(self._inflight) if self._inflight else ((self._active_block.operations[self._operation_cursor].id,) if self._running else ())
            owners = {resource: id for id, context in self._inflight.items() for resource in context["resources"]}
            if self._serial_context is not None:
                owners.update({resource: self._serial_context["operation_id"] for resource in self._serial_context["resources"]})
            self._observation_cache = Observation(
                self._time_us, self._version,
                MappingProxyType(dict(self._measurement_results)), tuple(self._completed_order),
                tuple(self._fragments),
                self._active_block is None and all(count == 0 for count in self._fragment_remaining.values()),
                len(self._scheduled_events) if self._active_block and self._active_block.execution_mode == "scheduled" else int(self._running is not None),
                MappingProxyType({atom: self._locations[index][0] for index, atom in enumerate(self._atom_ids)}),
                evaluated.positions,
                MappingProxyType(dict(self._measurement_times)),
                MappingProxyType(dict(self._fragment_remaining)),
                tuple(fragment for fragment, count in self._fragment_remaining.items() if count == 0),
                self._report_source.cursor if self._report_source else None,
                evaluated.aod_axes,
                inflight, tuple(self._block_completed), MappingProxyType(owners),
                MappingProxyType({atom: self._locations[index][1:] for index, atom in enumerate(self._atom_ids)}),
            )
        return self._observation_cache

    def bind_block(self, id: str, operations: Iterable[Operation], *, native_provenance: Mapping[str, Any] | None = None,
                   execution_mode: str = "serial") -> Block:
        return Block(id, tuple(operations), self._version, self._state_digest, native_provenance or {}, execution_mode)

    @staticmethod
    def _motion_fraction(profile: str, progress: float) -> float:
        progress = max(0., min(1., progress))
        return progress*progress*(3.-2.*progress) if profile == "row_column" else progress

    def evaluate(self, time_us: float | None = None) -> TrajectoryEvaluation:
        """Pure coordinates at the current/future active-event interval.

        Locations remain committed endpoints internally. This derives the same
        common trajectory used by observers, without installing interpolated
        positions into state or consuming future start/completion events.
        """
        time = self._time_us if time_us is None else float(time_us)
        if not isfinite(time) or time < self._time_us:
            raise KernelError("TRAJECTORY_TIME", "evaluate cannot reconstruct past committed state")
        next_event = self._scheduled_events[0][0] if self._scheduled_events else self._running[1] if self._running else None
        if next_event is not None and time > next_event:
            raise KernelError("TRAJECTORY_TIME", "advance events before evaluating beyond the next boundary")
        positions = {atom: self._locations[index][1:] for index, atom in enumerate(self._atom_ids)}
        axes = dict(self._device_axes)
        contexts = list(self._inflight.values())
        if self._serial_context is not None:
            contexts.append(self._serial_context)
        for context in contexts:
            operation = context["operation"]
            if operation.kind not in ("MOVE", "CONFIGURE"):
                continue
            start, end = context["start_us"], context["end_us"]
            fraction = self._motion_fraction(operation.motion_profile, (time-start)/(end-start) if end > start else 1.)
            source = context["source_axes"]
            target = context["target_axes"]
            rows = tuple(a+fraction*(b-a) for a, b in zip(source[0], target[0]))
            columns = tuple(a+fraction*(b-a) for a, b in zip(source[1], target[1]))
            active_rows = tuple(rows[index] for index, value in enumerate(source[0]) if value in source[2])
            active_columns = tuple(columns[index] for index, value in enumerate(source[1]) if value in source[3])
            axes[operation.aod_id] = (rows, columns, active_rows, active_columns)
            for atom, point in context["source_positions"]:
                column = source[1].index(point[0])
                row = source[0].index(point[1])
                positions[atom] = (columns[column], rows[row])
        frozen_axes = MappingProxyType({device: MappingProxyType(dict(zip(("rows", "columns", "active_rows", "active_columns"), value)))
                                      for device, value in axes.items()})
        return TrajectoryEvaluation(time, self._version, MappingProxyType(positions), frozen_axes)

    def activate_fragment(self, id: str, gates: Iterable[GateSpec], *, requires_report_ids: Iterable[str] = ()) -> Observation:
        self._check_writer_entry()
        gates, reports = tuple(gates), tuple(requires_report_ids)
        self._declare_fragment(id, gates, reports)
        self._commit("FRAGMENT_ACTIVATED", fragment_id=id, gates=tuple(self._gate_payload(gate) for gate in gates),
                     gate_ids=tuple(gate.id for gate in gates), activated_gate_ids=tuple(gate.id for gate in gates), requires_report_ids=reports)
        return self.observe()

    def _declare_fragment(self, id: str, gates: tuple[GateSpec, ...], reports: tuple[str, ...]) -> None:
        if not isinstance(id, str) or not id or id in self._fragments:
            raise KernelError("DUPLICATE_FRAGMENT", f"invalid or already activated fragment {id}")
        if len(set(reports)) != len(reports) or any(report not in self._measurement_results for report in reports):
            raise KernelError("REPORT_NOT_READY", f"fragment {id} requires uncommitted reports")
        additions = {gate.id: gate for gate in gates if isinstance(gate, GateSpec)}
        if len(additions) != len(gates) or set(additions) & self._gate_specs.keys():
            raise KernelError("DUPLICATE_GATE", "fragment contains invalid or already declared gates")
        known = self._gate_specs.keys() | additions.keys()
        for gate in gates:
            if gate.kind not in self._GATE_KINDS or len(gate.atoms) != (2 if gate.kind == "CZ" else 1):
                raise KernelError("GATE_IDENTITY", f"invalid kind/arity for gate {gate.id}")
            if set(gate.atoms) - self._atom_index.keys():
                raise KernelError("UNKNOWN_ATOM", f"gate {gate.id} names unknown atoms")
            if set(gate.depends_on) - known:
                raise KernelError("UNKNOWN_DEPENDENCY", f"gate {gate.id} names undeclared dependencies")
        # Only the newly declared subgraph needs a cycle check.
        indegree = {gate.id: sum(dependency in additions for dependency in gate.depends_on) for gate in gates}
        new_successors: dict[str, list[str]] = {key: [] for key in additions}
        for gate in gates:
            for dependency in gate.depends_on:
                if dependency in additions:
                    new_successors[dependency].append(gate.id)
        frontier = [key for key, count in indegree.items() if count == 0]
        visited = 0
        while frontier:
            key = frontier.pop()
            visited += 1
            for successor in new_successors[key]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    frontier.append(successor)
        if visited != len(gates):
            raise KernelError("DEPENDENCY_CYCLE", "fragment dependencies contain a cycle")
        # All checks precede declaration: activation failure is atomic.
        self._fragments[id] = (tuple(additions), reports)
        self._fragment_remaining[id] = len(gates)
        for gate in gates:
            self._gate_specs[gate.id] = gate
            self._gate_fragment[gate.id] = id
            remaining = sum(dependency not in self._completed for dependency in gate.depends_on)
            self._remaining_dependencies[gate.id] = remaining
            if remaining == 0:
                self._ready.add(gate.id)
            for dependency in gate.depends_on:
                self._successors.setdefault(dependency, []).append(gate.id)

    def run(self, block: Block | None = None, *, until_us: float | None = None) -> Observation:
        self._check_writer_entry()
        if until_us is not None:
            self._check_time(until_us)
        if block is not None:
            self._submit_block(block)
        self._drive(float(until_us) if until_us is not None else None)
        return self.observe()

    def wait_until(self, time_us: float) -> Observation:
        self._check_writer_entry()
        self._check_time(time_us)
        self._drive(float(time_us))
        return self.observe()

    def _check_writer_entry(self) -> None:
        if self._in_journal_sink:
            raise KernelError("OBSERVER_REENTRANCY", "a journal observer cannot submit runtime changes")

    def _check_time(self, time_us: float) -> None:
        if not isfinite(time_us) or time_us < self._time_us:
            raise KernelError("TIME_REVERSED", "requested time must be finite and cannot precede committed time")

    def _submit_block(self, block: Block) -> None:
        if not isinstance(block, Block):
            raise TypeError("run requires a Block")
        if block.expected_version != self._version or block.starting_state_hash != self._state_digest:
            raise KernelError("STALE_BLOCK", "block binding does not match committed state")
        if self._active_block is not None:
            raise KernelError("BLOCK_BUSY", "finish the current block before submitting another")
        if block.id in self._submitted_block_ids:
            raise KernelError("DUPLICATE_BLOCK", f"block {block.id} was already submitted")
        # Identity/shape checks are cheap and do not require a predicted state.
        effects_seen: set[str] = set()
        reports_seen: set[str] = set()
        for operation in block.operations:
            self._check_operation_shape(operation)
            if any(key in effects_seen or key in self._completed for key in operation.gate_ids):
                self._error(operation, "DUPLICATE_GATE_EFFECT", "block repeats an already completed or repeated gate effect")
            effects_seen.update(operation.gate_ids)
            if self._operation_kind(operation) == "MEASURE":
                reports = self._reports_for(operation)
                if any(report in reports_seen or report in self._measurement_results for report in reports):
                    self._error(operation, "DUPLICATE_REPORT", "block repeats an already committed or repeated report")
                reports_seen.update(reports)
        schedule_resources = self._prepare_schedule(block) if block.execution_mode == "scheduled" else {}
        if block.operations and block.execution_mode == "serial":
            self._validate_operation(block.operations[0])
        self._active_block, self._operation_cursor = block, 0
        self._block_start_us = self._time_us
        self._block_completed = []
        self._block_completed_set = set()
        self._operation_by_id = {operation.id: operation for operation in block.operations}
        self._operation_ordinals = {operation.id: index for index, operation in enumerate(block.operations)}
        self._scheduled_resources = schedule_resources
        self._scheduled_events = [(self._time_us+operation.start_us, 1, index, operation.id, "start")
                                  for index, operation in enumerate(block.operations)] if block.execution_mode == "scheduled" else []
        heapq.heapify(self._scheduled_events)
        self._submitted_block_ids.add(block.id)
        self._commit("BLOCK_STARTED", block_id=block.id, native_provenance=block.native_provenance,
                     execution_mode=block.execution_mode, block_start_us=self._block_start_us,
                     operations_hash=_digest([self._operation_payload(operation) for operation in block.operations]))

    def _resources_for(self, operation: Operation, locations: Mapping[str, tuple[str, float, float]] | None = None) -> tuple[str, ...]:
        if locations is None:
            locations = {atom: self._locations[index] for atom, index in self._atom_index.items()}
        kind = self._operation_kind(operation)
        resources = set(operation.resources)
        resources.update("ATOM:"+atom for atom in operation.atoms)
        if kind in ("CONFIGURE", "LOAD", "MOVE", "STORE"):
            resources.add(operation.aod_id)
            resources.update("ATOM:"+atom for atom, location in locations.items() if location[0] == operation.aod_id)
        elif kind in ("GATE", "CZ", "MEASURE", "RESET"):
            resources.update(locations[atom][0] for atom in operation.atoms if locations[atom][0] != "slm")
            if kind == "GATE":
                resources.update("RAMAN:"+atom for atom in operation.atoms)
            elif kind == "CZ":
                resources.add("ENTANGLING_LASER_0")
            elif kind == "MEASURE":
                resources.add("READOUT_0")
            elif kind == "RESET":
                resources.add("RESET_0")
        return tuple(sorted(resources))

    def _unitary_kind(self, operation: Operation) -> str | None:
        return self._gate_specs[operation.gate_ids[0]].kind if self._operation_kind(operation) in ("GATE", "CZ") else None

    @staticmethod
    def _relative_end(operation: Operation) -> float:
        return operation.end_us if operation.end_us is not None else operation.start_us+operation.duration_us

    def _prepare_schedule(self, block: Block) -> dict[str, tuple[str, ...]]:
        """Check explicit temporal/identity resources once at block submission.

        This is not a geometry audit. The independent reviewer owns continuous
        clearance and global illumination checks over these same intervals.
        """
        operations = {operation.id: operation for operation in block.operations}
        ends = {id: self._relative_end(operation) for id, operation in operations.items()}
        if any(not isfinite(end+self._time_us) for end in ends.values()):
            raise KernelError("TIME_OVERFLOW", "scheduled completion time is not finite")
        gate_operation = {gate: operation for operation in block.operations for gate in operation.gate_ids}
        report_operation = {report: operation for operation in block.operations if operation.kind == "MEASURE" for report in self._reports_for(operation)}
        for operation in block.operations:
            for dependency in operation.depends_on:
                if dependency not in operations or ends[dependency] > operation.start_us:
                    self._error(operation, "DEPENDENCY_NOT_READY", "scheduled operation dependency is absent or unfinished at its start")
            for gate in operation.gate_ids:
                for dependency in self._gate_specs[gate].depends_on:
                    if dependency not in self._completed:
                        parent = gate_operation.get(dependency)
                        if parent is None or ends[parent.id] > operation.start_us:
                            self._error(operation, "DEPENDENCY_NOT_READY", "scheduled gate dependency is unfinished at its start")
            for report in operation.metadata.get("requires_report_ids", ()):
                if report not in self._measurement_results:
                    parent = report_operation.get(report)
                    if parent is None or ends[parent.id] > operation.start_us:
                        self._error(operation, "REPORT_NOT_READY", "scheduled operation requires an unavailable report")
        # Predicted carriers are tiny and mutate only at operation completions.
        locations = {atom: self._locations[index] for atom, index in self._atom_index.items()}
        events = [(operation.start_us, 1, index, operation.id, "start") for index, operation in enumerate(block.operations)]
        heapq.heapify(events)
        owners, active_kinds, active_resources, completed = {}, {}, {}, set()
        result = {}
        while events:
            time, phase, ordinal, id, event = heapq.heappop(events)
            operation = operations[id]
            kind = self._operation_kind(operation)
            if event == "complete":
                for resource in active_resources.pop(id):
                    owners.pop(resource)
                active_kinds.pop(id, None)
                if kind in ("LOAD", "STORE", "MOVE"):
                    targets = dict(operation.positions)
                    for atom in operation.atoms:
                        before = locations[atom]
                        locations[atom] = (operation.aod_id, *before[1:]) if kind == "LOAD" else ("slm", *before[1:]) if kind == "STORE" else (before[0], *targets[atom])
                completed.add(id)
                continue
            if any(dependency not in completed for dependency in operation.depends_on):
                self._error(operation, "DEPENDENCY_NOT_READY", "same-time zero-duration dependencies require parent-first declaration")
            if any(dependency not in self._completed and gate_operation[dependency].id not in completed
                   for gate in operation.gate_ids for dependency in self._gate_specs[gate].depends_on):
                self._error(operation, "DEPENDENCY_NOT_READY", "scheduled gate dependency has not completed before its start")
            if any(report not in self._measurement_results and report_operation[report].id not in completed
                   for report in operation.metadata.get("requires_report_ids", ())):
                self._error(operation, "REPORT_NOT_READY", "scheduled report producer has not completed before its start")
            if kind in ("LOAD", "MOVE", "STORE"):
                carrier = "slm" if kind == "LOAD" else operation.aod_id
                if any(locations[atom][0] != carrier for atom in operation.atoms):
                    self._error(operation, "CARRIER_STATE", "scheduled transport has incompatible carrier state at start")
            if kind == "CONFIGURE" and any(location[0] == operation.aod_id for location in locations.values()):
                self._error(operation, "CARRIER_STATE", "scheduled CONFIGURE requires an empty AOD")
            resources = self._resources_for(operation, locations)
            conflicts = tuple(resource for resource in resources if resource in owners)
            if conflicts:
                self._error(operation, "RESOURCE_CONFLICT", "scheduled intervals overlap required resources: "+", ".join(conflicts))
            unitary = self._unitary_kind(operation)
            if unitary is not None and any(kind != unitary for kind in active_kinds.values()):
                self._error(operation, "LASER_KIND_CONFLICT", "different unitary gate kinds cannot overlap")
            if unitary is not None:
                active_kinds[id] = unitary
            for resource in resources:
                owners[resource] = id
            active_resources[id] = resources
            result[id] = resources
            heapq.heappush(events, (ends[id], 0, ordinal, id, "complete"))
        return result

    def _operation_context(self, operation: Operation, start: float, end: float, resources: tuple[str, ...]) -> dict[str, Any]:
        source_axes = self._device_axes.get(operation.aod_id, ((), (), (), ()))
        target_axes = source_axes
        source_positions = ()
        if operation.kind in ("MOVE", "CONFIGURE"):
            if "target_axes" in operation.metadata:
                target_axes = (*self._parse_axes(operation.metadata["target_axes"]), source_axes[2], source_axes[3])
            elif operation.kind == "MOVE":
                targets = dict(operation.positions)
                loaded = {atom: targets.get(atom, self._locations[index][1:]) for atom, index in self._atom_index.items()
                          if self._locations[index][0] == operation.aod_id}
                target_axes = (tuple(sorted({point[1] for point in loaded.values()})), tuple(sorted({point[0] for point in loaded.values()})), source_axes[2], source_axes[3])
            if len(source_axes[0]) != len(target_axes[0]) or len(source_axes[1]) != len(target_axes[1]):
                if operation.kind == "CONFIGURE" and not source_axes[0] and not source_axes[1]:
                    source_axes = (target_axes[0], target_axes[1], (), ())
                else:
                    self._error(operation, "AXIS_DIMENSIONS", "motion must preserve explicit full RF dimensions")
            if operation.kind == "MOVE":
                source_positions = tuple((atom, self._locations[index][1:]) for atom, index in self._atom_index.items()
                                         if self._locations[index][0] == operation.aod_id)
                targets = dict(operation.positions)
                for atom, point in source_positions:
                    try:
                        row, column = source_axes[0].index(point[1]), source_axes[1].index(point[0])
                    except ValueError:
                        self._error(operation, "AXIS_STATE", "loaded atoms are not supported by committed full RF axes")
                    if (target_axes[1][column], target_axes[0][row]) != targets.get(atom, point):
                        self._error(operation, "POSITION_IDENTITY", "AOD RF target implies an undeclared or inconsistent atom move")
            if operation.motion_profile == "rigid":
                if any(len({round(b-a, 10) for a, b in zip(source, target)}) > 1 for source, target in zip(source_axes[:2], target_axes[:2])):
                    self._error(operation, "RIGID_DEFORMATION", "rigid motion cannot deform relative RF axes")
        return {"operation_id": operation.id, "operation": operation, "start_us": start, "end_us": end,
                "resources": resources, "motion_profile": operation.motion_profile,
                "source_axes": source_axes, "target_axes": target_axes, "source_positions": source_positions}

    def _start_record(self, operation: Operation, context: Mapping[str, Any]) -> None:
        self._commit("OPERATION_STARTED", block_id=self._active_block.id, operation_id=operation.id,
                     kind=operation.kind, atoms=operation.atoms, start_us=context["start_us"], end_us=context["end_us"],
                     aod_id=operation.aod_id, positions=operation.positions, gate_ids=operation.gate_ids, metadata=operation.metadata,
                     resources=context["resources"], depends_on=operation.depends_on, motion_profile=operation.motion_profile,
                     trajectory_profile="cubic" if operation.motion_profile == "row_column" else "linear",
                     source_axes=dict(zip(("rows", "columns", "active_rows", "active_columns"), context["source_axes"])),
                     target_axes=dict(zip(("rows", "columns"), context["target_axes"][:2])),
                     start_positions=context["source_positions"])

    def _check_operation_shape(self, operation: Operation) -> None:
        kind = self._operation_kind(operation)
        if kind not in self._OP_KINDS:
            self._error(operation, "UNSUPPORTED_OPERATION", f"unsupported operation {operation.kind}")
        if set(operation.atoms) - self._atom_index.keys():
            self._error(operation, "UNKNOWN_ATOM", "operation names unknown atoms")
        if set(operation.gate_ids) - self._gate_specs.keys():
            self._error(operation, "UNKNOWN_GATE", "operation names undeclared gate effects")
        if operation.positions and {atom for atom, _ in operation.positions} != set(operation.atoms):
            self._error(operation, "POSITION_IDENTITY", "position targets must match operation atoms")
        if kind == "MOVE" and not operation.positions:
            self._error(operation, "POSITION_IDENTITY", "MOVE requires explicit target positions")
        if kind not in ("WAIT", "CONFIGURE") and not operation.atoms:
            self._error(operation, "ATOM_IDENTITY", "operation requires target atoms")
        if kind in ("GATE", "CZ", "MEASURE", "RESET") and not operation.gate_ids:
            self._error(operation, "GATE_IDENTITY", "effect operations require declared gate ids")
        if kind not in ("GATE", "CZ", "MEASURE", "RESET") and (operation.gate_ids or operation.report_ids):
            self._error(operation, "GATE_IDENTITY", "transport/wait cannot commit gate or report effects")
        if operation.report_ids and kind != "MEASURE":
            self._error(operation, "REPORT_IDENTITY", "only MEASURE can commit reports")
        if kind == "MEASURE" and len(self._reports_for(operation)) != len(operation.atoms):
            self._error(operation, "REPORT_IDENTITY", "MEASURE requires one report per target atom")
        if kind in ("GATE", "MEASURE", "RESET") and len(operation.gate_ids) != len(operation.atoms):
            self._error(operation, "GATE_IDENTITY", "a 1Q batch requires one declared effect per target atom")
        if kind in ("CONFIGURE", "LOAD", "MOVE", "STORE") and operation.aod_id == "slm":
            self._error(operation, "CARRIER_IDENTITY", "transport requires an AOD carrier")
        if kind == "CONFIGURE":
            if operation.atoms or operation.positions or "target_axes" not in operation.metadata:
                self._error(operation, "AXIS_IDENTITY", "CONFIGURE requires only explicit target axes")
            self._parse_axes(operation.metadata["target_axes"])
        if "source_axes" in operation.metadata:
            self._parse_axes(operation.metadata["source_axes"])
        if "target_axes" in operation.metadata:
            self._parse_axes(operation.metadata["target_axes"])

    @staticmethod
    def _operation_kind(operation: Operation) -> str:
        return "GATE" if operation.kind in ("H", "X", "Y", "Z", "T") else operation.kind

    def _validate_operation(self, operation: Operation) -> None:
        kind = self._operation_kind(operation)
        if kind == "CONFIGURE":
            if any(location[0] == operation.aod_id for location in self._locations):
                self._error(operation, "CARRIER_STATE", "CONFIGURE requires an empty AOD")
            if "source_axes" in operation.metadata and self._parse_axes(operation.metadata["source_axes"]) != self._device_axes.get(operation.aod_id, ((), (), (), ()))[:2]:
                self._error(operation, "AXIS_STATE", "CONFIGURE source axes do not match committed device axes")
        if kind in ("LOAD", "MOVE", "STORE"):
            expected_holder = "slm" if kind == "LOAD" else operation.aod_id
            for atom in operation.atoms:
                if self._locations[self._atom_index[atom]][0] != expected_holder:
                    self._error(operation, "CARRIER_STATE", f"{kind} requires {atom} in {expected_holder}")
            if kind != "MOVE":
                for atom, point in operation.positions:
                    if point != self._locations[self._atom_index[atom]][1:]:
                        self._error(operation, "POSITION_STATE", "LOAD/STORE cannot implicitly move atoms")
        required_reports = operation.metadata.get("requires_report_ids", ())
        if any(report not in self._measurement_results for report in required_reports):
            self._error(operation, "REPORT_NOT_READY", "operation requires uncommitted reports")
        if operation.gate_ids:
            specs = [self._gate_specs[key] for key in operation.gate_ids]
            if set(operation.atoms) != {atom for spec in specs for atom in spec.atoms}:
                self._error(operation, "GATE_IDENTITY", "operation atoms do not match declared gate targets")
            gate_kinds = {spec.kind for spec in specs}
            if kind == "GATE":
                expected = operation.kind if operation.kind != "GATE" else operation.metadata.get("gate_kind")
                if len(gate_kinds) != 1 or not gate_kinds <= {"H", "X", "Y", "Z", "T"} or (expected is not None and gate_kind(expected) not in gate_kinds):
                    self._error(operation, "GATE_IDENTITY", "GATE must apply one declared 1Q kind")
            elif gate_kinds != {kind}:
                self._error(operation, "GATE_IDENTITY", "operation kind disagrees with declared effects")
            for key in operation.gate_ids:
                if key in self._completed:
                    self._error(operation, "DUPLICATE_GATE_EFFECT", f"gate {key} is already completed")
                if key not in self._ready:
                    self._error(operation, "DEPENDENCY_NOT_READY", f"gate {key} has unfinished dependencies")
        if kind == "MEASURE":
            if any(report in self._measurement_results for report in self._reports_for(operation)):
                self._error(operation, "DUPLICATE_REPORT", "report ids were already committed")
            if self._report_source is None:
                self._error(operation, "MISSING_REPORT_SOURCE", "MEASURE requires a declared report source")

    @staticmethod
    def _reports_for(operation: Operation) -> tuple[str, ...]:
        return operation.report_ids or operation.gate_ids

    @staticmethod
    def _error(operation: Operation, code: str, message: str) -> None:
        raise KernelError(code, message, operation_id=operation.id)

    def _drive(self, limit: float | None) -> None:
        if self._active_block is not None and self._active_block.execution_mode == "scheduled":
            self._drive_scheduled(limit)
            return
        while self._active_block is not None:
            block = self._active_block
            if self._operation_cursor == len(block.operations):
                self._active_block, self._running = None, None
                self._serial_context = None
                self._commit("BLOCK_COMPLETED", block_id=block.id)
                continue
            operation = block.operations[self._operation_cursor]
            if self._running is None:
                if any(dependency not in self._block_completed_set for dependency in operation.depends_on):
                    self._error(operation, "DEPENDENCY_NOT_READY", "serial operation dependency is unfinished")
                self._validate_operation(operation)
                end_us = self._time_us + operation.duration_us
                if not isfinite(end_us):
                    self._error(operation, "TIME_OVERFLOW", "operation completion time is not finite")
                context = self._operation_context(operation, self._time_us, end_us, self._resources_for(operation))
                self._running = (self._time_us, end_us)
                self._serial_context = context
                self._start_record(operation, context)
            if limit is not None and self._running[1] > limit:
                break
            self._complete_operation(operation)
        if limit is not None and limit > self._time_us:
            self._time_us = limit
            self._commit("WAIT_COMPLETED", end_us=limit)

    def _drive_scheduled(self, limit: float | None) -> None:
        while self._active_block is not None:
            block = self._active_block
            if not self._scheduled_events:
                if self._inflight or len(self._block_completed) != len(block.operations):
                    raise KernelError("SCHEDULE_STATE", "scheduled queue does not cover unfinished operations")
                self._active_block = None
                self._commit("BLOCK_COMPLETED", block_id=block.id)
                break
            time, phase, ordinal, id, event = self._scheduled_events[0]
            if limit is not None and time > limit:
                break
            operation = self._operation_by_id[id]
            if event == "complete":
                self._complete_operation(operation, self._inflight[id])
                continue
            if any(dependency not in self._block_completed_set for dependency in operation.depends_on):
                self._error(operation, "DEPENDENCY_NOT_READY", "operation dependencies have not committed at scheduled start")
            self._validate_operation(operation)
            resources = self._resources_for(operation)
            if resources != self._scheduled_resources[id]:
                self._error(operation, "RESOURCE_STATE", "current carrier resources differ from the submitted schedule")
            occupied = {resource for context in self._inflight.values() for resource in context["resources"]}
            if occupied.intersection(resources):
                self._error(operation, "RESOURCE_CONFLICT", "required resources are currently occupied")
            unitary = self._unitary_kind(operation)
            if unitary is not None and any(self._unitary_kind(context["operation"]) not in (None, unitary) for context in self._inflight.values()):
                self._error(operation, "LASER_KIND_CONFLICT", "active unitary gate kind conflicts with scheduled start")
            context = self._operation_context(operation, time, self._block_start_us+self._relative_end(operation), resources)
            # All validation precedes queue/state mutation.
            heapq.heappop(self._scheduled_events)
            self._time_us = time
            self._inflight[id] = context
            heapq.heappush(self._scheduled_events, (context["end_us"], 0, ordinal, id, "complete"))
            self._start_record(operation, context)
        if limit is not None and limit > self._time_us:
            self._time_us = limit
            self._commit("WAIT_COMPLETED", end_us=limit)

    def _complete_operation(self, operation: Operation, context: Mapping[str, Any] | None = None) -> None:
        self._validate_operation(operation)
        scheduled = context is not None
        start, end = (context["start_us"], context["end_us"]) if scheduled else self._running
        if not isfinite(end):
            self._error(operation, "TIME_OVERFLOW", "operation completion time is not finite")
        kind = self._operation_kind(operation)
        reports = self._reports_for(operation) if kind == "MEASURE" else ()
        cursor_before = self._report_source.cursor if reports else None
        # Source preview is the last fallible operation before atomic effects.
        try:
            bits = self._report_source._preview(reports) if reports else ()
        except KernelError as error:
            raise KernelError(error.code, str(error), operation_id=operation.id) from error
        changed = []
        targets = dict(operation.positions)
        for atom in operation.atoms:
            index = self._atom_index[atom]
            before = self._locations[index]
            after = before
            if kind == "LOAD":
                after = (operation.aod_id, before[1], before[2])
            elif kind == "STORE":
                after = ("slm", before[1], before[2])
            elif kind == "MOVE":
                after = (before[0], *targets[atom])
            if after != before:
                changed.append((atom, before, after))
        # No full-state/history copy is made here: only affected entries change.
        if scheduled:
            heapq.heappop(self._scheduled_events)
            self._inflight.pop(operation.id)
        self._time_us = end
        for atom, _, after in changed:
            self._locations[self._atom_index[atom]] = after
        axes_delta = None
        if kind in ("CONFIGURE", "LOAD", "MOVE", "STORE"):
            before_axes = self._device_axes.get(operation.aod_id, ((), (), (), ()))
            if kind == "CONFIGURE":
                self._device_axes[operation.aod_id] = (*self._parse_axes(operation.metadata["target_axes"]), (), ())
            else:
                self._update_axes(operation.aod_id, operation.metadata.get("target_axes"), moving=kind == "MOVE")
            axes_delta = (operation.aod_id, before_axes, self._device_axes[operation.aod_id])
        for key in operation.gate_ids:
            self._completed.add(key)
            self._completed_order.append(key)
            self._ready.remove(key)
            self._fragment_remaining[self._gate_fragment[key]] -= 1
            for successor in self._successors.get(key, ()):
                self._remaining_dependencies[successor] -= 1
                if self._remaining_dependencies[successor] == 0:
                    self._ready.add(successor)
        for report, bit in zip(reports, bits):
            self._measurement_results[report] = bit
            self._measurement_times[report] = end
            self._report_order.append(report)
        if reports:
            gates_by_atom = {self._gate_specs[key].atoms[0]: key for key in operation.gate_ids}
            for atom, report in zip(operation.atoms, reports):
                self._report_bindings[report] = {"gate_id": gates_by_atom[atom], "operation_id": operation.id, "atom": atom}
        if reports:
            self._report_source._cursor += len(reports)
        block_id = self._active_block.id
        self._operation_cursor += 1
        self._block_completed.append(operation.id)
        self._block_completed_set.add(operation.id)
        if not scheduled:
            self._running = None
            self._serial_context = None
        self._commit("OPERATION_COMPLETED", block_id=block_id, operation_id=operation.id, kind=operation.kind,
                     start_us=start, end_us=end, changed_atoms=tuple(changed), gate_ids=operation.gate_ids,
                     reports=tuple(zip(reports, bits)), report_source_cursor_before=cursor_before,
                     report_source_cursor_after=self._report_source.cursor if reports else None, axes_delta=axes_delta,
                     resources=context["resources"] if scheduled else self._resources_for(operation),
                     motion_profile=operation.motion_profile, trajectory_profile="cubic" if operation.motion_profile == "row_column" else "linear")

    @staticmethod
    def _parse_axes(axes: Mapping[str, Sequence[float]]) -> tuple[tuple[float, ...], tuple[float, ...]]:
        if not isinstance(axes, Mapping) or "rows" not in axes or not ("columns" in axes or "cols" in axes):
            raise KernelError("AXIS_IDENTITY", "axes require rows and columns")
        rows = tuple(float(value) for value in axes["rows"])
        columns = tuple(float(value) for value in axes.get("columns", axes.get("cols")))
        if any(not isfinite(value) for value in rows + columns) or len(set(rows)) != len(rows) or len(set(columns)) != len(columns):
            raise KernelError("AXIS_IDENTITY", "axes must contain unique finite coordinates")
        return rows, columns

    def _update_axes(self, device: str, target: Mapping[str, Sequence[float]] | None = None, *, moving: bool = False) -> None:
        loaded = [location for location in self._locations if location[0] == device]
        active_rows = tuple(sorted({location[2] for location in loaded}))
        active_columns = tuple(sorted({location[1] for location in loaded}))
        previous = self._device_axes.get(device, ((), (), (), ()))
        if target is not None:
            rows, columns = self._parse_axes(target)
        elif moving and loaded:
            rows, columns = active_rows, active_columns
        else:
            rows = tuple(sorted(set(previous[0]) | set(active_rows)))
            columns = tuple(sorted(set(previous[1]) | set(active_columns)))
        self._device_axes[device] = (rows, columns, active_rows, active_columns)

    def _commit(self, event: str, **delta: Any) -> None:
        self._version += 1
        record = {"event": event, "time_us": self._time_us, "version": self._version, **delta}
        self._state_digest = _digest((self._state_digest, record))
        self._observation_cache = None
        if self._recording or self._journal_sink is not None:
            frozen = freeze(record)
            if self._recording:
                self._journal.append(frozen)
            if self._journal_sink is not None:
                try:
                    self._in_journal_sink = True
                    self._journal_sink(frozen)
                except Exception as error:
                    # Observers cannot roll back or change a committed result.
                    self._sink_errors.append(f"{type(error).__name__}: {error}")
                finally:
                    self._in_journal_sink = False

    @staticmethod
    def _gate_payload(gate: GateSpec) -> dict[str, Any]:
        return {"id": gate.id, "kind": gate.kind, "atoms": list(gate.atoms), "depends_on": list(gate.depends_on)}

    @staticmethod
    def _operation_payload(operation: Operation) -> dict[str, Any]:
        return {"id": operation.id, "kind": operation.kind, "atoms": list(operation.atoms),
                "duration_us": operation.duration_us, "positions": thaw(operation.positions),
                "gate_ids": list(operation.gate_ids), "report_ids": list(operation.report_ids),
                "aod_id": operation.aod_id, "metadata": thaw(operation.metadata), "start_us": operation.start_us,
                "depends_on": list(operation.depends_on), "resources": list(operation.resources), "motion_profile": operation.motion_profile,
                "end_us": operation.end_us}

    @classmethod
    def _block_payload(cls, block: Block) -> dict[str, Any]:
        return {"id": block.id, "operations": [cls._operation_payload(operation) for operation in block.operations],
                "expected_version": block.expected_version, "starting_state_hash": block.starting_state_hash,
                "native_provenance": thaw(block.native_provenance), "execution_mode": block.execution_mode}

    @staticmethod
    def _context_payload(context: Mapping[str, Any]) -> dict[str, Any]:
        return {key: thaw(value) for key, value in context.items() if key != "operation"}

    def _restore_context(self, operation: Operation, start: float, end: float, resources: tuple[str, ...],
                         saved: Mapping[str, Any] | None) -> dict[str, Any]:
        computed = self._operation_context(operation, start, end, resources)
        if saved is not None:
            if operation.aod_id not in resources:
                # A static SLM pulse/readout does not own the default AOD.
                # Its recorded start axes are historical observer metadata;
                # an independent legal LOAD/MOVE can since have changed them.
                # Preserve those exact values, rather than binding them to an
                # unrelated current carrier. The snapshot digest protects them.
                for key in ("source_axes", "target_axes"):
                    value = saved[key]
                    if len(value) != 4 or any(not isfinite(coordinate) for axis in value for coordinate in axis):
                        raise KernelError("CHECKPOINT_EVENT", "invalid historical start-axis metadata")
                    computed[key] = tuple(tuple(axis) for axis in value)
            if self._context_payload(computed) != saved:
                raise KernelError("CHECKPOINT_EVENT", "trajectory/resource start bindings disagree with state")
        return computed

    def checkpoint(self, *, include_journal: bool = False) -> dict[str, Any]:
        payload = {
            "schema": "neutral_atom_kernel", "version": self.CHECKPOINT_VERSION,
            "time_us": self._time_us, "state_version": self._version, "state_hash": self._state_digest,
            "atoms": [{"id": atom, "holder": self._locations[index][0], "position": list(self._locations[index][1:])}
                      for index, atom in enumerate(self._atom_ids)],
            "gates": [self._gate_payload(gate) for gate in self._gate_specs.values()],
            "completed_gate_ids": list(self._completed_order),
            "fragments": [{"id": id, "gate_ids": list(gates), "requires_report_ids": list(reports)}
                          for id, (gates, reports) in self._fragments.items()],
            "measurement_results": dict(self._measurement_results),
            "measurement_completion_times_us": dict(self._measurement_times),
            "report_commit_order": list(self._report_order),
            "report_bindings": {report: dict(binding) for report, binding in self._report_bindings.items()},
            "report_source": self._report_source.checkpoint() if self._report_source else None,
            "active_block": self._block_payload(self._active_block) if self._active_block else None,
            "operation_cursor": self._operation_cursor, "running": list(self._running) if self._running else None,
            "block_start_us": self._block_start_us, "block_completed_operation_ids": list(self._block_completed),
            "serial_context": self._context_payload(self._serial_context) if self._serial_context else None,
            "inflight": [self._context_payload(context) for context in self._inflight.values()],
            "scheduled_events": thaw(tuple(sorted(self._scheduled_events))),
            "scheduled_resources": {id: list(resources) for id, resources in self._scheduled_resources.items()},
            "submitted_block_ids": sorted(self._submitted_block_ids), "recording": self._recording,
            "aod_axes": {device: dict(zip(("rows", "columns", "active_rows", "active_columns"), map(list, axes)))
                         for device, axes in self._device_axes.items()},
        }
        if include_journal:
            payload["journal"] = thaw(tuple(self._journal))
        # Snapshot integrity is computed outside the per-event execution path.
        # It binds the whole serialized state, including the incremental history
        # digest, report declaration/cursor and any included delta journal.
        payload["checkpoint_digest"] = _digest(payload)
        return payload

    def checkpoint_json(self, *, include_journal: bool = False) -> str:
        return json.dumps(self.checkpoint(include_journal=include_journal), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def restore(cls, payload: Mapping[str, Any] | str, *, recording: bool | None = None,
                journal_sink: Callable[[Mapping[str, Any]], Any] | None = None) -> KernelExecutor:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload.get("schema") != "neutral_atom_kernel" or payload.get("version") not in (1, cls.CHECKPOINT_VERSION):
            raise KernelError("CHECKPOINT_VERSION", "unsupported kernel checkpoint")
        saved_digest = payload.get("checkpoint_digest")
        if not isinstance(saved_digest, str) or saved_digest != _digest({key: value for key, value in payload.items() if key != "checkpoint_digest"}):
            raise KernelError("CHECKPOINT_INTEGRITY", "kernel checkpoint content digest does not match")
        atoms = payload["atoms"]
        if len({atom["id"] for atom in atoms}) != len(atoms):
            raise KernelError("CHECKPOINT_IDENTITY", "checkpoint contains duplicate atoms")
        source = DeclaredReportSource.restore(payload["report_source"]) if payload["report_source"] is not None else None
        result = cls({atom["id"]: tuple(atom["position"]) for atom in atoms},
                     initial_holders={atom["id"]: atom["holder"] for atom in atoms}, report_source=source,
                     initial_aod_axes=payload.get("aod_axes"),
                     recording=payload["recording"] if recording is None else recording, journal_sink=journal_sink)
        gate_specs = {gate["id"]: GateSpec(**gate) for gate in payload["gates"]}
        if len(gate_specs) != len(payload["gates"]):
            raise KernelError("CHECKPOINT_IDENTITY", "checkpoint contains duplicate gates")
        # Declaration rebuilds the dependency indexes once, outside execution.
        result._declare_fragment("__restore__", tuple(gate_specs.values()), ())
        result._fragments.clear()
        result._fragment_remaining.clear()
        result._gate_fragment.clear()
        for fragment in payload["fragments"]:
            id, keys = fragment["id"], tuple(fragment["gate_ids"])
            if id in result._fragments or any(key not in gate_specs or key in result._gate_fragment for key in keys):
                raise KernelError("CHECKPOINT_IDENTITY", "invalid checkpoint fragment ownership")
            result._fragments[id] = (keys, tuple(fragment["requires_report_ids"]))
            result._fragment_remaining[id] = len(keys)
            result._gate_fragment.update({key: id for key in keys})
        if set(result._gate_fragment) != set(gate_specs):
            raise KernelError("CHECKPOINT_IDENTITY", "checkpoint gates lack fragment ownership")
        for key in payload["completed_gate_ids"]:
            if key not in result._ready or key in result._completed:
                raise KernelError("CHECKPOINT_DEPENDENCY", "checkpoint effects are not a valid causal prefix")
            result._ready.remove(key)
            result._completed.add(key)
            result._completed_order.append(key)
            result._fragment_remaining[result._gate_fragment[key]] -= 1
            for successor in result._successors.get(key, ()):
                result._remaining_dependencies[successor] -= 1
                if result._remaining_dependencies[successor] == 0:
                    result._ready.add(successor)
        report_order = payload["report_commit_order"]
        if len(set(report_order)) != len(report_order) or set(report_order) != set(payload["measurement_results"]):
            raise KernelError("CHECKPOINT_REPORT", "checkpoint report order does not match committed reports")
        for report in report_order:
            bit = payload["measurement_results"][report]
            DeclaredReportSource._check_bit(bit)
            result._measurement_results[report] = bit
        result._report_order = list(report_order)
        result._measurement_times = dict(payload["measurement_completion_times_us"])
        if set(result._measurement_times) != set(result._measurement_results):
            raise KernelError("CHECKPOINT_REPORT", "checkpoint report times do not match reports")
        if result._measurement_results and result._report_source is None:
            raise KernelError("CHECKPOINT_REPORT", "committed reports lack a declared source")
        if result._report_source is not None and result._report_source.cursor != len(result._measurement_results):
            raise KernelError("CHECKPOINT_REPORT", "report source cursor disagrees with committed reports")
        if result._report_source is not None:
            replay_source = DeclaredReportSource.restore(result._report_source.checkpoint())
            replay_source._cursor = 0
            try:
                replay_bits = replay_source._preview(tuple(report_order))
            except KernelError as error:
                raise KernelError("CHECKPOINT_REPORT", "committed reports cannot be reproduced from the declared source") from error
            if replay_bits != tuple(result._measurement_results[report] for report in report_order):
                raise KernelError("CHECKPOINT_REPORT", "committed report bits disagree with the declared source")
        bindings = payload["report_bindings"]
        if set(bindings) != set(result._measurement_results):
            raise KernelError("CHECKPOINT_REPORT", "checkpoint report bindings do not match reports")
        bound_gates = set()
        for report in report_order:
            binding = bindings[report]
            key = binding.get("gate_id")
            spec = gate_specs.get(key)
            if (key not in result._completed or key in bound_gates or spec.kind != "MEASURE"
                    or spec.atoms != (binding.get("atom"),) or not isinstance(binding.get("operation_id"), str)
                    or not binding["operation_id"]):
                raise KernelError("CHECKPOINT_REPORT", "report does not bind a unique completed measurement effect")
            bound_gates.add(key)
            result._report_bindings[report] = dict(binding)
        if bound_gates != {key for key in result._completed if gate_specs[key].kind == "MEASURE"}:
            raise KernelError("CHECKPOINT_REPORT", "completed measurements lack committed reports")
        result._time_us = float(payload["time_us"])
        result._version = payload["state_version"]
        if not isfinite(result._time_us) or result._time_us < 0 or not isinstance(result._version, int) or result._version < 0:
            raise KernelError("CHECKPOINT_TIME", "invalid checkpoint time or state version")
        if any(not isfinite(time) or not 0 <= time <= result._time_us for time in result._measurement_times.values()):
            raise KernelError("CHECKPOINT_REPORT", "invalid checkpoint report completion time")
        result._state_digest = payload["state_hash"]
        for device, axes in payload.get("aod_axes", {}).items():
            if tuple(axes.get("active_rows", ())) != result._device_axes[device][2] or tuple(axes.get("active_columns", ())) != result._device_axes[device][3]:
                raise KernelError("CHECKPOINT_AXES", "checkpoint active axes disagree with atom carriers")
        if not isinstance(result._state_digest, str) or len(result._state_digest) != 64:
            raise KernelError("CHECKPOINT_HASH", "invalid checkpoint state hash")
        result._submitted_block_ids = set(payload["submitted_block_ids"])
        result._block_start_us = float(payload.get("block_start_us", result._time_us))
        if not isfinite(result._block_start_us) or not 0 <= result._block_start_us <= result._time_us:
            raise KernelError("CHECKPOINT_EVENT", "invalid block epoch")
        result._block_completed = list(payload.get("block_completed_operation_ids", ()))
        result._block_completed_set = set(result._block_completed)
        if len(result._block_completed_set) != len(result._block_completed):
            raise KernelError("CHECKPOINT_EVENT", "checkpoint repeats completed operations")
        result._scheduled_resources = {id: tuple(resources) for id, resources in payload.get("scheduled_resources", {}).items()}
        result._operation_cursor = payload["operation_cursor"]
        if isinstance(result._operation_cursor, bool) or not isinstance(result._operation_cursor, int) or result._operation_cursor < 0:
            raise KernelError("CHECKPOINT_EVENT", "invalid operation cursor")
        active = payload["active_block"]
        if active is not None:
            result._active_block = Block(**{**active, "operations": tuple(Operation(**operation) for operation in active["operations"])})
            result._operation_by_id = {operation.id: operation for operation in result._active_block.operations}
            result._operation_ordinals = {operation.id: index for index, operation in enumerate(result._active_block.operations)}
            for operation in result._active_block.operations:
                result._check_operation_shape(operation)
            if not isinstance(result._operation_cursor, int) or not 0 <= result._operation_cursor <= len(result._active_block.operations):
                raise KernelError("CHECKPOINT_EVENT", "invalid pending operation cursor")
            if result._block_completed_set-set(result._operation_by_id):
                raise KernelError("CHECKPOINT_EVENT", "unknown completed block operations")
            running = payload["running"]
            if result._active_block.execution_mode == "scheduled":
                if running is not None or payload.get("serial_context") is not None:
                    raise KernelError("CHECKPOINT_EVENT", "scheduled block has a serial running operation")
                result._restore_schedule(payload)
            elif running is not None:
                if result._operation_cursor == len(result._active_block.operations):
                    raise KernelError("CHECKPOINT_EVENT", "completed serial block has an inflight event")
                start, end = map(float, running)
                operation = result._active_block.operations[result._operation_cursor]
                if not 0 <= start <= result._time_us <= end or end != start + operation.duration_us or not isfinite(end):
                    raise KernelError("CHECKPOINT_EVENT", "invalid pending operation interval")
                result._validate_operation(operation)
                result._running = (start, end)
                computed = result._restore_context(operation, start, end, result._resources_for(operation), payload.get("serial_context"))
                result._serial_context = computed
            if result._active_block.execution_mode == "serial":
                expected = [operation.id for operation in result._active_block.operations[:result._operation_cursor]]
                if payload.get("version") == 1 and "block_completed_operation_ids" not in payload:
                    result._block_completed, result._block_completed_set = expected, set(expected)
                elif result._block_completed != expected:
                    raise KernelError("CHECKPOINT_EVENT", "serial completed operation prefix disagrees with cursor")
        elif payload["running"] is not None:
            raise KernelError("CHECKPOINT_EVENT", "pending event has no active block")
        elif payload.get("inflight") or payload.get("scheduled_events") or payload.get("serial_context"):
            raise KernelError("CHECKPOINT_EVENT", "checkpoint inflight operations have no active block")
        if result._recording:
            result._journal = [freeze(record) for record in payload.get("journal", ())]
        cls._verify_checkpoint_journal(payload.get("journal", ()), result)
        return result

    def _restore_schedule(self, payload: Mapping[str, Any]) -> None:
        block = self._active_block
        if self._operation_cursor != len(self._block_completed):
            raise KernelError("CHECKPOINT_EVENT", "scheduled completed operation count disagrees with cursor")
        if set(self._scheduled_resources) != set(self._operation_by_id):
            raise KernelError("CHECKPOINT_EVENT", "scheduled resource ledger does not cover all operations")
        owners, kinds = {}, set()
        for saved in payload.get("inflight", ()):
            id = saved["operation_id"]
            if id not in self._operation_by_id or id in self._inflight or id in self._block_completed_set:
                raise KernelError("CHECKPOINT_EVENT", "invalid or repeated inflight operation")
            operation = self._operation_by_id[id]
            start = self._block_start_us+operation.start_us
            end = self._block_start_us+self._relative_end(operation)
            if not start <= self._time_us <= end:
                raise KernelError("CHECKPOINT_EVENT", "inflight interval does not contain current time")
            self._validate_operation(operation)
            resources = self._resources_for(operation)
            if resources != self._scheduled_resources[id] or any(resource in owners for resource in resources):
                raise KernelError("CHECKPOINT_EVENT", "inflight resources are inconsistent or overlap")
            context = self._restore_context(operation, start, end, resources, saved)
            owners.update({resource: id for resource in resources})
            unitary = self._unitary_kind(operation)
            if unitary is not None:
                kinds.add(unitary)
            self._inflight[id] = context
        if len(kinds) > 1:
            raise KernelError("CHECKPOINT_EVENT", "inflight unitary gate kinds conflict")
        expected = []
        for id, operation in self._operation_by_id.items():
            ordinal = self._operation_ordinals[id]
            if id in self._inflight:
                expected.append((self._inflight[id]["end_us"], 0, ordinal, id, "complete"))
            elif id not in self._block_completed_set:
                expected.append((self._block_start_us+operation.start_us, 1, ordinal, id, "start"))
        events = [tuple(event) for event in payload.get("scheduled_events", ())]
        if sorted(events) != sorted(expected) or any(event[0] < self._time_us for event in events):
            raise KernelError("CHECKPOINT_EVENT", "scheduled event suffix differs from inflight/unfinished operations")
        self._scheduled_events = events
        heapq.heapify(self._scheduled_events)

    @staticmethod
    def _verify_checkpoint_journal(journal: Sequence[Mapping[str, Any]], result: KernelExecutor) -> None:
        """Audit included reports/effects only during checkpoint restoration."""
        if not journal:
            return
        seen_reports, effects = set(), []
        previous_version, previous_time = journal[0]["version"]-1, 0.
        for record in journal:
            version, time = record["version"], record["time_us"]
            if version != previous_version+1 or not previous_time <= time <= result._time_us or version > result._version:
                raise KernelError("CHECKPOINT_JOURNAL", "checkpoint journal has invalid time/version ordering")
            previous_version, previous_time = version, time
            if record["event"] != "OPERATION_COMPLETED":
                if record.get("reports"):
                    raise KernelError("CHECKPOINT_JOURNAL", "reports occur before operation completion")
                continue
            effects.extend(record.get("gate_ids", ()))
            cursor_before = record.get("report_source_cursor_before")
            entries = record.get("reports", ())
            if entries and (not isinstance(cursor_before, int) or isinstance(cursor_before, bool)
                            or cursor_before < 0 or cursor_before+len(entries) > len(result._report_order)
                            or record.get("report_source_cursor_after") != cursor_before+len(entries)):
                raise KernelError("CHECKPOINT_JOURNAL", "measurement journal cursor does not match report effects")
            for offset, (report, bit) in enumerate(entries):
                binding = result._report_bindings.get(report)
                if (report in seen_reports or binding is None or binding["operation_id"] != record["operation_id"]
                        or binding["gate_id"] not in record.get("gate_ids", ())
                        or bit != result._measurement_results[report] or time != result._measurement_times[report]
                        or result._report_order[cursor_before+offset] != report):
                    raise KernelError("CHECKPOINT_JOURNAL", "measurement completion journal disagrees with committed reports")
                seen_reports.add(report)
        if previous_version != result._version:
            raise KernelError("CHECKPOINT_JOURNAL", "checkpoint journal does not end at committed version")
        if any(key not in result._completed for key in effects) or len(set(effects)) != len(effects):
            raise KernelError("CHECKPOINT_JOURNAL", "journal contains unknown or duplicate completed effects")
        if journal[0]["version"] == 1 and (seen_reports != set(result._measurement_results) or effects != result._completed_order):
            raise KernelError("CHECKPOINT_JOURNAL", "complete journal does not cover committed reports/effects")
