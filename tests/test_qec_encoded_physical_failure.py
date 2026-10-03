"""Failure evidence survives an incomplete accepted-plan timing export."""
import json
from types import SimpleNamespace

from neutral_atom_experiments.qec_pbc import encoded_physical
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program


def test_schedule_export_error_keeps_original_failure_and_checkpoint(monkeypatch, tmp_path):
    def reject_run(*args, **kwargs):
        return SimpleNamespace(status='rejected', diagnostics=('injected planner rejection',),
                               candidate_rejections=(), decision_log=())
    def incomplete_schedule(*args, **kwargs):
        raise ValueError('Plan/trace operation boundary mismatch: interrupted accepted plan')
    monkeypatch.setattr(encoded_physical, 'run_qec_sparse', reject_run)
    monkeypatch.setattr(encoded_physical, 'operation_schedule', incomplete_schedule)
    output = tmp_path/'failed-prefix'
    evidence = encoded_physical.execute_encoded_parity(encoded_parity_program(rounds=1), output)
    assert evidence['status'] == 'failed'
    assert 'injected planner rejection' in evidence['error']['message']
    assert not evidence['schedule_complete']
    assert evidence['physical_pulse_count'] is None and evidence['max_parallel_cz'] is None
    assert evidence['audit']['schedule_export_error']['type'] == 'ValueError'
    assert evidence['audit']['independent_plan_replay_equal']
    for filename in ('initial.json', 'checkpoint.json', 'trace.jsonl', 'recording.json',
                     'animation.html', 'evidence.json', 'plans.json', 'schedule.json'):
        assert (output/filename).is_file()
    assert json.loads((output/'evidence.json').read_text())['status'] == 'failed'
    assert json.loads((output/'schedule.json').read_text()) == []


def test_real_interrupted_accepted_plan_exports_prefix_without_complete_schedule(tmp_path):
    output = tmp_path/'interrupted-prefix'
    evidence = encoded_physical.execute_encoded_parity(
        encoded_parity_program(rounds=1), output, wall_budget_s=1e-12)
    assert evidence['status'] == 'failed'
    assert evidence['error']['type'] == 'TimeoutError'
    assert evidence['plans'] > 0
    assert not evidence['schedule_complete']
    assert evidence['physical_pulse_count'] is None
    assert evidence['audit']['schedule_export_error']['type'] == 'ValueError'
    assert (output/'checkpoint.json').read_text() != (output/'initial.json').read_text()
    assert (output/'trace.jsonl').stat().st_size > 0
    assert json.loads((output/'plans.json').read_text())
    assert json.loads((output/'evidence.json').read_text())['error']['type'] == 'TimeoutError'
