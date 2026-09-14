"""Editable QEC input keeps actual conditions and separates supported profiles."""
import json

import pytest

from neutral_atom_experiments.surface_qec import experiment_input
from neutral_atom_app.visualization.workbench import build_inputs, preview, validate_input
from neutral_atom_env.visualization.summary import operation_category, summarize_intervals


def test_qec_roundtrip_preserves_protocol_conditions_and_explicit_dependencies():
    raw=experiment_input({'pauli':'Y','qubit_id':'Q004'})
    value,circuit,platform,placement=build_inputs(raw)
    assert value==validate_input(json.loads(json.dumps(value)))
    assert len(circuit.gates)==len(raw['gates'])
    raw_by_id={g['id']:g for g in raw['gates']}
    for g in circuit.gates:
        assert list(map(list,g.condition))==raw_by_id[g.id].get('condition',[])
        assert list(g.depends_on)==raw_by_id[g.id].get('depends_on',[])
    assert (platform.aod.rows,platform.aod.columns)==(7,14)
    assert len(placement)==34
    assert next(g for g in circuit.gates if g.id=='QEC_FAULT').gate_type=='Y'
    assert value['qec_protocol']['fault_column']==raw['qec_protocol']['fault_column']


def test_qec_preview_has_actual_two_patch_roles_and_no_fake_measurements():
    p=preview(experiment_input())
    roles=p['recording']['scene']['atom_roles']
    assert sum(r['role']=='data' for r in roles.values())==18
    assert sum(r['role']=='ancilla' for r in roles.values())==16
    assert len(p['recording']['frames'][0]['atom_updates'])==34
    assert p['recording']['frames'][0].get('measurement_results',{})=={}
    assert p['recording']['duration']==0


@pytest.mark.parametrize('patch',[{'qec_enabled':False},{'qec_enabled':1},{'compiler':'patch_greedy'},
                                {'layout':'surface_patches'},{'atom_count':33}])
def test_qec_profile_requires_consistent_physical_platform(patch):
    with pytest.raises(ValueError):validate_input(experiment_input()|patch)


@pytest.mark.parametrize('kind',['MEASURE','RESET'])
def test_measurement_and_reset_are_rejected_in_ordinary_editor(kind):
    with pytest.raises(ValueError,match='QEC'):
        validate_input({'atom_count':1,'layout':'row','gates':[
            {'id':'g','gate_type':kind,'qubit_ids':['Q000'],'parameters':[],'column':0}]})


def test_qec_rejects_nonclifford_and_preserves_actual_edited_small_circuit():
    value=experiment_input()
    value['gates']=[{'id':'edited','gate_type':'T','qubit_ids':['Q000'],'parameters':[],'column':0}]
    with pytest.raises(ValueError,match='Clifford'):validate_input(value)
    value['gates'][0]['gate_type']='X'
    normalized,circuit,_,_=build_inputs(value)
    assert [g.id for g in circuit.gates]==['edited']
    assert len(normalized['gates'])==1


def test_qec_fault_invalid_shape_is_rejected():
    with pytest.raises(ValueError,match='qec_fault'):
        validate_input(experiment_input()|{'qec_fault':{'pauli':'H','qubit_id':'Q000'}})


def test_measure_reset_and_false_control_have_distinct_time_categories():
    operations=[]
    for start,kind,duration,applied,expected in ((0,'measurement',500,True,'measurement'),
            (500,'reset',100,True,'reset'),(600,'raman_rotation',1,False,'control'),
            (601,'raman_rotation',1,True,'raman')):
        category=operation_category({'operation_type':kind,'applied':applied},False)
        assert category==expected
        operations.append({'start':start,'end':start+duration,'category':category})
    result=summarize_intervals(operations,0,602)
    totals={c['key']:c['duration_us'] for c in result['categories']}
    assert totals['measurement']==500 and totals['reset']==100
    assert totals['control']==totals['raman']==1
    assert totals['pulse']==0
