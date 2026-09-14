"""Read-only saved-result metadata regression; fixture is not a physics claim."""
import json
import pytest
from neutral_atom_app.visualization.workbench_server import CompileJobs


@pytest.mark.parametrize('suffix',[False,True])
def test_saved_resume_scope_and_parent_observation_are_preserved(tmp_path,monkeypatch,suffix):
    monkeypatch.setattr('neutral_atom_app.visualization.workbench_server.validate_input',lambda x:x)
    source=tmp_path/'saved';source.mkdir()
    saved={'status':'checks_passed_replay_pending','actual_strategy':'qec_temporal_four',
           'compile_seconds':631.276,'metrics':{'completed_gate_count':1,'simulation_time_us':10}}
    if suffix:saved['compile_timing_scope']='suffix_only'
    files={'result.json':saved,'input.json':{'compiler':'qec_temporal_four','gates':[{'id':'only'}]},
        'recording.json':{'duration':10,'summary':{'metrics':{'completed_gate_count':1}}},
        'decisions.json':[{'kind':'service','selected':['only']}],
        'verification.json':{'compiler_free_replay':'PASS'},
        'resume-provenance.json':{'parent_output':'parent-attempt','selected_checkpoint':'parent/checkpoint',
          'classification':'timeout','prefix_completed_gates':1588,'prefix_plans':468,
          'prefix_time_us':94372.5,'prefix_trace_sha256':'abc','prefix_trace_records':7564,
          'parent_progress':{'elapsed_seconds':3579.865},'parent_result':None}}
    for name,value in files.items():(source/name).write_text(json.dumps(value),encoding='utf-8')
    original={p.name:p.read_bytes() for p in source.iterdir()}
    jobs=CompileJobs(tmp_path/'jobs')
    try:
        key=jobs.restore(source);actual=jobs.get(key,True)
        assert actual['compile_seconds']==631.276
        assert actual['decision_log']==files['decisions.json']
        assert jobs.active is None and 'process' not in jobs.jobs[key]
        assert actual['provenance']['acceptance_status']=='checks_passed_replay_pending'
        if suffix:
            assert actual['compile_timing_scope']=='suffix_only'
            metadata=actual['provenance']['resume']
            assert metadata['prefix_completed_gates']==1588 and metadata['prefix_plans']==468
            assert metadata['parent_observed_elapsed_seconds']==3579.865
            assert metadata['classification']=='timeout'
            assert metadata['recording_scope']=='full_prefix_and_suffix'
            assert metadata['decision_log_scope']=='suffix_only'
            assert 'parent_result' not in metadata
        else:
            assert 'compile_timing_scope' not in actual and 'resume' not in actual['provenance']
        assert {p.name:p.read_bytes() for p in source.iterdir()}==original
    finally:jobs.close()
