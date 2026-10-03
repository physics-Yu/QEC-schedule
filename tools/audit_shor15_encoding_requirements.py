"""Read the actual logical PBC export and inventory encoded-backend needs.

This is a read-only resource/observable audit, not a physical compiler or an
estimate of the number of simultaneous magic-state patches.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def inventory(program):
    if program.get('schema') != 'adaptive-pauli-resource-v1':
        raise ValueError('An adaptive-pauli-resource-v1 export is required')
    wires = tuple(program['wires'])
    injections = program['injections']
    data_bases, data_weights, joint_bases, joint_weights = (Counter() for _ in range(4))
    representative_weights = Counter()
    contains_y = mixed_joint = shape_compatible = 0
    for item in injections:
        data = item['rotation']['observable']['factors']
        joint = item['operations'][1]['observable']['factors']
        resource = item['resource']['wire']
        if (any(w not in wires or b not in ('X', 'Y', 'Z') for w, b in data)
                or len({w for w, _ in data}) != len(data)
                or len(joint) != len(data) + 1
                or len({w for w, _ in joint}) != len(joint)
                or dict(joint) != dict((*data, (resource, 'Z')))
                or resource in wires):
            raise ValueError('Observable/resource support is inconsistent')
        bases = ''.join(sorted({b for _, b in data}))
        joint_basis = ''.join(sorted({b for _, b in joint}))
        data_bases[bases] += 1
        data_weights[len(data)] += 1
        joint_bases[joint_basis] += 1
        joint_weights[len(joint)] += 1
        # Project canonical logical X/Z representatives have weight three;
        # Y=iXZ has weight five. Distinct patches have disjoint data roles.
        representative_weights[3 + sum(5 if b == 'Y' else 3 for _, b in data)] += 1
        contains_y += 'Y' in joint_basis
        mixed_joint += len(joint_basis) > 1
        shape_compatible += len(joint) == 2 and joint_basis in ('X', 'Z')
    return {
        'schema': 'shor15-encoding-requirements/1',
        'scope': 'Observable inventory of the supplied logical export; no encoded or physical execution',
        'logical_data_wires': len(wires), 'resource_consumptions_per_shot': len(injections),
        'data_basis_classes': dict(sorted(data_bases.items())),
        'data_weights': dict(sorted(data_weights.items())),
        'joint_basis_classes': dict(sorted(joint_bases.items())),
        'joint_weights': dict(sorted(joint_weights.items())),
        'joint_measurements_containing_y': contains_y,
        'joint_measurements_with_mixed_bases': mixed_joint,
        'max_joint_weight': max(joint_weights, default=0),
        'fixed_canonical_representative_joint_weights': dict(sorted(representative_weights.items())),
        'max_fixed_canonical_representative_joint_weight': max(representative_weights, default=0),
        'representative_weight_scope': 'Project fixed weight-3 X/Z and weight-5 Y logical strings; '
            'observable support only, not a verified cat circuit or FT resource estimate',
        'two_patch_homogeneous_shape_count': shape_compatible,
        'shape_compatibility_definition': 'Support size two and homogeneous X/Z only; '
            'this does not supply an encoded magic state or prove executability',
        'd3_base_algorithm_atoms': 17 * len(wires),
        'physical_atom_peak': None, 'magic_patch_peak': None,
        'missing_backend_capabilities': [
            'Nondestructive arbitrary mixed/Y Pauli-product measurement',
            'Executable encoded conditional S_P/Sdg_P and Pauli feedback',
            'Encoded magic preparation, consumption and error model',
            'Quantum reference tracking for non-Clifford encoded resources',
            'Full algorithm patch/ancilla schedule, decoding and physical replay'],
        'full_shor_encoded': False, 'full_shor_physical_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inventory(json.loads(args.input.read_text(encoding='utf-8')))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
