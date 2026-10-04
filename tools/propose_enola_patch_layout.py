"""Propose a d=3 patch's 10 um homes using the unmodified Enola SA placer.

Only the 24 syndrome CZs in the four canonical protocol layers are optimized.
The result is an initial-placement proposal, not routing or physical execution.
No Enola scheduler, code generator, model fidelity, or live Env is called.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from time import perf_counter

from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program


PINNED_COMMIT = '2944dbf4e163e8d2eeeec607add0d9139edce689'
PLACER_RELATIVE_PATH = 'enola/placer/placer.py'
# Independently checked against the author's raw file at the fixed commit.
PLACER_SHA256 = 'd256c84490bd72d525515f24acb081d7b21bcd5f7bbc31302a3bbf79a16997cf'
SOURCE_URL = ('https://raw.githubusercontent.com/UCLA-VAST/Enola/'
              + PINNED_COMMIT + '/' + PLACER_RELATIVE_PATH)
HOME_SPACING_UM = 10.0
SLM_GRID_SPACING_UM = 5.0


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def protocol_input(patch='A'):
    """Preserve the canonical four layers and all repeated pair occurrences."""
    memory = canonical_memory_program(patch=patch, rounds=1)
    roles = [role.id for role in memory.program.roles]
    index = {role: i for i, role in enumerate(roles)}
    layers = []
    for layer_index in range(1, 5):
        pairs = [(index[c.ancilla_role], index[c.data_role])
                 for c in memory.couplings if c.layer_index == layer_index]
        operands = [q for pair in pairs for q in pair]
        if len(pairs) != 6 or len(set(operands)) != 12:
            raise ValueError('Expected six disjoint canonical CZ pairs per layer')
        layers.append(pairs)
    if len(roles) != 17 or len({q for layer in layers for pair in layer for q in pair}) != 17:
        raise ValueError('Expected the complete 9 data / 8 syndrome patch')
    template = memory.to_dict()
    return roles, layers, {
        'template_sha256': _sha(_canonical_bytes(template)),
        'source': template['source'],
        'couplings': template['couplings'],
        'gate_count': 24,
        'scope': 'one canonical syndrome round; CSS encoder excluded',
        'protocol_reordered': False,
    }


def validate_mapping(mapping, width, height):
    if len(mapping) != 17:
        raise ValueError('Placement must contain every one of the 17 roles')
    points = []
    for point in mapping:
        if len(point) != 2 or any(type(v) is not int for v in point):
            raise ValueError('Placement site coordinates must be integer pairs')
        x, y = point
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError('Placement lies outside the declared site rectangle')
        points.append((x, y))
    if len(set(points)) != 17:
        raise ValueError('Placement has overlapping homes')
    return points


def distance_proxy(mapping, layers):
    """Author's initial SA proxy; neither microsecond cost nor fidelity."""
    weighted = sum(max(1.0 - 0.1 * k, 0.1) * math.dist(mapping[a], mapping[b])
                   for k, pairs in enumerate(layers) for a, b in pairs)
    unweighted = sum(math.dist(mapping[a], mapping[b])
                     for pairs in layers for a, b in pairs)
    return {'weighted_site_distance': weighted,
            'unweighted_pair_distance_um': HOME_SPACING_UM * unweighted,
            'weight_rule': 'max(1 - 0.1 * zero_based_layer, 0.1)',
            'physical_execution_time_us': None,
            'fidelity': None}


def _frozen_source(source):
    source = Path(source).resolve()
    placer = source / PLACER_RELATIVE_PATH
    raw = placer.read_bytes()
    if _sha(raw) != PLACER_SHA256:
        raise ValueError('Enola placer bytes differ from the pinned official source')
    commit = None
    if (source / '.git').exists():
        commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                         text=True).strip()
        if commit != PINNED_COMMIT:
            raise ValueError('Enola checkout commit differs from the pinned version')
    return placer, raw, {'upstream': 'https://github.com/UCLA-VAST/Enola',
        'source_url': SOURCE_URL, 'expected_commit': PINNED_COMMIT,
        'checkout_commit': commit, 'source_path': str(source),
        'verification': 'exact official placer bytes; Git commit also checked if checkout',
        'placer_sha256': PLACER_SHA256, 'placer_bytes': len(raw),
        'license': 'BSD-3-Clause; copyright (c) 2024 UCLA VAST Lab',
        'native_source_modified': False}


def _run_native_placer(placer_path, width, height, layers, seed):
    """Load only the author's stdlib placer; restore its import-time RNG seed."""
    rng_before = random.getstate()
    bytecode_before = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('_enola_frozen_patch_sa', placer_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        random.seed(seed)
        log = io.StringIO()
        start = perf_counter()
        with redirect_stdout(log):
            mapping = module.place_qubit((width, height), 17, layers, False)
        elapsed = perf_counter() - start
        return mapping, elapsed, log.getvalue()
    finally:
        random.setstate(rng_before)
        sys.dont_write_bytecode = bytecode_before


def propose_layout(source, *, width=5, height=5, seed=0, patch='A'):
    """Return a reproducible, importable proposal for root's physical compiler."""
    if any(type(v) is not int or v < 1 for v in (width, height)) or width * height < 17:
        raise ValueError('Site rectangle must contain at least 17 homes')
    if type(seed) is not int or seed < 0:
        raise ValueError('Seed must be a nonnegative integer')
    roles, layers, protocol = protocol_input(patch)
    placer, source_before, provenance = _frozen_source(source)
    try:
        mapping, elapsed, log = _run_native_placer(placer, width, height, layers, seed)
    finally:
        if placer.read_bytes() != source_before:
            raise RuntimeError('Enola source changed during the SA call')
    mapping = validate_mapping(mapping, width, height)
    trivial = [(i % width, i // width) for i in range(17)]
    min_spacing = HOME_SPACING_UM * min(math.dist(a, b)
        for i, a in enumerate(mapping) for b in mapping[:i])
    coordinates = {role: [HOME_SPACING_UM * x, HOME_SPACING_UM * y]
                   for role, (x, y) in zip(roles, mapping)}
    grid = {role: [2 * x, 2 * y] for role, (x, y) in zip(roles, mapping)}
    result = {
        'schema': 'enola-single-patch-placement-proposal/1',
        'scope': 'placement proposal only; no routing, Executor, replay, noise or Shor completion',
        'role_order': roles, 'layers': layers, 'protocol': protocol,
        'site_rectangle': [width, height], 'site_coordinates': dict(zip(roles, mapping)),
        'coordinates_um': coordinates, 'slm_grid_coordinates': grid,
        'home_spacing_um': HOME_SPACING_UM, 'slm_grid_spacing_um': SLM_GRID_SPACING_UM,
        'minimum_home_distance_um': min_spacing,
        'seed': seed, 'l2': False, 'method': 'unmodified official place_qubit initial SA',
        'native_placement_wall_seconds': elapsed, 'native_stdout': log,
        'comparison': {'trivial': distance_proxy(trivial, layers),
                       'enola_sa': distance_proxy(mapping, layers)},
        'source': provenance,
        'physical_validation_required': ['finite global CZ pair set', 'AOD Cartesian capture closure',
            'ordered row/column motion', 'continuous atom and empty-trap swept safety',
            'MZ/reset/readout and Raman service', 'original-initial full replay'],
        'adapter_sha256': _sha(Path(__file__).read_bytes()),
    }
    result['input_sha256'] = _sha(_canonical_bytes({'roles': roles, 'layers': layers,
        'template_sha256': protocol['template_sha256'], 'width': width, 'height': height,
        'seed': seed, 'home_spacing_um': HOME_SPACING_UM, 'placer_sha256': PLACER_SHA256}))
    result['placement_sha256'] = _sha(_canonical_bytes(coordinates))
    return result


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--width', type=int, default=5)
    cli.add_argument('--height', type=int, default=5)
    cli.add_argument('--seed', type=int, default=0)
    cli.add_argument('--patch', default='A')
    args = cli.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        result = propose_layout(args.source, width=args.width, height=args.height,
                                seed=args.seed, patch=args.patch)
        status = 'proposal_completed'
    except Exception as error:
        result = {'status': 'proposal_failed', 'error_type': type(error).__name__,
                  'error': str(error), 'physical_execution_completed': False}
        status = result['status']
    (args.output / ('proposal.json' if status == 'proposal_completed' else 'failure.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': status, 'output': str(args.output.resolve()),
                      'comparison': result.get('comparison')}))
    return 0 if status == 'proposal_completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
