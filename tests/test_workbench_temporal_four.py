"""Four-patch HTTP/profile integration; no full physical experiment."""
from copy import deepcopy
import json
import threading
from urllib.request import urlopen
from types import SimpleNamespace

import pytest

from neutral_atom_env.experiments.surface_qec_temporal_four import experiment_input
from neutral_atom_env.experiments.surface_qec import experiment_input as two_input
from neutral_atom_env.visualization.workbench import validate_input,build_inputs,preview,compile_input,aod_shape,aod_offsets
from neutral_atom_env.visualization.workbench_server import create_server,CompileJobs
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.domain.errors import ValidationError


@pytest.fixture(scope='module')
def four_input():
    return experiment_input({'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0})


def test_four_input_roundtrip_preserves_real_noise_and_protocol(four_input):
    value,circuit,platform,placement=build_inputs(four_input)
    assert value==validate_input(json.loads(json.dumps(value)))
    assert value['qec_patch_origins']==[[0,0],[40,0],[0,40],[40,40]]
    assert len(placement)==68 and (platform.aod.rows,platform.aod.columns)==(7,14)
    assert [g.id for g in circuit.gates if g.readout_flip]==['round2_X0_0']
    raw={g['id']:g for g in four_input['gates']}
    for gate in circuit.gates:
        assert list(gate.depends_on)==raw[gate.id].get('depends_on',[])
        assert list(map(list,gate.condition))==raw[gate.id].get('condition',[])


@pytest.mark.parametrize('patch',[{'atom_count':34},{'atom_count':67},{'qec_enabled':False},
    {'layout':'surface_qec_ghz2'},{'compiler':'qec_temporal'},{'compiler':'qec_joint'},
    {'qec_patch_origins':[[0,0],[40,0]]}])
def test_four_profile_mismatch_rejected(four_input,patch):
    with pytest.raises(ValueError):validate_input(four_input|patch)


def test_two_profile_cannot_be_relabelled_four():
    with pytest.raises(ValueError,match='surface_qec_ghz4'):
        validate_input(two_input()|{'compiler':'qec_temporal_four'})


def test_preview_has_all_actual_roles_and_four_patch_coordinates(four_input):
    raw=deepcopy(four_input);raw['gates']=[]
    result=preview(raw);roles=result['recording']['scene']['atom_roles']
    assert sum(r['role']=='data' for r in roles.values())==36
    assert sum(r['role']=='ancilla' for r in roles.values())==32
    atoms={a['id']:a for a in result['recording']['frames'][0]['atom_updates']}
    assert len(atoms)==68
    assert atoms['Q027']['position']=={'x_um':40,'y_um':40}
    assert atoms['Q036']['position']=={'x_um':5,'y_um':5}
    assert atoms['Q060']['position']=={'x_um':45,'y_um':45}
    assert result['recording']['frames'][0]['measurement_results']=={}


def test_absent_four_defaults_and_shared_aod_contract_do_not_change_two_inputs(four_input):
    raw=deepcopy(four_input);raw['gates']=[]
    for key in ('qec_patch_origins','aod_traps','aod_rows','aod_columns','aod_row_offsets_um','aod_column_offsets_um'):
        raw.pop(key,None)
    value,_,platform,_=build_inputs(raw)
    assert 'qec_patch_origins' not in value and aod_shape(value)==(7,14)
    assert aod_offsets(value,7,14)==(tuple(range(0,35,5)),tuple(range(0,35,5))+tuple(range(40,75,5)))
    assert (platform.aod.rows,platform.aod.columns)==(7,14)
    old=two_input();old_value,_,old_platform,_=build_inputs(old)
    assert 'qec_patch_origins' not in old_value
    assert next(z for z in old_platform.world.zones if z.id=='SZ').bounds.upper.y_um==35
    assert next(z for z in platform.world.zones if z.id=='SZ').bounds.upper.y_um==75


def test_empty_actual_compile_uses_four_runner_summary_and_saved_restore(four_input,tmp_path):
    raw=deepcopy(four_input);raw['gates']=[]
    result,state=compile_input(raw)
    assert result['status']=='completed' and state.dag.completed
    assert 'verified_logical_ghz4' in result['qec_result']
    assert 'verified_logical_ghz2' not in result['qec_result']
    assert result['qec_result']['history_complete'] is False
    assert len(result['recording']['scene']['atom_roles'])==68
    assert result['run_options']=={'max_decisions':10000,'candidate_budget':4096,'route_expansions':100000}
    values={'input.json':result['input'],'recording.json':result['recording'],
            'qec_result.json':result['qec_result'],
            'result.json':{'status':'completed','actual_strategy':'qec_temporal_four',
                           'metrics':result['recording']['summary']['metrics']},
            'strategy.json':{'actual_strategy':'qec_temporal_four'}}
    for name,value in values.items():(tmp_path/name).write_text(json.dumps(value),encoding='utf-8')
    jobs=CompileJobs(tmp_path/'jobs');key=jobs.restore(tmp_path)
    try:
        restored=jobs.get(key,True)
        assert restored['input']==result['input']
        assert restored['recording']==result['recording']
        assert restored['provenance']['actual_strategy']=='qec_temporal_four'
        assert jobs.active is None and 'process' not in jobs.jobs[key]
    finally:jobs.close()


def test_real_example_endpoint_supplies_representative_flip_without_compiling(tmp_path):
    server=create_server(0,tmp_path/'http-jobs');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/examples/surface-qec-temporal-four') as response:
            value=json.load(response)
        assert value['compiler']=='qec_temporal_four' and value['seed']==7
        assert value['atom_count']==68 and len(value['qec_protocol']['history_ids'])==128
        assert [g['id'] for g in value['gates'] if g.get('readout_flip')]==['round2_X0_0']
        assert server.jobs.active is None and not server.jobs.jobs
    finally:
        server.shutdown();server.server_close();server.jobs.close();thread.join(5)


def guard_state(*,omit_history=False,bits=None,ordinary=False):
    from neutral_atom_env.experiments.surface_qec_temporal_four import HISTORY_IDS,CORRECTION_PREFIX
    assert len(HISTORY_IDS)==128
    correction=PhysicalGate(CORRECTION_PREFIX+'edited','X',('Q000',))
    gates=([PhysicalGate('edited','H',('Q000',))] if ordinary else
           [PhysicalGate(gid,'MEASURE',('Q036',)) for gid in (HISTORY_IDS[:-1] if omit_history else HISTORY_IDS)]+[correction])
    return SimpleNamespace(dag=SimpleNamespace(circuit=SimpleNamespace(gates=gates)),measurement_results=bits or {}),correction


def test_four_guard_missing_named_history_stalls_before_joint(monkeypatch):
    from neutral_atom_env.simulation import qec_temporal_four as runner
    state,_=guard_state(omit_history=True)
    monkeypatch.setattr(runner,'run_qec_joint',lambda *args,**kwargs:pytest.fail('Missing named history reached physical compiler'))
    result=runner.run_qec_temporal_four(state)
    assert result.status=='stalled'
    assert result.diagnostics[0]['code']=='INCOMPLETE_SYNDROME_HISTORY'
    assert state.measurement_results=={}


@pytest.mark.parametrize('all_ones,expected',[(False,'INCOMPLETE_SYNDROME_HISTORY'),(True,'UNSUPPORTED_SYNDROME_HISTORY')])
def test_four_guard_rejects_premature_or_unsupported_ready_correction(monkeypatch,all_ones,expected):
    from neutral_atom_env.simulation import qec_temporal_four as runner
    from neutral_atom_env.experiments.surface_qec_temporal_four import HISTORY_IDS
    from neutral_atom_env.motion.partitioned_cohort import PartitionedCohortCompiler
    state,correction=guard_state(bits=dict.fromkeys(HISTORY_IDS,1) if all_ones else {})
    before=dict(state.measurement_results)
    def joint(current,**options):
        assert options['compiler_type'] is PartitionedCohortCompiler
        options['frontier_validator'](current,[correction])
        pytest.fail('Invalid history reached physical correction planning')
    monkeypatch.setattr(runner,'run_qec_joint',joint)
    with pytest.raises(ValidationError) as caught:runner.run_qec_temporal_four(state)
    assert caught.value.violation.code==expected
    assert state.measurement_results==before


def test_four_guard_allows_ordinary_short_and_dispatches_partitioned_compiler(monkeypatch):
    from neutral_atom_env.simulation import qec_temporal_four as runner
    from neutral_atom_env.motion.partitioned_cohort import PartitionedCohortCompiler
    state,_=guard_state(ordinary=True);observed=[];expected=SimpleNamespace(status='completed')
    def joint(current,**options):
        assert current is state and options['compiler_type'] is PartitionedCohortCompiler
        assert options['candidate_budget']==12 and options['route_expansions']==345
        options['frontier_validator'](current,current.dag.circuit.gates)
        options['on_event'](current,'committed event')
        return expected
    monkeypatch.setattr(runner,'run_qec_joint',joint)
    result=runner.run_qec_temporal_four(state,candidate_budget=12,route_expansions=345,
        on_event=lambda current,event:observed.append((current,event)))
    assert result is expected and observed==[(state,'committed event')]
