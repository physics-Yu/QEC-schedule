"""Independent signed stabilizer/isometry check for arbitrary encoder seeds."""
from .semantic_common import conjugate, multiply
from na_pipeline.qec.surface17 import CHECKS, LOGICAL_X, LOGICAL_Z


def certify_encoder(recipe):
    def span(gs):
        group = {(0, 0, 0)}
        for g in gs:
            group |= {multiply(p, g) for p in list(group)}
        return group
    def p(indices, axis):
        n = sum(1 << i for i in indices)
        return (n, 0, 0) if axis == 'X' else (0, n, 0)
    seed = int(recipe['seed'][1:]); plus = [int(q[1:]) for q in recipe['plus_inputs']]; zero = [int(q[1:]) for q in recipe['zero_inputs']]
    if sorted([seed, *plus, *zero]) != list(range(9)):
        raise ValueError('ENCODER_INPUT_PARTITION')
    def image(pauli):
        for c, t in recipe['cx']:
            pauli = conjugate(pauli, 'CX', [c, t])
        return pauli
    desired = span([p(s, b) for _, b, s, _ in CHECKS])
    actual = span([image(p([i], 'X')) for i in plus] + [image(p([i], 'Z')) for i in zero])
    lx, lz = p(LOGICAL_X, 'X'), p(LOGICAL_Z, 'Z')
    x, z = p([seed], 'X'), p([seed], 'Z')
    # Y = i X Z, including its sign, for arbitrary coherent seed amplitudes.
    def y(a, b):
        v = multiply(a, b)
        return (*v[:2], (v[2] + 1) % 4)
    maps = {axis: {'image': image(a), 'target': b, 'signed_coset_passed': multiply(image(a), b) in desired}
            for axis, a, b in [('X', x, lx), ('Z', z, lz), ('Y', y(x, z), y(lx, lz))]}
    passed = len(desired) == 256 and actual == desired and all(m['signed_coset_passed'] for m in maps.values())
    return {'schema_version': 'SignedEncoderIsometry/0.1', 'passed': passed,
            'stabilizer_group_equal': actual == desired, 'signed_logical_maps': maps,
            'arbitrary_seed': True, 'quantum_state_simulated': False, 'fault_tolerance_claimed': False}
