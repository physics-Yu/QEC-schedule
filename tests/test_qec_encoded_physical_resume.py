"""Strict checkpoint continuation of real encoded physical execution."""
import json
import shutil

import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_experiments.qec_pbc.encoded_physical import execute_encoded_parity
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program


@pytest.fixture(scope='module')
def interrupted(tmp_path_factory):
    directory = tmp_path_factory.mktemp('encoded-resume-prefix')
    protocol = encoded_parity_program(basis='X', rounds=1)
    evidence = execute_encoded_parity(protocol, directory/'prefix', seed=7, wall_budget_s=1e-12)
    assert evidence['status'] == 'failed' and evidence['plans'] > 0
    return protocol, directory/'prefix', directory


@pytest.mark.parametrize('filename', ('compiled.json', 'platform.json', 'protocol.json'))
def test_resume_rejects_changed_experiment_before_output_creation(interrupted, filename):
    protocol, prefix, directory = interrupted
    corrupted = directory/f'changed-{filename}'
    shutil.copytree(prefix, corrupted)
    data = json.loads((corrupted/filename).read_text(encoding='utf-8'))
    data['unapproved_input_change'] = True
    (corrupted/filename).write_text(json.dumps(data), encoding='utf-8')
    output = directory/f'rejected-{filename}'
    with pytest.raises(ValueError, match='differs from current experiment'):
        execute_encoded_parity(protocol, output, seed=7, resume_from=corrupted)
    assert not output.exists()


def test_resume_rejects_different_seed(interrupted):
    protocol, prefix, directory = interrupted
    with pytest.raises(ValueError, match='initial checkpoint'):
        execute_encoded_parity(protocol, directory/'wrong-seed', seed=8, resume_from=prefix)


def test_resume_rejects_same_id_operation_tampering_before_continuation(interrupted):
    protocol, prefix, directory = interrupted
    corrupted = directory/'same-id-modified-operation'
    shutil.copytree(prefix, corrupted)
    plans = json.loads((corrupted/'plans.json').read_text(encoding='utf-8'))
    original_id = plans[0]['id']
    plans[0]['operations'][0]['duration_us'] += 1
    assert plans[0]['id'] == original_id
    (corrupted/'plans.json').write_text(json.dumps(plans), encoding='utf-8')
    output = directory/'rejected-same-id-tampering'
    with pytest.raises(ValueError, match='plan contents differ'):
        execute_encoded_parity(protocol, output, seed=7, resume_from=corrupted)
    assert not output.exists()


def test_unstarted_tail_requires_exact_pending_plan_contents(interrupted):
    protocol, prefix, directory = interrupted
    queued = directory/'queued-unstarted-plan'
    shutil.copytree(prefix, queued)
    plans = json.loads((queued/'plans.json').read_text(encoding='utf-8'))
    env = NeutralAtomEnv.restore((queued/'initial.json').read_text(encoding='utf-8'))
    env.submit(plan_from_dict(plans[0]))
    assert env.pending and not env.state.trace.records
    (queued/'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    accepted = execute_encoded_parity(protocol, directory/'queued-resume', seed=7,
                                      wall_budget_s=1e-12, resume_from=queued)
    assert accepted['error']['type'] == 'TimeoutError'
    assert accepted['audit']['independent_plan_replay_equal']
    plans[0]['operations'][0]['duration_us'] += 1
    (queued/'plans.json').write_text(json.dumps(plans), encoding='utf-8')
    with pytest.raises(ValueError, match='pending PLAN_STARTED'):
        execute_encoded_parity(protocol, directory/'queued-modified-plan', seed=7, resume_from=queued)


def test_pending_accepted_plan_continues_without_resubmission(interrupted):
    protocol, prefix, directory = interrupted
    output = directory/'second-interruption'
    evidence = execute_encoded_parity(protocol, output, seed=7, wall_budget_s=1e-12,
                                      resume_from=prefix)
    assert evidence['status'] == 'failed' and evidence['error']['type'] == 'TimeoutError'
    assert evidence['plans'] == evidence['resume']['inherited_accepted_plans'] == 1
    assert evidence['audit']['independent_plan_replay_equal']
    assert evidence['recording_scope'] == 'complete_committed_prefix_from_original_initial'
    checkpoint = json.loads((output/'checkpoint.json').read_text(encoding='utf-8'))
    previous = json.loads((prefix/'checkpoint.json').read_text(encoding='utf-8'))
    assert checkpoint['version'] > previous['version']
    assert checkpoint['time_us'] >= previous['time_us']
    assert (output/'initial.json').read_text(encoding='utf-8') == (prefix/'initial.json').read_text(encoding='utf-8')
    assert json.loads((output/'recording.json').read_text(encoding='utf-8'))['frames'][0]['time'] == 0


def test_real_mid_plan_resume_matches_uninterrupted_low_round_execution(tmp_path):
    protocol = encoded_parity_program(basis='X', rounds=1)
    def interrupt_after_preparation(row):
        if row['completed_gates'] >= 60:
            raise TimeoutError('Injected mid-plan timeout after initial native preparation operations')
    prefix_dir = tmp_path/'prepared-prefix'
    failed = execute_encoded_parity(protocol, prefix_dir, seed=7, wall_budget_s=1800,
                                    progress=interrupt_after_preparation)
    assert failed['status'] == 'failed' and failed['error']['type'] == 'TimeoutError'
    assert failed['metrics']['completed_gate_count'] >= 60
    assert not failed['schedule_complete']
    checkpoint = json.loads((prefix_dir/'checkpoint.json').read_text(encoding='utf-8'))
    assert checkpoint['event_queue']['pending']
    resumed_dir, complete_dir = tmp_path/'resumed', tmp_path/'uninterrupted'
    resumed = execute_encoded_parity(protocol, resumed_dir, seed=7, wall_budget_s=1800,
                                     resume_from=prefix_dir)
    complete = execute_encoded_parity(protocol, complete_dir, seed=7, wall_budget_s=1800)
    assert resumed['status'] == 'completed', resumed['error']
    assert complete['status'] == 'completed', complete['error']
    assert resumed['resume']['inherited_completed_gates'] >= 60
    assert resumed['resume']['inherited_pending_events'] > 0
    assert resumed['resume']['inherited_simulation_time_us'] > 0
    assert resumed['plans'] == complete['plans']
    assert resumed['metrics'] == complete['metrics']
    assert resumed['recording_scope'] == 'complete_committed_prefix_from_original_initial'
    for key in ('terminal_verified', 'event_queue_empty', 'effects_exactly_once',
                'reference_state_equal', 'independent_plan_replay_equal',
                'retained_output_coherence_verified', 'dependency_timing_verified'):
        assert resumed['audit'][key] and complete['audit'][key]
    assert (resumed_dir/'initial.json').read_text(encoding='utf-8') == (prefix_dir/'initial.json').read_text(encoding='utf-8')
    assert (resumed_dir/'checkpoint.json').read_text(encoding='utf-8') == (complete_dir/'checkpoint.json').read_text(encoding='utf-8')
    recording = json.loads((resumed_dir/'recording.json').read_text(encoding='utf-8'))
    assert recording['frames'][0]['time'] == 0
    final_checkpoint = json.loads((resumed_dir/'checkpoint.json').read_text(encoding='utf-8'))
    assert recording['frames'][-1]['time'] == final_checkpoint['time_us']
    assert recording['frames'][-1]['time'] > checkpoint['time_us']
    metadata = json.loads((resumed_dir/'run_metadata.json').read_text(encoding='utf-8'))
    assert metadata['resume']['prefix_directory'] == str(prefix_dir.resolve())
    assert (prefix_dir/'evidence.json').is_file()
