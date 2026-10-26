"""Optional reference checks for a compiled or decoded result document."""

from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any, NotRequired, TypedDict

from .atom_ir import (
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
from .compiler import CompilationResult
from .contracts import validate_transport_goals
from .device import Device
from .metrics import collect_metrics
from .motion import ConstraintResult, check_load, check_move, check_store
from .physical_ir import PhysicalDAG
from .replay import apply_step
from .semantic_actions import check_action_semantics
from .state import (
    COORDINATE_TOLERANCE,
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)
from .validation_durations import check_duration, metrics_equal
from .validation_timing import TIME_TOLERANCE_US as TIME_TOLERANCE_US
from .validation_timing import check_timing


class ValidationFailure(TypedDict):
    """First violated rule, with null indices for whole-result checks."""

    step: int | None
    action: int | None
    kind: str
    rule: str
    message: str


class ValidationReport(TypedDict):
    """JSON-ready outcome of the requested reference checks."""

    ok: bool
    failure: ValidationFailure | None
    failures: NotRequired[list[ValidationFailure]]
    failure_count: NotRequired[int]
    checks: NotRequired[list[str]]
    semantic: NotRequired[str]
    device_override: NotRequired[str]


_ACTION_KINDS: dict[type[AtomAction], str] = {
    Load: "LOAD",
    Move: "MOVE",
    Store: "STORE",
    CZPulse: "CZ_PULSE",
    Rotation: "ROT",
    LocalU: "U",
    GlobalRY: "GLOBAL_RY",
    Reset: "R",
    Measure: "M",
    Wait: "WAIT",
}


def validate_result(
    result: CompilationResult,
    *,
    entry_state: AtomLayout,
    device: Device,
    dag: PhysicalDAG | None = None,
    detailed: bool = False,
    stored_metrics: Mapping[str, Any] | None = None,
) -> ValidationReport:
    """Check saved actions independently of compiler construction.

    Args:
        result: Decoded actions, records, and expected exit layout.
        entry_state: Layout before the first step.
        device: Embedded Device snapshot, or an explicitly chosen replacement.
        dag: Native circuit for pulse, addressing, timing, and branch checks.
        detailed: Include all-check reporting for a legacy result without a DAG.

    Returns:
        With a DAG, a semantic report containing at most 20 failure details,
        the full failure count, and the executed check groups. Without a DAG,
        detailed reports mark semantics unavailable; the default retains the
        legacy compact structural report. Checks use common step-entry layouts.
        If replay cannot produce a state, independent timing and coverage checks
        continue; subsequent spatial checks cannot use an invented layout.
    """
    if result.transport_goals and dag is None:
        return _failure(
            None,
            None,
            "TRANSPORT_GOAL",
            "missing_dag",
            "Transport goals require their native DAG for validation.",
        )
    if dag is None and not detailed and stored_metrics is None:
        return _validate_legacy(result, entry_state=entry_state, device=device)
    return _validate_detailed(result, entry_state, device, dag, stored_metrics)


def _validate_legacy(
    result: CompilationResult, *, entry_state: AtomLayout, device: Device
) -> ValidationReport:
    """Check transport, replay, and source coverage without compiling again.

    Args:
        result: Compilation output, including its recorded exit layout.
        entry_state: Atom layout before the program's first step.
        device: Device geometry used to interpret the actions.

    Returns:
        A JSON-ready report with ``ok`` and ``failure``. Action indices are
        zero-based. Entry, missing-coverage, and exit-state failures use null
        indices. The first action failure follows program tuple order; each
        action is checked against its unchanged step-entry layout. Metadata
        operations do not require an action source reference.

    This reference tool is independent of the compiler's construction path.
    It uses endpoint transport rules and retained-readout replay; it does not
    simulate quantum states, trajectories, or independently validate pulses.
    """
    try:
        validate_layout(device, entry_state)
    except ValueError as error:
        return _failure(None, None, "ENTRY", "invalid_entry", str(error))

    layout = entry_state
    covered: set[int] = set()
    skipped = {
        operation.operation_id
        for operation in result.operations
        if operation.status == "skipped"
    }
    for step_index, step in enumerate(result.program.steps):
        for action_index, action in enumerate(step.actions):
            checked = _check_action(device, layout, action)
            if checked.rule is not None:
                return _failure(
                    step_index,
                    action_index,
                    _ACTION_KINDS[type(action)],
                    checked.rule,
                    checked.message,
                )
            for source in action.source_ids:
                if source in skipped:
                    return _failure(
                        step_index,
                        action_index,
                        _ACTION_KINDS[type(action)],
                        "skipped_source",
                        f"Skipped operation {source} appears in action source_ids.",
                    )
                covered.add(source)
        layout = apply_step(layout, step, device)

    for operation in result.operations:
        if operation.status == "emitted" and operation.operation_id not in covered:
            return _failure(
                None,
                None,
                "COVERAGE",
                "missing_source",
                f"Emitted operation {operation.operation_id} has no action "
                "source reference.",
            )
    if layout != result.exit_state:
        return _failure(
            None,
            None,
            "RESULT",
            "exit_state_mismatch",
            "Replayed layout does not equal the recorded exit state.",
        )
    return {"ok": True, "failure": None}


class _Failures:
    def __init__(self) -> None:
        self.items: list[ValidationFailure] = []
        self.count = 0

    def add(self, failure: ValidationFailure) -> None:
        self.count += 1
        if len(self.items) < 20:
            self.items.append(failure)

    def record(
        self,
        step: int | None,
        action: int | None,
        kind: str,
        rule: str,
        message: str,
    ) -> None:
        self.add(
            {
                "step": step,
                "action": action,
                "kind": kind,
                "rule": rule,
                "message": message,
            }
        )


class _TransportChecks:
    """Inspect mechanical provenance during the existing independent replay."""

    def __init__(
        self,
        result: CompilationResult,
        entry: AtomLayout,
        device: Device,
        dag: PhysicalDAG | None,
        failures: _Failures,
    ) -> None:
        self.device, self.entry, self.failures = device, entry, failures
        self.expected: dict[int, dict[int, str]] = {}
        self.initial: dict[int, AtomLayout] = {}
        self.loaded: dict[int, set[int]] = defaultdict(set)
        self.moved: dict[int, set[int]] = defaultdict(set)
        self.stores: dict[int, set[tuple[int, str]]] = defaultdict(set)
        self.records = {record.operation_id: record for record in result.operations}
        self.atom_goals: dict[int, list[int]] = defaultdict(list)
        if dag is not None:
            try:
                validate_transport_goals(dag, device, result.transport_goals)
            except ValueError as error:
                self.fail("transport_goal_registry", str(error))
            else:
                for goal in result.transport_goals:
                    if any(
                        wire >= len(entry.qubit_to_atom) for wire, _site in goal.targets
                    ):
                        continue  # The entry addressing check records this mismatch.
                    self.expected[goal.operation_id] = {
                        entry.qubit_to_atom[wire]: site for wire, site in goal.targets
                    }
                    for atom in self.expected[goal.operation_id]:
                        self.atom_goals[atom].append(goal.operation_id)
                    if (
                        goal.operation_id not in self.records
                        or self.records[goal.operation_id].status != "emitted"
                    ):
                        self.fail(
                            "transport_goal_status",
                            f"Transport goal {goal.operation_id} must be emitted.",
                        )
        self.endings = deque(
            sorted(
                (record.end_us, identity)
                for identity, record in self.records.items()
                if identity in self.expected
            )
        )

    def fail(self, rule: str, message: str) -> None:
        self.failures.record(None, None, "TRANSPORT_GOAL", rule, message)

    def at_target(self, atom: AtomState, site: str) -> bool:
        target = self.device.site(site).position
        return (
            atom.holder == SLMHolder(site)
            and abs(atom.position.x - target.x) <= COORDINATE_TOLERANCE
            and abs(atom.position.y - target.y) <= COORDINATE_TOLERANCE
        )

    def action(
        self, action: AtomAction, start: float, layout: AtomLayout | None
    ) -> None:
        if not self.expected:
            return
        sources = set(action.source_ids) & self.expected.keys()
        if not isinstance(action, Load | Move | Store):
            if sources:
                self.fail(
                    "transport_goal_provenance",
                    "A relocation may reference only Load, Move and Store actions.",
                )
            return
        touched = {
            item[0]
            for item in (
                action.targets if isinstance(action, Move) else action.bindings
            )
        }
        for identity in sources:
            if not touched & self.expected[identity].keys():
                self.fail(
                    "transport_goal_provenance",
                    f"Transport source {identity} does not touch its bound atoms.",
                )
            if layout is not None:
                self.initial.setdefault(identity, layout)
            self.chain(identity, action, layout)
        for atom in touched:
            for identity in self.atom_goals.get(atom, ()):
                record = self.records.get(identity)
                if (
                    record is None
                    or not record.start_us - TIME_TOLERANCE_US
                    <= start
                    < record.end_us - TIME_TOLERANCE_US
                ):
                    continue
                if (
                    identity not in sources
                    or start + action.duration_us > record.end_us + TIME_TOLERANCE_US
                ):
                    self.fail(
                        "transport_goal_provenance",
                        f"Transport of goal {identity}'s atom {atom} lacks source "
                        "provenance or outlasts completion.",
                    )

    def chain(
        self, identity: int, action: Load | Move | Store, layout: AtomLayout | None
    ) -> None:
        """Record ordered, source-attributed chains without adopting an AOD prefix."""
        atoms = {atom.id: atom for atom in layout.atoms} if layout is not None else {}
        if isinstance(action, Load):
            for atom, _row, _column in action.bindings:
                if (
                    atom in self.expected[identity]
                    and atom in atoms
                    and isinstance(atoms[atom].holder, SLMHolder)
                ):
                    self.loaded[identity].add(atom)
                    self.moved[identity].discard(atom)
        elif isinstance(action, Move):
            for atom, target in action.targets:
                if (
                    atom in self.loaded[identity]
                    and atom in atoms
                    and (
                        abs(atoms[atom].position.x - target.x) > COORDINATE_TOLERANCE
                        or abs(atoms[atom].position.y - target.y) > COORDINATE_TOLERANCE
                    )
                ):
                    self.moved[identity].add(atom)
        else:
            for atom, site in action.bindings:
                if atom in self.loaded[identity] and atom in self.moved[identity]:
                    self.stores[identity].add((atom, site))
                self.loaded[identity].discard(atom)
                self.moved[identity].discard(atom)

    def step(
        self,
        start: float,
        step: AtomStep,
        before: AtomLayout | None,
        after: AtomLayout | None,
    ) -> None:
        end = start + step.duration_us
        while self.endings and self.endings[0][0] <= end + TIME_TOLERANCE_US:
            completed, identity = self.endings.popleft()
            endpoint = after
            if before is not None and completed < end - TIME_TOLERANCE_US:
                try:
                    endpoint = apply_step(
                        before,
                        AtomStep(
                            tuple(
                                action
                                for action in step.actions
                                if start + action.duration_us
                                <= completed + TIME_TOLERANCE_US
                            )
                        ),
                        self.device,
                    )
                except (KeyError, ValueError, NotImplementedError):
                    endpoint = None
            self.endpoint(identity, endpoint)

    def endpoint(self, identity: int, layout: AtomLayout | None) -> None:
        initial = self.initial.get(identity)
        if (
            initial is None
            or layout is None
            or layout.qubit_to_atom != self.entry.qubit_to_atom
        ):
            self.fail(
                "transport_goal_proof",
                f"Transport goal {identity} lacks replayed same-atom endpoint proof.",
            )
            return
        before, after = (
            {atom.id: atom for atom in state.atoms} for state in (initial, layout)
        )
        displaced = False
        for atom, site in self.expected[identity].items():
            if atom not in before or atom not in after:
                self.fail(
                    "transport_goal_proof",
                    f"Transport goal {identity} lost bound atom {atom}.",
                )
                continue
            if not isinstance(before[atom].holder, SLMHolder):
                self.fail(
                    "transport_goal_proof",
                    f"Transport goal {identity}'s atom {atom} must start in SLM; "
                    "an earlier unattributed AOD prefix is not a goal proof.",
                )
            changed = not self.at_target(before[atom], site)
            displaced |= changed
            if not self.at_target(after[atom], site):
                self.fail(
                    "transport_goal_endpoint",
                    f"Transport goal {identity}'s atom {atom} is not stored at "
                    f"{site!r} at completion.",
                )
            if changed and (atom, site) not in self.stores[identity]:
                self.fail(
                    "transport_goal_proof",
                    f"Transport goal {identity} has no attributed "
                    f"SLM Load/Move/target Store chain for atom {atom}.",
                )
        if not displaced:
            self.fail(
                "transport_goal_noop",
                f"Transport goal {identity} was already satisfied; "
                "omit the unsupported no-op.",
            )


def _validate_detailed(
    result: CompilationResult,
    entry: AtomLayout,
    device: Device,
    dag: PhysicalDAG | None,
    stored_metrics: Mapping[str, Any] | None = None,
) -> ValidationReport:
    failures = _Failures()
    transport = _TransportChecks(result, entry, device, dag, failures)
    layout: AtomLayout | None = entry
    try:
        validate_layout(device, entry)
    except ValueError as error:
        failures.record(None, None, "ENTRY", "invalid_entry", str(error))
        layout = None
    spatial_checks_ran = layout is not None
    if dag is not None and len(entry.qubit_to_atom) != dag.num_qubits:
        failures.record(
            None,
            None,
            "ENTRY",
            "addressing",
            "Entry state must bind every physical qubit to an atom.",
        )

    timed: dict[tuple[int | None, int | None], list[ValidationFailure]] = defaultdict(
        list
    )
    if dag is not None:
        for failure in check_timing(dag, result, device):
            timed[failure["step"], failure["action"]].append(failure)
    covered: set[int] = set()
    executed: set[int] = set()
    skipped = {
        item.operation_id for item in result.operations if item.status == "skipped"
    }

    for step_index, (start, step) in enumerate(result.program.timeline()):
        before = layout
        for action_index, action in enumerate(step.actions):
            kind = _ACTION_KINDS[type(action)]
            transport.action(action, start, layout)
            if layout is not None:
                checked = _check_action(device, layout, action)
                if checked.rule is not None:
                    failures.record(
                        step_index, action_index, kind, checked.rule, checked.message
                    )
                if dag is not None:
                    for checked in check_action_semantics(
                        dag, device, layout, action, step
                    ):
                        if checked.rule is not None:
                            failures.record(
                                step_index,
                                action_index,
                                kind,
                                checked.rule,
                                checked.message,
                            )
            if isinstance(
                action, CZPulse | Rotation | LocalU | GlobalRY | Reset | Measure
            ):
                for source in action.source_ids:
                    if source in executed:
                        failures.record(
                            step_index,
                            action_index,
                            kind,
                            "addressing",
                            f"Native operation {source} is executed more than once.",
                        )
                    executed.add(source)
            for failure in timed.pop((step_index, action_index), ()):
                failures.add(failure)
            for source in action.source_ids:
                if source in skipped:
                    failures.record(
                        step_index,
                        action_index,
                        kind,
                        "skipped_source",
                        f"Skipped operation {source} appears in action source_ids.",
                    )
                covered.add(source)
        if layout is not None:
            try:
                layout = apply_step(layout, step, device)
            except (KeyError, ValueError, NotImplementedError) as error:
                failures.record(step_index, None, "REPLAY", "replay_error", str(error))
                layout = None
        transport.step(start, step, before, layout)
        for failure in timed.pop((step_index, None), ()):
            failures.add(failure)

    for operation in result.operations:
        if operation.status != "emitted":
            continue
        if operation.operation_id not in covered:
            failures.record(
                None,
                None,
                "COVERAGE",
                "missing_source",
                f"Emitted operation {operation.operation_id} has no action "
                "source reference.",
            )
        elif (
            dag is not None
            and operation.operation_id not in executed
            and not (
                0 <= operation.operation_id < len(dag.nodes)
                and dag.nodes[operation.operation_id].name == "relocate"
            )
        ):
            failures.record(
                None,
                None,
                "COVERAGE",
                "addressing",
                f"Emitted operation {operation.operation_id} has no executable "
                "gate action.",
            )
    for remaining in timed.values():
        for failure in remaining:
            failures.add(failure)
    if layout is not None and layout != result.exit_state:
        failures.record(
            None,
            None,
            "RESULT",
            "exit_state_mismatch",
            "Replayed layout does not equal the recorded exit state.",
        )
    if stored_metrics is not None and not metrics_equal(
        stored_metrics, collect_metrics(result)
    ):
        failures.record(
            None,
            None,
            "RESULT",
            "metrics_mismatch",
            "Stored metrics differ from recomputed program metrics.",
        )
    checks = ["motion", "coverage"]
    if spatial_checks_ran:
        checks.append("replay")
    if dag is not None:
        if spatial_checks_ran:
            checks += ["pulse", "addressing"]
        checks.append("timing")
        if result.transport_goals:
            checks.append("transport_goals")
    return {
        "ok": failures.count == 0,
        "failure": failures.items[0] if failures.items else None,
        "failures": failures.items,
        "failure_count": failures.count,
        "checks": checks,
        "semantic": "checked" if dag is not None else "unavailable",
    }


def _check_action(
    device: Device, layout: AtomLayout, action: AtomAction
) -> ConstraintResult:
    duration = check_duration(device, layout, action)
    if not duration.ok:
        return duration
    if isinstance(action, Load):
        return check_load(
            device,
            layout,
            action.grid,
            {atom: (row, column) for atom, row, column in action.bindings},
        )
    if isinstance(action, Move):
        return check_move(device, layout, action.grid, dict(action.targets))
    if isinstance(action, Store):
        return check_store(device, layout, action.grid, dict(action.bindings))
    if isinstance(action, Measure) and not action.retain_atoms:
        return ConstraintResult(
            "unsupported_replay", "Replay currently supports retained readout only."
        )
    return ConstraintResult()


def _failure(
    step: int | None,
    action: int | None,
    kind: str,
    rule: str,
    message: str,
) -> ValidationReport:
    return {
        "ok": False,
        "failure": {
            "step": step,
            "action": action,
            "kind": kind,
            "rule": rule,
            "message": message,
        },
    }
