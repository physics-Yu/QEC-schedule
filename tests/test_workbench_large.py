"""Large experiments keep editable input, bounded rendering and explicit budgets."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.request import Request, urlopen

import pytest

from neutral_atom_env.domain.models import MobileCellIndex
from neutral_atom_env.visualization.workbench import (MAX_ATOMS, MAX_COLUMNS, MAX_GATES,
    SEARCH_LIMITS, build_inputs, compile_input, validate_input)
from neutral_atom_env.visualization.workbench_server import CompileJobs, create_server


def experiment(**changes):
    return {'atom_count':36, 'layout':'row', 'compiler':'greedy', 'ez_policy':'adaptive',
            'aod_traps':36, 'seed':7, 'gates':[], **changes}


@pytest.mark.parametrize('capacity', [3, 9, 36, 128])
def test_experimental_capacity_preserves_occupied_spacing_and_physics(capacity):
    value, circuit, platform, placement = build_inputs(experiment(aod_traps=capacity))
    assert value['aod_traps'] == platform.aod.columns == capacity
    assert platform.aod.rows == 1 and platform.aod.spacing_um == 10
    assert platform.world.grid_spacing_um == 5
    assert platform.world.traps['S035'].position.x_um == 350
    assert len(placement) == 36 and not platform.aod.active_cells
    assert platform.world.bounds.contains(platform.aod.position(MobileCellIndex(0, capacity-1)))


def test_large_input_limits_and_round_trip_preserve_every_gate_and_budget():
    gates = [{'id':f'g{i}', 'gate_type':'H', 'qubit_ids':[f'Q{i%128:03d}'],
              'column':i} for i in range(4096)]
    raw = experiment(atom_count=128, aod_traps=128, gates=gates,
                     compile_timeout_s=86400, **SEARCH_LIMITS)
    valid = validate_input(raw)
    assert validate_input(json.loads(json.dumps(valid))) == valid
    assert len(valid['gates']) == MAX_GATES == 4096
    assert valid['gates'][-1]['column'] == MAX_COLUMNS-1
    assert valid['atom_count'] == MAX_ATOMS == 128
    for key, limit in SEARCH_LIMITS.items():
        assert valid[key] == limit
        with pytest.raises(ValueError):
            validate_input(raw | {key:limit+1})


@pytest.mark.parametrize('field,value', [('atom_count',129),('aod_traps',129),
    ('compile_timeout_s',0),('compile_timeout_s',86401),('compile_timeout_s',True)])
def test_large_parameters_still_have_explicit_bounds(field,value):
    with pytest.raises(ValueError):
        validate_input(experiment(**{field:value}))


def test_row_policy_wrong_platform_has_visible_structured_failure():
    raw = experiment(compiler='row_greedy', aod_traps=9,
        gates=[{'id':'h', 'gate_type':'H', 'qubit_ids':['Q000'], 'column':0}])
    result, state = compile_input(raw)
    assert result['status'] == 'stalled'
    assert result['failure_report']['code'] == 'ROW_CAPACITY'
    assert result['run_options']['candidate_budget'] == 4096
    assert result['run_options']['route_expansions'] == 100000
    assert state.time_us == 0 and state.committed_events == 0


def test_explicit_job_timeout_overrides_service_default_and_is_exported(tmp_path):
    jobs = CompileJobs(tmp_path, timeout=.001)
    try:
        key = jobs.start(experiment(atom_count=2,aod_traps=2,compile_timeout_s=30))
        deadline = time.monotonic()+15
        while jobs.get(key)['status'] == 'compiling' and time.monotonic()<deadline:
            time.sleep(.03)
        status = jobs.get(key)
        assert status['status'] == 'completed', status
        assert status['timeout_seconds'] == 30
        assert json.loads((tmp_path/key/'input.json').read_text(encoding='utf-8'))['compile_timeout_s'] == 30
        assert json.loads((tmp_path/key/'run_options.json').read_text(encoding='utf-8'))['ready_limit'] == 16
    finally:
        jobs.close()


def test_timeout_is_enforced_even_if_worker_always_has_progress(tmp_path,monkeypatch):
    class Process:
        terminated = False
        def is_alive(self): return not self.terminated
        def terminate(self): self.terminated = True
        def join(self,timeout): pass
    class Connection:
        closed = False
        def poll(self,timeout): return True
        def recv(self): return 'progress', {'completed_gates':0,'total_gates':1}
        def close(self): self.closed = True
    jobs = CompileJobs(tmp_path)
    (tmp_path/'fake').mkdir()
    process, connection = Process(), Connection()
    job = {'id':'fake','status':'compiling','started':0,'timeout_seconds':1,
           'process':process,'input':experiment(),'progress':{}}
    clock = iter([.2, .4, 1.1])
    monkeypatch.setattr('neutral_atom_env.visualization.workbench_server.time.monotonic',lambda:next(clock))
    jobs._monitor(job,connection)
    assert job['error']['code'] == 'COMPILE_TIMEOUT'
    assert process.terminated and connection.closed
    assert json.loads((tmp_path/'fake'/'failure_report.json').read_text(encoding='utf-8'))['timeout_seconds'] == 1


def test_http_preview_accepts_import_larger_than_old_64_kib(tmp_path):
    gates = [{'id':f'g{i}', 'gate_type':'H','qubit_ids':[f'Q{i%36:03d}'],
              'column':i} for i in range(1024)]
    body = json.dumps(experiment(gates=gates, compile_timeout_s=3600)).encode()
    assert len(body)>65536
    server = create_server(0,tmp_path)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        req = Request(f'http://127.0.0.1:{server.server_port}/api/preview',body,
                      headers={'Content-Type':'application/json'})
        result = json.load(urlopen(req,timeout=20))
        assert len(result['input']['gates']) == 1024
        assert len(result['recording']['frames'][0]['atom_updates']) == 36
        assert result['input']['compile_timeout_s'] == 3600
        example = json.load(urlopen(f'http://127.0.0.1:{server.server_port}/api/examples/surface-ghz'))
        assert example['atom_count'] == example['aod_traps'] == 36
        assert len(example['gates']) == 194 and example['compiler'] == 'patch_greedy'
        assert example['aod_rows'] == example['aod_columns'] == 6
    finally:
        server.shutdown(); server.jobs.close(); server.server_close(); thread.join()


def test_editor_deep_links_use_real_api_and_recompile_saved_input(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for real-API editor handler test')
    server = create_server(0,tmp_path)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        value = experiment(atom_count=2, aod_traps=2, gates=[
            {'id':f'h{i}','gate_type':'H','qubit_ids':[f'Q{i:03d}'],'column':0}
            for i in range(2)])
        key = server.jobs.start(value)
        deadline = time.monotonic()+20
        while server.jobs.get(key)['status']=='compiling' and time.monotonic()<deadline:
            time.sleep(.03)
        assert server.jobs.get(key)['status']=='completed'
        run = subprocess.run([node,'tests/workbench_links_controls.cjs',
            f'http://127.0.0.1:{server.server_port}',key],cwd=Path(__file__).resolve().parents[1],
            text=True,encoding='utf-8',capture_output=True,timeout=45)
        assert run.returncode==0,run.stdout+run.stderr
        assert 'PASS: real-API' in run.stdout
    finally:
        server.shutdown(); server.jobs.close(); server.server_close(); thread.join()
