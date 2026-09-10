"""Immutable physical operations and plans; no simulator dependencies."""
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from .models import Position2D, MobileCellIndex, HolderRef
from .aod import AODConfiguration


class EndDisposition(str, Enum):
    RETURN_AND_OFFLOAD = 'return_and_offload'
    KEEP_LOADED = 'keep_loaded'


class OperationType(str, Enum):
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

    def __post_init__(self):
        if type(self.selective_transfer_enabled) is not bool:
            raise ValueError('selective_transfer_enabled must be boolean')
        for name in ('load_duration_us','offload_duration_us','speed_um_per_us','pulse_duration_us',
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
class Operation:
    id: str
    operation_type: OperationType
    label: str
    duration_us: float
    target_pose: Position2D | None = None
    target_configuration: AODConfiguration | None = None
    transfer_phase: str | None = None
    transfer_bindings: tuple[CaptureBinding, ...] = ()

    def __post_init__(self):
        object.__setattr__(self,'transfer_bindings',tuple(self.transfer_bindings))


@dataclass(frozen=True)
class CompiledPlan:
    id: str
    state_version: int
    state_fingerprint: str
    intent: ExecuteGateBatchIntent
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

    @property
    def captured_atom_ids(self):
        return frozenset(b.atom_id for b in self.bindings)


@dataclass(frozen=True)
class PlanRuntime:
    plan: CompiledPlan
    started_us: float
    operation_index: int = 0
    operation_started_us: float | None = None


@dataclass(frozen=True)
class ResourceReservation:
    resource_id: str
    plan_id: str


@dataclass(frozen=True)
class PhysicalMetrics:
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
