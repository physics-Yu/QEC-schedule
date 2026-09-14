"""Immutable physical operations and plans; no simulator dependencies."""
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from .models import Position2D, MobileCellIndex, HolderRef, Atom
from .aod import AODConfiguration


class EndDisposition(str, Enum):
    EXPLICIT = 'explicit'
    RETURN_AND_OFFLOAD = 'return_and_offload'
    KEEP_LOADED = 'keep_loaded'


class OperationType(str, Enum):
    MEASUREMENT = 'measurement'
    RESET = 'reset'
    RAMAN_ROTATION = 'raman_rotation'
    TRAP_SWITCH = 'trap_switch'
    AOD_LOAD = 'aod_load'
    AOD_MOVE = 'aod_move'
    ENTANGLING_PULSE = 'entangling_pulse'
    AOD_OFFLOAD = 'aod_offload'
    AOD_PARK = 'aod_park'
    AOD_RECAPTURE = 'aod_recapture'


@dataclass(frozen=True)
class HardwareConfig:
    load_duration_us: float = 100.0
    offload_duration_us: float = 100.0
    speed_um_per_us: float = .5
    pulse_duration_us: float = .3
    interaction_distance_um: float = 2.0
    minimum_clearance_um: float = 1.0
    slm_clearance_um: float = 1.0
    alignment_tolerance_um: float = 1e-7
    escape_um: float = 2.5
    interaction_offset: Position2D = Position2D(-2,0)
    interaction_slot_id: str = 'slot_0'
    backend: str = 'rigid'
    minimum_axis_spacing_um: float = 1.01
    max_acceleration_um_per_us2: float = .01
    max_jerk_um_per_us3: float = .001
    mobile_pair_center: Position2D = Position2D(5,-25)
    selective_transfer_enabled: bool = False
    # Optional discrete parking policy; collision/support/light checks stay mandatory.
    ez_neighbor_guard_enabled: bool = True
    # Project default in microseconds, not an experimental calibration.
    switch_duration_us: float = 1.0
    # User-confirmed fixed 1 us single-qubit pulse, including I/RZ.
    # Retained in serialized hardware for audit, not an adjustable parameter.
    raman_duration_us: float = 1.0
    raman_zone_types: tuple[str, ...] = ('storage', 'entanglement')
    raman_minimum_separation_um: float = 5.0
    # Explicit ideal-QEC simulation timing assumptions, not device calibration.
    measurement_duration_us: float = 500.0
    reset_duration_us: float = 100.0

    def __post_init__(self):
        if type(self.raman_duration_us) not in (int, float) or self.raman_duration_us != 1.0:
            raise ValueError('Single-qubit Raman duration is fixed at 1 us')
        object.__setattr__(self, 'raman_zone_types', tuple(self.raman_zone_types))
        if not self.raman_zone_types or len(set(self.raman_zone_types)) != len(self.raman_zone_types) or any(z not in {'storage', 'entanglement', 'measurement'} for z in self.raman_zone_types):
            raise ValueError('Invalid Raman addressing zones')
        if type(self.selective_transfer_enabled) is not bool:
            raise ValueError('selective_transfer_enabled must be boolean')
        if type(self.ez_neighbor_guard_enabled) is not bool:
            raise ValueError('ez_neighbor_guard_enabled must be boolean')
        for name in ('measurement_duration_us','reset_duration_us','raman_minimum_separation_um','raman_duration_us','switch_duration_us','load_duration_us','offload_duration_us','speed_um_per_us','pulse_duration_us',
                     'interaction_distance_um','minimum_clearance_um','slm_clearance_um','alignment_tolerance_um','escape_um',
                     'minimum_axis_spacing_um','max_acceleration_um_per_us2','max_jerk_um_per_us3'):
            value=getattr(self,name)
            if not isfinite(value) or value<=0:raise ValueError(f'{name} must be finite and positive')
        if self.backend not in {'rigid', 'row_column'}:
            raise ValueError('Unknown AOD backend; choose rigid or row_column')


@dataclass(frozen=True)
class ExecuteGateBatchIntent:
    gate_ids: frozenset[str]
    end_disposition: EndDisposition = EndDisposition.RETURN_AND_OFFLOAD

    def __post_init__(self):
        object.__setattr__(self,'gate_ids',frozenset(self.gate_ids))


@dataclass(frozen=True)
class CaptureBinding:
    atom_id: str
    cell: MobileCellIndex
    static_trap_id: str


@dataclass(frozen=True)
class TrapState:
    """Enabled light supports; capacity and geometry live elsewhere."""
    rows: tuple[bool, ...]
    columns: tuple[bool, ...]
    slm: tuple[tuple[str, bool], ...]

    def __post_init__(self):
        object.__setattr__(self, 'rows', tuple(self.rows))
        object.__setattr__(self, 'columns', tuple(self.columns))
        object.__setattr__(self, 'slm', tuple(tuple(p) for p in self.slm))
        if (any(type(v) is not bool for v in (*self.rows, *self.columns))
                or any(not isinstance(k, str) or type(v) is not bool for k, v in self.slm)
                or len(dict(self.slm)) != len(self.slm) or self.slm != tuple(sorted(self.slm))):
            raise ValueError('Trap state requires canonical boolean masks')


@dataclass(frozen=True)
class TransferRuntime:
    kind: OperationType
    bindings: tuple[CaptureBinding, ...]
    source_traps: TrapState
    target_traps: TrapState
    stage: str = 'target_supported'

    def __post_init__(self):
        object.__setattr__(self, 'bindings', tuple(self.bindings))


@dataclass(frozen=True)
class TaskTarget:
    """Conjunction of explicit terminal holders, axes and light supports.

    Unspecified fields are unconstrained; backend legality always applies.
    """
    holders: tuple[tuple[str, HolderRef], ...] = ()
    aod_configuration: AODConfiguration | None = None
    traps: TrapState | None = None

    def __post_init__(self):
        object.__setattr__(self, 'holders', tuple(sorted(tuple(p) for p in self.holders)))
        if len(dict(self.holders)) != len(self.holders):
            raise ValueError('Duplicate target atom')


@dataclass(frozen=True)
class TaskIntent:
    """An independent task; effect_gate_id or program gate_effects authorize pulses."""
    task_id: str
    target: TaskTarget
    atom_ids: frozenset[str] = frozenset()
    effect_gate_id: str | None = None
    phase: str = 'transport'
    related_gate_id: str | None = None
    allowed_atom_ids: frozenset[str] | None = None
    allowed_site_ids: frozenset[str] | None = None
    max_duration_us: float | None = None
    gate_effects: frozenset[str] = frozenset()

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError('Task needs a nonempty stable ID')
        if self.phase not in {'transport', 'prepare', 'effect', 'cleanup', 'program'}:
            raise ValueError('Unknown task phase')
        if (self.phase == 'effect') != (self.effect_gate_id is not None):
            raise ValueError('Only an effect task may authorize a gate')
        object.__setattr__(self, 'gate_effects', frozenset(self.gate_effects))
        if self.gate_effects and self.phase != 'program':
            raise ValueError('Multiple effects require a scheduled program')
        for name in ('effect_gate_id', 'related_gate_id'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError('Invalid gate reference')
        for name in ('atom_ids', 'allowed_atom_ids', 'allowed_site_ids'):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, frozenset(value))
        if self.max_duration_us is not None and (type(self.max_duration_us) not in (int, float)
                or not isfinite(self.max_duration_us) or self.max_duration_us <= 0):
            raise ValueError('Task duration budget must be finite and positive')

    @property
    def gate_ids(self):
        return frozenset((self.effect_gate_id,)) if self.effect_gate_id else self.gate_effects

    @property
    def end_disposition(self):
        return EndDisposition.EXPLICIT


@dataclass(frozen=True)
class Operation:
    id: str
    operation_type: OperationType
    label: str
    duration_us: float
    target_pose: Position2D | None = None
    target_configuration: AODConfiguration | None = None
    transfer_phase: str | None = None
    transfer_bindings: tuple[CaptureBinding, ...] = ()
    switch_state: TrapState | None = None
    gate_id: str | None = None
    depends_on: tuple[str, ...] = ()
    task_phase: str | None = None
    gate_ids: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self,'transfer_bindings',tuple(self.transfer_bindings))
        object.__setattr__(self,'depends_on',tuple(self.depends_on))
        object.__setattr__(self,'gate_ids',tuple(self.gate_ids))
        if self.gate_ids and (self.operation_type not in {OperationType.ENTANGLING_PULSE,OperationType.RAMAN_ROTATION,OperationType.MEASUREMENT,OperationType.RESET} or self.gate_id is not None
                or len(set(self.gate_ids)) != len(self.gate_ids) or any(not isinstance(g,str) or not g for g in self.gate_ids)):
            raise ValueError('Batch effects require unique CZ/Raman/readout/reset gate_ids and no singular gate_id')

    @property
    def effect_gate_ids(self):
        return self.gate_ids or ((self.gate_id,) if self.gate_id else ())


@dataclass(frozen=True)
class OperationInterval:
    """Audited relative timing/demand, not permission for concurrent execution."""
    operation_id: str
    start_us: float
    end_us: float
    resources: tuple[str, ...]
    atom_ids: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, 'resources', tuple(self.resources))
        object.__setattr__(self, 'atom_ids', tuple(self.atom_ids))


@dataclass(frozen=True)
class CompiledPlan:
    id: str
    state_version: int
    state_fingerprint: str
    intent: ExecuteGateBatchIntent | TaskIntent
    bindings: tuple[CaptureBinding,...]
    requested_atom_ids: frozenset[str]
    incidental_atom_ids: frozenset[str]
    operations: tuple[Operation,...]
    resources: tuple[str,...]
    estimated_duration_us: float
    estimated_distance_um: float
    predicted_placement: tuple[tuple[str,HolderRef],...]
    initial_aod_configuration: AODConfiguration | None = None
    planner_id: str = 'external'
    # Explicit origin distinguishes general operation programs from legacy cycle contracts.
    initial_placement: tuple[tuple[str,HolderRef],...] | None = None
    initial_traps: TrapState | None = None
    predicted_traps: TrapState | None = None
    operation_intervals: tuple[OperationInterval, ...] = ()
    initial_dag: str | None = None
    execution_mode: str = 'serial'
    initial_time_us: float | None = None
    initial_metrics: 'PhysicalMetrics | None' = None
    initial_atoms: tuple[tuple[str,Atom], ...] | None = None
    initial_quantum_state: str | None = None
    initial_measurement_results: tuple[tuple[str,int], ...] = ()
    initial_rng_state: tuple | None = None

    @property
    def captured_atom_ids(self):
        return frozenset(b.atom_id for b in self.bindings)


@dataclass(frozen=True)
class PlanRuntime:
    plan: CompiledPlan
    started_us: float
    operation_index: int = 0
    operation_started_us: float | None = None
    completed_operation_ids: tuple[str, ...] = ()
    running_operations: tuple[tuple[str, float], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'completed_operation_ids', tuple(self.completed_operation_ids))
        object.__setattr__(self, 'running_operations', tuple(tuple(p) for p in self.running_operations))


@dataclass(frozen=True)
class ResourceReservation:
    resource_id: str
    plan_id: str


@dataclass(frozen=True)
class PhysicalMetrics:
    raman_busy_time_us: float = 0.0
    episode_start_us: float | None = None
    completed_plan_count: int = 0
    circuit_makespan_us: float = 0.0
    cycle_makespan_us: float = 0.0
    total_atom_distance_um: float = 0.0
    total_aod_distance_um: float = 0.0
    aod_load_count: int = 0
    aod_offload_count: int = 0
    captured_atom_count_total: int = 0
    incidental_atom_transport_total: int = 0
    aod_busy_time_us: float = 0.0
    laser_busy_time_us: float = 0.0
    measurement_busy_time_us: float = 0.0
    reset_busy_time_us: float = 0.0
