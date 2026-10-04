"""Streaming native d=3 encoded branches with exact qualified boundaries.

This is an ideal encoded instrument, not ENV execution, motion or noise.
All emitted M/RESET gates have a native kernel/Born record. A bounded logical
tensor and reusable native certificates replace a global 204+ atom vector.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from .adaptive_pbc import AdaptivePBCProgram, AdaptiveInjection, _apply_clifford, _apply_pauli, compile_adaptive_pbc
from .canonical import canonical_memory_program
from .conditional_clifford_frame import FrameController
from .encoded_injection_reference import _canonical_kernel, _codewords
from .encoded_resource_reference import build_css_isometry, build_encoded_resource, execute_resource_reference, apply_native_unitaries
from .logical_pauli import LogicalGate, conjugate_pauli
from .magic_injection import ResourceRequest
from .pauli import PauliProduct
from .qft_synthesis import SynthesizedShor15, apply_synthesized
from .shor15 import build_shor15, postprocess_sample
from .surface import patch_roles, logical_product


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(4 << 20):
            digest.update(block)
    return digest.hexdigest()


def deserialize_adaptive(value):
    """Dataclass validation followed by exact round-trip schema validation."""
    if value.get('schema') != 'adaptive-pauli-resource-v1':
        raise ValueError('Unknown adaptive PBC schema')
    items = []
    for row in value['injections']:
        rotation, request = row['rotation'], row['resource']
        word = rotation['observable']
        items.append(AdaptiveInjection(row['index'], row['source_index'], PauliProduct(word['factors'], word['sign']),
            rotation['quarter_turns'], ResourceRequest(**request), row['operations'][1]['id'], row['operations'][2]['id']))
    program = AdaptivePBCProgram(tuple(value['wires']), tuple(items),
        tuple(LogicalGate(g['name'], tuple(g['wires'])) for g in value['residual_clifford']),
        value['source_global_phase_eighth_turns'], value['global_phase_eighth_turns'])
    if program.to_dict() != value:
        raise ValueError('Adaptive input has altered operation semantics, omitted fields or unknown extensions')
    return program


def load_cached_shor(source_directory):
    """Rebuild the source and CT→PBC normalization; never trust cached flags."""
    directory = Path(source_directory)
    ct_path, pbc_path, source_path = (directory / name for name in
        ('complete_clifford_t.json', 'complete_adaptive_pbc.json', 'shor15_circuit.json'))
    ct, serialized, source_dict = (json.loads(path.read_text(encoding='utf-8')) for path in (ct_path, pbc_path, source_path))
    source = build_shor15(phase_bits=8)
    if source.to_dict() != source_dict or ct.get('schema') != 'shor15-clifford-t-synthesis-v1':
        raise ValueError('Cached source must be the complete unchanged eight-phase-bit Shor15 circuit')
    program = SynthesizedShor15(source, tuple(ct['wires']),
        tuple(LogicalGate(g['name'], tuple(g['wires'])) for g in ct['gates']),
        ct['global_phase_radians'], ct['total_operator_error_budget'], ct['local_operator_error_budget'],
        tuple(ct['rz_certificates']), tuple(ct['source_gate_spans']))
    if program.to_dict() != ct:
        raise ValueError('Cached CT metadata disagrees with its actual gates')
    if not all(math.isfinite(v) for v in (program.global_phase_radians,program.total_error_budget,program.local_error_budget)):
        raise ValueError('Cached phase and operator budgets must be finite')
    if not 1e-8<=program.total_error_budget<=.1 or abs(program.local_error_budget-program.total_error_budget/(6*28))>1e-15:
        raise ValueError('Cached synthesis budgets differ from the complete 28CP synthesis contract')
    if len(program.wires) != 12 or len(program.rz_certificates) != 84 or len(program.source_gate_spans) != len(source.gates):
        raise ValueError('Complete 12-wire source, all 28 CP and 84 Rz expansions are required')
    cursor = 0
    from .shor_frontend import ArithmeticProgram, expand_clifford_t
    for index, span in enumerate(program.source_gate_spans):
        gate = source.gates[index]
        if (span['source_gate_index'] != index or span['stage'] != gate.stage or span['name'] != gate.name or
            span['source_cp_angle_radians'] != gate.angle_radians or span['gate_span'][0] != cursor or
            not cursor <= span['gate_span'][1] <= len(program.gates)):
            raise ValueError('Cached source/CT spans are incomplete or reordered')
        cursor = span['gate_span'][1]
        actual_block=program.gates[slice(*span['gate_span'])]
        if gate.name!='CP':
            expected_block=expand_clifford_t(ArithmeticProgram(program.wires,((gate.name,gate.qubits),),'cached source validation'))
            if actual_block!=expected_block:
                raise ValueError('Cached arithmetic/initialization block differs from full source decomposition')
        else:
            certificates=[c for c in program.rz_certificates if c['source_gate_index']==index]
            control,target=(program.wires[q] for q in gate.qubits)
            theta=gate.angle_radians
            recipes=((control,theta/2),(target,theta/2),(target,-theta/2))
            if len(certificates)!=3 or any(c['wire']!=wire or c['rz_angle_radians']!=angle or
                c['source_cp_angle_radians']!=theta for c,(wire,angle) in zip(certificates,recipes)):
                raise ValueError('Cached CP decomposition has the wrong Rz axes/angles/source')
            c0,c1,c2=certificates
            expected_spans=((span['gate_span'][0],c0['gate_span'][1]),
                (c0['gate_span'][1],c1['gate_span'][1]),
                (c1['gate_span'][1]+1,c2['gate_span'][1]))
            if any(tuple(c['gate_span'])!=s for c,s in zip(certificates,expected_spans)) or span['gate_span'][1]!=c2['gate_span'][1]+1:
                raise ValueError('Cached CP expansion does not cover every Rz and two CX gates')
            if (program.gates[c1['gate_span'][1]]!=LogicalGate('CX',(control,target)) or
                program.gates[c2['gate_span'][1]]!=LogicalGate('CX',(control,target))):
                raise ValueError('Cached CP decomposition omitted its actual two CX gates')
    if cursor != len(program.gates):
        raise ValueError('CT gates are outside the complete source spans')
    phase=sum(g.angle_radians/4 for g in source.gates if g.name=='CP')+sum(c['global_phase_radians'] for c in program.rz_certificates)
    if abs(np.exp(1j*phase)-np.exp(1j*program.global_phase_radians))>2e-12:
        raise ValueError('Cached complete external global phase differs from source decomposition')
    wrapper_fields={'external_global_phase_radians':program.global_phase_radians,
        'external_phase_action':'multiply final instrument state by exp(i*external_global_phase_radians)',
        'instrument_statevector_bit_order':'big-endian data wires then external reference'}
    if any(serialized.get(key)!=value for key,value in wrapper_fields.items()):
        raise ValueError('Cached PBC external phase or vector-order wrapper differs from complete CT source')
    adaptive = deserialize_adaptive({key:value for key,value in serialized.items() if key not in wrapper_fields})
    first = adaptive.injections[0].resource
    rebuilt = compile_adaptive_pbc(program.compile_pauli(), resource_quality=first.quality,
        resource_provenance=first.provenance)
    if rebuilt != adaptive:
        raise ValueError('Cached PBC differs from independent normalization of the actual CT gates')
    # Validate each synthesized Rz matrix independently, including its scalar
    # phase; matching a cached gate count is not a synthesis certificate.
    matrices = {'H': np.array([[1, 1], [1, -1]], complex)/math.sqrt(2), 'X': np.array([[0, 1], [1, 0]], complex),
        'S': np.diag([1, 1j]), 'Sdg': np.diag([1, -1j]), 'T': np.diag([1, np.exp(1j*math.pi/4)]),
        'Tdg': np.diag([1, np.exp(-1j*math.pi/4)])}
    errors = []
    for certificate in program.rz_certificates:
        if not all(math.isfinite(certificate[key]) for key in ('global_phase_radians','rz_angle_radians','operator_error')):
            raise ValueError('Cached Rz numerical certificate must be finite')
        unitary = np.eye(2, dtype=complex)
        for gate in program.gates[slice(*certificate['gate_span'])]:
            if gate.wires != (certificate['wire'],) or gate.name not in matrices:
                raise ValueError('Rz certificate includes the wrong native logical gate')
            unitary = matrices[gate.name] @ unitary
        unitary *= np.exp(1j * certificate['global_phase_radians'])
        theta = certificate['rz_angle_radians']
        error = float(np.linalg.norm(unitary - np.diag([np.exp(-1j*theta/2), np.exp(1j*theta/2)]), ord=2))
        if error > program.local_error_budget + 1e-12 or abs(error-certificate['operator_error']) > 1e-12:
            raise ValueError('Actual cached Rz gates fail phase-sensitive synthesis verification')
        errors.append(error)
    return program, adaptive, {'source_files': {p.name: {'sha256': _file_hash(p), 'bytes': p.stat().st_size}
        for p in (ct_path, pbc_path, source_path)}, 'all_source_cp_retained': 28,
        'rz_matrices_independently_checked': len(errors), 'rz_error_sum': sum(errors),
        'ct_to_pbc_recompiled_exactly': True, 'source_directory': str(directory.resolve())}


@lru_cache(maxsize=2)
def _producer(sign):
    prepared = build_encoded_resource(sign=sign, patch='resource',
        bindings={r.id: r.id for r in patch_roles('resource')}, namespace='kernel.producer')
    actual = execute_resource_reference(prepared, seed=0)
    _, code = _codewords('resource')
    matrix = actual.state.reshape(512, 256)
    logical = code.conj().T @ matrix[:, 0]
    error = float(np.linalg.norm(matrix[:, 0] - code @ logical))
    target = np.array([1, np.exp(1j*sign*math.pi/4)]) / math.sqrt(2)
    if max(error, np.linalg.norm(matrix[:, 1:]), np.linalg.norm(logical-target)) > 3e-12:
        raise AssertionError('Actual 17q native producer failed its complete signed encoded boundary')
    records = [{'native_gate_id': r['id'], 'kind': 'RESET', 'outcome': r['projected_bit'],
        'conditional_probability': r['conditional_probability'], 'source': 'qualified_actual_native_17q_resource_producer'} for r in actual.reset_records]
    records += [{'native_gate_id': r['id'], 'kind': 'MEASURE', 'outcome': r['outcome'],
        'conditional_probability': r['conditional_probability'], 'source': 'qualified_actual_native_17q_resource_producer'} for r in actual.measurement_records]
    certificate = {'kind': 'actual_17q_native_producer', 'sign': sign, 'native_gate_sha256': _sha([asdict(g) for g in prepared.circuit.gates]),
        'native_gate_signature_sha256': _sha([(g.gate_type,[q.removeprefix('resource.') for q in g.qubit_ids]) for g in prepared.circuit.gates]),
        'native_gate_count': len(prepared.circuit.gates), 'state_dimension': 1 << 17, 'encoded_boundary_l2_error': error,
        'logical_vector': [[v.real, v.imag] for v in logical], 'projection_records': records,
        'qualified_once_then_exact_zero_input_kernel_reuse': True, 'input_condition': 'all17 wires known zero after explicit prior release/reset',
        'factory': False, 'fault_tolerant': False}
    return prepared, logical, records, certificate


@lru_cache(maxsize=1)
def _resource_x_kernel():
    """Every raw-X bra follows the actual nine emitted native H matrices."""
    roles, code = _codewords('resource')
    gates = PhysicalCircuit(tuple(PhysicalGate(f'kernel.resource_x.h{i}', 'H', (role,)) for i, role in enumerate(roles)))
    transformed = np.column_stack([apply_native_unitaries(gates, code[:, i], roles) for i in (0, 1)])
    if np.linalg.norm(transformed.conj().T @ transformed-np.eye(2)) > 2e-12:
        raise AssertionError('Native H9 readout is not a complete encoded instrument')
    # The fixed logical X is X0 X3 X6; check each complete complex bra.
    for value, row in enumerate(transformed):
        bit = ((value >> 8) ^ (value >> 5) ^ (value >> 2)) & 1
        if np.linalg.norm(row[1] - (-1)**bit * row[0]) > 2e-12:
            raise AssertionError('Native physical readout does not implement the fixed logical X')
    return transformed


class _Writer:
    def __init__(self, output, wires, cat_capacity=63):
        self.output = Path(output)
        if self.output.exists():
            raise FileExistsError('A fresh output directory is required; failed attempts are preserved')
        self.output.mkdir(parents=True)
        self.streams = {name: (self.output / (name + '.jsonl')).open('wb') for name in
            ('functions', 'native_gates', 'native_projections', 'frames')}
        self.counts = Counter()
        self.gate_types = Counter()
        self.tail = None
        self.certificates = {}
        self.frame_hashes = set()
        roles = [r for patch in (*wires, 'resource') for r in patch_roles(patch)]
        role_dicts = [{'role': r.id, 'kind': r.kind, 'patch': r.patch} for r in roles]
        role_dicts += [{'role': f'cat.{i}', 'kind': 'cat_ancilla', 'patch': None} for i in range(cat_capacity)]
        role_dicts += [{'role': 'cat.verifier', 'kind': 'verification_ancilla', 'patch': None}]
        self.mapping = {row['role']: f'Q{i:03d}' for i, row in enumerate(role_dicts)}
        for row in role_dicts:
            row['id'] = self.mapping[row['role']]
        from neutral_atom_experiments.surface_ghz import X_CHECKS, Z_CHECKS, LOGICAL_X, LOGICAL_Z
        self.save('roles.json', {'schema': 'encoded-native-roles/1', 'roles': role_dicts,
            'algorithm_patches': list(wires), 'resource_patch': 'resource', 'cat_pool_size': cat_capacity,
            'code_checks': {'X':[list(check) for check in X_CHECKS], 'Z':[list(check) for check in Z_CHECKS]},
            'logical_X':list(LOGICAL_X),'logical_Z':list(LOGICAL_Z)})

    def save(self, name, value):
        (self.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

    def frame(self, frame):
        value = {'wires': list(frame.wires), 'inverse_generator_images': [p.to_dict() for p in frame.generator_images],
            'ledger_length': len(frame.ledger), 'last_correction': frame.ledger[-1].to_dict() if frame.ledger else None}
        key = _sha(value)
        if key not in self.frame_hashes:
            self.line('frames', dict(sha256=key, **value))
            self.frame_hashes.add(key)
        return key

    def line(self, name, value):
        encoded = (_json(value) + '\n').encode()
        self.streams[name].write(encoded)
        return encoded

    def function(self, kind, namespace, gates=(), records=(), *, shot_index=0, injection_index=None,
                 epoch=None, context=None, certificate_ids=(), **fields):
        index = self.counts['functions']
        fid = f'function.{index:07d}'
        gate_start, projection_start = self.counts['native_gates'], self.counts['native_projections']
        gate_offset = self.streams['native_gates'].tell()
        projection_offset = self.streams['native_projections'].tell()
        input_records=tuple(records)
        records = {r['native_gate_id']: dict(r) for r in input_records}
        if len(records)!=len(input_records):
            raise ValueError('Duplicate native projection inputs cannot be silently collapsed')
        expected = {g.id for g in gates if g.gate_type in ('MEASURE', 'RESET')}
        if set(records) != expected or len(expected) != sum(g.gate_type in ('MEASURE', 'RESET') for g in gates):
            raise AssertionError('Exactly one legitimate kernel/Born record is required for every emitted M/RESET')
        gate_hash, projection_hash = hashlib.sha256(), hashlib.sha256()
        for gate in gates:
            if gate.id == self.tail or gate.condition:
                raise ValueError('Native stream requires globally fresh unconditional actual selected-branch gates')
            if any(role not in self.mapping for role in gate.qubit_ids):
                raise ValueError('Gate targets an undeclared or unbound physical role')
            # Serial dependencies give a concrete legal circuit order. No
            # geometry/timing/parallelism claim is inferred from this order.
            row = {'index': self.counts['native_gates'], 'id': gate.id, 'gate_type': gate.gate_type,
                'qubit_ids': [self.mapping[r] for r in gate.qubit_ids], 'role_ids': list(gate.qubit_ids),
                'depends_on': [self.tail] if self.tail else [], 'condition': [], 'epoch': epoch,
                'function_id': fid, 'source': 'selected_branch_encoded_native_generator'}
            gate_hash.update(self.line('native_gates', row))
            self.tail = gate.id
            self.counts['native_gates'] += 1
            self.gate_types[gate.gate_type] += 1
            if gate.id in records:
                record = records[gate.id]
                if type(record['outcome']) is not int or record['outcome'] not in (0, 1) or not 0 < record['conditional_probability'] <= 1+1e-10:
                    raise ValueError('Projection record must contain a positive finite actual branch probability and integer bit')
                record.update(index=self.counts['native_projections'], function_id=fid, epoch=epoch)
                projection_hash.update(self.line('native_projections', record))
                self.counts['native_projections'] += 1
        row = {'index': index, 'function_id': fid, 'shot_index': shot_index, 'injection_index': injection_index,
            'kind': kind, 'namespace': namespace, 'epoch': epoch, 'gate_start': gate_start,
            'gate_end': self.counts['native_gates'], 'gate_count': self.counts['native_gates']-gate_start,
            'gate_byte_start': gate_offset, 'gate_byte_end': self.streams['native_gates'].tell(),
            'projection_start': projection_start, 'projection_count': self.counts['native_projections']-projection_start,
            'projection_byte_start': projection_offset, 'projection_byte_end': self.streams['native_projections'].tell(),
            'native_sha256': gate_hash.hexdigest(), 'projection_sha256': projection_hash.hexdigest(),
            'certificate_ids': list(certificate_ids), 'depends_on': [f'function.{index-1:07d}'] if index else [],
            'context': context or {}, **fields}
        self.line('functions', row)
        self.counts['functions'] += 1
        return row

    def finish(self, summary, complete=True):
        for stream in self.streams.values():
            stream.close()
        self.save('certificates.json', {'schema': 'encoded-native-certificates/1', 'certificates': self.certificates,
            'scope': 'exact ideal native kernels reused at qualified encoded boundaries'})
        self.save('summary.json', summary)
        artifacts = {p.name: {'sha256': _file_hash(p), 'bytes': p.stat().st_size} for p in self.output.iterdir() if p.is_file() and p.name != 'manifest.json'}
        self.save('manifest.json', {'schema': 'encoded-native-run-manifest/1', 'complete': complete,
            'artifacts': artifacts, 'physical_executed': False, 'environment_committed_reports': False,
            'fault_tolerant': False, 'scope': 'ideal encoded selected native branch and factorized Born instrument'})


def _renamed(gates, records, old, new):
    gates = tuple(replace(g, id=new+g.id.removeprefix(old), depends_on=()) for g in gates)
    records = tuple(dict(r, native_gate_id=new+r['native_gate_id'].removeprefix(old)) for r in records)
    return gates, records


def _canonical(writer, patch, rounds, namespace, **context):
    template = canonical_memory_program(patch=patch, rounds=rounds)
    selected = {key for phase in template.phases if phase.round_index is not None for key in phase.gate_ids}
    gates = tuple(PhysicalGate(namespace+'.'+op.id, op.gate_type, op.targets) for op in template.program.operations if op.id in selected)
    kernel, error = _canonical_kernel(rounds, False)
    records = tuple({'native_gate_id': namespace+'.'+patch+'.'+key, 'kind': kind, 'outcome': bit,
        'conditional_probability': probability, 'source': 'qualified_actual_native_18q_canonical_choi_kernel'}
        for key, kind, bit, probability in kernel)
    cid = f'canonical.{rounds}'
    writer.certificates[cid] = {'kind': 'actual_native_18q_canonical_choi', 'rounds': rounds,
        'identity_channel_l2_error': error, 'all_native_projection_records': [list(r) for r in kernel],
        'input_condition': 'complete +1 stabilizer code sector, arbitrary entangled logical input',
        'native_gate_count_per_patch': len(gates), 'qualified_once_then_exact_boundary_reuse': True,
        'native_gate_signature_sha256':_sha([(g.gate_type,[q.removeprefix(patch+'.') for q in g.qubit_ids]) for g in gates])}
    return writer.function('canonical_check', namespace, gates, records, certificate_ids=(cid,),
        context={'patch': patch, 'rounds': rounds, 'signed_sector': [0]*8, 'syndrome_auxiliaries_released': True}, **context)


def _encode(writer, wires, rounds, shot, *, zero_input):
    for patch in wires:
        namespace = f'shot{shot}.encode.{patch}'
        reset = tuple(PhysicalGate(namespace+f'.reset{i}', 'RESET', (r.id,)) for i, r in enumerate(patch_roles(patch))
                      if zero_input or r.id != patch+'.d0')
        # Shot input is logical zero. All old algorithm data are discarded by
        # terminal cleanup before reuse; first shot starts known physicalzero.
        records = tuple({'native_gate_id': g.id, 'kind': 'RESET', 'outcome': 0,
            'conditional_probability': 1., 'source': 'known_zero_native_reset_boundary'} for g in reset)
        encoder = build_css_isometry(patch=patch, data_qubits=tuple(f'{patch}.d{i}' for i in range(9)), namespace=namespace)
        roles, code = _codewords(patch)
        actual_columns=[]
        for bit in (0,1):
            zero = np.zeros(512, complex); zero[bit<<8] = 1
            actual_columns.append(apply_native_unitaries(encoder.isometry_circuit, zero, roles))
        error = float(np.linalg.norm(np.column_stack(actual_columns)-code))
        if error > 2e-12:
            raise AssertionError('Native algorithm encoder failed independent CSS projector oracle')
        cid = 'data.css.encoder'
        writer.certificates[cid] = {'kind': 'actual_native_9q_css_isometry', 'isometry_gate_count': len(encoder.isometry_circuit.gates),
            'both_complex_columns_l2_error': error, 'complete_isometry_proof': 'both actual native encoder columns checked against CSS projector; arbitrary reference by linearity',
            'input_condition': 'unknown logical d0 with other8data zero, auxzero', 'qualified_once_then_relabelled': True}
        writer.function('data_encode', namespace, (*reset, *encoder.isometry_circuit.gates), records,
            shot_index=shot, context={'patch': patch, 'input': 'logical_zero' if zero_input else 'caller_supplied_unknown_d0',
                'unknown_input_preserved': not zero_input, 'signed_sector': [0]*8}, certificate_ids=(cid,))
        _canonical(writer, patch, rounds, namespace+'.check', shot_index=shot)


def _read_resource(writer, joint, wires, rng, namespace, *, shot, index, epoch, reference_qubits):
    bras = _resource_x_kernel()
    matrix = joint.reshape(1 << len(wires), 2, 1 << reference_qubits)
    active=np.flatnonzero(np.max(abs(bras),axis=1)>1e-12)
    candidate = np.einsum('abr,vb->avr', matrix, bras[active])
    probabilities=np.zeros(512)
    probabilities[active] = np.sum(abs(candidate)**2, axis=(0,2))
    probabilities /= probabilities.sum()
    value = int(rng.choice(512, p=probabilities))
    bits = tuple((value >> (8-i)) & 1 for i in range(9))
    r = bits[0] ^ bits[3] ^ bits[6]
    parity = np.array([((v >> 8) ^ (v >> 5) ^ (v >> 2)) & 1 for v in range(512)])
    pr = float(probabilities[parity == r].sum())
    state = candidate[:, int(np.flatnonzero(active==value)[0]), :].ravel() / math.sqrt(float(probabilities[value]))
    gates, records = [], []
    for kind, label in (('H', 'h'), ('MEASURE', 'measure'), ('RESET', 'reset')):
        for i in range(9):
            gid = namespace+f'.{label}{i}'
            gates.append(PhysicalGate(gid, kind, (f'resource.d{i}',)))
            if kind == 'MEASURE':
                prefix_mask = (np.arange(512) >> (8-i)) == (value >> (8-i))
                previous = np.ones(512, bool) if i == 0 else (np.arange(512) >> (9-i)) == (value >> (9-i))
                probability = float(probabilities[prefix_mask].sum()/probabilities[previous].sum())
                records.append({'native_gate_id': gid, 'kind': kind, 'outcome': bits[i], 'conditional_probability': probability,
                    'source': 'qualified_native_H9_css_raw_bra_Born_projection'})
            elif kind == 'RESET':
                records.append({'native_gate_id': gid, 'kind': kind, 'outcome': bits[i], 'conditional_probability': 1.,
                    'source': 'actual_measured_resource_data_release'})
    keys = [namespace+f'.measure{i}' for i in (0, 3, 6)]
    writer.certificates['resource.raw_x'] = {'kind': 'actual_native_H9_complete512_css_bras',
        'bra_matrix_sha256': hashlib.sha256(bras.tobytes()).hexdigest(), 'raw_patterns_checked': 512,
        'logical_x_fixed_support': [0, 3, 6], 'complete_bra_phase_retained': True}
    writer.function('resource_readout_reset', namespace, gates, records, shot_index=shot, injection_index=index,
        epoch=epoch, certificate_ids=('resource.raw_x',), logical_result=r, conditional_probability=pr,
        raw_parity={'keys': keys, 'constant': 0, 'bit': r},
        context={'all_nine_raw_bits': list(bits), 'selected_pattern_probability': float(probabilities[value]),
            'all_nine_data_measured_and_reset': True, 'syndrome_auxiliaries_already_released': True})
    return state, r, pr, keys


def _cat(writer, word, state, wires, reference_qubits, rng, namespace, *, shot, index=None, epoch=None):
    from .wide_cat_reference import build_wide_cat, certify_wide_cat, sample_wide_cat
    size = len(logical_product(word).factors)
    item = build_wide_cat(word, namespace=namespace, cat_roles=tuple(f'cat.{i}' for i in range(size)), verifier_role='cat.verifier')
    proof = certify_wide_cat(item)
    acted = _apply_pauli(state, word, wires, reference_qubits)
    expectation = float(np.vdot(state, acted).real)
    sampled = sample_wide_cat(item, expectation, rng)
    bit, probability = sampled.semantic_branch, sampled.logical_branch_probability
    projected = (state + (-1)**bit*acted)/math.sqrt(4*probability)
    projected *= sampled.coefficient_phase
    cid = 'widecat.'+proof['native_program_sha256']
    writer.certificates[cid] = proof
    records = tuple({'native_gate_id': r['native_gate_id'], 'kind': r['operation_kind'],
        'outcome':r['projected_bit'],'conditional_probability':r['selected_probability_given_prefix'],
        'source':'qualified_actual_wide_native_cat_Born_kernel','stage':r['stage']} for r in sampled.projection_records)
    writer.function('terminal_readout' if index is None else 'cat_joint', namespace,
        item.program.operations, records, shot_index=shot, injection_index=index, epoch=epoch,
        certificate_ids=(cid,), logical_pauli=word.to_dict(), logical_result=bit,
        conditional_probability=probability, raw_parity={'keys': list(item.cat_measurement_ids),
            'constant': int(item.physical_product.sign == -1), 'bit': bit},
        context={'signed_expectation': expectation, 'verification_accepted_before_data_coupling':
            all(bit==0 for gid,bit in sampled.raw_results if gid in item.verification_ids),
            'cat_size': len(item.cat_roles), 'cat_helpers_released': True})
    return projected, bit, probability, list(item.cat_measurement_ids)


def _cleanup(writer, state, wires, reference_qubits, rng, shot):
    """Actual encoded computational readout, followed by all9 data RESETs."""
    indices=np.arange(len(state));total=len(wires)+reference_qubits
    for patch_index,patch in enumerate(wires):
        roles,code=_codewords(patch)
        position=total-1-patch_index
        bits=(indices>>position)&1
        logical_prob=np.array([np.sum(abs(state[bits==b])**2) for b in (0,1)])
        probabilities=abs(code)**2 @ logical_prob
        probabilities/=probabilities.sum()
        value=int(rng.choice(512,p=probabilities))
        # Positive real CSS computational bras retain no omitted phase.
        state=state*code[value,bits]/math.sqrt(float(probabilities[value]))
        if not np.isclose(np.linalg.norm(state),1,rtol=0,atol=2e-11):
            raise AssertionError('Destructive encoded cleanup lost its Born branch')
        rawbits=tuple((value>>(8-i))&1 for i in range(9))
        namespace=f'shot{shot}.cleanup.{patch}'
        gates=[];records=[]
        for kind,label in (('MEASURE','measure'),('RESET','reset')):
            for i in range(9):
                gid=namespace+f'.{label}{i}'
                gates.append(PhysicalGate(gid,kind,(roles[i],)))
                prefix=(np.arange(512)>>(8-i))==(value>>(8-i))
                previous=np.ones(512,bool) if i==0 else (np.arange(512)>>(9-i))==(value>>(9-i))
                probability=float(probabilities[prefix].sum()/probabilities[previous].sum()) if kind=='MEASURE' else 1.
                records.append({'native_gate_id':gid,'kind':kind,'outcome':rawbits[i],'conditional_probability':probability,
                    'source':'qualified_css_computational_raw_bra_Born_projection' if kind=='MEASURE' else 'actual_measured_algorithm_data_release'})
        writer.certificates['data.raw_z']={'kind':'complete512_css_computational_bras',
            'bra_matrix_sha256':hashlib.sha256(code.tobytes()).hexdigest(),'raw_patterns_checked':512,
            'native_measurement_basis':'Z','all_nine_data_reset_after_actual_projection':True}
        writer.function('algorithm_cleanup_reset',namespace,gates,records,shot_index=shot,certificate_ids=('data.raw_z',),
            context={'patch':patch,'all_nine_raw_bits':list(rawbits),'all_nine_data_reset':True,'syndrome_aux_already_zero':True})


def execute_encoded_native(program, input_state, output, *, rounds=1, seed=0, reference_qubits=0,
                           terminal_wires=(), external_global_phase_radians=0., synthesized=None,
                           max_attempts=1, source_provenance=None, on_progress=None):
    """Stream every selected native gate; store failed Shor attempts unchanged.

    For generic probes max_attempts is one and no terminal cleanup/retry is
    made. Full Shor retries initialize every physical data patch by actual
    destructive Z readout/RESET, so reset kernels never assume unknownzero.
    """
    if not isinstance(program, AdaptivePBCProgram) or not 1 <= len(program.wires) <= 12:
        raise ValueError('A validated one-to-twelve-wire adaptive program is required')
    if 'resource' in program.wires:
        raise ValueError('Algorithm patch resource aliases the reserved physical resource patch')
    if type(rounds) is not int or rounds < 1 or type(seed) is not int or seed < 0 or type(reference_qubits) is not int or not 0 <= reference_qubits <= 1:
        raise ValueError('Positive syndrome rounds, nonnegative seed and zero/one reference required')
    if type(max_attempts) is not int or max_attempts < 1 or any(i.resource.quality != 'ideal_reference' for i in program.injections):
        raise ValueError('Positive attempt budget and explicit ideal-reference resource quality required')
    initial = np.asarray(input_state, dtype=complex)
    if initial.shape != (1 << (len(program.wires)+reference_qubits),) or not np.isclose(np.linalg.norm(initial), 1, rtol=0, atol=1e-12):
        raise ValueError('Normalized logical input and declared reference dimension required')
    if max_attempts > 1 and (synthesized is None or reference_qubits or np.linalg.norm(initial-np.eye(1,len(initial),0).ravel()) > 1e-12):
        raise ValueError('Retries require complete zero-input Shor with no spectator')
    if synthesized is not None and (synthesized.wires != program.wires or terminal_wires != program.wires[:8]):
        raise ValueError('Shor source and complete phase register must match the encoded program')
    writer = _Writer(output, program.wires)
    started, attempts, rng = time.perf_counter(), [], np.random.default_rng(seed)
    try:
        if source_provenance and source_provenance.get('source_directory'):
            source_directory=Path(source_provenance['source_directory'])
            for name in ('complete_clifford_t.json','shor15_circuit.json'):
                path=source_directory/name
                if _file_hash(path)!=source_provenance['source_files'][name]['sha256']:
                    raise ValueError('Cached source changed after validation; refusing stale provenance')
                (writer.output/name).write_bytes(path.read_bytes())
        writer.save('input.json', {'schema': 'encoded-native-input/1', 'program': program.to_dict(), 'rounds': rounds,
            'seed': seed, 'reference_qubits': reference_qubits, 'initial_logical_state': [[v.real,v.imag] for v in initial],
            'external_global_phase_radians': external_global_phase_radians, 'source_provenance': source_provenance or {}})
        for shot in range(max_attempts):
            state, controller, branch_phase = initial.copy(), FrameController(program), 0
            g0, p0 = writer.counts['native_gates'], writer.counts['native_projections']
            zero_input=bool(np.linalg.norm(initial-np.eye(1,len(initial),0).ravel())<1e-12)
            _encode(writer, program.wires, rounds, shot,zero_input=zero_input)
            for index, injection in enumerate(program.injections):
                epoch = f'shot{shot}.resource{index:05d}'
                before = writer.frame(controller.frame)
                q = controller.begin(index)
                template, logical_resource, records, certificate = _producer(injection.quarter_turns)
                cid = f'producer.{injection.quarter_turns:+d}'
                writer.certificates[cid] = certificate
                gates, records = _renamed(template.circuit.gates, records, 'kernel.producer', epoch+'.producer')
                source_context={'source_ct_gate_index':injection.source_index}
                if synthesized is not None:
                    span=next(s for s in synthesized.source_gate_spans if s['gate_span'][0]<=injection.source_index<s['gate_span'][1])
                    source_context.update(source_shor_gate_index=span['source_gate_index'],source_shor_gate_name=span['name'],source_shor_stage=span['stage'])
                writer.function('resource_prepare', epoch+'.producer', gates, records, shot_index=shot,
                    injection_index=index, epoch=epoch, certificate_ids=(cid,), context={'resource_wire': f'shot{shot}.'+injection.resource.wire,
                        'source_resource_wire':injection.resource.wire,
                        'physical_patch': 'resource', 'phase_sign': injection.quarter_turns, 'fresh_logical_resource': True,
                        'physical_patch_reused_after_complete_release': bool(shot or index), 'native_kernel_reuse_explicit': True,
                        **source_context})
                word = PauliProduct(q.factors+(('resource','Z'),), q.sign)
                joint = np.einsum('ar,b->abr',state.reshape(1<<len(program.wires),1<<reference_qubits),logical_resource).ravel()
                for patch in word.support:
                    _canonical(writer, patch, rounds, epoch+'.before.'+patch, shot_index=shot, injection_index=index, epoch=epoch)
                joint, m, pm, mkeys = _cat(writer, word, joint, (*program.wires,'resource'), reference_qubits,
                    rng, epoch+'.joint', shot=shot, index=index, epoch=epoch)
                for patch in word.support:
                    _canonical(writer, patch, rounds, epoch+'.after.'+patch, shot_index=shot, injection_index=index, epoch=epoch)
                state, r, pr, rkeys = _read_resource(writer, joint, program.wires, rng,
                    epoch+'.resource_x', shot=shot, index=index, epoch=epoch,reference_qubits=reference_qubits)
                if not np.allclose([pm,pr],[.5,.5],rtol=0,atol=2e-11):
                    raise AssertionError('Qualified encoded producer/consumer lost ideal injection probabilities')
                controller.commit_joint(injection.joint_measurement_id,m,pm)
                controller.commit_resource_x(injection.resource_measurement_id,r,pr)
                controller.update()
                after = writer.frame(controller.frame)
                branch_phase=(branch_phase+(2*injection.quarter_turns+8*r if m else 0))%16
                writer.function('frame_update', epoch+'.frame', shot_index=shot,injection_index=index,epoch=epoch,
                    frame_before_sha256=before,frame_after_sha256=after,
                    context={'m':m,'r':r,'semantic_joint_id':injection.joint_measurement_id,
                        'semantic_resource_id':injection.resource_measurement_id,'joint_raw_ids':mkeys,'resource_x_raw_ids':rkeys,
                        'resource_wire':f'shot{shot}.'+injection.resource.wire,'source_resource_wire':injection.resource.wire,'physical_patch':'resource',
                        'statuses':['prepared','joint_measured','destructively_read_out','consumed','reset_released'],
                        'all_nine_data_reset':True,'all_eight_aux_released':True,'environment_committed':False})
                if on_progress and (index % 100 == 0 or index+1==len(program.injections)):
                    on_progress({'shot_index':shot,'injection_done':index+1,'injection_total':len(program.injections),
                        'native_gates':writer.counts['native_gates'],'wall_seconds':time.perf_counter()-started})
            controller.require_complete()
            writer.save(f'shot{shot}_unrealized_state.json',{'amplitudes':[[v.real,v.imag] for v in state],
                'logical_wire_order':'big endian; optional reference last','frame':controller.frame.to_dict(),
                'branch_global_phase_eighth_turns':branch_phase})
            semantic = controller.frame.realize(state,reference_qubits=reference_qubits)
            for gate in program.residual_clifford:
                semantic = _apply_clifford(semantic,gate,program.wires,reference_qubits)
            semantic *= np.exp(1j*(math.pi*program.global_phase_eighth_turns/8+external_global_phase_radians))
            writer.save(f'shot{shot}_semantic_state.json', {'amplitudes':[[v.real,v.imag] for v in semantic],
                'branch_global_phase_eighth_turns':branch_phase,'logical_wire_order':'big endian; optional reference last',
                'residual_clifford_realized_for_semantic_audit_only':True})
            audit_error = None
            if synthesized is not None:
                width=len(program.wires)
                indices=np.arange(len(initial));reverse=np.zeros(len(initial),dtype=int)
                for b in range(width):reverse|=((indices>>b)&1)<<(width-1-b)
                expected=apply_synthesized(synthesized,initial[reverse])[reverse]
                audit_error=float(np.linalg.norm(semantic-np.exp(1j*math.pi*branch_phase/8)*expected))
                if audit_error>4e-10:raise AssertionError('Complete encoded branch differs from independent CT simulation')
            phase_readout=[]
            for bit_index, wire in enumerate(terminal_wires):
                word=PauliProduct(((wire,'Z'),))
                for gate in reversed(program.residual_clifford):word=conjugate_pauli(word,gate,inverse=True)
                word=controller.frame.pullback(word)
                state, bit, prob, raw=_cat(writer,word,state,program.wires,reference_qubits,rng,
                    f'shot{shot}.terminal{bit_index}',shot=shot)
                phase_readout.append({'wire':wire,'bit':bit,'conditional_probability':prob,'raw_gate_ids':raw,
                    'signed_label':word.to_dict(),'real_reference_projection':True})
            outcome=sum(row['bit']<<i for i,row in enumerate(phase_readout)) if phase_readout else None
            classical=postprocess_sample(outcome,phase_bits=8,base=2,modulus=15) if synthesized is not None else {}
            attempts.append({'shot_index':shot,'phase_outcome':outcome,'phase_readout':phase_readout,
                'classical_postprocessing':classical,'resource_consumptions':len(program.injections),
                'native_gate_count':writer.counts['native_gates']-g0,'native_projection_count':writer.counts['native_projections']-p0,
                'complete_ct_instrument_l2_error':audit_error,'branch_global_phase_eighth_turns':branch_phase,
                'final_frame_sha256':writer.frame(controller.frame),'all_resources_consumed_and_released':True})
            # Retry cleanup is destructive actual data-Z measurement. For
            # entangled encoded state sample logical computationalbasis then
            # independent CSS physical bit orbit, and project sequentially.
            if synthesized is not None and not classical.get('success') and shot+1<max_attempts:
                cleanup_g0,cleanup_p0=writer.counts['native_gates'],writer.counts['native_projections']
                _cleanup(writer,state,program.wires,reference_qubits,rng,shot)
                attempts[-1].update(native_gate_count=writer.counts['native_gates']-g0,
                    native_projection_count=writer.counts['native_projections']-p0,
                    cleanup_native_gate_count=writer.counts['native_gates']-cleanup_g0,
                    cleanup_projection_count=writer.counts['native_projections']-cleanup_p0,
                    algorithm_reset_released_before_next_shot=True)
            if classical.get('success') or synthesized is None:break
        success=bool(attempts and attempts[-1]['classical_postprocessing'].get('success'))
        last=attempts[-1]['classical_postprocessing'] if success else {}
        summary={'schema':'encoded-native-shor-run/1','success':success,'order':last.get('order'),'factors':last.get('factors'),
            'attempts':attempts,'logical_width':len(program.wires),'algorithm_patch_atoms':17*len(program.wires),
            'declared_atom_count':len(writer.mapping),'native_gate_count':writer.counts['native_gates'],
            'native_gate_counts':dict(writer.gate_types),'native_projection_count':writer.counts['native_projections'],
            'function_count':writer.counts['functions'],'syndrome_rounds':rounds,'wall_seconds':time.perf_counter()-started,
            'encoded_native_branch_complete':True,'source_global_phases_retained':True,
            'selected_branch_generation':True,'qualified_native_kernel_execution':True,'global_physical_dense_state':False,
            'environment_committed_reports':False,'physical_executed':False,'fault_tolerant':False,'magic_factory':False,
            'motion_schedule':False,'physical_time_microseconds':None,'resource_consumptions':sum(a['resource_consumptions'] for a in attempts)}
        writer.save('shots.json',attempts)
        writer.save('terminal.json',{'readouts':[a['phase_readout'] for a in attempts],'residual_clifford_gate_count':len(program.residual_clifford),
            'readout_contract':'native cats measure signed Fdagger Cdagger Z C F; residual not omitted or silently executed'})
        writer.finish(summary)
        return summary
    except BaseException as error:
        summary={'schema':'encoded-native-shor-run/1','success':False,'complete':False,'attempts':attempts,
            'error':{'type':type(error).__name__,'message':str(error)},'native_gate_count':writer.counts['native_gates'],
            'native_projection_count':writer.counts['native_projections'],'physical_executed':False,
            'wall_seconds':time.perf_counter()-started}
        writer.finish(summary,complete=False)
        raise
