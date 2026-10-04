"""Independent dense native instruments and scalable wide-cat contracts."""
from dataclasses import replace
from itertools import product
import math
import random

import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.qec_pbc.wide_cat_reference import (
    audit_wide_cat_codespace, build_wide_cat, certify_wide_cat, sample_wide_cat,
)


H = np.array([[1, 1], [1, -1]], dtype=complex) / math.sqrt(2)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.diag([1, -1]).astype(complex)


def _one(v, matrix, target, n):
    a = v.reshape((2,) * n)
    a = np.moveaxis(a, target, 0)
    a = np.tensordot(matrix, a, axes=(1, 0))
    return np.moveaxis(a, 0, target).reshape(-1)


def _dense_native(item, input_data_ref, forced_cat):
    """No producer emulator or factorized proof is called by this oracle."""
    data = tuple(q for q, _ in item.physical_product.factors)
    helpers = (*item.cat_roles, item.verifier_role)
    wires = (*data, 'ref', *helpers)
    n = len(wires)
    v = np.kron(input_data_ref, np.eye(1, 1 << len(helpers), 0).reshape(-1))
    indices, total_probability, observed = np.arange(len(v)), 1.0, {}
    for gate in item.program.operations:
        positions = tuple(wires.index(q) for q in gate.qubit_ids)
        if gate.gate_type == 'CZ':
            a, b = (n - 1 - q for q in positions)
            v *= 1 - 2 * (((indices >> a) & (indices >> b)) & 1)
        elif gate.gate_type in ('H', 'T'):
            matrix = H if gate.gate_type == 'H' else np.diag([1, np.exp(1j * np.pi / 4)])
            v = _one(v, matrix, positions[0], n)
        else:
            q = positions[0]
            ones = (indices & (1 << (n - 1 - q))) != 0
            p0 = float(np.vdot(v[~ones], v[~ones]).real)
            if gate.gate_type == 'MEASURE':
                bit = forced_cat.get(gate.id, 0)
                observed[gate.id] = bit
            else:
                # All resets have either fresh zero or preceding projected
                # eigenstate; this oracle derives it from actual dense v.
                bit = int(p0 < .5)
            prob = p0 if bit == 0 else 1 - p0
            if prob < 1e-14:
                raise AssertionError('Independent dense branch is impossible')
            total_probability *= prob
            v = v.copy()
            v[ones if bit == 0 else ~ones] = 0
            v /= math.sqrt(prob)
            if gate.gate_type == 'RESET' and bit:
                v = _one(v, X, q, n)
    # Helpers were *actually* measured/reset. Extract their all-zero arm.
    output = v.reshape((-1, 1 << len(helpers)))[:, 0]
    assert np.linalg.norm(v.reshape((-1, 1 << len(helpers)))[:, 1:]) < 1e-13
    return output, total_probability, observed


@pytest.mark.parametrize('basis,sign', product('XYZ', (-1, 1)))
def test_all_small_actual_native_raw_channels_keep_external_reference(basis, sign):
    item = build_wide_cat(PauliProduct((('A', basis),), sign))
    cert = certify_wide_cat(item)
    n = len(item.cat_roles)
    # Physical data is arbitrary and entangled with an external reference.
    rng = np.random.default_rng(56)
    v = rng.normal(size=1 << (n + 1)) + 1j * rng.normal(size=1 << (n + 1))
    v /= np.linalg.norm(v)
    unsigned = np.array([[1]], dtype=complex)
    for _, b in item.physical_product.factors:
        unsigned = np.kron(unsigned, {'X': X, 'Y': Y, 'Z': Z}[b])
    signed = item.physical_product.sign * np.kron(unsigned, np.eye(2))
    expectation = float(np.vdot(v, signed @ v).real)
    probabilities = [0.0, 0.0]
    for bits in product((0, 1), repeat=n):
        forced = dict(zip(item.cat_measurement_ids, bits))
        native, p_native, observed = _dense_native(item, v, forced)
        sample = sample_wide_cat(item, expectation, random.Random(5), forced_raw=forced, certificate=cert)
        m = sample.semantic_branch
        p_m = (1 + (-1) ** m * expectation) / 2
        expected = (v + (-1) ** m * signed @ v) / math.sqrt(4 * p_m)
        # Complex L2 without stripping global phase tests actual CY/i phases.
        assert np.linalg.norm(native - expected) < 4e-13
        assert abs(p_native - sample.raw_branch_probability) < 4e-14
        assert abs(p_native - p_m / (1 << (n - 1))) < 4e-14
        assert observed == dict(sample.raw_results)
        assert sample.coefficient_phase == 1
        probabilities[m] += p_native
    assert np.allclose(probabilities, [(1 + expectation) / 2, (1 - expectation) / 2], atol=3e-13)
    assert math.isclose(sum(probabilities), 1, abs_tol=4e-13)


def test_sixty_three_native_factors_operator_certificate_no_enumeration():
    # Maximum full-Shor request: 12 Y algorithm patches and Z resource.
    p = PauliProduct(tuple((f'L{i:02}', 'Y') for i in range(12)) + (('R', 'Z'),), -1)
    item = build_wide_cat(p)
    cert = certify_wide_cat(item)
    assert len(item.cat_roles) == 63
    assert cert['raw_branches_symbolically_covered'] == 1 << 63
    assert cert['all_raw_enumeration_used'] is False
    assert cert['canonical_codespace']['signed_sectors_algebraically_checked'] == 256
    assert cert['local_matrix_error'] < 1e-12
    sample = sample_wide_cat(item, .125, random.Random(91), certificate=cert)
    assert len(sample.raw_results) == 2 * 62 + 63
    assert {gid for gid, _ in sample.raw_results} == {g.id for g in item.program.operations if g.gate_type == 'MEASURE'}
    expected_probability = sample.logical_branch_probability / (1 << 62)
    assert math.isclose(sample.raw_branch_probability, expected_probability, rel_tol=1e-12)
    assert tuple(r['native_gate_id'] for r in sample.projection_records) == tuple(
        g.id for g in item.program.operations if g.gate_type in ('MEASURE', 'RESET'))
    for before, after in zip(sample.projection_records, sample.projection_records[1:]):
        if before['operation_kind'] == 'MEASURE' and before['target'] == after['target']:
            assert after['operation_kind'] == 'RESET'
            assert after['projected_bit'] == before['projected_bit']
            assert after['reset_output_bit'] == 0


@pytest.mark.parametrize('expectation', (-1, -.25, 0, .77, 1))
def test_complete_prefix_born_rules_and_fixed_parity(expectation):
    item = build_wide_cat(PauliProduct((('A', 'X'),), -1))
    cert = certify_wide_cat(item)
    probabilities = [0., 0.]
    for bits in product((0, 1), repeat=3):
        m = sum(bits) % 2 ^ 1
        forced = dict(zip(item.cat_measurement_ids, bits))
        if (1 + (-1) ** m * expectation) / 2 == 0:
            with pytest.raises(ValueError, match='zero conditional Born'):
                sample_wide_cat(item, expectation, random.Random(1), forced_raw=forced)
            continue
        sample = sample_wide_cat(item, expectation, random.Random(1), forced_raw=forced, certificate=cert)
        cat = [r for r in sample.projection_records if r['stage'] == 'cat_readout']
        assert [r['probability_zero_given_prefix'] for r in cat[:2]] == [.5, .5]
        assert cat[2]['probability_zero_given_prefix'] == (1 - (-1) ** (bits[0] ^ bits[1]) * expectation) / 2
        probabilities[m] += sample.raw_branch_probability
    assert np.allclose(probabilities, [(1 + expectation) / 2, (1 - expectation) / 2])


@pytest.mark.parametrize('change', ('remove_h', 'reverse_cy', 'phase_t', 'dependency', 'readout_flip', 'missing_reset', 'sidecar', 'verifier'))
def test_complete_native_tampering_rejected_before_sampling(change):
    item = build_wide_cat(PauliProduct((('A', 'Y'),)))
    operations = list(item.program.operations)
    if change == 'remove_h':
        j = next(i for i, g in enumerate(operations) if '.prepare.h__' in g.id)
        operations[j] = replace(operations[j], gate_type='X')
    elif change == 'reverse_cy':
        j = next(i for i, g in enumerate(operations) if '.couple0.z__' in g.id)
        operations[j] = replace(operations[j], qubit_ids=tuple(reversed(operations[j].qubit_ids)))
    elif change == 'phase_t':
        j = next(i for i, g in enumerate(operations) if '.s.t1__' in g.id)
        operations[j] = replace(operations[j], gate_type='Z')
    elif change == 'dependency':
        operations[-1] = replace(operations[-1], depends_on=())
    elif change == 'readout_flip':
        j = next(i for i, g in enumerate(operations) if g.id in item.cat_measurement_ids)
        operations[j] = replace(operations[j], readout_flip=True)
    elif change == 'missing_reset':
        operations[-1] = replace(operations[-1], gate_type='X')
    elif change == 'sidecar':
        obs = item.program.observables[0]
        altered = replace(item, program=replace(item.program, observables=(replace(obs, expression=replace(obs.expression, constant=1)),)))
    elif change == 'verifier':
        altered = replace(item, verification_ids=item.verification_ids[:-1])
    if change not in ('sidecar', 'verifier'):
        altered = replace(item, program=replace(item.program, operations=tuple(operations)))
    with pytest.raises(ValueError, match='contract was altered'):
        sample_wide_cat(altered, 0, random.Random(3))


def test_force_audit_only_actual_ids_and_deterministic_verifier_zero():
    item = build_wide_cat(PauliProduct((('A', 'Z'),)))
    with pytest.raises(ValueError, match='zero conditional Born'):
        sample_wide_cat(item, 0, random.Random(1), forced_raw={item.verification_ids[0]: 1})
    for key, value in [('invented', 0), (item.cat_measurement_ids[0], True)]:
        with pytest.raises(ValueError, match='actual native MEASURE'):
            sample_wide_cat(item, 0, random.Random(1), forced_raw={key: value})
    with pytest.raises(ValueError, match='Certificate differs'):
        sample_wide_cat(item, 0, random.Random(1), certificate={'passed': True})


@pytest.mark.parametrize('expectation', (float('nan'), float('inf'), 1.01, -1.01, True))
def test_invalid_expectation_rejected(expectation):
    item = build_wide_cat(PauliProduct((('A', 'X'),)))
    with pytest.raises(ValueError, match='finite signed Born'):
        sample_wide_cat(item, expectation, random.Random(1))


def test_signed_sector_proof_cached_result_cannot_be_mutated():
    report = audit_wide_cat_codespace()
    assert report['syndrome_and_logical_constraint_rank'] == 10
    assert report['signed_sectors_algebraically_checked'] == 256
    report['passed'] = False
    assert audit_wide_cat_codespace()['passed'] is True


def test_all_signed_sectors_independent_css_orbit_and_complex_logical_axes():
    """Fixed CSS orbit, exhaustive *local* masks; no GF2 proof solver used."""
    from neutral_atom_experiments.surface_ghz import X_CHECKS, Z_CHECKS, LOGICAL_X, LOGICAL_Z
    from neutral_atom_experiments.qec_pbc.encoded_resource_reference import build_css_isometry
    masks = lambda supports: tuple(sum(1 << (8 - q) for q in s) for s in supports)
    xs, zs = masks(X_CHECKS), masks(Z_CHECKS)
    lx, lz = masks((LOGICAL_X, LOGICAL_Z))
    orbit = [0]
    for mask in xs:
        orbit += [value ^ mask for value in orbit]
    independent = np.zeros((512, 2), dtype=complex)
    independent[orbit, 0] = .25
    independent[[q ^ lx for q in orbit], 1] = .25
    wires = tuple(f'A.d{i}' for i in range(9))
    circuit = build_css_isometry(patch='A', data_qubits=wires).isometry_circuit
    actual = []
    indices = np.arange(512)
    for bit in (0, 1):
        v = np.zeros(512, dtype=complex)
        v[bit << 8] = 1
        for gate in circuit.gates:
            if gate.gate_type == 'H':
                v = _one(v, H, wires.index(gate.qubit_ids[0]), 9)
            else:
                a, b = (8 - wires.index(q) for q in gate.qubit_ids)
                v *= 1 - 2 * (((indices >> a) & (indices >> b)) & 1)
        actual.append(v)
    assert np.linalg.norm(np.column_stack(actual) - independent) < 2e-13
    # Exhaustive 512 candidates for each CSS half, independently choosing
    # corrections with zero logical parity. This does not reuse the solver.
    def table(checks, logical):
        found = {}
        for mask in range(512):
            if (mask & logical).bit_count() % 2:
                continue
            syndrome = sum(((mask & support).bit_count() % 2) << i for i, support in enumerate(checks))
            found.setdefault(syndrome, mask)
        assert len(found) == 16
        return found
    xtable, ztable = table(zs, lz), table(xs, lx)
    phase = lambda mask: np.array([(-1) ** ((int(i) & mask).bit_count() % 2) for i in indices])
    for xsector, zsector in product(range(16), repeat=2):
        xmask, zmask = xtable[zsector], ztable[xsector]
        v = (phase(zmask)[:, None] * independent)[indices ^ xmask]
        for i, mask in enumerate(xs):
            assert np.linalg.norm(v[indices ^ mask] - (-1) ** ((xsector >> i) & 1) * v) < 2e-13
        for i, mask in enumerate(zs):
            assert np.linalg.norm(phase(mask)[:, None] * v - (-1) ** ((zsector >> i) & 1) * v) < 2e-13
        px, pz = v[indices ^ lx], phase(lz)[:, None] * v
        py = 1j * pz[indices ^ lx]
        for physical, expected in ((px, X), (py, Y), (pz, Z)):
            assert np.linalg.norm(physical - v @ expected) < 2e-13


def test_caps_fresh_resource_alias_and_identity_rejected():
    with pytest.raises(ValueError, match='1 to 63'):
        build_wide_cat(PauliProduct(tuple((f'P{i}', 'Y') for i in range(13))))
    with pytest.raises(ValueError, match='nonidentity'):
        build_wide_cat(PauliProduct(()))
    with pytest.raises(ValueError, match='Distinct fresh'):
        build_wide_cat(PauliProduct((('A', 'X'),)), cat_roles=('A.d0', 'c1', 'c2'))
