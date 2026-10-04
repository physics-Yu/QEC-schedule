"""Canonical matching geometry and real graph-state execution, not pulse mocks."""
from collections import Counter
from dataclasses import replace
from math import hypot
from pathlib import Path
import json

import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.parallel_prefix import load_native_parallel_prefix
from neutral_atom_experiments.qec_pbc.patch_layout import build_interleaved_platform, create_interleaved_environment, create_enola_environment
from neutral_atom_strategies.scheduling.parallel_patch import run_parallel_patch, select_intrapatch_cz_group, select_geometric_cz_group


SOURCE = Path(__file__).resolve().parents[1]/'references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04'
PROPOSAL = SOURCE.parent/'enola_patch_proposal_2026_10_04.json'


@pytest.mark.parametrize('count', (1, 2, 4, 12))
def test_platform_replicates_canonical_geometry_without_changing_native_protocol(count):
    prefix = load_native_parallel_prefix(SOURCE, patch_count=count, include_magic=True)
    before = prefix.circuit_dict()
    platform, placement, meta = build_interleaved_platform(prefix)
    assert prefix.circuit_dict() == before
    assert platform.aod.rows*platform.aod.columns == 9*count
    assert len(placement) == 17*(count+1)
    positions = [platform.world.traps[k].position for k in placement.values()]
    assert min(hypot(a.x_um-b.x_um, a.y_um-b.y_um)
               for i, a in enumerate(positions) for b in positions[i+1:]) >= 10
    assert all(p.x_um % 5 == p.y_um % 5 == 0 for p in positions)
    assert platform.hardware.interaction_distance_um == 6
    assert meta['layout_contract']['protocol_reordered'] is False


def layer_graph(count, layer):
    prefix = load_native_parallel_prefix(SOURCE, patch_count=count)
    binding = dict(prefix.bindings)
    rotations = tuple(PhysicalGate('plus.'+q, 'H', (q,)) for q in binding.values())
    gates = []
    for patch in prefix.patches:
        canonical = canonical_memory_program(patch=patch, rounds=1)
        for pair in canonical.couplings:
            if pair.layer_index == layer:
                gates.append(PhysicalGate(pair.native_cz_id, 'CZ',
                    (binding[pair.control_role], binding[pair.target_role])))
    return replace(prefix, circuit=PhysicalCircuit((*rotations, *gates))), tuple(gates)


@pytest.mark.parametrize('layer,expected', ((1, [6]), (2, [2, 2, 1, 1]),
                                           (3, [2, 2, 1, 1]), (4, [6])))
def test_cartesian_closure_controls_real_intrapatch_graph_state(layer, expected):
    prefix, gates = layer_graph(1, layer)
    env, _, _, meta = create_interleaved_environment(prefix)
    initial, plans = env.snapshot(), []
    result = run_parallel_patch(env, atom_roles=meta['atom_roles'], intra_patch=True,
        on_plan=lambda p, _: plans.append(p), mz_translation_um=-400.)
    assert result.status == 'completed', result.diagnostics
    batches = [row['batch_size'] for row in result.decision_log if row['kind'] == 'CZ']
    assert sorted(batches, reverse=True) == sorted(expected, reverse=True)
    # Independent graph generators for every vertex, including idle auxiliaries.
    neighbors = {q: [] for _, q in prefix.bindings}
    for gate in gates:
        a, b = gate.qubit_ids
        neighbors[a].append(b)
        neighbors[b].append(a)
    for q, adjacent in neighbors.items():
        assert env.state.quantum_state.expectation({q: 'X', **{a: 'Z' for a in adjacent}}) == 1
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()


def test_twelve_patch_frontier_selects_actual_72_disjoint_pairs():
    prefix, gates = layer_graph(12, 1)
    # Pure CZ frontier for grouping checks; no live state or dependency mutation.
    prefix = replace(prefix, circuit=PhysicalCircuit(gates))
    env, _, _, meta = create_interleaved_environment(prefix)
    selected, mobiles = select_intrapatch_cz_group(env.state, gates, meta['atom_roles'])
    assert len(selected) == 72
    assert len(set(mobiles.values())) == 72
    assert Counter(meta['atom_roles'][g.qubit_ids[0]]['patch'] for g in selected) == Counter({p: 6 for p in prefix.patches})


def test_middle_layer_cannot_capture_three_x_checks_as_a_closed_rectangle():
    prefix, gates = layer_graph(1, 2)
    prefix = replace(prefix, circuit=PhysicalCircuit(gates))
    env, _, _, meta = create_interleaved_environment(prefix)
    xgates = tuple(g for g in gates if meta['atom_roles'][g.qubit_ids[0]]['role'].split('.')[-1].startswith('X'))
    selected, mobiles = select_intrapatch_cz_group(env.state, xgates, meta['atom_roles'])
    assert len(xgates) == 3
    assert len(selected) == 2
    assert {meta['atom_roles'][q]['role'].split('.')[-1] for q in mobiles.values()} == {'X1', 'X2'}


@pytest.mark.parametrize('field', ('commit', 'seed', 'layers', 'roles', 'extra_role', 'input_hash', 'grid', 'site'))
def test_proposal_provenance_tampering_is_rejected_before_environment_creation(tmp_path, field):
    prefix = load_native_parallel_prefix(SOURCE, patch_count=1)
    value = json.loads(PROPOSAL.read_bytes())
    if field == 'commit': value['source']['expected_commit'] = '0'*40
    elif field == 'seed': value['seed'] += 1
    elif field == 'layers': value['layers'][0].reverse()
    elif field == 'roles': value['role_order'].reverse()
    elif field == 'extra_role': value['coordinates_um']['extra.d0'] = [0, 0]
    elif field == 'input_hash': value['input_sha256'] = '0'*64
    elif field == 'grid': value['site_rectangle'] = [7, 7]
    else: value['site_coordinates'][value['role_order'][0]] = [0, 0]
    path = tmp_path/'proposal.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='Proposal|proposal|Unsupported'):
        create_enola_environment(prefix, path)


@pytest.mark.parametrize('layer', (1, 2, 3, 4))
def test_enola_layout_layer_executes_with_finite_pairs_and_graph_oracle(layer):
    prefix, gates = layer_graph(1, layer)
    env, _, _, meta = create_enola_environment(prefix, PROPOSAL)
    initial, plans = env.snapshot(), []
    result = run_parallel_patch(env, atom_roles=meta['atom_roles'], intra_patch=True, pair_search=True,
        on_plan=lambda p, _: plans.append(p), mz_translation_um=-400.)
    assert result.status == 'completed', result.diagnostics
    neighbors = {q: [] for _, q in prefix.bindings}
    for gate in gates:
        a, b = gate.qubit_ids
        neighbors[a].append(b)
        neighbors[b].append(a)
    for q, adjacent in neighbors.items():
        assert env.state.quantum_state.expectation({q: 'X', **{a: 'Z' for a in adjacent}}) == 1
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()


def test_dense_sa_css_gate_changes_moving_operand_instead_of_relaxing_spacing():
    prefix = load_native_parallel_prefix(SOURCE, patch_count=1)
    gate = next(g for g in prefix.circuit.gates if g.id.endswith('encode.cx19.cz'))
    prefix = replace(prefix, circuit=PhysicalCircuit((replace(gate, depends_on=()),)))
    env, _, _, meta = create_enola_environment(prefix, PROPOSAL)
    selected, moving, offset = select_geometric_cz_group(env.state, env.state.dag.ready_gates(), meta['atom_roles'])
    assert len(selected) == 1
    assert moving[gate.id] == gate.qubit_ids[0]
    assert hypot(offset.x_um, offset.y_um) <= 6
