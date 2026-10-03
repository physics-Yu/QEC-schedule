"""Resource-aware signed-Pauli measurement compilation and ideal execution.

This retains data wires, consumes external logical magic resources and applies
explicit conditional Clifford/Pauli corrections.  It is not BSS stabilizer
register elimination, encoded surgery, physical preparation or Executor code.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

from .logical_pauli import LogicalGate, LogicalPauliProgram, PauliRotation
from .magic_injection import ResourceRequest
from .pauli import PauliProduct


@dataclass(frozen=True, slots=True)
class AdaptiveInjection:
    index: int
    source_index: int
    observable: PauliProduct
    quarter_turns: int
    resource: ResourceRequest
    joint_measurement_id: str
    resource_measurement_id: str

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0 or type(self.source_index) is not int or self.source_index < 0:
            raise ValueError('Injection indices must be nonnegative integers')
        if not isinstance(self.observable, PauliProduct) or type(self.quarter_turns) is not int or self.quarter_turns not in (-1, 1):
            raise ValueError('Injection requires a Hermitian observable and +/-1 quarter turns')
        if not isinstance(self.resource, ResourceRequest) or self.resource.state != ('T' if self.quarter_turns == 1 else 'Tdg'):
            raise ValueError('Resource state must match the rotation sign')
        if self.resource.wire in self.observable.support:
            raise ValueError('A resource cannot also be a data observable wire')
        ids = (self.joint_measurement_id, self.resource_measurement_id)
        if any(not isinstance(value, str) or not value.strip() for value in ids) or ids[0] == ids[1]:
            raise ValueError('Injection measurement IDs must be distinct nonempty names')

    @property
    def joint_observable(self) -> PauliProduct:
        return PauliProduct(self.observable.factors + ((self.resource.wire, 'Z'),), self.observable.sign)

    def to_dict(self) -> dict:
        return {
            'index': self.index, 'source_index': self.source_index,
            'rotation': {'observable': self.observable.to_dict(), 'quarter_turns': self.quarter_turns},
            'resource': {'wire': self.resource.wire, 'state': self.resource.state,
                         'provenance': self.resource.provenance, 'quality': self.resource.quality,
                         'consumed': True},
            'operations': [
                {'kind': 'RESOURCE_INPUT', 'wire': self.resource.wire, 'state': self.resource.state,
                 'initial_status': 'available', 'preparation_implemented': False},
                {'kind': 'PAULI_MEASURE', 'id': self.joint_measurement_id,
                 'observable': self.joint_observable.to_dict(), 'destructive': False,
                 'result_convention': '+1 -> 0; -1 -> 1', 'resource_status_after': 'joint_measured'},
                {'kind': 'PAULI_MEASURE', 'id': self.resource_measurement_id,
                 'observable': PauliProduct(((self.resource.wire, 'X'),)).to_dict(), 'destructive': True,
                 'depends_on': [self.joint_measurement_id], 'resource_status_after': 'read_out'},
                {'kind': 'CONDITIONAL_CLIFFORD', 'name': 'S_P' if self.quarter_turns == 1 else 'Sdg_P',
                 'observable': self.observable.to_dict(), 'condition': {'bit': self.joint_measurement_id, 'equals': 1},
                 'definition': 'Pi_plus + exp(i*sign*pi/2)*Pi_minus'},
                {'kind': 'CONDITIONAL_PAULI', 'observable': self.observable.to_dict(),
                 'condition': {'bit': self.resource_measurement_id, 'equals': 1}},
                {'kind': 'CONSUME_RESOURCE', 'wire': self.resource.wire, 'final_status': 'consumed',
                 'depends_on': [self.joint_measurement_id, self.resource_measurement_id]},
            ],
        }


@dataclass(frozen=True, slots=True)
class AdaptivePBCProgram:
    wires: tuple[str, ...]
    injections: tuple[AdaptiveInjection, ...]
    residual_clifford: tuple[LogicalGate, ...]
    source_global_phase_eighth_turns: int
    global_phase_eighth_turns: int

    def __post_init__(self):
        object.__setattr__(self, 'wires', tuple(self.wires))
        object.__setattr__(self, 'injections', tuple(self.injections))
        object.__setattr__(self, 'residual_clifford', tuple(self.residual_clifford))
        if not self.wires or len(set(self.wires)) != len(self.wires) or any(not isinstance(w, str) or not w.strip() for w in self.wires):
            raise ValueError('Adaptive program requires unique nonempty data wires')
        resources, measurements = set(), set()
        for index, injection in enumerate(self.injections):
            if not isinstance(injection, AdaptiveInjection) or injection.index != index or not set(injection.observable.support).issubset(self.wires):
                raise ValueError('Injections must be ordered and refer to declared data wires')
            if injection.resource.wire in resources or injection.resource.wire in self.wires:
                raise ValueError('A consumed resource cannot be reused or alias a data wire')
            resources.add(injection.resource.wire)
            for measurement in (injection.joint_measurement_id, injection.resource_measurement_id):
                if measurement in measurements:
                    raise ValueError('Measurement IDs must be globally unique')
                measurements.add(measurement)
        if any(not isinstance(g, LogicalGate) or g.name in ('T', 'Tdg') or not set(g.wires).issubset(self.wires) for g in self.residual_clifford):
            raise ValueError('Residual operations must be Clifford gates on declared data wires')
        if any(type(v) is not int for v in (self.source_global_phase_eighth_turns, self.global_phase_eighth_turns)):
            raise ValueError('Program global phases must be integer eighth turns')
        expected = (self.source_global_phase_eighth_turns - sum(g.quarter_turns for g in self.injections)) % 16
        if self.global_phase_eighth_turns != expected:
            raise ValueError('Global phase must compensate exactly once for every magic injection')

    def to_dict(self) -> dict:
        return {
            'schema': 'adaptive-pauli-resource-v1', 'wires': list(self.wires),
            'scope': 'logical resource-aware measurement program, preserving arbitrary quantum input/output',
            'rotation_convention': 'R_P(s)=exp(-i*s*pi*P/8)',
            'resource_convention': '|A_s>=(|0>+exp(i*s*pi/4)|1>)/sqrt(2)',
            'injection_unitary_convention': 'T_P(s)=Pi_plus+exp(i*s*pi/4)*Pi_minus=exp(i*s*pi/8)*R_P(s)',
            'source_global_phase_eighth_turns': self.source_global_phase_eighth_turns,
            'global_phase_eighth_turns': self.global_phase_eighth_turns,
            'global_phase_definition': '(source_phase - sum(injection quarter_turns)) mod 16; apply after residual Clifford',
            'injections': [g.to_dict() for g in self.injections],
            'residual_clifford': [{'name': g.name, 'wires': list(g.wires)} for g in self.residual_clifford],
            'resource_consumptions': len(self.injections),
            'resource_buffer_peak': None, 'physical_atom_peak': None,
            'implementation_status': {'adaptive_measurement_program': True, 'ideal_instrument_executor': True,
                                      'bss_stabilizer_register_elimination': False,
                                      'encoded_resource_preparation': False, 'encoded_ppm': False,
                                      'physical_circuit': False, 'executor_run': False},
        }


def compile_adaptive_pbc(source: LogicalPauliProgram, *,
                         resource_provenance: str = 'External logical resource; physical preparation is not implemented',
                         resource_quality: str = 'unknown') -> AdaptivePBCProgram:
    """Lower each +/- pi/8 exponent rotation into two actual measurements.

    Only quarter_turns +1/-1 are supported. Other rotations are rejected rather
    than silently conflated with a single magic consumption or omitted.
    """
    if not isinstance(source, LogicalPauliProgram):
        raise TypeError('Adaptive compilation requires LogicalPauliProgram')
    wires = tuple(source.wires)
    if not wires or len(set(wires)) != len(wires) or any(not isinstance(w, str) or not w.strip() for w in wires):
        raise ValueError('Adaptive program requires unique nonempty data wires')
    if type(source.global_phase_eighth_turns) is not int:
        raise ValueError('Source global phase must be an integer eighth turn')
    rotations = tuple(source.rotations)
    residual = tuple(source.residual_clifford)
    for gate in residual:
        if not isinstance(gate, LogicalGate) or gate.name in ('T', 'Tdg') or not set(gate.wires).issubset(wires):
            raise ValueError('Residual operations must be Clifford gates on declared data wires')
    injections = []
    occupied = set(wires)
    for index, rotation in enumerate(rotations):
        if not isinstance(rotation, PauliRotation) or not set(rotation.observable.support).issubset(wires):
            raise ValueError('Rotation must refer only to declared data wires')
        if rotation.quarter_turns not in (-1, 1):
            raise ValueError(f'Rotation {index} has quarter_turns={rotation.quarter_turns}; only +/-1 magic injections are implemented')
        wire = f'magic.r{index:05d}'
        while wire in occupied:
            wire += '.resource'
        occupied.add(wire)
        resource = ResourceRequest(wire, 'T' if rotation.quarter_turns == 1 else 'Tdg',
                                   resource_provenance, resource_quality)
        injections.append(AdaptiveInjection(index, rotation.source_index, rotation.observable,
                                            rotation.quarter_turns, resource,
                                            f'pbc.r{index:05d}.joint', f'pbc.r{index:05d}.resource_x'))
    phase = (source.global_phase_eighth_turns - sum(g.quarter_turns for g in injections)) % 16
    return AdaptivePBCProgram(wires, tuple(injections), residual, source.global_phase_eighth_turns % 16, phase)


def _apply_pauli(state: np.ndarray, observable: PauliProduct, wires: tuple[str, ...],
                 reference_qubits: int = 0) -> np.ndarray:
    """Big-endian data-wire order followed by untouched reference wires."""
    indices = np.arange(len(state))
    target = indices.copy()
    phase = np.full(len(state), complex(observable.sign))
    total = len(wires) + reference_qubits
    for wire, basis in observable.factors:
        position = total - 1 - wires.index(wire)
        bit = (indices >> position) & 1
        if basis in ('X', 'Y'):
            target ^= 1 << position
        if basis == 'Y':
            phase *= np.where(bit, -1j, 1j)
        elif basis == 'Z':
            phase *= 1 - 2 * bit
    result = np.empty_like(state)
    result[target] = phase * state
    return result


def _apply_clifford(state: np.ndarray, gate: LogicalGate, wires: tuple[str, ...], reference_qubits: int) -> np.ndarray:
    if gate.name in ('X', 'Y', 'Z'):
        return _apply_pauli(state, PauliProduct(((gate.wires[0], gate.name),)), wires, reference_qubits)
    total = len(wires) + reference_qubits
    if gate.name in ('H', 'S', 'Sdg'):
        position = total - 1 - wires.index(gate.wires[0])
        if gate.name == 'H':
            result = state.copy()
            low = np.arange(len(state))[(np.arange(len(state)) & (1 << position)) == 0]
            high = low | (1 << position)
            a, b = state[low], state[high]
            result[low], result[high] = (a + b) / math.sqrt(2), (a - b) / math.sqrt(2)
            return result
        result = state.copy()
        result[((np.arange(len(state)) >> position) & 1).astype(bool)] *= 1j if gate.name == 'S' else -1j
        return result
    c, t = (total - 1 - wires.index(w) for w in gate.wires)
    indices = np.arange(len(state))
    result = state.copy()
    if gate.name == 'CX':
        targets = indices ^ (((indices >> c) & 1) << t)
        result[targets] = state
    elif gate.name == 'CZ':
        result[(((indices >> c) & 1) & ((indices >> t) & 1)).astype(bool)] *= -1
    else:
        raise ValueError('Reference executor supports residual Clifford gates only')
    return result


@dataclass(frozen=True)
class AdaptiveReferenceResult:
    state: np.ndarray
    measurement_records: tuple[dict, ...]
    resource_lifecycle: tuple[dict, ...]
    branch_global_phase_eighth_turns: int
    branch_probability: float
    assumed_ideal_resources: bool

    def to_dict(self) -> dict:
        return {'scope': 'ideal logical measurement-instrument reference only',
                'state_dimension': len(self.state), 'state_norm': float(np.linalg.norm(self.state)),
                'measurement_records': list(self.measurement_records),
                'resource_lifecycle': list(self.resource_lifecycle),
                'branch_global_phase_eighth_turns': self.branch_global_phase_eighth_turns,
                'branch_probability': self.branch_probability,
                'assumed_ideal_resources': self.assumed_ideal_resources,
                'encoded': False, 'physical_executed': False}


def execute_reference(program: AdaptivePBCProgram, state: np.ndarray, *, reference_qubits: int = 0,
                      outcomes: Iterable[tuple[int, int]] | None = None, seed: int = 0,
                      assume_ideal_resources: bool = False) -> AdaptiveReferenceResult:
    """Append resource, project signed PZ, project resource X, then correct.

    Each measurement uses its actual projected vector and probability.  Data
    may be entangled with reference_qubits spectator wires.  Deterministic
    outcomes select real instrument branches; stochastic execution samples the
    calculated Born probabilities.  There is no physical state mutation.
    """
    if not isinstance(program, AdaptivePBCProgram):
        raise TypeError('Reference executor requires AdaptivePBCProgram')
    if type(reference_qubits) is not int or reference_qubits < 0:
        raise ValueError('reference_qubits must be a nonnegative integer')
    if type(assume_ideal_resources) is not bool:
        raise ValueError('The ideal-resource assumption must be an explicit boolean')
    if any(g.resource.quality != 'ideal_reference' for g in program.injections) and not assume_ideal_resources:
        raise ValueError('Unknown resource quality: ideal execution requires an explicit ideal-resource assumption')
    state = np.array(state, dtype=complex, copy=True)
    dimension = 1 << (len(program.wires) + reference_qubits)
    if state.shape != (dimension,) or not np.isclose(np.linalg.norm(state), 1, atol=1e-12, rtol=0):
        raise ValueError('Input must be a normalized vector on data and declared reference wires')
    replay = None if outcomes is None else tuple(tuple(pair) for pair in outcomes)
    if replay is not None and (len(replay) != len(program.injections) or
                               any(len(pair) != 2 or any(type(b) is not int or b not in (0, 1) for b in pair) for pair in replay)):
        raise ValueError('One pair of integer bits (m,r) is required for every injection')
    rng = np.random.default_rng(seed)
    records, lifecycle = [], []
    branch_phase, branch_probability = 0, 1.0
    for index, injection in enumerate(program.injections):
        sign = injection.quarter_turns
        resource_phase = np.exp(sign * 1j * math.pi / 4)
        # Tensor ordering: all data/reference axes, then the appended resource.
        joint = np.column_stack((state, resource_phase * state)) / math.sqrt(2)
        pauli_joint = np.column_stack((_apply_pauli(joint[:, 0], injection.observable, program.wires, reference_qubits),
                                      -_apply_pauli(joint[:, 1], injection.observable, program.wires, reference_qubits)))
        joint_projected = tuple((joint + (-1) ** m * pauli_joint) / 2 for m in (0, 1))
        joint_probabilities = np.array([np.vdot(v.ravel(), v.ravel()).real for v in joint_projected])
        m = replay[index][0] if replay is not None else int(rng.choice(2, p=joint_probabilities / joint_probabilities.sum()))
        m_probability = float(joint_probabilities[m])
        if m_probability <= 0:
            raise ValueError('Selected joint-measurement branch has zero probability')
        measured_joint = joint_projected[m] / math.sqrt(m_probability)
        resource_projected = tuple((measured_joint[:, 0] + (-1) ** r * measured_joint[:, 1]) / math.sqrt(2) for r in (0, 1))
        resource_probabilities = np.array([np.vdot(v, v).real for v in resource_projected])
        r = replay[index][1] if replay is not None else int(rng.choice(2, p=resource_probabilities / resource_probabilities.sum()))
        r_probability = float(resource_probabilities[r])
        if r_probability <= 0:
            raise ValueError('Selected resource-X branch has zero probability')
        state = resource_projected[r] / math.sqrt(r_probability)
        if m:
            # S_{s,P}=Pi_plus + exp(i*s*pi/2)*Pi_minus, a general Clifford.
            phase = sign * 1j
            state = ((1 + phase) * state + (1 - phase) * _apply_pauli(state, injection.observable, program.wires, reference_qubits)) / 2
        if r:
            state = _apply_pauli(state, injection.observable, program.wires, reference_qubits)
        branch_phase = (branch_phase + (2 * sign + 8 * r if m else 0)) % 16
        branch_probability *= m_probability * r_probability
        records.extend(({'id': injection.joint_measurement_id, 'outcome': m,
                         'observable': injection.joint_observable.to_dict(), 'conditional_probability': m_probability},
                        {'id': injection.resource_measurement_id, 'outcome': r,
                         'observable': PauliProduct(((injection.resource.wire, 'X'),)).to_dict(),
                         'conditional_probability': r_probability}))
        lifecycle.append({'wire': injection.resource.wire, 'state': injection.resource.state,
                          'statuses': ['available', 'joint_measured', 'read_out', 'consumed'],
                          'measurement_ids': [injection.joint_measurement_id, injection.resource_measurement_id],
                          'clifford_correction_applied': bool(m), 'pauli_correction_applied': bool(r),
                          'final_status': 'consumed'})
    for gate in program.residual_clifford:
        state = _apply_clifford(state, gate, program.wires, reference_qubits)
    state *= np.exp(1j * math.pi * program.global_phase_eighth_turns / 8)
    return AdaptiveReferenceResult(state, tuple(records), tuple(lifecycle), branch_phase,
                                   branch_probability, assume_ideal_resources)


def audit_adaptive_pbc(source: LogicalPauliProgram, *, input_state: np.ndarray | None = None,
                       reference_qubits: int = 0, outcomes: Iterable[tuple[int, int]] | None = None,
                       seed: int = 0, expected_state: np.ndarray | None = None) -> dict:
    """Compare measurement execution to the source unitary on a complex input.

    Resources are consumed sequentially: the largest temporary vector is only
    twice the data/reference dimension.  expected_state may be supplied by an
    independent original-circuit oracle (e.g. the Shor X/H/CX/CCX prefix).
    Without it, the target is evaluated directly from source Pauli rotations,
    residual Clifford and source global phase, without an injected resource.
    """
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference',
                                   resource_provenance='Explicit ideal vectors for logical instrument verification')
    if type(reference_qubits) is not int or reference_qubits < 0:
        raise ValueError('reference_qubits must be a nonnegative integer')
    dimension = 1 << (len(program.wires) + reference_qubits)
    if input_state is None:
        rng = np.random.default_rng(seed)
        input_state = rng.normal(size=dimension) + 1j * rng.normal(size=dimension)
        input_state /= np.linalg.norm(input_state)
    actual = execute_reference(program, input_state, reference_qubits=reference_qubits, outcomes=outcomes, seed=seed)
    if expected_state is None:
        target = np.array(input_state, dtype=complex, copy=True)
        for rotation in source.rotations:
            angle = math.pi * rotation.quarter_turns / 8
            target = math.cos(angle) * target - 1j * math.sin(angle) * _apply_pauli(target, rotation.observable, program.wires, reference_qubits)
        for gate in source.residual_clifford:
            target = _apply_clifford(target, gate, program.wires, reference_qubits)
        target *= np.exp(1j * math.pi * source.global_phase_eighth_turns / 8)
    else:
        target = np.array(expected_state, dtype=complex, copy=True)
        if target.shape != (dimension,) or not np.isclose(np.linalg.norm(target), 1, atol=1e-12, rtol=0):
            raise ValueError('Expected state must be normalized on the same data/reference wires')
    phase = np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8)
    error = float(np.max(abs(actual.state - phase * target)))
    probability_error = max((abs(record['conditional_probability'] - 0.5) for record in actual.measurement_records), default=0.0)
    lifecycle_valid = (len(actual.resource_lifecycle) == len(program.injections) and
                       all(resource['final_status'] == 'consumed' for resource in actual.resource_lifecycle))
    if error > 2e-12 or probability_error > 2e-12 or not lifecycle_valid:
        raise AssertionError('Adaptive measurement instrument/source unitary audit failed')
    return {'passed': True, 'scope': 'ideal logical resource measurement instrument only',
            'source_oracle': 'caller-supplied original-circuit state' if expected_state is not None else 'direct source Pauli-rotation unitary',
            'data_qubits': len(program.wires), 'reference_qubits': reference_qubits,
            'state_dimension': dimension, 'largest_resource_state_dimension': 2 * dimension if program.injections else dimension,
            'resource_consumptions': len(program.injections), 'measurement_count': len(actual.measurement_records),
            'max_statevector_error': error, 'max_conditional_probability_error': probability_error,
            'all_resources_consumed': lifecycle_valid, 'source_global_phase_eighth_turns': source.global_phase_eighth_turns,
            'program_global_phase_eighth_turns': program.global_phase_eighth_turns,
            'branch_global_phase_eighth_turns': actual.branch_global_phase_eighth_turns,
            'branch_probability': actual.branch_probability,
            'measurements': list(actual.measurement_records), 'resource_lifecycle': list(actual.resource_lifecycle),
            'encoded': False, 'physical_executed': False}
