from dataclasses import dataclass, field
from types import MappingProxyType
import random
from collections.abc import Mapping
from math import isfinite
from neutral_atom_env.domain.models import Atom
from neutral_atom_env.domain.operations import HardwareConfig, PlanRuntime, ResourceReservation, PhysicalMetrics, TransferRuntime
from dataclasses import asdict
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.circuit import DynamicGateDAG
from neutral_atom_env.simulation.event_queue import EventQueue
from neutral_atom_env.replay.trace import Trace


@dataclass(frozen=True)
class SimulationState:
    world: WorldState
    placement: PlacementState
    atoms: Mapping[str, Atom]
    aod: AODRuntimeState
    dag: DynamicGateDAG
    seed: int = 0
    version: int = 0
    time_us: float = 0.0
    event_queue: EventQueue = field(default_factory=EventQueue)
    trace: Trace = field(default_factory=Trace)
    committed_events: int = 0
    rng_state: tuple | None = None
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    active_plan: PlanRuntime | None = None
    reservations: tuple[ResourceReservation, ...] = ()
    physical_metrics: PhysicalMetrics = field(default_factory=PhysicalMetrics)
    slm_enabled: Mapping[str, bool] | None = None
    transfer: TransferRuntime | None = None
    quantum_state: object | None = None
    measurement_results: Mapping[str,int] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "atoms", MappingProxyType(dict(self.atoms)))
        object.__setattr__(self,'measurement_results',MappingProxyType(dict(self.measurement_results)))
        if self.quantum_state is not None:
            from neutral_atom_env.quantum.stabilizer import StabilizerState
            if not isinstance(self.quantum_state,StabilizerState) or set(self.quantum_state.qubit_ids)!=set(self.atoms):
                raise ValidationError('INVALID_QUANTUM_STATE','Quantum state must cover exactly the physical atoms')
        if any(g not in self.dag.nodes or self.dag.nodes[g].gate.gate_type not in {'MEASURE','MZ'} or
               type(bit) is not int or bit not in (0,1) for g,bit in self.measurement_results.items()):
            raise ValidationError('INVALID_MEASUREMENT_RESULT','Results must map measurement gate IDs to integer bits')
        slm = {k: t.enabled for k, t in self.world.traps.items()} if self.slm_enabled is None else dict(self.slm_enabled)
        if set(slm) != set(self.world.traps) or any(type(v) is not bool for v in slm.values()):
            raise ValidationError('INVALID_SLM_MASK', 'SLM runtime mask must cover every candidate trap')
        object.__setattr__(self, 'slm_enabled', MappingProxyType(slm))
        object.__setattr__(self, 'reservations', tuple(self.reservations))
        if self.rng_state is None:
            object.__setattr__(self, 'rng_state', random.Random(self.seed).getstate())
        else:
            rng = random.Random()
            rng.setstate(self.rng_state)
        if (not isfinite(self.time_us) or self.time_us < 0 or self.version != self.committed_events or
            type(self.version) is not int or self.version < 0 or len(self.trace.records) != self.committed_events):
            raise ValidationError('INVALID_RUNTIME', 'Invalid time or event version')
        if any(k != a.id for k, a in self.atoms.items()):
            raise ValidationError('ATOM_ID_MISMATCH', 'Atom identity mismatch')
        if any(q not in self.atoms for n in self.dag.nodes.values() for q in n.gate.qubit_ids):
            raise ValidationError('UNKNOWN_QUBIT', 'Circuit references unknown physical qubit')
        self.placement.validate(self.atoms, self.world, self.aod)
        from neutral_atom_env.hardware.dynamic_traps import validate_support
        validate_support(self)
        from neutral_atom_env.hardware.trap_spacing import validate_trap_spacing
        validate_trap_spacing(self.aod,self.hardware)
        from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
        validate_ez_neighbors(self)

    def metrics(self):
        start=self.physical_metrics.episode_start_us
        wall=self.time_us-start if start is not None else 0.0
        logical=max(0.0,self.physical_metrics.circuit_makespan_us-start) if start is not None else 0.0
        count=sum(n.status.value == "completed" for n in self.dag.nodes.values())
        return {"episode_wall_time_us": wall,
                "logical_completion_elapsed_us": logical if self.dag.completed else None,
                "last_pulse_time_us": self.physical_metrics.circuit_makespan_us,
                "last_pulse_elapsed_us": logical,
                "last_cycle_duration_us": self.physical_metrics.cycle_makespan_us,
                "aod_utilization": self.physical_metrics.aod_busy_time_us/wall if wall else 0.0,
                "laser_utilization": self.physical_metrics.laser_busy_time_us/wall if wall else 0.0,
                "raman_utilization": self.physical_metrics.raman_busy_time_us/wall if wall else 0.0,
                "throughput_gates_per_us": count/wall if wall else 0.0,
                **asdict(self.physical_metrics), "simulation_time_us": self.time_us, "committed_events": self.committed_events,
                "completed_gate_count": sum(n.status.value == "completed" for n in self.dag.nodes.values())}

    def snapshot(self):
        """Versioned checkpoint with complete continuation state, including trace and RNG."""
        from neutral_atom_env.replay.snapshot_encoding import encode_snapshot
        return encode_snapshot(self.snapshot_data())

    def snapshot_data(self):
        """Fresh complete payload, shared by exact encoding and streaming hash."""
        return {"schema_version": 19, "version": self.version, "time_us": self.time_us,
            "world": self.world, "placement": self.placement, "atoms": self.atoms,
            "aod": self.aod, "dag": self.dag.nodes, "event_queue": self.event_queue.snapshot(),
            "circuit": self.dag.circuit, "seed": self.seed,
            "rng_state": self.rng_state, "trace": self.trace.records, "metrics": self.metrics(),
            "hardware": self.hardware, "active_plan": self.active_plan, "reservations": self.reservations,
            "physical_metrics": self.physical_metrics, "slm_enabled": self.slm_enabled, "transfer": self.transfer,
            "quantum_state":self.quantum_state.to_dict() if self.quantum_state is not None else None,
            "measurement_results":self.measurement_results}

    @classmethod
    def restore(cls, snapshot: str) -> 'SimulationState':
        from neutral_atom_env.replay.checkpoint import restore
        return restore(snapshot)
