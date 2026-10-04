"""Independent spectator/capture counterexamples for placement proposals."""
import importlib.util
import json
import math
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location('enola_endpoint_audit',
    Path(__file__).parents[1] / 'tools/audit_enola_patch_proposal.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
SITES = [(4, 2), (3, 3), (2, 4), (3, 1), (2, 2), (1, 3), (2, 0), (1, 1),
         (0, 2), (3, 2), (1, 2), (3, 4), (1, 0), (2, 3), (2, 1), (4, 1), (0, 3)]
ROLES = [f'A.d{i}' for i in range(9)] + [f'A.{b}{i}' for b in ('X', 'Z') for i in range(4)]
HOMES = {q: (10 * x, 10 * y) for q, (x, y) in zip(ROLES, SITES)}


def fixture_file(tmp_path):
    """Explicit geometric test fixture; does not claim an author SA execution."""
    layers = [[list(p) for p in layer] for layer in AUDIT.CANONICAL_PAIRS]
    coords = {q: list(p) for q, p in HOMES.items()}
    value = {'schema': 'enola-single-patch-placement-proposal/1',
        'role_order': ROLES, 'layers': layers, 'coordinates_um': coords,
        'site_coordinates': dict(zip(ROLES, SITES)),
        'placement_sha256': AUDIT._sha(AUDIT._json_bytes(coords)),
        'home_spacing_um': 10.0, 'slm_grid_spacing_um': 5.0,
        'site_rectangle': [5, 5], 'seed': 0,
        'protocol': {'source': {'commit': '42e0b9e099180e8570407c33f87b4683cac00d81'},
                     'template_sha256': 'geometric-test-template'},
        'source': {'expected_commit': '2944dbf4e163e8d2eeeec607add0d9139edce689',
                   'placer_sha256': AUDIT.PINNED_PLACER_SHA256}}
    source_input = {'roles': ROLES, 'layers': layers, 'template_sha256': 'geometric-test-template',
        'width': 5, 'height': 5, 'seed': 0, 'home_spacing_um': 10.0,
        'placer_sha256': AUDIT.PINNED_PLACER_SHA256}
    value['input_sha256'] = AUDIT._sha(AUDIT._json_bytes(source_input))
    path = tmp_path / 'proposal.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_finite_exact_pairs_alone_do_not_imply_ten_um_spectator_clearance():
    result = AUDIT.endpoint_check(HOMES, [('A.X0', 'A.d4')], [(-3, 0)])
    assert result['global_exact_cz_pairs'] is True
    assert result['endpoint_accepted'] is False
    assert result['minimum_nonpair_distance_um'] == 7
    assert result['closest_nonpair'] == ('A.X0', 'A.X1')


def test_move_toward_vacated_neighbor_preserves_all_other_ten_um_distances():
    result = AUDIT.endpoint_check(HOMES, [('A.X0', 'A.d4')], [(3, 0)])
    assert result['endpoint_accepted'] is True
    assert result['minimum_nonpair_distance_um'] == 10
    assert result['mobile_endpoints_um']['A.X0'] == (23, 20)
    assert AUDIT.four_neighbor_obstruction(HOMES, 'A.X0', 'A.d4') is None


def test_four_unmoved_neighbors_obstruct_entire_finite_cz_circle():
    homes = {'data': (0, 0), 'ancilla': (30, 30),
             'east': (10, 0), 'west': (-10, 0), 'north': (0, 10), 'south': (0, -10)}
    certificate = AUDIT.four_neighbor_obstruction(homes, 'ancilla', 'data')
    assert certificate['necessary_nonzero_target_radius_um'] == pytest.approx(math.sqrt(200))
    assert certificate['available_cz_radius_um'] == 6
    assert certificate['impossible_for_any_nonzero_offset_within_cz_range'] is True
    for offset in AUDIT.OFFSETS:
        result = AUDIT.endpoint_check(homes, [('ancilla', 'data')], [offset])
        assert result['endpoint_accepted'] is False
        assert result['nonpair_clearance_ge_10um'] is False


def test_single_three_um_offset_keeps_every_unrequested_atom_at_its_home():
    result = AUDIT.endpoint_check(HOMES, [('A.X0', 'A.d4')], [(3, 0)])
    assert result['actual_pairs'] == [('A.X0', 'A.d4')]
    # The minimum remains 10 because static untouched neighbors are included.
    assert result['minimum_nonpair_distance_um'] == 10


@pytest.mark.parametrize('offsets', [[], [(7, 0)], [(0, 0)], [(float('nan'), 0)]])
def test_invalid_or_out_of_range_endpoints_are_rejected(offsets):
    with pytest.raises(ValueError):
        AUDIT.endpoint_check(HOMES, [('A.X0', 'A.d4')], offsets)


def test_full_layer_cartesian_product_contains_seven_unrequested_data_atoms():
    mobiles = ['A.X0', 'A.X1', 'A.X2', 'A.Z0', 'A.Z1', 'A.Z3']
    capture = AUDIT.cartesian_capture(HOMES, mobiles)
    assert capture['active_rectangle'] == [4, 4]
    assert capture['active_intersections'] == 16
    assert len(capture['actual_capture_closure']) == 13
    assert capture['extra_captured_atoms'] == [f'A.d{i}' for i in (1, 2, 3, 4, 5, 7, 8)]
    assert capture['requested_only_capture'] is False
    assert capture['fits_3_by_3_uniform_20um_axes'] is False


def test_x_bank_three_sources_capture_only_requested_ancillas():
    capture = AUDIT.cartesian_capture(HOMES, ['A.X0', 'A.X1', 'A.X2'])
    assert capture['active_rectangle'] == [2, 2]
    assert capture['active_intersections'] == 4
    assert capture['actual_capture_closure'] == ['A.X0', 'A.X1', 'A.X2']
    assert capture['fits_3_by_3_uniform_20um_axes'] is True


def test_whole_source_audit_finds_solutions_but_rejects_unsupported_full_capture(tmp_path):
    path = fixture_file(tmp_path)
    before = path.read_bytes()
    result = AUDIT.audit_proposal(path)
    expected_subset = {
        'single_couplings_with_scanned_solution': 24, 'single_couplings_total': 24,
        'single_couplings_fixed_minus3x_accepted': 13,
        'all6_source_capture_accepted': 0, 'X3_Z3_source_and_endpoint_accepted': 8,
        'full_physical_execution_certified': False}
    assert all(result['summary'][key] == value for key, value in expected_subset.items())
    full = [row for row in result['layer_groups'] if row['group'] == 'all6']
    assert [row['toward_vacated_home_candidate']['movement_shape']['shared_rigid_shift'] for row in full] == [True, False, False, True]
    assert [row['toward_vacated_home_candidate']['movement_shape']['ordered_row_column_embedding'] for row in full] == [True, False, False, True]
    assert path.read_bytes() == before
    assert result['proposal_sha256'] == AUDIT._sha(before)


def test_scale_twenty_um_is_explicitly_a_different_candidate_not_original_sa(tmp_path):
    result = AUDIT.audit_proposal(fixture_file(tmp_path), scale=2)
    assert result['derived_candidate_changes_original_10um_layout'] is True
    assert result['site_pitch_um'] == result['minimum_home_distance_um'] == 20
    assert result['summary']['single_couplings_fixed_minus3x_accepted'] == 24
    assert result['summary']['all6_source_capture_accepted'] == 0
    assert result['summary']['full_physical_execution_certified'] is False
    assert result['css_encoder']['fixed_second_mobile_scanned_solution_count'] == 44
    assert result['summary']['full_prefix_fixed_second_mobile_endpoint_screen_passed'] is True


def test_css_actual_d4_anchors_are_analytically_obstructed_at_ten_um(tmp_path):
    result = AUDIT.audit_proposal(fixture_file(tmp_path))
    css = result['css_encoder']
    assert css['native_cz_count'] == 44
    assert css['fixed_second_mobile_analytic_obstruction_indices'] == [19, 21, 30, 32, 36, 38]
    assert result['summary']['full_prefix_fixed_second_mobile_endpoint_screen_passed'] is False
    example = css['gates'][19]
    assert example['authored_pair'] == ['A.d4', 'A.d7']
    orientation = example['orientations'][0]
    assert orientation['fixed_anchor_role'] == 'A.d4'
    assert orientation['moving_role'] == 'A.d7'
    assert orientation['analytical_obstruction']['unmoved_neighbors'] == ['A.X0', 'A.X1', 'A.Z0', 'A.Z1']
    assert orientation['any_scanned_endpoint_accepted'] is False
    # CZ symmetry permits a different transport choice; not a path certificate.
    assert example['orientations'][1]['any_scanned_endpoint_accepted'] is True
    assert result['summary']['full_physical_execution_certified'] is False


def test_css_frozen_pairs_match_actual_generator_with_all_repetitions():
    from neutral_atom_experiments.qec_pbc.encoded_resource_reference import build_css_isometry
    encoder = build_css_isometry()
    assert encoder.cnot_network == AUDIT.CSS_PAIRS
    assert len(encoder.isometry_circuit.gates) == 136
    actual = [tuple(int(q[1:]) for q in gate.qubit_ids)
              for gate in encoder.isometry_circuit.gates if gate.gate_type == 'CZ']
    assert tuple(actual) == AUDIT.CSS_PAIRS
    assert len(set(actual)) < len(actual) == 44


@pytest.mark.parametrize('tamper', ['coordinates', 'layer', 'source', 'input'])
def test_tampered_proposal_identity_or_canonical_order_is_rejected(tmp_path, tamper):
    path = fixture_file(tmp_path)
    value = json.loads(path.read_bytes())
    if tamper == 'coordinates':
        value['coordinates_um']['A.d0'][0] += 10
    elif tamper == 'layer':
        value['layers'][0].reverse()
    elif tamper == 'source':
        value['source']['placer_sha256'] = 'wrong'
    else:
        value['seed'] += 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        AUDIT.audit_proposal(path)


def test_cli_preserves_existing_evidence_directory(tmp_path):
    output = tmp_path / 'saved'
    output.mkdir()
    evidence = output / 'audit.json'
    evidence.write_text('earlier counterexamples')
    with pytest.raises(FileExistsError):
        AUDIT.main(['--proposal', str(fixture_file(tmp_path)), '--output', str(output)])
    assert evidence.read_text() == 'earlier counterexamples'
