"""Independently audit finite-CZ endpoints and Cartesian capture of SA homes.

Static candidate checks only: no gate timing, motion path, holder transitions,
SLM illumination, measurement, Executor or independent physical replay.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


CZ_RANGE_UM = 6.0
NONPAIR_CLEARANCE_UM = 10.0
MIN_PAIR_SEPARATION_UM = 1.0
TOLERANCE_UM = 1e-9
OFFSETS = ((-3., 0.), (3., 0.), (0., -3.), (0., 3.),
           (-3., -3.), (-3., 3.), (3., -3.), (3., 3.))
CANONICAL_PAIRS = (
    ((9, 3), (10, 7), (11, 1), (13, 4), (14, 6), (16, 8)),
    ((9, 4), (10, 8), (11, 2), (13, 1), (14, 3), (16, 5)),
    ((9, 0), (10, 4), (12, 6), (13, 5), (14, 7), (15, 3)),
    ((9, 1), (10, 5), (12, 7), (13, 2), (14, 4), (15, 0)),
)
PINNED_PLACER_SHA256 = 'd256c84490bd72d525515f24acb081d7b21bcd5f7bbc31302a3bbf79a16997cf'
CSS_SOURCE_PATH = 'src/neutral_atom_experiments/qec_pbc/encoded_resource_reference.py'
CSS_SOURCE_SHA256 = 'c903a1753b2d7963beb7e720f3aa2bbcbb984df3cd83ec32cd332d2c4e05acce'
# Exact native CZ occurrences from the frozen build_css_isometry source.
# Repeated pairs and their original cx indices are deliberately retained.
CSS_PAIRS = (
    (8, 6), (8, 4), (8, 2), (8, 1), (8, 0), (7, 5), (7, 4), (7, 0),
    (6, 8), (6, 4), (6, 2), (6, 1), (6, 0), (5, 7), (5, 4), (5, 0),
    (6, 5), (5, 6), (6, 5), (4, 7), (6, 4), (4, 6), (6, 4), (3, 8),
    (3, 7), (3, 6), (3, 5), (3, 2), (3, 1), (3, 0), (4, 3), (3, 4),
    (4, 3), (2, 8), (2, 7), (2, 5), (4, 2), (2, 4), (4, 2), (1, 6),
    (1, 4), (1, 0), (0, 6), (0, 3),
)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def endpoint_check(homes, intended_pairs, offsets):
    """Move only specified ancillas; enumerate every pair of all atoms."""
    if not intended_pairs or len(intended_pairs) != len(offsets):
        raise ValueError('Each intended pair requires one candidate offset')
    wires = [q for pair in intended_pairs for q in pair]
    if len(wires) != len(set(wires)) or any(q not in homes for q in wires):
        raise ValueError('Intended pairs require distinct, known operands')
    if any(len(offset) != 2 or any(not math.isfinite(v) for v in offset)
           or not MIN_PAIR_SEPARATION_UM <= math.hypot(*offset) <= CZ_RANGE_UM
           for offset in offsets):
        raise ValueError('Candidate offset must remain inside finite CZ range')
    intended = {tuple(sorted(pair)) for pair in intended_pairs}
    endpoints = dict(homes)
    for (ancilla, data), offset in zip(intended_pairs, offsets):
        endpoints[ancilla] = (homes[data][0] + offset[0], homes[data][1] + offset[1])
    actual, nonpairs, desired = [], [], []
    roles = sorted(endpoints)
    for i, a in enumerate(roles):
        for b in roles[:i]:
            pair = tuple(sorted((a, b)))
            distance = math.dist(endpoints[a], endpoints[b])
            if distance <= CZ_RANGE_UM + TOLERANCE_UM:
                actual.append(pair)
            (desired if pair in intended else nonpairs).append((distance, pair))
    exact_pairs = set(actual) == intended
    minimum_nonpair, closest_nonpair = min(nonpairs)
    minimum_pair = min(distance for distance, pair in desired)
    clearance = minimum_nonpair >= NONPAIR_CLEARANCE_UM - TOLERANCE_UM
    separation = minimum_pair >= MIN_PAIR_SEPARATION_UM - TOLERANCE_UM
    return {'offsets_um': offsets, 'endpoint_accepted': exact_pairs and clearance and separation,
        'global_exact_cz_pairs': exact_pairs, 'nonpair_clearance_ge_10um': clearance,
        'intended_pair_separation_ge_1um': separation,
        'minimum_nonpair_distance_um': minimum_nonpair,
        'closest_nonpair': closest_nonpair, 'minimum_intended_pair_distance_um': minimum_pair,
        'actual_pairs': actual, 'unintended_pairs': sorted(set(actual) - intended),
        'missing_pairs': sorted(intended - set(actual)),
        'mobile_endpoints_um': {a: endpoints[a] for a, d in intended_pairs}}


def cartesian_capture(homes, mobiles):
    """Closure of selected source axes; every aligned spectator is retained."""
    xs = sorted({homes[q][0] for q in mobiles})
    ys = sorted({homes[q][1] for q in mobiles})
    captured = sorted(q for q, (x, y) in homes.items() if x in xs and y in ys)
    extra = sorted(set(captured) - set(mobiles))
    def fits_axis_3_pitch20(axis):
        return max(axis) - min(axis) <= 40 + TOLERANCE_UM and all(
            abs((v - axis[0]) / 20 - round((v - axis[0]) / 20)) < TOLERANCE_UM for v in axis)
    return {'source_x_axes_um': xs, 'source_y_axes_um': ys,
        'active_rectangle': [len(ys), len(xs)],
        'active_intersections': len(xs) * len(ys),
        'requested_mobiles': list(mobiles), 'actual_capture_closure': captured,
        'extra_captured_atoms': extra, 'extra_captured_count': len(extra),
        'requested_only_capture': not extra,
        'fits_3_by_3_uniform_20um_axes': fits_axis_3_pitch20(xs) and fits_axis_3_pitch20(ys)}


def movement_shape(homes, pairs, candidate):
    ends = candidate['mobile_endpoints_um']
    shifts = {(ends[a][0] - homes[a][0], ends[a][1] - homes[a][1]) for a, d in pairs}
    violations = []
    for axis in (0, 1):
        by_source = {}
        for a, d in pairs:
            by_source.setdefault(homes[a][axis], set()).add(ends[a][axis])
        if any(len(values) != 1 for values in by_source.values()):
            violations.append({'axis': 'x' if axis == 0 else 'y', 'reason': 'one source axis has multiple destinations'})
            continue
        ordered = [next(iter(by_source[src])) for src in sorted(by_source)]
        if any(a >= b for a, b in zip(ordered, ordered[1:])):
            violations.append({'axis': 'x' if axis == 0 else 'y', 'reason': 'axis order crosses or merges'})
    return {'shared_rigid_shift': len(shifts) == 1,
        'shifts_um': sorted(shifts), 'ordered_row_column_embedding': not violations,
        'axis_violations': violations,
        'scope': 'source/destination axis consistency only; no continuous path or full capture validation'}


def four_neighbor_obstruction(homes, ancilla, data):
    """Analytical necessary radius when four unmoved axis neighbours remain."""
    center = homes[data]
    neighbors = []
    for offset in ((10, 0), (-10, 0), (0, 10), (0, -10)):
        point = (center[0] + offset[0], center[1] + offset[1])
        found = [q for q, p in homes.items() if q not in (ancilla, data) and math.dist(p, point) <= TOLERANCE_UM]
        if not found:
            return None
        neighbors.append(found[0])
    return {'unmoved_neighbors': neighbors,
        'necessary_nonzero_target_radius_um': math.sqrt(2) * NONPAIR_CLEARANCE_UM,
        'available_cz_radius_um': CZ_RANGE_UM,
        'impossible_for_any_nonzero_offset_within_cz_range': True,
        'derivation': '|x|,|y| <= r^2/(2s) implies r^2 >= 2s^2 for r>0; s=10um, r<=6um'}


def css_encoder_endpoint_audit(homes, roles):
    """Check fixed qubit_ids[1] mobility, also report the symmetric CZ option."""
    source = Path(__file__).resolve().parents[1] / CSS_SOURCE_PATH
    raw = source.read_bytes()
    normalized = source.read_text(encoding='utf-8').replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')
    if _sha(normalized) != CSS_SOURCE_SHA256:
        raise ValueError('Frozen CSS source changed; review the independent native pair snapshot')
    rows = []
    for index, (control, target) in enumerate(CSS_PAIRS):
        orientations = []
        for moving, anchor, name in ((roles[target], roles[control], 'fixed_second_operand_mobile'),
                                     (roles[control], roles[target], 'flipped_mobile_operand')):
            candidates = [endpoint_check(homes, [(moving, anchor)], [offset]) for offset in OFFSETS]
            orientations.append({'orientation': name, 'moving_role': moving,
                'fixed_anchor_role': anchor, 'candidates': candidates,
                'any_scanned_endpoint_accepted': any(c['endpoint_accepted'] for c in candidates),
                'analytical_obstruction': four_neighbor_obstruction(homes, moving, anchor)})
        rows.append({'native_cz_suffix': f'encode.cx{index}.cz', 'cx_index': index,
            'authored_pair': [roles[control], roles[target]], 'orientations': orientations,
            'fixed_second_mobile_scanned_solution': orientations[0]['any_scanned_endpoint_accepted'],
            'either_mobile_scanned_solution': any(o['any_scanned_endpoint_accepted'] for o in orientations)})
    return {'source_path': CSS_SOURCE_PATH, 'source_raw_sha256': _sha(raw),
        'source_utf8_lf_sha256': _sha(normalized), 'generator': 'build_css_isometry',
        'native_cz_count': 44, 'native_isometry_gate_count': 136,
        'duplicate_pair_occurrences_preserved': True, 'gates': rows,
        'fixed_second_mobile_scanned_solution_count': sum(r['fixed_second_mobile_scanned_solution'] for r in rows),
        'either_mobile_scanned_solution_count': sum(r['either_mobile_scanned_solution'] for r in rows),
        'fixed_second_mobile_analytic_obstruction_indices': [r['cx_index'] for r in rows
            if r['orientations'][0]['analytical_obstruction'] is not None],
        'scope': 'all 44 original CSS CZs, both mobile choices, spectators unmoved; no transport proof'}


def _validate_proposal(proposal):
    if proposal.get('schema') != 'enola-single-patch-placement-proposal/1':
        raise ValueError('Unknown proposal schema')
    roles = proposal['role_order']
    if len(roles) != 17 or len(set(roles)) != 17:
        raise ValueError('Missing or duplicated role identity')
    prefix = roles[0].rsplit('.', 1)[0]
    expected_roles = [f'{prefix}.d{i}' for i in range(9)] + [f'{prefix}.{b}{i}' for b in ('X', 'Z') for i in range(4)]
    if roles != expected_roles:
        raise ValueError('Role ordering differs from the declared canonical patch')
    if proposal['layers'] != [[list(pair) for pair in layer] for layer in CANONICAL_PAIRS]:
        raise ValueError('Canonical hook layers changed')
    coordinates = proposal['coordinates_um']
    if set(coordinates) != set(roles) or _sha(_json_bytes(coordinates)) != proposal['placement_sha256']:
        raise ValueError('Placement identity hash changed')
    if proposal['home_spacing_um'] != 10 or proposal['slm_grid_spacing_um'] != 5:
        raise ValueError('Unexpected source spacing')
    source = proposal['source']
    if source['expected_commit'] != '2944dbf4e163e8d2eeeec607add0d9139edce689' or source['placer_sha256'] != PINNED_PLACER_SHA256:
        raise ValueError('Unexpected author source identity')
    if proposal['protocol']['source']['commit'] != '42e0b9e099180e8570407c33f87b4683cac00d81':
        raise ValueError('Unexpected canonical protocol source')
    original_input = {'roles': roles, 'layers': proposal['layers'],
        'template_sha256': proposal['protocol']['template_sha256'],
        'width': proposal['site_rectangle'][0], 'height': proposal['site_rectangle'][1],
        'seed': proposal['seed'], 'home_spacing_um': 10.0, 'placer_sha256': PINNED_PLACER_SHA256}
    if _sha(_json_bytes(original_input)) != proposal['input_sha256']:
        raise ValueError('Proposal input identity hash changed')
    sites = proposal['site_coordinates']
    for q, position in coordinates.items():
        if len(position) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in position):
            raise ValueError('Invalid physical coordinates')
        if position != [10 * v for v in sites[q]]:
            raise ValueError('Source physical coordinates differ from the declared SA sites')
    return roles


def audit_proposal(path, *, scale=1):
    if scale not in (1, 2) or type(scale) is not int:
        raise ValueError('Only original 10um sites or explicit scaled20um candidate is supported')
    path = Path(path)
    raw = path.read_bytes()
    proposal = json.loads(raw)
    roles = _validate_proposal(proposal)
    homes = {q: tuple(scale * v for v in xy) for q, xy in proposal['coordinates_um'].items()}
    min_home = min(math.dist(a, b) for i, a in enumerate(homes.values()) for b in list(homes.values())[:i])
    if min_home < 10 - TOLERANCE_UM:
        raise ValueError('Initial nonpair home clearance is insufficient')
    singles, layers = [], []
    for layer_index, indexed in enumerate(CANONICAL_PAIRS, 1):
        pairs = [(roles[a], roles[d]) for a, d in indexed]
        for a, d in pairs:
            candidates = [endpoint_check(homes, [(a, d)], [offset]) for offset in OFFSETS]
            singles.append({'layer': layer_index, 'ancilla': a, 'data': d,
                'any_scanned_endpoint_accepted': any(c['endpoint_accepted'] for c in candidates),
                'candidates': candidates, 'analytical_obstruction': four_neighbor_obstruction(homes, a, d)})
        groups = [('all6', pairs), ('X3', [pair for pair in pairs if '.X' in pair[0]]),
                  ('Z3', [pair for pair in pairs if '.Z' in pair[0]])]
        for name, group in groups:
            inward = []
            for a, d in group:
                direction = (homes[a][0] - homes[d][0], homes[a][1] - homes[d][1])
                norm = math.hypot(*direction)
                inward.append(tuple(3 * v / norm for v in direction))
            candidates = [endpoint_check(homes, group, [offset] * len(group)) for offset in OFFSETS]
            toward_home = endpoint_check(homes, group, inward)
            toward_home['movement_shape'] = movement_shape(homes, group, toward_home)
            capture = cartesian_capture(homes, [a for a, d in group])
            layers.append({'layer': layer_index, 'group': name, 'pairs': group,
                'capture': capture, 'uniform_offset_candidates': candidates,
                'toward_vacated_home_candidate': toward_home,
                'source_and_endpoint_candidate_accepted': capture['requested_only_capture']
                    and capture['fits_3_by_3_uniform_20um_axes'] and toward_home['endpoint_accepted']
                    and toward_home['movement_shape']['shared_rigid_shift'],
                'full_physical_execution_certified': False})
    css = css_encoder_endpoint_audit(homes, roles)
    return {'schema': 'enola-patch-endpoint-capture-audit/1',
        'scope': 'static all-pair endpoints and source Cartesian closure; not an ENV execution or path proof',
        'proposal_path': str(path.resolve()), 'proposal_sha256': _sha(raw),
        'source_placement_sha256': proposal['placement_sha256'],
        'source_input_sha256': proposal['input_sha256'], 'source': proposal['source'],
        'scale': scale, 'site_pitch_um': scale * 10., 'minimum_home_distance_um': min_home,
        'derived_candidate_changes_original_10um_layout': scale != 1,
        'parameters': {'cz_range_um': CZ_RANGE_UM, 'nonpair_clearance_um': NONPAIR_CLEARANCE_UM,
            'minimum_pair_separation_um': MIN_PAIR_SEPARATION_UM, 'numeric_tolerance_um': TOLERANCE_UM},
        'singles': singles, 'layer_groups': layers, 'css_encoder': css,
        'summary': {'single_couplings_with_scanned_solution': sum(s['any_scanned_endpoint_accepted'] for s in singles),
            'single_couplings_total': len(singles),
            'single_couplings_fixed_minus3x_accepted': sum(s['candidates'][0]['endpoint_accepted'] for s in singles),
            'all6_source_capture_accepted': sum(r['capture']['requested_only_capture'] for r in layers if r['group'] == 'all6'),
            'X3_Z3_source_and_endpoint_accepted': sum(r['source_and_endpoint_candidate_accepted'] for r in layers if r['group'] != 'all6'),
            'css_fixed_second_mobile_scanned_solutions': css['fixed_second_mobile_scanned_solution_count'],
            'css_either_mobile_scanned_solutions': css['either_mobile_scanned_solution_count'],
            'css_fixed_second_mobile_analytic_obstructions': len(css['fixed_second_mobile_analytic_obstruction_indices']),
            'full_prefix_fixed_second_mobile_endpoint_screen_passed': css['fixed_second_mobile_scanned_solution_count'] == 44,
            'full_physical_execution_certified': False},
        'auditor_sha256': _sha(Path(__file__).read_bytes())}


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--proposal', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--scale', type=int, choices=(1, 2), default=1)
    args = cli.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    result = audit_proposal(args.proposal, scale=args.scale)
    (args.output / 'audit.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'scale': args.scale, 'summary': result['summary']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
