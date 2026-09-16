from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from neutral_atom_env.domain.models import Position2D, MobileCellIndex
from neutral_atom_app.visualization.studio_config import ALGORITHMS, GENERAL_IMPLEMENTATIONS, DEMOS, demo_input
from neutral_atom_app.visualization.workbench import build_inputs, compile_input, validate_input


def custom(algorithm='greedy'):
    return {'studio': {'mode': 'custom'}, 'circuit_profile': 'physical',
            'compilation': {'strategy': 'legacy', 'implementation': algorithm},
            'atom_count': 2, 'layout': 'grid', 'seed': 7, 'ez_policy': 'adaptive',
            'aod_rows': 1, 'aod_columns': 1,
            'gates': [{'id': 'h', 'gate_type': 'H', 'qubit_ids': ['Q000'], 'column': 0},
                      {'id': 'cz', 'gate_type': 'CZ', 'qubit_ids': ['Q000', 'Q001'], 'column': 1},
                      {'id': 't', 'gate_type': 'T', 'qubit_ids': ['Q001'], 'column': 2}]}


@pytest.mark.parametrize('algorithm', sorted(GENERAL_IMPLEMENTATIONS))
def test_each_general_algorithm_executes_an_ordinary_edited_circuit(algorithm):
    value = custom(algorithm)
    if algorithm in {'ordered_greedy','smt_ordered'}:value['aod_backend']='row_column_orthogonal'
    original = deepcopy(value)
    result, state = compile_input(value)
    assert value == original
    assert result['status'] == 'completed'
    assert state.metrics()['completed_gate_count'] == 3
    assert result['input']['compiler'] == algorithm
    assert result['recording']['atom_statistics']['atoms']['Q001']['gate_counts'] == {'CZ': 1, 'T': 1}


@pytest.mark.parametrize('demo', [d['id'] for d in DEMOS])
def test_demo_is_normalized_repeatable_and_rejects_config_or_circuit_changes(demo):
    value = demo_input(demo)
    assert validate_input(value) == value
    for key, changed in [('seed', value['seed']+1), ('gates', value['gates'][:-1]),
                         ('ez_neighbor_guard_enabled', not value.get('ez_neighbor_guard_enabled', True))]:
        damaged = deepcopy(value); damaged[key] = changed
        with pytest.raises(ValueError, match='locked'):
            validate_input(damaged)
    assert demo_input(demo) == value
    damaged = deepcopy(value)
    damaged['compilation']['compile_timeout_s'] += 1
    with pytest.raises(ValueError, match='locked'):
        validate_input(damaged)


@pytest.mark.parametrize('implementation', ['patch_greedy', 'patch_symmetric', 'row_greedy', 'qec_joint'])
def test_specialized_algorithms_cannot_enter_custom_mode(implementation):
    with pytest.raises(ValueError):
        validate_input(custom(implementation))


def test_custom_rejects_specialized_layout_and_single_trap_rejects_array():
    value = demo_input('surface-ghz'); value['studio'] = {'mode': 'custom'}
    with pytest.raises(ValueError, match='general algorithm'):
        validate_input(value)
    value = custom('returning'); value['aod_columns'] = 2
    with pytest.raises(ValueError, match='Multiple AOD traps'):
        validate_input(value)


def test_aod_offsets_are_relative_and_nonuniform_cartesian():
    value = custom() | {'aod_rows': 2, 'aod_columns': 3,
                        'aod_row_offsets_um': [0, 15], 'aod_column_offsets_um': [0, 10, 30]}
    _, _, platform, _ = build_inputs(value)
    aod = replace(platform.aod, pose=Position2D(20, -30))
    assert aod.position(MobileCellIndex(1, 2)) == Position2D(50, -15)
    assert len({aod.position(MobileCellIndex(r,c)) for r in range(2) for c in range(3)}) == 6
    assert validate_input(value)['compilation_backend']['configuration_error']
    with pytest.raises(ValueError, match='10 μm'):
        compile_input(value)


def test_circuit_only_presets_preserve_configuration_and_prepare_physical_ghz():
    script = Path(__file__).resolve().parents[1] / 'src/neutral_atom_app/visualization/studio_model.js'
    code = "const m=require(process.argv[1]);const d=m.newCustom(require(process.argv[2]));const before=JSON.stringify({...d,gates:null});d.gates=m.circuitPreset('ghz',4);if(JSON.stringify({...d,gates:null})!==before)throw Error('configuration mutated');console.log(JSON.stringify(d.gates));"
    result = subprocess.run(['node', '-e', code, str(script), str(script.parents[3] / 'configs/studio/workbench.json')], capture_output=True, text=True, check=True)
    gates = json.loads(result.stdout)
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    state = StabilizerState.zero(tuple(f'Q{i:03d}' for i in range(4)))
    for g in gates:
        state = state.apply_gate(g['gate_type'], tuple(g['qubit_ids']))
    assert state.expectation({f'Q{i:03d}': 'X' for i in range(4)}) == 1
    for i in range(1, 4):
        assert state.expectation({'Q000': 'Z', f'Q{i:03d}': 'Z'}) == 1


def test_unsupported_geometry_rejected_before_starting_a_worker(tmp_path):
    from neutral_atom_app.visualization.workbench_server import CompileJobs
    jobs = CompileJobs(tmp_path / 'jobs')
    value = custom() | {'aod_columns': 3, 'aod_column_offsets_um': [0, 10, 30]}
    with pytest.raises(ValueError, match='10 μm'):
        jobs.start(value)
    assert not jobs.jobs and jobs.active is None
    assert not jobs.output.exists()
