"""Portable actual Executor/VisualRecorder evidence and adversarial MZ audit."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from math import hypot, isclose
from pathlib import Path

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, Position2D as P, Rectangle
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.scheduling.parallel_patch import compile_dual_reset_prologue, compile_readout_group

from test_rigid_readout_placement import service_state


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rigid_readout_audit', ROOT / 'tools/audit_rigid_readout_placement.py')
audit_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_tool)


def write(directory, name, value):
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def read(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def portable_run(directory, *, source_epsilon=0., dual=False):
    state = service_state(dual=dual)
    if dual:
        right = replace(state.world.zones[-1], bounds=Rectangle(P(100, -120), P(160, -60)))
        native = tuple(PhysicalGate(f'r.{q}', 'RESET', (q,)) for q in ('Q000', 'Q001', 'Q100', 'Q101'))
        state = replace(state, world=replace(state.world, zones=state.world.zones[:-1] + (right,)),
                        dag=DynamicGateDAG(PhysicalCircuit(native)))
    if source_epsilon:
        traps = dict(state.world.traps)
        traps['Q001'] = replace(traps['Q001'], position=P(10, 40 + source_epsilon))
        state = replace(state, world=replace(state.world, traps=traps))
    initial = state.snapshot()
    recorder = VisualRecorder(state)
    decisions = []
    if dual:
        gates, resets = native, ()
        plan = compile_dual_reset_prologue(state, gates[:2], gates[2:], readout_placement_log=decisions)
    else:
        gates = tuple(state.dag.nodes[f'm.{q}'].gate for q in ('Q000', 'Q001'))
        plan, resets = compile_readout_group(state, gates, readout_placement_log=decisions)
    executor = Executor(state)
    executor.submit(plan)
    while state.event_queue:
        event = executor.step()
        recorder.observe(state, event)
    replay = SimulationState.restore(initial)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot() and state.dag.completed
    write(directory, 'initial.json', json.loads(initial))
    write(directory, 'recording.json', recorder.payload())
    write(directory, 'decisions.json', [{'decision': 0, 'kind': 'RESET' if dual else 'MEASURE',
        'gate_ids': [g.id for g in gates], 'included_reset_gate_ids': [g.id for g in resets],
        'start_us': 0., 'end_us': state.time_us, 'duration_us': plan.estimated_duration_us,
        'plan_id': plan.id, 'readout_placement_decisions': decisions}])
    write(directory, 'summary.json', {'status': 'completed', 'readout_placement': 'nearest_mz',
        'audit': {'independent_plan_replay_equal': replay.snapshot() == state.snapshot()}})
    return directory


@pytest.fixture
def recorded(tmp_path):
    return portable_run(tmp_path)


def change_selected(directory, transform):
    decisions = read(directory, 'decisions.json')
    row = decisions[0]['readout_placement_decisions'][0]
    original = deepcopy(row['selected'])
    index = next(i for i, c in enumerate(row['candidates']) if c == original)
    transform(row['selected'])
    transform(row['candidates'][index])
    write(directory, 'decisions.json', decisions)


def test_portable_real_recording_has_nonzero_projection_and_geometry_evidence(recorded):
    result = audit_tool.audit(recorded)
    assert result['passed'] and result['selection_count'] == 1
    assert result['original_projection_count'] == 4
    selection = result['selections'][0]
    assert selection['source_origin_um'] == [10, 20]
    assert selection['nearest_geometric_pose_um'] == [10, -40]
    assert selection['selected_pose_um'] == [10, -40]
    assert selection['geometric_nearest_distance_um'] == 60
    assert selection['pulse_count_checked'] == 2
    assert result['accepted_actual_cost_minimum'] and result['committed_pose_positions_match_selection']
    assert result['continuous_global_optimum_claimed'] is False


def test_portable_shared_reset_audits_both_lanes_without_charging_joint_wait_as_motion(tmp_path):
    portable_run(tmp_path, dual=True)
    result = audit_tool.audit(tmp_path)
    assert result['passed'] and result['selection_count'] == 2 and result['original_projection_count'] == 4
    selections = {s['aod_id']: s for s in result['selections']}
    assert selections['AOD_0']['selected_pose_um'] == [10, -40]
    assert selections['AOD_MAGIC']['selected_pose_um'] == [110, -80]
    assert all(s['pulse_count_checked'] == 1 and s['cost_verified_from_recording'] for s in selections.values())
    # Both share one 100 us RESET. Magic needs 80 us more MOVE in each
    # direction; algorithm's joint waiting time is not part of its lane cost.
    assert (selections['AOD_MAGIC']['selected_actual_service_us']
            - selections['AOD_0']['selected_actual_service_us']) == pytest.approx(160)


def test_claimed_nearest_target_cannot_override_original_source_geometry(recorded):
    change_selected(recorded, lambda c: c['features']['geometric_nearest_pose_um'].__setitem__(1, -45))
    with pytest.raises(ValueError, match='Nearest geometry'):
        audit_tool.audit(recorded)


def test_claimed_feasible_domain_cannot_ignore_actual_carrier_or_spare_axes(recorded):
    change_selected(recorded, lambda c: c['features']['feasible_origin_bounds_um'].__setitem__(3, -20))
    with pytest.raises(ValueError, match='Feasible domain'):
        audit_tool.audit(recorded)


def test_log_self_consistent_wrong_selected_pose_fails_against_recorded_device(recorded):
    def shifted(c):
        c['target_pose_um'][0] += 2.5
        c['positions'] = [[q, [x + 2.5, y]] for q, (x, y) in c['positions']]
        c['proxy_distance_um'] = hypot(2.5, 60)
    change_selected(recorded, shifted)
    with pytest.raises(ValueError, match='Committed device measurement pose'):
        audit_tool.audit(recorded)


def test_selected_cost_must_be_best_among_actual_accepted_candidates(recorded):
    decisions = read(recorded, 'decisions.json')
    row = decisions[0]['readout_placement_decisions'][0]
    alternate = next(c for c in row['candidates'] if c['status'] == 'accepted' and c != row['selected'])
    alternate['actual_us'] = 1
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='actual accepted service cost'):
        audit_tool.audit(recorded)


def test_self_consistent_logged_cost_cannot_replace_executed_service_duration(recorded):
    decisions = read(recorded, 'decisions.json')
    row = decisions[0]['readout_placement_decisions'][0]
    row['selected']['actual_us'] += 1
    for c in row['candidates']:
        if c['status'] == 'accepted':
            c['actual_us'] += 1
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='(duration|cost|time)'):
        audit_tool.audit(recorded)


def test_native_projection_removed_from_decision_cannot_hide_in_atom_set(recorded):
    decisions = read(recorded, 'decisions.json')
    decisions[0]['readout_placement_decisions'][0]['included_reset_gate_ids'].remove('r.Q001')
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='projection'):
        audit_tool.audit(recorded)


def test_empty_recorded_pulse_set_cannot_vacuously_validate_selected_target(recorded):
    recording = read(recorded, 'recording.json')
    recording['operations'] = [op for op in recording['operations'] if op['kind'] not in ('measurement', 'reset')]
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='(projection|pulse|readout)'):
        audit_tool.audit(recorded)


def test_one_original_projection_missing_from_actual_pulse_is_rejected(recorded):
    recording = read(recorded, 'recording.json')
    measurement = next(op for op in recording['operations'] if op['kind'] == 'measurement')
    measurement['gate_ids'].remove('m.Q000')
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='(projection|pulse|readout)'):
        audit_tool.audit(recorded)


def test_duplicate_actual_projection_is_rejected_even_at_the_same_pose(recorded):
    recording = read(recorded, 'recording.json')
    measurement = next(op for op in recording['operations'] if op['kind'] == 'measurement')
    recording['operations'].append(deepcopy(measurement))
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='(projection|pulse|readout)'):
        audit_tool.audit(recorded)


def test_recorded_carrier_position_cannot_override_selected_rigid_target(recorded):
    recording = read(recorded, 'recording.json')
    measurement = next(op for op in recording['operations'] if op['kind'] == 'measurement')
    changed = 0
    for frame in recording['frames']:
        if isclose(frame['time'], measurement['start'], abs_tol=1e-8):
            for atom in frame['atom_updates']:
                if atom['id'] == 'Q000':
                    atom['position']['x_um'] += 1
                    changed += 1
    assert changed
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='Committed carrier position'):
        audit_tool.audit(recorded)


@pytest.mark.parametrize('epsilon', (-1e-10, 1e-10))
def test_true_alignment_tolerant_load_still_audits_strict_mz_boundary(tmp_path, epsilon):
    portable_run(tmp_path, source_epsilon=epsilon)
    result = audit_tool.audit(tmp_path)
    assert result['passed'] and result['original_projection_count'] == 4


def test_report_cannot_claim_completed_audit_when_original_state_replay_is_missing(recorded):
    summary = read(recorded, 'summary.json')
    summary['audit']['independent_plan_replay_equal'] = False
    write(recorded, 'summary.json', summary)
    with pytest.raises(ValueError, match='Original-initial-state replay'):
        audit_tool.audit(recorded)
