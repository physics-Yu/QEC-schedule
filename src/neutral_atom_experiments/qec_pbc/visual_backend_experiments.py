"""JSON-ready experiments from real protocol constructors and static audits.

No plotted coordinate is a movement trajectory or proof of Executor validity.
"""
from dataclasses import asdict
from itertools import combinations
from math import hypot

from .backend_contract import (AncillaLifecycle, BackendCapabilities,
    canonical_layer_requests, preflight, validate_aod_rectangle, validate_global_cz_pairs)
from .canonical import canonical_memory_program
from .logical_gadgets import conjugate_sequence, logical_hadamard, transversal_cnot


def _patch(patch):
    return {'id': patch.id, 'orientation': patch.orientation,
        'coordinates': {role: [i % 3, i // 3] for i, role in enumerate(patch.data_roles)},
        'coordinate_units': 'logical_grid_index; not physical micrometres',
        'x_checks': [s.to_dict() for s in patch.x_checks],
        'z_checks': [s.to_dict() for s in patch.z_checks],
        'logical_x': patch.logical_x.to_dict(), 'logical_z': patch.logical_z.to_dict()}


def _pulse_case(name, positions, intended, radius):
    accepted, rejection = True, None
    try:
        actual = validate_global_cz_pairs(positions, intended, radius)
    except ValueError as error:
        accepted, rejection = False, str(error)
        actual = tuple(sorted(tuple(sorted((a, b))) for a, b in combinations(positions, 2)
            if hypot(positions[a][0]-positions[b][0], positions[a][1]-positions[b][1]) <= radius))
    return {'name': name, 'positions': positions, 'coordinate_units': 'micrometres',
        'radius_um': radius, 'intended_pairs': intended, 'actual_pairs': actual,
        'accepted': accepted, 'rejection': rejection,
        'validator': 'backend_contract.validate_global_cz_pairs',
        'claim': 'static exact-pair audit; not support/motion/resource validation or Executor execution'}


def _signed_product(a, b):
    phase, product = a.multiply(b)
    if phase not in (1, -1):
        raise AssertionError('Expected commuting Hermitian product')
    return type(product)(product.factors, int(phase.real))


def backend_experiment_data(*, basis='Z', rounds=3, orientation='standard'):
    """Selectors: basis X/Z, rounds 1 or 3, logical orientation standard/dual."""
    if basis not in {'X', 'Z'} or type(rounds) is not int or rounds not in {1, 3}:
        raise ValueError('Visualization supports basis X/Z and rounds 1 or 3')
    canonical = canonical_memory_program(basis=basis, rounds=rounds)
    bindings = {role.id: role.id for role in canonical.program.roles}
    layers = canonical_layer_requests(canonical, bindings)
    capacity = BackendCapabilities(34, True, True)
    lifecycle = {mode: asdict(preflight(capacity, AncillaLifecycle(9, 8, 4, mode)))
                 for mode in ('reuse', 'fresh')}
    for result in lifecycle.values():
        result['compatible'] = not result['issues']
    pulses = [_pulse_case('spectator_far', {'A': (0, 0), 'B': (4, 0), 'S': (20, 0)},
                          [('A', 'B')], 6),
              _pulse_case('spectator_near', {'A': (0, 0), 'B': (4, 0), 'S': (0, 4)},
                          [('A', 'B')], 6)]
    captures = {(0, 0): 'A', (0, 1): 'spectator', (1, 1): 'B'}
    try:
        validate_aod_rectangle((0, 1), (0, 1), captures, ('A', 'B'))
        rectangle_rejection = None
    except ValueError as error:
        rectangle_rejection = str(error)
    gadget = transversal_cnot('A', 'B', control_orientation=orientation,
                              target_orientation=orientation)
    a, b = gadget.control, gadget.target
    stabilizers = []
    for kind, left, right in (('X', a.x_checks, b.x_checks), ('Z', a.z_checks, b.z_checks)):
        for i, (sa, sb) in enumerate(zip(left, right)):
            for patch, observable, expected in (
                    ('A', sa, _signed_product(sa, sb) if kind == 'X' else sa),
                    ('B', sb, sb if kind == 'X' else _signed_product(sa, sb))):
                actual = conjugate_sequence(observable, gadget.gates)
                stabilizers.append({'id': f'{patch}.{kind}{i}',
                    'input': observable.to_dict(), 'image': actual.to_dict(),
                    'expected_group_member': expected.to_dict(), 'passed': actual == expected})
    h = logical_hadamard('A', orientation=orientation)
    return {'schema': 'qec-backend-visual-experiments/1',
        'selectors': {'basis': basis, 'rounds': rounds, 'orientation': orientation},
        'E2': {'canonical_source': canonical.source_url,
            'coordinate_units': 'canonical logical integer grid; not physical micrometres',
            'role_coordinates': dict(canonical.role_coordinates),
            'layers': [asdict(layer) for layer in layers],
            'lifecycle': {'capacity': 34, 'comparison_rounds': 4, **lifecycle},
            'pulse_cases': pulses,
            'rectangle_case': {'active_rows': [0, 1], 'active_columns': [0, 1],
                'captures': [{'row': r, 'column': c, 'atom': atom} for (r, c), atom in captures.items()],
                'requested_atoms': ['A', 'B'], 'accepted': rectangle_rejection is None,
                'rejection': rectangle_rejection,
                'validator': 'backend_contract.validate_aod_rectangle'},
            'claim': 'protocol coupling layers; actual pulse count and parallel execution unverified'},
        'E3': {'control': _patch(a), 'target': _patch(b),
            'directed_pairs': gadget.coupling.cnot_pairs,
            'logical_images': {name: p.to_dict() for name, p in gadget.logical_images},
            'stabilizer_checks': stabilizers,
            'all_stabilizers_preserved': all(row['passed'] for row in stabilizers),
            'hadamard': {'input_patch': _patch(h.input_patch), 'output_patch': _patch(h.output_patch),
                'logical_images': {name: p.to_dict() for name, p in h.logical_images},
                'boundary_update': h.boundary_update, 'claim': h.claim},
            'claim': gadget.claim}}
