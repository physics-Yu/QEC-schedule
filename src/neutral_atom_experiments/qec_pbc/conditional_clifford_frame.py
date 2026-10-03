"""Signed, correlated Clifford frames and a deferred ideal resource instrument.

The convention is psi_semantic = F psi_unrealized. No native/encoded S gate
is executed here. Every injection projects the pulled-back physical Pauli;
the exact chronological correction ledger can subsequently realize F.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from itertools import combinations
import math
from typing import Iterable

import numpy as np

from .adaptive_pbc import AdaptivePBCProgram, _apply_clifford, _apply_pauli, compile_adaptive_pbc, execute_reference
from .logical_pauli import conjugate_pauli
from .pauli import PauliProduct


def _bit(value):
    if type(value) is not int or value not in (0, 1):
        raise ValueError('Measurement outcome must be a known integer bit')
    return value


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    index: int
    observable: PauliProduct
    sign: int
    joint_bit: int
    resource_bit: int
    resource: str
    joint_id: str
    resource_id: str

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0 or not isinstance(self.observable, PauliProduct):
            raise ValueError('Correction requires an ordered index and a signed Pauli')
        if type(self.sign) is not int or self.sign not in (-1, 1):
            raise ValueError('Correction sign must be +1 or -1')
        _bit(self.joint_bit)
        _bit(self.resource_bit)
        if any(type(v) is not str or not v.strip() for v in (self.resource, self.joint_id, self.resource_id)) or self.joint_id == self.resource_id:
            raise ValueError('Correction requires distinct measurement IDs and a resource name')

    def to_dict(self):
        return {'index': self.index, 'observable': self.observable.to_dict(), 'sign': self.sign,
                'joint_bit': self.joint_bit, 'resource_bit': self.resource_bit,
                'resource': self.resource, 'depends_on': [self.joint_id, self.resource_id],
                'chronological_correction': ['S_P(sign)^joint_bit', 'P^resource_bit']}


@dataclass(frozen=True, slots=True)
class SignedCliffordFrame:
    wires: tuple[str, ...]
    generator_images: tuple[PauliProduct, ...]
    ledger: tuple[CorrectionRecord, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'wires', tuple(self.wires))
        object.__setattr__(self, 'generator_images', tuple(self.generator_images))
        object.__setattr__(self, 'ledger', tuple(self.ledger))
        if not self.wires or len(set(self.wires)) != len(self.wires) or any(type(w) is not str or not w.strip() for w in self.wires):
            raise ValueError('Frame requires unique named data wires')
        self.validate_symplectic()
        resources, ids = set(), set()
        for index, record in enumerate(self.ledger):
            if not isinstance(record, CorrectionRecord) or record.index != index or not set(record.observable.support).issubset(self.wires):
                raise ValueError('Frame ledger must be chronological on declared data wires')
            if record.resource in resources or record.resource in self.wires or any(v in ids for v in (record.joint_id, record.resource_id)):
                raise ValueError('Consumed resources and committed measurement IDs cannot be reused')
            resources.add(record.resource)
            ids.update((record.joint_id, record.resource_id))
        if self.ledger:
            self.validate_ledger()
        elif self.generator_images != tuple(PauliProduct(((w, b),)) for w in self.wires for b in ('X', 'Z')):
            raise ValueError('Generator images disagree with the empty correction ledger')

    @classmethod
    def identity(cls, wires):
        wires = tuple(wires)
        return cls(wires, tuple(PauliProduct(((w, b),)) for w in wires for b in ('X', 'Z')))

    def validate_symplectic(self):
        """Check all 2n generator supports and their complete commutation form."""
        if len(self.generator_images) != 2 * len(self.wires) or any(
                not isinstance(p, PauliProduct) or not set(p.support).issubset(self.wires) for p in self.generator_images):
            raise ValueError('Frame must contain every signed X/Z generator image')
        for (i, a), (j, b) in combinations(enumerate(self.generator_images), 2):
            expected = not (i // 2 == j // 2)
            if a.commutes_with(b) != expected:
                raise ValueError('Generator images violate the full symplectic commutation form')

    def pullback(self, observable: PauliProduct) -> PauliProduct:
        """Compute F† P F, including Hermitian signs and Y = i X Z."""
        if not isinstance(observable, PauliProduct) or not set(observable.support).issubset(self.wires):
            raise ValueError('Observable must use declared frame wires')
        scalar, result = complex(observable.sign), PauliProduct(())
        for wire, basis in observable.factors:
            index = 2 * self.wires.index(wire)
            if basis == 'Y':
                phase, local = self.generator_images[index].multiply(self.generator_images[index + 1])
                scalar *= 1j * phase
            else:
                local = self.generator_images[index + (basis == 'Z')]
            phase, result = result.multiply(local)
            scalar *= phase
        if scalar not in (1, -1):
            raise AssertionError('Signed Clifford pullback must remain Hermitian')
        return PauliProduct(result.factors, int(scalar.real))

    def corrected(self, record: CorrectionRecord):
        """Update F_new = P^r S_P(s)^m F without applying it to the state."""
        if not isinstance(record, CorrectionRecord) or record.index != len(self.ledger):
            raise ValueError('Correction update is out of order or has already been applied')
        if record.resource in self.wires or any(record.resource == old.resource or
                bool({record.joint_id, record.resource_id} & {old.joint_id, old.resource_id}) for old in self.ledger):
            raise ValueError('Consumed resources and committed measurement IDs cannot be reused')
        q = self.pullback(record.observable)
        images = []
        for index, old in enumerate(self.generator_images):
            generator = PauliProduct(((self.wires[index // 2], ('X', 'Z')[index % 2]),))
            anticommutes = not generator.commutes_with(record.observable)
            phase, image = 1, old
            if anticommutes:
                phase *= (-1) ** record.resource_bit
                if record.joint_bit:
                    product_phase, image = q.multiply(old)
                    phase *= 1j * record.sign * product_phase
            if phase not in (1, -1):
                raise AssertionError('Clifford correction must preserve Hermitian generator signs')
            images.append(PauliProduct(image.factors, int(phase.real) * image.sign))
        # Internal trusted construction: the input frame is immutable and was
        # checked on creation, the appended record was checked above, and every
        # generator was just updated. Public/deserialized construction instead
        # independently replays the complete ledger once in __post_init__.
        frame = object.__new__(SignedCliffordFrame)
        object.__setattr__(frame, 'wires', self.wires)
        object.__setattr__(frame, 'generator_images', tuple(images))
        object.__setattr__(frame, 'ledger', self.ledger + (record,))
        frame.validate_symplectic()
        return frame

    def realize(self, state, *, reference_qubits=0):
        """Apply exact ledger phases, which the symplectic tableau cannot store."""
        if type(reference_qubits) is not int or reference_qubits < 0:
            raise ValueError('Reference count must be a nonnegative integer')
        state = np.array(state, dtype=complex, copy=True)
        if state.shape != (1 << (len(self.wires) + reference_qubits),):
            raise ValueError('Realization vector must use the frame data/reference order')
        for record in self.ledger:
            if record.joint_bit:
                phase = 1j * record.sign
                state = ((1 + phase) * state + (1 - phase) * _apply_pauli(state, record.observable, self.wires, reference_qubits)) / 2
            if record.resource_bit:
                state = _apply_pauli(state, record.observable, self.wires, reference_qubits)
        return state

    def validate_ledger(self):
        """Reject a manually constructed tableau inconsistent with its ledger."""
        replay = SignedCliffordFrame.identity(self.wires)
        for record in self.ledger:
            replay = replay.corrected(record)
        if self.generator_images != replay.generator_images:
            raise ValueError('Generator images disagree with the exact correction ledger')

    def to_dict(self):
        return {'convention': 'psi_semantic = F psi_unrealized', 'wires': list(self.wires),
                'generator_order': [[w, b] for w in self.wires for b in ('X', 'Z')],
                'inverse_generator_images': [p.to_dict() for p in self.generator_images],
                'correction_ledger': [r.to_dict() for r in self.ledger],
                'all_generator_commutations_valid': True}


class FrameController:
    """Ordered result dependencies and a single-use logical resource lifecycle.

    commit_* receives actual instrument results from an executor. It does not
    fabricate a quantum projection or insert computed native measurement keys.
    """
    def __init__(self, program: AdaptivePBCProgram):
        if not isinstance(program, AdaptivePBCProgram):
            raise TypeError('Frame controller requires AdaptivePBCProgram')
        self.program = program
        self.frame = SignedCliffordFrame.identity(program.wires)
        self._next = 0
        self._active = None
        self._bits = {}
        self._records = []
        self._lifecycle = []

    @property
    def measurement_records(self):
        return tuple(deepcopy(r) for r in self._records)

    @property
    def resource_lifecycle(self):
        return tuple(deepcopy(r) for r in self._lifecycle)

    def begin(self, index):
        if type(index) is not int or index != self._next or self._active is not None or index >= len(self.program.injections):
            raise ValueError('Resource is consumed, out of order, or depends on an unfinished correction')
        injection = self.program.injections[index]
        self._active = injection
        return self.frame.pullback(injection.observable)

    def _commit(self, measurement_id, bit, probability, resource_x):
        _bit(bit)
        injection = self._active
        if injection is None:
            raise ValueError('No available injection resource')
        expected = injection.resource_measurement_id if resource_x else injection.joint_measurement_id
        if type(measurement_id) is not str or measurement_id != expected or measurement_id in self._bits:
            raise ValueError('Unknown or repeated measurement ID')
        if resource_x and injection.joint_measurement_id not in self._bits:
            raise ValueError('Resource-X readout depends on its committed joint projection')
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 < probability <= 1 + 1e-12:
            raise ValueError('Projection must have a positive finite Born probability')
        observable = (PauliProduct(((injection.resource.wire, 'X'),)) if resource_x else
                      PauliProduct(self.frame.pullback(injection.observable).factors + ((injection.resource.wire, 'Z'),),
                                   self.frame.pullback(injection.observable).sign))
        self._bits[measurement_id] = bit
        self._records.append({'id': measurement_id, 'outcome': bit, 'observable': observable.to_dict(),
                              'conditional_probability': float(probability),
                              'depends_on': [injection.joint_measurement_id] if resource_x else
                                            [self._records[-1]['id']] if self._records else []})

    def commit_joint(self, measurement_id, bit, conditional_probability):
        self._commit(measurement_id, bit, conditional_probability, False)

    def commit_resource_x(self, measurement_id, bit, conditional_probability):
        self._commit(measurement_id, bit, conditional_probability, True)

    def update(self):
        injection = self._active
        if injection is None or any(i not in self._bits for i in (injection.joint_measurement_id, injection.resource_measurement_id)):
            raise ValueError('Frame update requires both committed projection results')
        m, r = (self._bits[i] for i in (injection.joint_measurement_id, injection.resource_measurement_id))
        self.frame = self.frame.corrected(CorrectionRecord(injection.index, injection.observable,
                                    injection.quarter_turns, m, r, injection.resource.wire,
                                    injection.joint_measurement_id, injection.resource_measurement_id))
        self._lifecycle.append({'wire': injection.resource.wire, 'state': injection.resource.state,
                               'statuses': ['available', 'joint_measured', 'read_out', 'consumed'],
                               'measurement_ids': [injection.joint_measurement_id, injection.resource_measurement_id],
                               'correction_deferred_in_ledger': True, 'final_status': 'consumed'})
        self._next += 1
        self._active = None

    def require_complete(self):
        if self._active is not None or self._next != len(self.program.injections):
            raise ValueError('Final output depends on unfinished resource measurements')


@dataclass(frozen=True)
class DeferredReferenceResult:
    unrealized_state: np.ndarray
    frame: SignedCliffordFrame
    program: AdaptivePBCProgram
    reference_qubits: int
    measurement_records: tuple[dict, ...]
    resource_lifecycle: tuple[dict, ...]
    branch_global_phase_eighth_turns: int
    log2_branch_probability: float
    assumed_ideal_resources: bool
    terminal_measurement_records: tuple[dict, ...] = ()

    def realize(self, *, external_global_phase_radians=0.0):
        if not math.isfinite(external_global_phase_radians):
            raise ValueError('External global phase must be finite')
        state = self.frame.realize(self.unrealized_state, reference_qubits=self.reference_qubits)
        for gate in self.program.residual_clifford:
            state = _apply_clifford(state, gate, self.program.wires, self.reference_qubits)
        state *= np.exp(1j * (math.pi * self.program.global_phase_eighth_turns / 8 + external_global_phase_radians))
        return state

    def terminal_z_labels(self, wires: Iterable[str]):
        """Executable signed labels F† C_res† Z_j C_res F, in caller order."""
        wires = tuple(wires)
        if len(set(wires)) != len(wires) or not set(wires).issubset(self.program.wires):
            raise ValueError('Terminal Z outputs require unique declared data wires')
        labels = []
        for wire in wires:
            observable = PauliProduct(((wire, 'Z'),))
            for gate in reversed(self.program.residual_clifford):
                observable = conjugate_pauli(observable, gate, inverse=True)
            labels.append(self.frame.pullback(observable))
        if any(not p.commutes_with(q) for p, q in combinations(labels, 2)):
            raise AssertionError('Pulled-back terminal Z labels must commute')
        return tuple(labels)

    def to_dict(self):
        return {'schema': 'ideal-deferred-clifford-frame-v1', 'scope': 'ideal logical controller and measurement instrument',
                'quantum_output': 'frame-labelled unrealized vector; realize() applies the exact ledger and residual',
                'frame': self.frame.to_dict(), 'measurements': list(self.measurement_records),
                'terminal_measurements': list(self.terminal_measurement_records),
                'resource_lifecycle': list(self.resource_lifecycle),
                'program_global_phase_eighth_turns': self.program.global_phase_eighth_turns,
                'branch_global_phase_eighth_turns': self.branch_global_phase_eighth_turns,
                'log2_branch_probability': self.log2_branch_probability,
                'assumed_ideal_resources': self.assumed_ideal_resources,
                'native_s_implemented': False, 'encoded': False, 'fault_tolerant': False, 'physical_executed': False}


def execute_deferred_reference(program: AdaptivePBCProgram, state, *, reference_qubits=0,
                               outcomes=None, seed=0, assume_ideal_resources=False):
    """Real sequential PZ/X projections; corrections never touch the live vector."""
    controller = FrameController(program)
    if type(reference_qubits) is not int or reference_qubits < 0 or type(assume_ideal_resources) is not bool:
        raise ValueError('Reference count and ideal-resource assumption must be explicit valid values')
    if any(g.resource.quality != 'ideal_reference' for g in program.injections) and not assume_ideal_resources:
        raise ValueError('Unknown resource quality requires an explicit ideal-resource assumption')
    state = np.array(state, dtype=complex, copy=True)
    if state.shape != (1 << (len(program.wires) + reference_qubits),) or not np.isclose(np.linalg.norm(state), 1, atol=1e-12, rtol=0):
        raise ValueError('Input must be normalized on data and declared reference wires')
    replay = None if outcomes is None else tuple(tuple(pair) for pair in outcomes)
    if replay is not None and (len(replay) != len(program.injections) or
            any(len(pair) != 2 or any(type(b) is not int or b not in (0, 1) for b in pair) for pair in replay)):
        raise ValueError('Exactly one known integer (m,r) pair is required per resource')
    rng = np.random.default_rng(seed)
    branch_phase, log_probability = 0, 0.0
    for index, injection in enumerate(program.injections):
        q = controller.begin(index)
        w = np.exp(1j * injection.quarter_turns * math.pi / 4)
        joint = np.column_stack((state, w * state)) / math.sqrt(2)
        # Apply the current inverse-frame label, including its sign, to data.
        acted = np.column_stack((_apply_pauli(joint[:, 0], q, program.wires, reference_qubits),
                                 -_apply_pauli(joint[:, 1], q, program.wires, reference_qubits)))
        branches = tuple((joint + (-1) ** bit * acted) / 2 for bit in (0, 1))
        probabilities = np.array([np.vdot(v.ravel(), v.ravel()).real for v in branches])
        m = replay[index][0] if replay is not None else int(rng.choice(2, p=probabilities / probabilities.sum()))
        p_m = float(probabilities[m])
        if p_m <= 0:
            raise ValueError('Selected joint projection is impossible')
        joint = branches[m] / math.sqrt(p_m)
        controller.commit_joint(injection.joint_measurement_id, m, p_m)
        branches = tuple((joint[:, 0] + (-1) ** bit * joint[:, 1]) / math.sqrt(2) for bit in (0, 1))
        probabilities = np.array([np.vdot(v, v).real for v in branches])
        r = replay[index][1] if replay is not None else int(rng.choice(2, p=probabilities / probabilities.sum()))
        p_r = float(probabilities[r])
        if p_r <= 0:
            raise ValueError('Selected resource-X projection is impossible')
        state = branches[r] / math.sqrt(p_r)
        controller.commit_resource_x(injection.resource_measurement_id, r, p_r)
        controller.update()
        branch_phase = (branch_phase + (2 * injection.quarter_turns + 8 * r if m else 0)) % 16
        log_probability += math.log2(p_m) + math.log2(p_r)
    controller.require_complete()
    state.setflags(write=False)
    return DeferredReferenceResult(state, controller.frame, program, reference_qubits,
                controller.measurement_records, controller.resource_lifecycle, branch_phase, log_probability,
                assume_ideal_resources)


def execute_terminal_z(result: DeferredReferenceResult, wires, *, outcomes=None, seed=0):
    """Actually project ordered terminal labels on the unrealized retained data."""
    if not isinstance(result, DeferredReferenceResult):
        raise TypeError('Terminal execution requires a completed deferred result')
    wires = tuple(wires)
    labels = result.terminal_z_labels(wires)
    replay = None if outcomes is None else tuple(outcomes)
    if replay is not None and (len(replay) != len(labels) or any(type(b) is not int or b not in (0, 1) for b in replay)):
        raise ValueError('One known bit is required for every terminal projection')
    state, records = result.unrealized_state.copy(), []
    rng = np.random.default_rng(seed)
    for index, (wire, label) in enumerate(zip(wires, labels)):
        acted = _apply_pauli(state, label, result.program.wires, result.reference_qubits)
        branches = tuple((state + (-1) ** bit * acted) / 2 for bit in (0, 1))
        probabilities = np.array([np.vdot(v, v).real for v in branches])
        bit = replay[index] if replay is not None else int(rng.choice(2, p=probabilities / probabilities.sum()))
        probability = float(probabilities[bit])
        if probability <= 0:
            raise ValueError('Selected terminal projection has zero probability')
        state = branches[bit] / math.sqrt(probability)
        measurement_id = f'deferred.terminal.{len(result.terminal_measurement_records) + index}'
        used_ids = ({r['id'] for r in result.measurement_records} |
                    {r['id'] for r in result.terminal_measurement_records} | {r['id'] for r in records})
        while measurement_id in used_ids:
            measurement_id += '.readout'
        records.append({'id': measurement_id, 'semantic_wire': wire, 'outcome': bit,
                        'observable': label.to_dict(), 'conditional_probability': probability,
                        'depends_on': [records[-1]['id']] if records else
                                      [result.terminal_measurement_records[-1]['id']] if result.terminal_measurement_records else
                                      [result.measurement_records[-1]['id']] if result.measurement_records else []})
    state.setflags(write=False)
    return replace(result, unrealized_state=state,
                   terminal_measurement_records=result.terminal_measurement_records + tuple(records)), tuple(records)


def framed_inventory(result: DeferredReferenceResult):
    """Count actual branch labels, never the original eager-label inventory."""
    joints = result.measurement_records[::2]
    data_weights, joint_weights, ys, signs, representative_weights = {}, {}, {}, {}, {}
    mixed = 0
    for record in joints:
        observable = record['observable']
        bases = [b for w, b in observable['factors'] if w in result.program.wires]
        for hist, value in ((data_weights, len(bases)), (joint_weights, len(bases) + 1),
                            (ys, bases.count('Y')), (signs, observable['sign'])):
            hist[value] = hist.get(value, 0) + 1
        # Candidate fixed d=3 representatives only: X/Z length3, Y length5,
        # resource Z length3. This is not an encoded backend or FT cost audit.
        representative_weight = 3 * len(bases) + 2 * bases.count('Y') + 3
        representative_weights[representative_weight] = representative_weights.get(representative_weight, 0) + 1
        mixed += int(len(set(bases)) > 1)
    return {'branch_specific': True, 'joint_measurements': len(joints),
            'data_weight_histogram': data_weights, 'joint_weight_histogram': joint_weights,
            'y_factor_histogram': ys, 'joint_sign_histogram': signs,
            'candidate_fixed_representative_weight_histogram': representative_weights,
            'max_candidate_fixed_representative_joint_weight': max(representative_weights, default=0),
            'representative_cost_scope': 'template_shape_only; not physical atom peak, FT or executed encoded gates',
            'measurements_with_y': sum(v for k, v in ys.items() if k > 0),
            'mixed_data_basis_measurements': mixed,
            'max_data_weight': max(data_weights, default=0), 'max_joint_weight': max(joint_weights, default=0),
            'generator_count': len(result.frame.generator_images), 'encoded': False, 'physical_executed': False}


def audit_deferred_program(source, *, input_state, reference_qubits=0, outcomes=None, seed=0,
                           expected_state=None, external_global_phase_radians=0.0,
                           include_measurement_records=False):
    """Compare realized deferred, eager, and source complex amplitudes.

    expected_state, when provided, includes the external global phase and must
    come from the caller's original-circuit oracle. Otherwise the source Pauli
    rotations are directly evaluated without a resource state or projection.
    """
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference',
                resource_provenance='Explicit external ideal vectors; no encoded preparation')
    actual = execute_deferred_reference(program, input_state, reference_qubits=reference_qubits,
                                        outcomes=outcomes, seed=seed)
    actual.frame.validate_ledger()
    replay = tuple((actual.measurement_records[2 * i]['outcome'], actual.measurement_records[2 * i + 1]['outcome'])
                   for i in range(len(program.injections)))
    eager = execute_reference(program, input_state, reference_qubits=reference_qubits, outcomes=replay)
    output = actual.realize(external_global_phase_radians=external_global_phase_radians)
    if expected_state is None:
        target = np.array(input_state, dtype=complex, copy=True)
        for rotation in source.rotations:
            angle = math.pi * rotation.quarter_turns / 8
            target = math.cos(angle) * target - 1j * math.sin(angle) * _apply_pauli(target, rotation.observable, program.wires, reference_qubits)
        for gate in program.residual_clifford:
            target = _apply_clifford(target, gate, program.wires, reference_qubits)
        target *= np.exp(1j * (math.pi * source.global_phase_eighth_turns / 8 + external_global_phase_radians))
    else:
        target = np.array(expected_state, dtype=complex, copy=True)
        if target.shape != output.shape or not np.isclose(np.linalg.norm(target), 1, atol=1e-12, rtol=0):
            raise ValueError('Expected source state must be normalized on the same wires')
    phase = np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8)
    eager_error = float(np.linalg.norm(output - np.exp(1j * external_global_phase_radians) * eager.state))
    source_error = float(np.linalg.norm(output - phase * target))
    probability_error = max((abs(r['conditional_probability'] - 0.5) for r in actual.measurement_records), default=0.0)
    seen = set()
    for record in actual.measurement_records:
        if record['id'] in seen or not set(record['depends_on']).issubset(seen):
            raise AssertionError('Measurement history has unknown, repeated or premature dependencies')
        seen.add(record['id'])
    if max(eager_error, source_error, probability_error) > 2e-11:
        raise AssertionError('Deferred frame instrument disagrees with eager/source complex amplitudes')
    audit = {'passed': True, 'scope': 'ideal logical controller and real measurement projections only',
             'data_qubits': len(program.wires), 'reference_qubits': reference_qubits,
             'resource_consumptions': len(program.injections), 'measurement_count': len(actual.measurement_records),
             'deferred_eager_l2_error': eager_error, 'source_l2_error': source_error,
             'max_conditional_probability_error': probability_error,
             'all_resources_consumed': all(r['final_status'] == 'consumed' for r in actual.resource_lifecycle),
             'all_measurement_dependencies_valid': True, 'full_generator_and_ledger_audit': True,
             'branch_global_phase_eighth_turns': actual.branch_global_phase_eighth_turns,
             'log2_branch_probability': actual.log2_branch_probability,
             'external_global_phase_radians_applied': external_global_phase_radians,
             'framed_inventory': framed_inventory(actual),
             'native_s_implemented': False, 'encoded': False, 'fault_tolerant': False, 'physical_executed': False}
    if include_measurement_records:
        audit['measurement_records'] = list(actual.measurement_records)
        audit['resource_lifecycle'] = list(actual.resource_lifecycle)
        audit['frame'] = actual.frame.to_dict()
    return actual, audit
