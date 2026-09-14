"""Independent expectations for M4 benchmark fairness and physical evidence."""
import importlib.util
from pathlib import Path
import sys

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
sys.path.insert(0, str(EXAMPLES))
spec = importlib.util.spec_from_file_location('m4_acceptance_script', EXAMPLES/'validate_m4_complete.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def test_all_policies_replay_four_independent_h_in_one_microsecond(tmp_path):
    rows = [acceptance.run_case(acceptance.cases()['parallel'], policy, tmp_path/'parallel'/policy)
            for policy in acceptance.STRATEGIES]
    acceptance.audit_comparisons(rows)
    assert all(row['completed_gates'] == 4 and row['loads'] == row['offloads'] == 0 for row in rows)
    assert all(row['operations'] == 4 for row in rows)
    for row in rows:
        assert row['makespan_us'] == pytest.approx(1)
        assert all(0 <= value <= 1 for value in row['resource_utilization'].values())


@pytest.mark.parametrize('field', ['initial_sha256', 'terminal_sha256'])
def test_comparison_refuses_different_initial_state_or_terminal(field):
    rows = [{'case': 'probe', 'strategy': policy, 'verification': 'verified', 'status': 'completed',
             'initial_sha256': 'same', 'terminal_sha256': 'same', 'makespan_us': 1}
            for policy in acceptance.STRATEGIES]
    rows[1][field] = 'different'
    with pytest.raises(AssertionError, match='unequal'):
        acceptance.audit_comparisons(rows)


def test_equal_local_distance_does_not_hide_different_next_service_cost(tmp_path):
    rows = acceptance.terminal_witness(tmp_path)
    assert rows[0]['local_distance_um'] == rows[1]['local_distance_um'] == 98
    assert rows[0]['end_state']['holders'] != rows[1]['end_state']['holders']
    assert rows[0]['next_service_us'] == pytest.approx(rows[1]['next_service_us'] + 10)
    assert all(row['complete_makespan_us'] > row['local_duration_us'] + row['next_service_us'] for row in rows)
