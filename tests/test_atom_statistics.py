import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from neutral_atom_env.domain.models import PhysicalGate as Gate
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.statistics import AtomStatistics, summarize_atoms, write_atom_statistics
from neutral_atom_env.visualization import VisualRecorder


def test_real_single_trap_distances_handoffs_and_cz_partners():
    from test_single_trap_pipeline import inputs, schedule
    from neutral_atom_env.platform import initialize
    state = initialize(*inputs())
    recorder = VisualRecorder(state)
    assert schedule(state, observe=recorder.observe).status == 'completed'
    before = state.snapshot()
    report = summarize_atoms(state)
    assert state.snapshot() == before
    assert report == recorder.payload()['atom_statistics']
    assert report == summarize_atoms(SimulationState.restore(before))
    a, b = (report['atoms'][q] for q in ('Q000', 'Q001'))
    assert a['distance_um'] == 85
    assert b['distance_um'] == 96
    assert (a['load_count'], a['offload_count']) == (2, 2)
    assert (b['load_count'], b['offload_count']) == (1, 1)
    assert a['gate_counts'] == b['gate_counts'] == {'CZ': 1}
    assert a['busy_time_us'] == pytest.approx(85/.5 + 400 + .3)
    assert b['busy_time_us'] == pytest.approx(96/.5 + 200 + .3)
    assert sum(r['distance_um'] for r in report['atoms'].values()) == state.metrics()['total_atom_distance_um']
    for q, row in report['atoms'].items():
        assert row['busy_time_us'] + row['waiting_time_us'] == pytest.approx(state.time_us)
        if q not in ('Q000', 'Q001'):
            assert row['distance_um'] == row['load_count'] == 0
            assert row['gate_counts'] == {}
            assert row['waiting_time_us'] == state.time_us


def test_parallel_gate_counts_are_per_atom_and_only_committed():
    from test_batch_raman import batch_state, builder
    state = batch_state(n=3)
    p = builder(state)
    p.add(K.RAMAN_ROTATION, 'parallel H', gate_ids=('h0', 'h1', 'h2'))
    executor = Executor(state)
    executor.submit(p.finish('statistics-H'))
    assert all(not a['gate_counts'] for a in summarize_atoms(state)['atoms'].values())
    executor.step(); executor.step()  # Plan and operation start; pulse not complete.
    assert all(not a['gate_counts'] for a in summarize_atoms(state)['atoms'].values())
    executor.run()
    for row in summarize_atoms(state)['atoms'].values():
        assert row['gate_counts'] == {'H': 1}
        assert row['busy_time_us'] == 1
        assert row['waiting_time_us'] == 0
    accumulator = AtomStatistics.from_state(state)
    before = accumulator.report()
    accumulator.observe(state)
    assert accumulator.report() == before


def test_real_row_column_incidental_atom_has_transport_but_no_gate():
    from test_row_column_aod import run_case
    state, _, _ = run_case('incidental')
    report = summarize_atoms(state)
    assert sum(row['distance_um'] for row in report['atoms'].values()) == 174
    for q in ['Q000', 'Q001', 'Q002']:
        row = report['atoms'][q]
        assert row['distance_um'] == 58
        assert row['load_count'] == row['offload_count'] == 1
    assert report['atoms']['Q002']['gate_counts'] == {}
    assert report['atoms']['Q000']['gate_counts'] == report['atoms']['Q001']['gate_counts'] == {'CZ': 1}


def test_legacy_serial_plan_without_initial_placement():
    from test_milestone1 import make_single_gate_state, compile_plan
    # Legacy serial plans omit initial_placement; committed loads establish it.
    state = make_single_gate_state('incidental')
    stats = AtomStatistics.from_state(state)
    executor = Executor(state); executor.submit(compile_plan(state))
    while state.event_queue:
        event = executor.step(); stats.observe(state, event)
    assert stats.report() == summarize_atoms(state)
    for q in ('Q000', 'Q002'):
        assert stats.report()['atoms'][q]['distance_um'] == 56
        assert stats.report()['atoms'][q]['load_count'] == 1


def test_actual_parking_and_recapture_count_only_the_transferred_atom():
    from test_rigid_parking import run
    state, _, recorder = run()
    report = summarize_atoms(state)
    assert recorder.payload()['atom_statistics'] == report
    a, b = (report['atoms'][q] for q in ('Q000', 'Q001'))
    assert (a['load_count'], a['offload_count'], a['distance_um']) == (2, 2, 80)
    assert (b['load_count'], b['offload_count'], b['distance_um']) == (1, 1, 96)
    assert a['gate_counts'] == b['gate_counts'] == {'CZ': 1}


def test_reported_conditions_measurement_reset_and_repeated_gate_types():
    from test_quantum_readout import state_for, build
    gates = [Gate('m', 'MEASURE', ('q0',), readout_flip=True),
             Gate('r', 'RESET', ('q0',)),
             Gate('x0', 'X', ('q0',), condition=(('m', 0),)),
             Gate('x1', 'X', ('q1',), condition=(('m', 1),)),
             Gate('h1', 'H', ('q1',)), Gate('h2', 'H', ('q1',))]
    state = state_for(gates)
    plan, _ = build(state, [(K.MEASUREMENT, ('m',)), (K.RESET, ('r',)),
                           (K.RAMAN_ROTATION, ('x0', 'x1')),
                           (K.RAMAN_ROTATION, ('h1',)), (K.RAMAN_ROTATION, ('h2',))])
    recorder = VisualRecorder(state)
    executor = Executor(state); executor.submit(plan)
    while state.event_queue:
        event = executor.step(); recorder.observe(state, event)
    report = summarize_atoms(state)
    assert report == recorder.payload()['atom_statistics']
    assert report['elapsed_us'] == 603
    assert report['atoms']['q0']['gate_counts'] == {'MEASURE': 1, 'RESET': 1}
    assert report['atoms']['q0']['waiting_time_us'] == 3
    assert report['atoms']['q1']['gate_counts'] == {'H': 2, 'X': 1}
    assert report['atoms']['q1']['waiting_time_us'] == 600


def _transport_trace():
    """Independent geometry: three occupied corners; middle cell stays still."""
    cells = {'a': {'row': 0, 'column': 0}, 'b': {'row': 1, 'column': 1},
             'c': {'row': 0, 'column': 1}}
    bindings = [{'atom_id': q, 'cell': c, 'static_trap_id': 's'+q} for q, c in cells.items()]
    operations = [dict(id='load', operation_type='aod_load', duration_us=2, transfer_bindings=bindings),
                  dict(id='move', operation_type='aod_move', duration_us=8),
                  dict(id='park', operation_type='aod_park', duration_us=2, transfer_bindings=bindings)]
    plan = dict(id='p', operations=operations, execution_mode='scheduled', initial_placement=[])
    records = []
    def add(kind, t, op=None, **extra):
        event = dict(event_type=kind, time_us=t, plan_id='p', operation_id=op)
        if kind == 'plan_started': event['plan'] = plan
        records.append(dict(sequence=len(records), event=event, **extra))
    add('plan_started', 0)
    add('operation_started', 0, 'load')
    add('operation_completed', 2, 'load')
    add('operation_started', 2, 'move', source_configuration={'x_um':[0,10], 'y_um':[0,10]},
        target_configuration={'x_um':[3,10], 'y_um':[0,14]}, moving_atom_ids=['a','b','c'], motion_profile='cubic')
    add('wait_completed', 4)  # Accounting fixture: observation at 1/4 of the move.
    add('operation_completed', 10, 'move')
    add('operation_started', 10, 'park')
    add('operation_completed', 12, 'park')
    add('plan_completed', 12)
    add('wait_completed', 15)
    return records


def test_deformed_array_incidental_atoms_zero_motion_and_partial_cubic():
    stats = AtomStatistics(['a','b','c','idle'], [])
    records = _transport_trace()
    for r in records[:5]: stats.consume(r)
    partial = stats.report()
    assert partial['atoms']['a']['distance_um'] == pytest.approx(3 * .15625)
    assert partial['atoms']['b']['distance_um'] == pytest.approx(4 * .15625)
    assert partial['atoms']['c']['distance_um'] == 0
    assert partial['atoms']['c']['waiting_time_us'] == 2
    assert partial['atoms']['a']['offload_count'] == 0
    for r in records[5:]: stats.consume(r)
    report = stats.report()
    assert [report['atoms'][q]['distance_um'] for q in ['a','b','c']] == [3,4,0]
    assert [report['atoms'][q]['waiting_time_us'] for q in ['a','b','c','idle']] == [3,3,11,15]
    assert all(report['atoms'][q]['load_count'] == report['atoms'][q]['offload_count'] == 1 for q in ['a','b','c'])
    # Returned summaries are detached from the accumulator.
    report['atoms']['a']['gate_counts']['H'] = 999
    assert stats.report()['atoms']['a']['gate_counts'] == {}
    with pytest.raises(ValueError, match='exactly once'): stats.consume(records[-1])
    with pytest.raises(ValueError, match='latest committed'): stats.report(end_time_us=100)


def test_interval_union_does_not_double_charge_overlaps():
    from neutral_atom_env.statistics.atoms import _union
    assert _union([(0,5),(2,3),(4,8),(10,12)]) == 10


def test_exports_match_json_and_csv(tmp_path):
    stats = AtomStatistics(['q'], [dict(id='h', gate_type='H', qubit_ids=['q'])])
    report = stats.report()
    json_path, csv_path = write_atom_statistics(report, tmp_path)
    assert json.loads(json_path.read_text()) == report
    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]['atom_id'] == 'q'
    assert float(rows[0]['waiting_time_us']) == 0


def test_workbench_worker_and_offline_cli_export_actual_gate_counts(tmp_path):
    from neutral_atom_app.visualization.workbench_server import _worker
    from test_workbench import request
    kinds = ['H', 'X', 'Y', 'Z', 'T', 'CZ']
    gates = [dict(id='g'+str(i), gate_type=kind, column=i,
                  qubit_ids=['Q000', 'Q001'] if kind == 'CZ' else ['Q000'])
             for i, kind in enumerate(kinds)]
    class Connection:
        def __init__(self): self.messages = []; self.closed = False
        def send(self, message): self.messages.append(message)
        def close(self): self.closed = True
    connection = Connection()
    output = tmp_path / 'worker'
    _worker(request(count=2, gates=gates), output, connection)
    assert connection.closed
    kind, result = connection.messages[-1]
    assert kind == 'result', result
    assert result['status'] == 'completed'
    report = json.loads((output / 'atom_statistics.json').read_text())
    assert report == result['recording']['atom_statistics']
    assert report['atoms']['Q000']['gate_counts'] == dict.fromkeys(kinds, 1)
    assert report['atoms']['Q001']['gate_counts'] == {'CZ': 1}
    with (output / 'atom_statistics.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(rows[0]['gate_'+kind] == '1' for kind in kinds)
    assert rows[1]['gate_H'] == '0' and rows[1]['gate_CZ'] == '1'
    script = Path(__file__).resolve().parents[1] / 'examples' / 'summarize_atoms.py'
    offline = tmp_path / 'offline'
    command = [sys.executable, str(script), '--input', str(output / 'input.json'),
               '--trace', str(output / 'trace.jsonl'), '--output', str(offline)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    assert json.loads((offline / 'atom_statistics.json').read_text()) == report
