"""Saved physical execution provenance and the editable persistent QEC strategy."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from neutral_atom_experiments.surface_qec import experiment_input
from neutral_atom_app.visualization.workbench import build_inputs, validate_input
from neutral_atom_app.visualization.workbench_server import CompileJobs


def test_persistent_strategy_keeps_actual_edited_circuit():
    raw=experiment_input();raw['compiler']='qec_persistent'
    raw['gates']=[{'id':'edited','gate_type':'H','qubit_ids':['Q000'],'parameters':[],'column':0}]
    value,circuit,_,_=build_inputs(raw)
    assert value['compiler']=='qec_persistent'
    assert [g.id for g in circuit.gates]==['edited']
    assert validate_input(value)==value


def saved_fixture(tmp_path):
    source=Path('artifacts/qec-roadmap/step2-attempt1')
    for name in ('input.json','recording.json','result.json','strategy.json','qec_result.json','decisions.json'):
        shutil.copy2(source/name,tmp_path/name)
    return tmp_path


def test_restore_exposes_saved_execution_without_starting_worker_or_mutating_source(tmp_path):
    source=saved_fixture(tmp_path)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    original=json.loads((source/'input.json').read_text(encoding='utf-8'))
    jobs=CompileJobs(tmp_path/'new-jobs');key=jobs.restore(source);result=jobs.get(key,True)
    assert jobs.active is None and 'process' not in jobs.jobs[key]
    assert result['input']==validate_input(original|{'compiler':'qec_persistent'})
    assert result['recording']==json.loads((source/'recording.json').read_text(encoding='utf-8'))
    assert result['provenance']['source_input_compiler']=='qec_ghz2'
    assert result['provenance']['actual_strategy']=='qec_persistent'
    assert result['provenance']['kind']=='saved_execution'
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    assert not (tmp_path/'new-jobs').exists()
    jobs.close()


def test_restore_rejects_inconsistent_saved_metrics_as_expected(tmp_path):
    source=saved_fixture(tmp_path)
    saved=json.loads((source/'result.json').read_text(encoding='utf-8'))
    saved['metrics']['completed_gate_count']=0
    (source/'result.json').write_text(json.dumps(saved),encoding='utf-8')
    with pytest.raises(ValueError,match='not completed'):
        CompileJobs(tmp_path/'new-jobs').restore(source)
